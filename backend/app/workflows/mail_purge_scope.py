"""What a purge of one mailbox covers (M13 T2): the ids of every row that goes, read in one place.

The company comes from the mailbox's own channel account and every query filters by it. In scope is the company's Gmail
mail of that mailbox, plus mail no mailbox was recorded for (the old imports); another connected mailbox's mail stays.
A case goes when all its messages go; a case that also holds WhatsApp, and a case without any message (opened from
BRIXX or by hand), stays.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, String, Uuid, any_, bindparam, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.contracts import Channel
from app.db.enums import QuoteSource
from app.db.models import (
    ActionRow,
    Approval,
    AttachmentRow,
    Case,
    CaseLink,
    DocumentRow,
    MessageChunk,
    MessageRow,
    QuoteReview,
    QuoteRow,
    RawEvent,
    WaitRow,
)
from app.ingestion.repository import resolve_channel_account

Ids = tuple[UUID, ...]


def one_of(column: Any, ids: Sequence[UUID]) -> ColumnElement[bool]:
    """`column = ANY(ids)`: one parameter, however many ids (thousands of them would not fit in an IN list)."""
    return column == any_(bindparam(None, list(ids), type_=ARRAY(Uuid)))  # type: ignore[no-any-return]


def names_one_of(column: Any, ids: Sequence[UUID]) -> ColumnElement[bool]:
    """The same for a text column that holds an id."""
    return column == any_(bindparam(None, [str(i) for i in ids], type_=ARRAY(String)))  # type: ignore[no-any-return]


@dataclass(frozen=True)
class PurgeScope:
    company_id: UUID
    messages: Ids
    raw_events: Ids
    attachments: Ids
    documents: Ids
    chunks: Ids
    cases: Ids  # left with no message
    actions: Ids
    approvals: Ids
    waits: Ids  # of the cases that go
    quotes: Ids
    reviews: Ids
    oldest: datetime | None
    newest: datetime | None


def mailbox_company(session: Session, mailbox: str) -> UUID:
    return resolve_channel_account(session, Channel.gmail, mailbox.strip().lower()).company_id


def of_mailbox(company_id: UUID, mailbox: str) -> ColumnElement[bool]:
    """The company's stored Gmail messages of this mailbox (or of no recorded mailbox)."""
    received_in = func.lower(MessageRow.meta["mailbox"].astext)
    return (
        (MessageRow.company_id == company_id)
        & (MessageRow.channel == Channel.gmail)
        & or_(received_in == mailbox.strip().lower(), received_in.is_(None))
    )


def _ids(session: Session, query: Any) -> Ids:
    return tuple(session.scalars(query))


def _raw_events(session: Session, company_id: UUID, mailbox: str, messages: Ids) -> Ids:
    received_in = func.lower(RawEvent.payload["mailbox"].astext)
    theirs = select(MessageRow.raw_event_id).where(MessageRow.company_id == company_id, one_of(MessageRow.id, messages))
    kept = select(MessageRow.id).where(
        MessageRow.company_id == company_id,
        MessageRow.raw_event_id == RawEvent.id,
        ~one_of(MessageRow.id, messages),
    )
    return _ids(
        session,
        select(RawEvent.id).where(
            RawEvent.company_id == company_id,
            RawEvent.provider == Channel.gmail,
            or_(received_in == mailbox, received_in.is_(None), RawEvent.id.in_(theirs)),
            ~kept.exists(),
        ),
    )


def _emptied_cases(session: Session, company_id: UUID, messages: Ids) -> Ids:
    mine = select(CaseLink.case_id).where(CaseLink.company_id == company_id, one_of(CaseLink.message_id, messages))
    other = select(CaseLink.case_id).where(CaseLink.company_id == company_id, ~one_of(CaseLink.message_id, messages))
    return _ids(session, select(Case.id).where(Case.company_id == company_id, Case.id.in_(mine), Case.id.not_in(other)))


def load_scope(session: Session, mailbox: str) -> PurgeScope:
    box = mailbox.strip().lower()
    cid = mailbox_company(session, box)
    messages = _ids(session, select(MessageRow.id).where(of_mailbox(cid, box)))
    attachments = _ids(
        session,
        select(AttachmentRow.id).where(AttachmentRow.company_id == cid, one_of(AttachmentRow.message_id, messages)),
    )
    cases = _emptied_cases(session, cid, messages)
    about_mail = ActionRow.context_ref.overlap(bindparam(None, list(messages), type_=ARRAY(Uuid)))
    actions = _ids(
        session,
        select(ActionRow.id).where(ActionRow.company_id == cid, or_(one_of(ActionRow.case_id, cases), about_mail)),
    )
    quotes = _ids(
        session,
        select(QuoteRow.id).where(
            QuoteRow.company_id == cid, QuoteRow.source == QuoteSource.message, one_of(QuoteRow.source_id, messages)
        ),
    )
    held = MessageChunk.message_ids.overlap(bindparam(None, list(messages), type_=ARRAY(Uuid)))
    edges = or_(one_of(MessageChunk.first_message_id, messages), one_of(MessageChunk.last_message_id, messages))
    oldest, newest = session.execute(
        select(func.min(MessageRow.sent_at), func.max(MessageRow.sent_at)).where(
            MessageRow.company_id == cid, one_of(MessageRow.id, messages)
        )
    ).one()
    return PurgeScope(
        company_id=cid, messages=messages, attachments=attachments, cases=cases, actions=actions, quotes=quotes,
        raw_events=_raw_events(session, cid, box, messages),
        documents=_ids(session, select(DocumentRow.id).where(
            DocumentRow.company_id == cid, one_of(DocumentRow.attachment_id, attachments))),
        chunks=_ids(session, select(MessageChunk.id).where(MessageChunk.company_id == cid, or_(held, edges))),
        approvals=_ids(session, select(Approval.id).where(
            Approval.company_id == cid, one_of(Approval.action_id, actions))),
        waits=_ids(session, select(WaitRow.id).where(WaitRow.company_id == cid, one_of(WaitRow.case_id, cases))),
        reviews=_ids(session, select(QuoteReview.id).where(
            QuoteReview.company_id == cid, one_of(QuoteReview.quote_id, quotes))),
        oldest=oldest, newest=newest,
    )  # fmt: skip
