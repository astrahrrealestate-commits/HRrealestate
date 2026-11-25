"""Read-side queries for the dashboard API. Every function requires `company_id` (CLAUDE.md invariant 4)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, ScalarSelect, Select, and_, func, select, tuple_
from sqlalchemy.orm import Session, aliased

from app.contracts import Channel, Direction
from app.contracts.thread_key import MAX_REF_LEN as MAX_REF_LEN
from app.contracts.thread_key import BadThreadKeyError as BadThreadKeyError
from app.contracts.thread_key import decode_thread_key as decode_thread_key
from app.contracts.thread_key import encode_thread_key as encode_thread_key
from app.core.errors import EstateOSError
from app.db.enums import PipelineStatus
from app.db.models.dashboard import OwnerFeed
from app.db.models.directory import Person
from app.db.models.ingestion import AttachmentRow, MessageRow, not_chat_only
from app.db.models.pipeline import CaseLink, UnderstandingRow

MAX_PAGE = 100
MAX_THREAD_MESSAGES = 200
MAX_REASON_LEN = 200
Cursor = tuple[datetime, UUID]


class BadCursorError(EstateOSError):
    """A feed cursor that is not `{created_at_iso}|{id}` with a timezone-aware timestamp."""


def parse_cursor(raw: str) -> Cursor:
    stamp, sep, ident = raw.partition("|")
    try:
        if not sep:
            raise ValueError("missing separator")
        created_at = datetime.fromisoformat(stamp.replace(" ", "+"))  # a raw "+" in a query string decodes to " "
        if created_at.tzinfo is None:
            raise ValueError("naive timestamp")
        return created_at, UUID(ident)
    except ValueError:
        raise BadCursorError("invalid cursor") from None


def feed_page(session: Session, company_id: UUID, after: Cursor | None, limit: int) -> list[OwnerFeed]:
    q = select(OwnerFeed).where(OwnerFeed.company_id == company_id)
    if after is not None:
        q = q.where(tuple_(OwnerFeed.created_at, OwnerFeed.id) > tuple_(*after))
    capped = max(1, min(limit, MAX_PAGE))
    return list(session.scalars(q.order_by(OwnerFeed.created_at, OwnerFeed.id).limit(capped)))


@dataclass(frozen=True)
class ThreadRow:
    thread_key: str
    channel: Channel
    last_at: datetime
    last_message_id: UUID
    last_text: str
    sender: str
    person_name: str | None
    case_id: UUID | None
    unread_pipeline: PipelineStatus
    message_count: int


def _thread_ref() -> ColumnElement[str]:
    return func.coalesce(MessageRow.thread_ref, MessageRow.provider_msg_id)


def _count_inbound(status: PipelineStatus) -> ColumnElement[int]:
    """Inbound messages of the thread in `status`, as a window over the thread partition."""
    cond = and_(MessageRow.direction == Direction.inbound, MessageRow.pipeline_status == status)
    return func.count().filter(cond).over(partition_by=(MessageRow.channel, _thread_ref()))


def _ranked(company_id: UUID) -> Select[tuple[object, ...]]:
    part = (MessageRow.channel, _thread_ref())
    return select(
        MessageRow.id.label("id"),
        MessageRow.channel.label("channel"),
        _thread_ref().label("ref"),
        MessageRow.sent_at.label("sent_at"),
        MessageRow.text.label("text"),
        MessageRow.sender_identity.label("sender"),
        MessageRow.person_id.label("person_id"),
        func.row_number()
        .over(partition_by=part, order_by=(MessageRow.sent_at.desc(), MessageRow.id.desc()))
        .label("rn"),
        func.count().over(partition_by=part).label("n"),
        _count_inbound(PipelineStatus.pending).label("n_pending"),
        _count_inbound(PipelineStatus.failed).label("n_failed"),
    ).where(MessageRow.company_id == company_id, not_chat_only())


def _worst(pending: int, failed: int) -> PipelineStatus:
    if pending:
        return PipelineStatus.pending
    return PipelineStatus.failed if failed else PipelineStatus.done


def _same_thread(m: Any, r: Any) -> ColumnElement[bool]:
    return and_(m.channel == r.c.channel, func.coalesce(m.thread_ref, m.provider_msg_id) == r.c.ref)


def _case_id(r: Any, company_id: UUID) -> ScalarSelect[UUID]:
    """Case of the newest linked message in the thread."""
    m = aliased(MessageRow)
    return (
        select(CaseLink.case_id)
        .join(m, and_(m.id == CaseLink.message_id, m.company_id == company_id))
        .where(CaseLink.company_id == company_id, _same_thread(m, r))
        .order_by(m.sent_at.desc(), m.id.desc())
        .limit(1)
        .scalar_subquery()
    )


def _person_name(r: Any, company_id: UUID) -> ScalarSelect[str]:
    """Person of the newest inbound message that has one (the thread's last message may be our own reply)."""
    m = aliased(MessageRow)
    return (
        select(Person.display_name)
        .join(m, and_(m.person_id == Person.id, m.company_id == company_id))
        .where(Person.company_id == company_id, m.direction == Direction.inbound, _same_thread(m, r))
        .order_by(m.sent_at.desc(), m.id.desc())
        .limit(1)
        .scalar_subquery()
    )


def inbox_page(session: Session, company_id: UUID, *, before: Cursor | None, limit: int) -> list[ThreadRow]:
    """One row per thread, newest activity first; `before` is the (last_at, last_message_id) of the previous page."""
    r = _ranked(company_id).subquery()
    q = select(r, _person_name(r, company_id).label("display_name"), _case_id(r, company_id).label("case_id"))
    q = q.where(r.c.rn == 1)
    if before is not None:
        q = q.where(tuple_(r.c.sent_at, r.c.id) < tuple_(*before))
    q = q.order_by(r.c.sent_at.desc(), r.c.id.desc()).limit(max(1, min(limit, MAX_PAGE)))
    return [
        ThreadRow(
            thread_key=encode_thread_key(row.channel, row.ref),
            channel=row.channel,
            last_at=row.sent_at,
            last_message_id=row.id,
            last_text=row.text,
            sender=row.sender,
            person_name=row.display_name,
            case_id=row.case_id,
            unread_pipeline=_worst(row.n_pending, row.n_failed),
            message_count=row.n,
        )
        for row in session.execute(q)
    ]


def thread_messages(session: Session, company_id: UUID, thread_key: str) -> list[MessageRow]:
    """Oldest first, newest 200 at most. Raises `BadThreadKeyError`; an unknown or foreign key yields `[]`."""
    channel, ref = decode_thread_key(thread_key)
    q = (
        select(MessageRow)
        .where(
            MessageRow.company_id == company_id,
            MessageRow.channel == channel,
            func.coalesce(MessageRow.thread_ref, MessageRow.provider_msg_id) == ref,
            not_chat_only(),
        )
        .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
        .limit(MAX_THREAD_MESSAGES)
    )
    return list(reversed(session.scalars(q).all()))


def attachments_for(session: Session, company_id: UUID, message_ids: list[UUID]) -> list[AttachmentRow]:
    q = select(AttachmentRow).where(AttachmentRow.company_id == company_id, AttachmentRow.message_id.in_(message_ids))
    return list(session.scalars(q.order_by(AttachmentRow.created_at, AttachmentRow.id)))


def suspicious_flags(
    session: Session, company_id: UUID, message_ids: list[UUID]
) -> dict[UUID, tuple[bool, str | None]]:
    """(flag, reason) from the understanding of each message; messages without one are (False, None)."""
    q = select(UnderstandingRow.message_id, UnderstandingRow.body).where(
        UnderstandingRow.company_id == company_id, UnderstandingRow.message_id.in_(message_ids)
    )
    out: dict[UUID, tuple[bool, str | None]] = {}
    for message_id, body in session.execute(q):
        info = body.get("suspicious") or {}
        reason = info.get("reason")
        out[message_id] = (bool(info.get("flag", False)), str(reason)[:MAX_REASON_LEN] if reason else None)
    return out
