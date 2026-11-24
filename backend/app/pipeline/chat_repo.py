"""Read-side queries for the WhatsApp-style Chats view. A chat is every WhatsApp message sharing one `thread_ref`
(the contact's E.164 number, in both directions). Every function requires `company_id` (CLAUDE.md invariant 4)."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import ColumnElement, Select, and_, exists, func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from app.contracts import ActionType, Channel, Direction
from app.contracts.message import normalise_identity
from app.core.errors import EstateOSError
from app.db.enums import ActionStatus, DeliveryStatus, PersonKind
from app.db.models.chat import ChatRead
from app.db.models.directory import ChannelIdentity, Person
from app.db.models.ingestion import MessageRow
from app.db.models.pipeline import ActionRow, CaseLink
from app.pipeline.read_repo import MAX_PAGE, Cursor

__all__ = [
    "BadChatKeyError",
    "ChatFilter",
    "ChatSummary",
    "chat_contact",
    "chat_list",
    "chat_messages",
    "is_pending_send",
    "latest_case_id",
    "latest_inbound",
    "mark_read",
    "parse_chat_key",
    "quoted_messages",
    "suggestions",
]

ChatFilter = Literal["all", "unread", "tenants", "contractors"]
MAX_SUGGESTIONS = 3
_OPEN_DRAFT = (ActionStatus.proposed, ActionStatus.pending_approval)
_E164 = re.compile(r"\+[0-9]{1,15}")


class BadChatKeyError(EstateOSError):
    """A chat key that is not a canonical E.164 WhatsApp number."""


def parse_chat_key(raw: str) -> str:
    try:
        key = normalise_identity(raw)
    except ValueError:
        raise BadChatKeyError("invalid chat key") from None
    if not _E164.fullmatch(key):
        raise BadChatKeyError("invalid chat key")
    return key


@dataclass(frozen=True)
class ChatSummary:
    chat_key: str
    name: str | None
    person_kind: PersonKind | None
    last_message_id: UUID
    last_at: datetime
    last_text: str
    last_kind: str | None
    last_direction: Direction
    last_delivery: DeliveryStatus | None
    last_pending: bool
    unread: int


def is_pending_send(direction: Direction, delivery: DeliveryStatus | None, meta: dict[str, Any]) -> bool:
    """An outbound row our own send path created (it carries the browser's `client_msg_id`) that has no delivery
    status and no send error yet. Business-app echoes and old outbound rows without a status are not pending."""
    return (
        direction == Direction.outbound
        and delivery is None
        and meta.get("client_msg_id") is not None
        and not meta.get("send_error")
    )


def _chat_messages_of(company_id: UUID, m: Any = MessageRow) -> tuple[ColumnElement[bool], ...]:
    return (m.company_id == company_id, m.channel == Channel.whatsapp, m.thread_ref.is_not(None))


def _ranked(company_id: UUID) -> Select[tuple[object, ...]]:
    """Every WhatsApp message with its rank inside its chat (1 = newest)."""
    return select(
        MessageRow.id.label("id"),
        MessageRow.thread_ref.label("ref"),
        MessageRow.sent_at.label("sent_at"),
        MessageRow.text.label("text"),
        MessageRow.meta["type"].as_string().label("msg_kind"),
        MessageRow.direction.label("direction"),
        MessageRow.delivery_status.label("delivery"),
        and_(
            MessageRow.direction == Direction.outbound,
            MessageRow.delivery_status.is_(None),
            MessageRow.meta["client_msg_id"].as_string().is_not(None),
            MessageRow.meta["send_error"].as_string().is_(None),
        ).label("pending"),
        func.row_number()
        .over(partition_by=MessageRow.thread_ref, order_by=(MessageRow.sent_at.desc(), MessageRow.id.desc()))
        .label("rn"),
    ).where(*_chat_messages_of(company_id))


def _unread_count(r: Any, company_id: UUID) -> ColumnElement[int]:
    """Inbound messages created after the chat's last read marker (all of them without a marker)."""
    m = aliased(MessageRow)
    marker = and_(ChatRead.company_id == company_id, ChatRead.chat_key == m.thread_ref)
    return (
        select(func.count())
        .select_from(m)
        .outerjoin(ChatRead, marker)
        .where(
            *_chat_messages_of(company_id, m),
            m.thread_ref == r.c.ref,
            m.direction == Direction.inbound,
            or_(ChatRead.last_read_at.is_(None), m.created_at > ChatRead.last_read_at),
        )
        .scalar_subquery()
    )


def _like_pattern(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _matches(r: Any, company_id: UUID, q: str) -> ColumnElement[bool]:
    """Name, number, or the text of any message in the chat."""
    pattern = _like_pattern(q)
    m = aliased(MessageRow)
    in_text = exists().where(
        *_chat_messages_of(company_id, m), m.thread_ref == r.c.ref, m.text.ilike(pattern, escape="\\")
    )
    return or_(Person.display_name.ilike(pattern, escape="\\"), r.c.ref.ilike(pattern, escape="\\"), in_text)


def _apply_filter(stmt: Select[Any], r: Any, company_id: UUID, flt: ChatFilter, q: str | None) -> Select[Any]:
    if flt == "unread":
        stmt = stmt.where(_unread_count(r, company_id) > 0)
    elif flt == "tenants":
        stmt = stmt.where(Person.kind == PersonKind.tenant)
    elif flt == "contractors":
        stmt = stmt.where(Person.kind == PersonKind.contractor)
    if q:
        stmt = stmt.where(_matches(r, company_id, q))
    return stmt


def chat_list(
    session: Session,
    company_id: UUID,
    *,
    before: Cursor | None,
    limit: int,
    filter: ChatFilter = "all",
    q: str | None = None,
) -> list[ChatSummary]:
    """One row per chat, newest activity first; `before` is the (last_at, last_message_id) of the previous page."""
    r = _ranked(company_id).subquery()
    identity = and_(
        ChannelIdentity.company_id == company_id,
        ChannelIdentity.channel == Channel.whatsapp,
        ChannelIdentity.identity == r.c.ref,
        ChannelIdentity.valid_to.is_(None),
    )
    stmt = (
        select(r, Person.display_name, Person.kind.label("person_kind"), _unread_count(r, company_id).label("unread"))
        .select_from(r)
        .outerjoin(ChannelIdentity, identity)
        .outerjoin(Person, and_(Person.id == ChannelIdentity.person_id, Person.company_id == company_id))
        .where(r.c.rn == 1)
    )
    stmt = _apply_filter(stmt, r, company_id, filter, q)
    if before is not None:
        stmt = stmt.where(tuple_(r.c.sent_at, r.c.id) < tuple_(*before))
    stmt = stmt.order_by(r.c.sent_at.desc(), r.c.id.desc()).limit(max(1, min(limit, MAX_PAGE)))
    return [_summary(row) for row in session.execute(stmt)]


def _summary(row: Any) -> ChatSummary:
    return ChatSummary(
        chat_key=row.ref,
        name=row.display_name,
        person_kind=row.person_kind,
        last_message_id=row.id,
        last_at=row.sent_at,
        last_text=row.text,
        last_kind=row.msg_kind,
        last_direction=row.direction,
        last_delivery=row.delivery,
        last_pending=bool(row.pending),
        unread=row.unread,
    )


def chat_contact(session: Session, company_id: UUID, chat_key: str) -> tuple[str | None, PersonKind | None]:
    """Name and kind of the person whose current WhatsApp identity is `chat_key`; (None, None) for a stranger."""
    stmt = (
        select(Person.display_name, Person.kind)
        .join(ChannelIdentity, ChannelIdentity.person_id == Person.id)
        .where(
            Person.company_id == company_id,
            ChannelIdentity.company_id == company_id,
            ChannelIdentity.channel == Channel.whatsapp,
            ChannelIdentity.identity == chat_key,
            ChannelIdentity.valid_to.is_(None),
        )
        .limit(1)
    )
    row = session.execute(stmt).first()
    return (row.display_name, row.kind) if row is not None else (None, None)


def quoted_messages(session: Session, company_id: UUID, chat_key: str, provider_ids: set[str]) -> dict[str, MessageRow]:
    """Messages of this chat by `provider_msg_id`, for resolving the messages a reply quotes. The id is unique per
    (company, channel), so each maps to one row."""
    if not provider_ids:
        return {}
    stmt = select(MessageRow).where(
        *_chat_messages_of(company_id), MessageRow.thread_ref == chat_key, MessageRow.provider_msg_id.in_(provider_ids)
    )
    return {m.provider_msg_id: m for m in session.scalars(stmt)}


def chat_messages(
    session: Session, company_id: UUID, chat_key: str, *, before: Cursor | None, limit: int
) -> list[MessageRow]:
    """The newest `limit` messages before the cursor, oldest first. Unknown or foreign chats yield `[]`."""
    stmt = select(MessageRow).where(*_chat_messages_of(company_id), MessageRow.thread_ref == chat_key)
    if before is not None:
        stmt = stmt.where(tuple_(MessageRow.sent_at, MessageRow.id) < tuple_(*before))
    stmt = stmt.order_by(MessageRow.sent_at.desc(), MessageRow.id.desc()).limit(max(1, min(limit, MAX_PAGE)))
    return list(reversed(session.scalars(stmt).all()))


def mark_read(session: Session, company_id: UUID, chat_key: str, now: datetime) -> None:
    """Upsert the read marker; an older `now` never moves it backwards."""
    ins = insert(ChatRead).values(company_id=company_id, chat_key=chat_key, last_read_at=now)
    stmt = ins.on_conflict_do_update(
        index_elements=[ChatRead.company_id, ChatRead.chat_key],
        set_={"last_read_at": func.greatest(ChatRead.last_read_at, ins.excluded.last_read_at)},
    )
    session.execute(stmt)


def latest_inbound(session: Session, company_id: UUID, chat_key: str) -> MessageRow | None:
    stmt = (
        select(MessageRow)
        .where(
            *_chat_messages_of(company_id),
            MessageRow.thread_ref == chat_key,
            MessageRow.direction == Direction.inbound,
        )
        .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def latest_case_id(session: Session, company_id: UUID, chat_key: str) -> UUID | None:
    """Case of the newest message in the chat that is linked to one."""
    stmt = (
        select(CaseLink.case_id)
        .join(MessageRow, MessageRow.id == CaseLink.message_id)
        .where(CaseLink.company_id == company_id, *_chat_messages_of(company_id), MessageRow.thread_ref == chat_key)
        .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def suggestions(session: Session, company_id: UUID, chat_key: str) -> tuple[UUID | None, list[str]]:
    """Open reply draft for the chat's latest inbound message: its action id and up to 3 body variants."""
    inbound = latest_inbound(session, company_id, chat_key)
    if inbound is None:
        return None, []
    stmt = (
        select(ActionRow)
        .where(
            ActionRow.company_id == company_id,
            ActionRow.type == ActionType.reply_draft,
            ActionRow.status.in_(_OPEN_DRAFT),
            ActionRow.context_ref.contains([inbound.id]),
        )
        .order_by(ActionRow.created_at.desc(), ActionRow.id.desc())
        .limit(1)
    )
    action = session.scalars(stmt).first()
    if action is None:
        return None, []
    raw = action.payload.get("body_variants")
    variants = [v for v in raw if isinstance(v, str) and v.strip()] if isinstance(raw, list) else []
    return action.id, variants[:MAX_SUGGESTIONS]
