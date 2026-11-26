"""Delete the stored Gmail data of one mailbox so it can be reloaded (M13 T2). Run by `mail_reload_cli` only, with the
worker stopped and a database snapshot taken (`scripts/mail_reload.sh`).

`preview` counts and deletes nothing. `purge` needs the typed confirmation, then deletes in one transaction, children
first. Stays: people, units, leases, WhatsApp, BRIXX, `model_calls`, the send log (`sends`, with `action_id` emptied),
calendar events (their case emptied), due diligence reports, the files in Drive and the objects in S3. Raw events go
too: they are unique per provider message, so a mail whose raw event stayed could never be recorded again.

Before anything is deleted, `stamp` is called with the Drive file and content hash of every filed document that goes:
it writes the hash onto the Drive file, so the reload finds that file instead of uploading a second copy.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.errors import EstateOSError
from app.core.logging import get_logger
from app.db.enums import DocLinkKind, DocumentStatus, OutboxStatus
from app.db.models import (
    ActionRevision,
    ActionRow,
    Approval,
    AttachmentRow,
    CalendarEventRow,
    Case,
    CaseEvent,
    CaseLink,
    Company,
    DDDocumentRead,
    DDReviewDocument,
    DocumentLink,
    DocumentRow,
    DriveReorgItem,
    MessageChunk,
    MessageIndexState,
    MessageRow,
    Outcome,
    OwnerFeed,
    OwnerOutbox,
    PersonProfile,
    PriceSnapshot,
    QuoteLineRow,
    QuoteReview,
    QuoteRow,
    RawEvent,
    Send,
    TaskRow,
    TicketEdit,
    Timer,
    UnderstandingRow,
    WaitRow,
)
from app.workflows.mail_purge_scope import PurgeScope, load_scope, names_one_of, one_of

log = get_logger(__name__)
FileHash = tuple[str, str]  # (Drive file id, content sha256)
Stamp = Callable[[UUID, Sequence[FileHash]], None]


class PurgeRefusedError(EstateOSError):
    """The purge was not confirmed with exactly the words asked for."""


@dataclass(frozen=True)
class ReloadPreview:
    """Counts only: nothing here quotes a message."""

    messages: int
    attachments: int
    raw_events: int
    cases: int
    actions: int
    approvals: int
    documents: int
    quotes: int
    sends: int
    oldest: datetime | None
    newest: datetime | None
    tables: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class _Doomed:
    """Rows of one table that go, as a filter."""

    model: Any
    where: Any

    @property
    def table(self) -> str:
        return str(self.model.__tablename__)


def _key_names(column: Any, position: int, ids: Sequence[UUID]) -> Any:
    return names_one_of(func.split_part(column, ":", position), ids)


def _owner_feed(scope: PurgeScope) -> Any:
    """Cards about what goes: by their reference, or by the id inside their key (`{company}:{prefix}:{id}...`)."""
    ids = (*scope.messages, *scope.attachments, *scope.approvals, *scope.actions, *scope.quotes, *scope.reviews)
    key = OwnerFeed.idempotency_key
    return or_(one_of(OwnerFeed.ref_id, ids), _key_names(key, 3, ids), _key_names(key, 4, ids))


def _finance(s: PurgeScope) -> list[_Doomed]:
    return [
        _Doomed(QuoteReview, one_of(QuoteReview.quote_id, s.quotes)),
        _Doomed(QuoteLineRow, one_of(QuoteLineRow.quote_id, s.quotes)),
        _Doomed(QuoteRow, one_of(QuoteRow.id, s.quotes)),
        _Doomed(PriceSnapshot,
                or_(one_of(PriceSnapshot.action_id, s.actions), one_of(PriceSnapshot.case_id, s.cases))),
    ]  # fmt: skip


def _documents(s: PurgeScope) -> list[_Doomed]:
    """Document chunks and links go with their document (ON DELETE CASCADE); the links of other documents to a case
    that goes are removed here (`ref_id` has no foreign key)."""
    to_case = (DocumentLink.kind == DocLinkKind.case) & one_of(DocumentLink.ref_id, s.cases)
    return [
        _Doomed(DDReviewDocument, one_of(DDReviewDocument.document_id, s.documents)),
        _Doomed(DDDocumentRead, one_of(DDDocumentRead.document_id, s.documents)),
        _Doomed(DriveReorgItem, one_of(DriveReorgItem.document_id, s.documents)),
        _Doomed(DocumentLink, or_(one_of(DocumentLink.document_id, s.documents), to_case)),
        _Doomed(DocumentRow, one_of(DocumentRow.id, s.documents)),
    ]


def _actions(s: PurgeScope) -> list[_Doomed]:
    return [
        _Doomed(OwnerFeed, _owner_feed(s)),
        _Doomed(Outcome, one_of(Outcome.action_id, s.actions)),
        _Doomed(Approval, one_of(Approval.id, s.approvals)),
        _Doomed(ActionRevision, one_of(ActionRevision.action_id, s.actions)),
        _Doomed(Timer, names_one_of(Timer.payload["wait_id"].astext, s.waits)),
        _Doomed(WaitRow, one_of(WaitRow.id, s.waits)),
        _Doomed(TaskRow, or_(one_of(TaskRow.action_id, s.actions), one_of(TaskRow.case_id, s.cases))),
        _Doomed(ActionRow, one_of(ActionRow.id, s.actions)),
    ]


def _messages(s: PurgeScope) -> list[_Doomed]:
    return [
        _Doomed(AttachmentRow, one_of(AttachmentRow.id, s.attachments)),
        _Doomed(UnderstandingRow, one_of(UnderstandingRow.message_id, s.messages)),
        _Doomed(CaseLink, one_of(CaseLink.message_id, s.messages)),
        _Doomed(MessageRow, one_of(MessageRow.id, s.messages)),
        _Doomed(RawEvent, one_of(RawEvent.id, s.raw_events)),
        _Doomed(CaseEvent, one_of(CaseEvent.case_id, s.cases)),
        _Doomed(TicketEdit, one_of(TicketEdit.case_id, s.cases)),
        _Doomed(Case, one_of(Case.id, s.cases)),
    ]


def _doomed(s: PurgeScope) -> list[_Doomed]:
    """Every table the purge deletes from, children before parents."""
    index = or_(one_of(MessageIndexState.message_id, s.messages), one_of(MessageIndexState.chunk_id, s.chunks))
    return [
        _Doomed(MessageIndexState, index),
        _Doomed(MessageChunk, one_of(MessageChunk.id, s.chunks)),
        *_finance(s),
        *_actions(s),
        *_documents(s),
        *_messages(s),
    ]


def _count(session: Session, company_id: UUID, model: Any, where: Any) -> int:
    query = select(func.count()).select_from(model).where(model.company_id == company_id, where)
    return int(session.scalar(query) or 0)


def _report(session: Session, s: PurgeScope) -> ReloadPreview:
    tables = {d.table: _count(session, s.company_id, d.model, d.where) for d in _doomed(s)}
    return ReloadPreview(
        messages=len(s.messages), attachments=len(s.attachments), raw_events=len(s.raw_events), cases=len(s.cases),
        actions=len(s.actions), approvals=len(s.approvals), documents=len(s.documents), quotes=len(s.quotes),
        sends=_count(session, s.company_id, Send, one_of(Send.action_id, s.actions)),
        oldest=s.oldest, newest=s.newest, tables=tables,
    )  # fmt: skip


def preview(engine: Engine, mailbox: str) -> ReloadPreview:
    """What `purge` would delete now. Reads only."""
    with Session(engine) as session:
        return _report(session, load_scope(session, mailbox))


def _detach(session: Session, s: PurgeScope) -> None:
    """Rows that stay stop pointing at rows that go."""
    cid = s.company_id
    session.execute(
        update(Send).where(Send.company_id == cid, one_of(Send.action_id, s.actions)).values(action_id=None)
    )
    session.execute(
        update(WaitRow)
        .where(WaitRow.company_id == cid, one_of(WaitRow.source_action_id, s.actions))
        .values(source_action_id=None)
    )
    session.execute(
        update(CalendarEventRow)
        .where(CalendarEventRow.company_id == cid, one_of(CalendarEventRow.case_id, s.cases))
        .values(case_id=None)
    )
    session.execute(
        update(QuoteRow)
        .where(QuoteRow.company_id == cid, one_of(QuoteRow.case_id, s.cases), ~one_of(QuoteRow.id, s.quotes))
        .values(case_id=None)
    )
    _cancel_outbox(session, s)
    _forget_memory_marks(session, s)


def _cancel_outbox(session: Session, s: PurgeScope) -> None:
    """Owner messages still waiting for the WhatsApp window about what goes."""
    ids = (*s.messages, *s.attachments, *s.approvals, *s.actions)
    key = OwnerOutbox.idempotency_key
    session.execute(
        update(OwnerOutbox)
        .where(
            OwnerOutbox.company_id == s.company_id,
            OwnerOutbox.status == OutboxStatus.queued,
            or_(_key_names(key, 2, ids), _key_names(key, 3, ids)),
        )
        .values(status=OutboxStatus.cancelled)
    )


def _forget_memory_marks(session: Session, s: PurgeScope) -> None:
    """The memory of these people is read again from the reloaded mail: no marker may say it was read already."""
    people = select(MessageRow.person_id).where(
        MessageRow.company_id == s.company_id, one_of(MessageRow.id, s.messages)
    )
    session.execute(
        update(PersonProfile)
        .where(PersonProfile.company_id == s.company_id, PersonProfile.person_id.in_(people))
        .values(source_max_message_at=None, memory_at=None)
    )


def _filed(session: Session, s: PurgeScope) -> list[FileHash]:
    rows = session.execute(
        select(DocumentRow.drive_file_id, AttachmentRow.sha256)
        .join(AttachmentRow, AttachmentRow.id == DocumentRow.attachment_id)
        .where(
            DocumentRow.company_id == s.company_id,
            AttachmentRow.company_id == s.company_id,
            one_of(DocumentRow.id, s.documents),
            DocumentRow.status == DocumentStatus.filed,
            DocumentRow.drive_file_id.is_not(None),
        )
    )
    return [(str(file_id), sha256) for file_id, sha256 in rows]


def _skip_stamping(_company_id: UUID, _files: Sequence[FileHash]) -> None:
    """No Drive connected: nothing to find again after the reload."""


def purge(engine: Engine, mailbox: str, *, confirm: str, stamp: Stamp = _skip_stamping) -> ReloadPreview:
    """Delete the mailbox's stored mail and everything made from it; returns what was deleted. Refuses unless
    `confirm` is exactly `purge <mailbox>`. A second run finds nothing to delete."""
    if confirm != f"purge {mailbox}":
        raise PurgeRefusedError(f"not confirmed: pass exactly 'purge {mailbox}'")
    with Session(engine) as session:
        before = load_scope(session, mailbox)
        files = _filed(session, before)
    stamp(before.company_id, files)  # outside the transaction: it calls Drive; safe to repeat
    with Session(engine) as session, session.begin():
        session.scalar(select(Company.id).where(Company.id == before.company_id).with_for_update())
        scope = load_scope(session, mailbox)
        report = _report(session, scope)
        _detach(session, scope)
        for doomed in _doomed(scope):
            session.execute(delete(doomed.model).where(doomed.model.company_id == scope.company_id, doomed.where))
    log.info("mail_reload.purged", company_id=str(scope.company_id), messages=report.messages, cases=report.cases)
    return report
