"""After a reload: draft the conversations still waiting for Harjot (M13 T2, option A in the spec).

History mail is never drafted on its own. This looks at every open case and drafts only its newest mail, and only when
it is recent, needs an answer and nobody has given one. "Answered" also means: Harjot's own mail came after it, or a
later mail quotes his reply (he answers from his own mailbox, so the quote is often the only record). The owner gets no
cards or messages for these; the drafts wait in the dashboard like any other, and nothing is sent without his approval.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Engine, or_, select
from sqlalchemy.orm import Session

from app.channels.gmail.quoted import quoted_owner_reply
from app.context.message_origin import full_text, is_owner_authored
from app.contracts import ActionType, Channel, Direction
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import ApprovalStatus
from app.db.models import ActionRow, Approval, Case, CaseLink, MessageRow, UnderstandingRow
from app.ingestion.process import owner_addresses
from app.pipeline.case_repo import OPEN_STATES
from app.pipeline.propose import propose_for_message
from app.workflows.mail_purge_scope import mailbox_company

log = get_logger(__name__)
MAX_AGE_DAYS = 14

Prepare = Callable[[Engine, Settings, UUID], None]  # read, review and research (T8)
RefreshMemory = Callable[[Engine, Settings, UUID, UUID], None]  # (engine, settings, company, person) (T7)


class SkipReason(StrEnum):
    no_message = "no_message"
    other_channel = "other_channel"
    answered = "answered"
    answered_in_quote = "answered_in_quote"
    no_reply_needed = "no_reply_needed"
    too_old = "too_old"
    draft_waiting = "draft_waiting"
    already_proposed = "already_proposed"
    no_draft = "no_draft"
    failed = "failed"


@dataclass(frozen=True)
class DraftOpenReport:
    """Case ids only. In a dry run `drafted` is what would be drafted."""

    drafted: tuple[UUID, ...]
    skipped: tuple[tuple[UUID, SkipReason], ...]


@dataclass(frozen=True)
class _Candidate:
    case_id: UUID
    message_id: UUID
    person_id: UUID | None


def no_memory_refresh(_engine: Engine, _settings: Settings, _company_id: UUID, _person_id: UUID) -> None:
    """Person memory (T7) is not wired yet: drafts use the memory as it is."""


def _open_cases(session: Session, company_id: UUID) -> list[UUID]:
    return list(
        session.scalars(
            select(Case.id).where(Case.company_id == company_id, Case.state.in_(OPEN_STATES)).order_by(Case.id)
        )
    )


def _conversation(session: Session, company_id: UUID, case_id: UUID) -> list[MessageRow]:
    """The case's messages and everything else in their Gmail threads (a reply of ours may carry no case link), newest
    first."""
    linked = select(CaseLink.message_id).where(CaseLink.company_id == company_id, CaseLink.case_id == case_id)
    threads = select(MessageRow.thread_ref).where(
        MessageRow.company_id == company_id,
        MessageRow.channel == Channel.gmail,
        MessageRow.thread_ref.is_not(None),
        MessageRow.id.in_(linked),
    )
    in_thread = (MessageRow.channel == Channel.gmail) & MessageRow.thread_ref.in_(threads)
    return list(
        session.scalars(
            select(MessageRow)
            .where(MessageRow.company_id == company_id, or_(MessageRow.id.in_(linked), in_thread))
            .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
        )
    )


def _needs_reply(session: Session, company_id: UUID, message_id: UUID) -> bool:
    body = session.scalar(
        select(UnderstandingRow.body).where(
            UnderstandingRow.company_id == company_id, UnderstandingRow.message_id == message_id
        )
    )
    return bool(body and body.get("requires_reply"))


def _live_reply(session: Session, company_id: UUID, case_id: UUID) -> bool:
    return (
        session.scalar(
            select(Approval.id)
            .join(ActionRow, (ActionRow.id == Approval.action_id) & (ActionRow.company_id == company_id))
            .where(
                Approval.company_id == company_id,
                ActionRow.case_id == case_id,
                ActionRow.type == ActionType.reply_draft,
                Approval.status.in_([ApprovalStatus.pending, ApprovalStatus.approved]),
            )
            .limit(1)
        )
        is not None
    )


def _proposed(session: Session, company_id: UUID, message_id: UUID) -> bool:
    return (
        session.scalar(
            select(ActionRow.id)
            .where(ActionRow.company_id == company_id, ActionRow.context_ref.contains([message_id]))
            .limit(1)
        )
        is not None
    )


def _consider(
    session: Session, company_id: UUID, case_id: UUID, owner: frozenset[str], cutoff: datetime
) -> _Candidate | SkipReason:
    messages = _conversation(session, company_id, case_id)
    if not messages:
        return SkipReason.no_message
    newest = messages[0]
    if newest.direction is Direction.outbound or is_owner_authored(newest):
        return SkipReason.answered
    if newest.channel is not Channel.gmail:
        return SkipReason.other_channel
    if not _needs_reply(session, company_id, newest.id):
        quoted = quoted_owner_reply(full_text(newest), owner)
        return SkipReason.answered_in_quote if quoted else SkipReason.no_reply_needed
    if newest.sent_at < cutoff:
        return SkipReason.too_old
    if _live_reply(session, company_id, case_id):
        return SkipReason.draft_waiting
    if _proposed(session, company_id, newest.id):
        return SkipReason.already_proposed
    return _Candidate(case_id, newest.id, newest.person_id)


def _draft(
    engine: Engine, settings: Settings, company_id: UUID, found: _Candidate, prepare: Prepare, memory: RefreshMemory
) -> SkipReason | None:
    """None when a draft now waits for Harjot; one case that fails never stops the others."""
    try:
        prepare(engine, settings, found.message_id)
    except Exception as exc:  # research helps a draft but never blocks one
        log.warning("mail_reload.prepare_failed", case_id=str(found.case_id), reason=type(exc).__name__)
    if found.person_id is not None:
        try:
            memory(engine, settings, company_id, found.person_id)
        except Exception as exc:
            log.warning("mail_reload.memory_failed", case_id=str(found.case_id), reason=type(exc).__name__)
    try:
        result = propose_for_message(engine, settings, found.message_id)
    except Exception as exc:
        log.error("mail_reload.draft_failed", case_id=str(found.case_id), reason=type(exc).__name__)
        return SkipReason.failed
    return None if result.approval_ids else SkipReason.no_draft


def draft_open(
    engine: Engine,
    settings: Settings,
    mailbox: str,
    *,
    max_age_days: int = MAX_AGE_DAYS,
    dry_run: bool,
    prepare: Prepare,
    refresh_memory: RefreshMemory = no_memory_refresh,
) -> DraftOpenReport:
    """Draft the newest unanswered mail of every open case. A dry run writes nothing and calls no model."""
    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    drafted: list[UUID] = []
    skipped: list[tuple[UUID, SkipReason]] = []
    with Session(engine) as session:
        company_id = mailbox_company(session, mailbox)
        cases = _open_cases(session, company_id)
    owner = owner_addresses(engine, company_id)
    for case_id in cases:
        with Session(engine) as session:
            found = _consider(session, company_id, case_id, owner, cutoff)
        if isinstance(found, SkipReason):
            skipped.append((case_id, found))
            continue
        failed = None if dry_run else _draft(engine, settings, company_id, found, prepare, refresh_memory)
        if failed is None:
            drafted.append(case_id)
        else:
            skipped.append((case_id, failed))
    log.info("mail_reload.draft_open", drafted=len(drafted), skipped=len(skipped), dry_run=dry_run)
    return DraftOpenReport(tuple(drafted), tuple(skipped))
