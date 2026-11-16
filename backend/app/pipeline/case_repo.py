"""Case persistence: create, link messages (once), thread lookup, open candidates, summary CAS, state transitions.

Every function takes `company_id` (invariant 4) and flushes; the caller owns the transaction.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.context.person_profile import refresh_profile_deterministic
from app.contracts import CaseState, Category, Channel, Direction, Urgency, assert_transition
from app.core.errors import NotFoundError
from app.db.enums import CaseEventKind, LinkMethod
from app.db.models import Case, CaseEvent, CaseLink, Lease, LeaseParty, MessageRow

WHATSAPP_THREAD_WINDOW = timedelta(hours=72)
OPEN_STATES = (CaseState.open, CaseState.waiting_on_owner, CaseState.waiting_on_third_party)


@dataclass(frozen=True)
class CaseCandidate:
    case_id: UUID
    category: Category
    summary: str
    last_message_at: datetime | None


def get_case(session: Session, company_id: UUID, case_id: UUID) -> Case:
    case = session.scalar(select(Case).where(Case.id == case_id, Case.company_id == company_id))
    if case is None:
        raise NotFoundError(f"case {case_id} not found")
    return case


def create_case(
    session: Session, company_id: UUID, person_id: UUID | None, category: Category, urgency: Urgency
) -> UUID:
    unit_id = None
    lease_id = None
    if person_id:
        lease = session.scalars(
            select(Lease)
            .join(LeaseParty, LeaseParty.lease_id == Lease.id)
            .where(
                LeaseParty.person_id == person_id,
                LeaseParty.company_id == company_id,
                Lease.company_id == company_id,
            )
            # The current lease first (a tenant can have ended ones, or one per unit of a contract); every lease of
            # one mapper run shares created_at, so it never decides.
            .order_by(Lease.valid_to.is_(None).desc(), Lease.valid_to.desc(), Lease.valid_from.desc(), Lease.id.desc())
            .limit(1)
        ).first()
        if lease:
            unit_id = lease.unit_id
            lease_id = lease.id

    case = Case(
        company_id=company_id,
        primary_person_id=person_id,
        category=category,
        urgency=urgency,
        unit_id=unit_id,
        lease_id=lease_id,
    )
    session.add(case)
    session.flush()
    return case.id


def case_of_message(session: Session, company_id: UUID, message_id: UUID) -> UUID | None:
    return session.scalar(
        select(CaseLink.case_id).where(CaseLink.company_id == company_id, CaseLink.message_id == message_id)
    )


def link_message(
    session: Session, company_id: UUID, case_id: UUID, message_id: UUID, method: LinkMethod, confidence: float | None
) -> bool:
    """Link once (unique message_id). Returns True when this call created the link (and its audit event)."""
    inserted = session.execute(
        insert(CaseLink)
        .values(company_id=company_id, case_id=case_id, message_id=message_id, method=method, confidence=confidence)
        .on_conflict_do_nothing(index_elements=["message_id"])
        .returning(CaseLink.id)
    ).scalar()
    if inserted is not None:
        session.add(
            CaseEvent(
                company_id=company_id, case_id=case_id, kind=CaseEventKind.link, note=method.value, actor="system"
            )
        )
        session.flush()
    return inserted is not None


def thread_case(session: Session, company_id: UUID, message: MessageRow) -> UUID | None:
    """The open case already holding this thread. WhatsApp "threads" are the counterpart, so only recent messages
    (72 h) count; Gmail thread ids are real threads and count regardless of age."""
    if not message.thread_ref:
        return None
    query = (
        select(CaseLink.case_id)
        .join(MessageRow, MessageRow.id == CaseLink.message_id)
        .join(Case, Case.id == CaseLink.case_id)
        .where(
            CaseLink.company_id == company_id,
            MessageRow.channel == message.channel,
            MessageRow.thread_ref == message.thread_ref,
            MessageRow.id != message.id,
            Case.state.in_(OPEN_STATES),
        )
        .order_by(MessageRow.sent_at.desc())
        .limit(1)
    )
    if message.channel is Channel.whatsapp:
        query = query.where(MessageRow.sent_at >= message.sent_at - WHATSAPP_THREAD_WINDOW)
    return session.scalar(query)


def open_candidates(session: Session, company_id: UUID, person_id: UUID) -> list[CaseCandidate]:
    last = (
        select(CaseLink.case_id, func.max(MessageRow.sent_at).label("last_at"))
        .join(MessageRow, MessageRow.id == CaseLink.message_id)
        .where(CaseLink.company_id == company_id)
        .group_by(CaseLink.case_id)
        .subquery()
    )
    rows = session.execute(
        select(Case.id, Case.category, Case.summary, last.c.last_at)
        .outerjoin(last, last.c.case_id == Case.id)
        .where(Case.company_id == company_id, Case.primary_person_id == person_id, Case.state.in_(OPEN_STATES))
        .order_by(last.c.last_at.desc().nulls_last())
    ).all()
    return [CaseCandidate(r[0], r[1], r[2], r[3]) for r in rows]


def update_summary(session: Session, company_id: UUID, case_id: UUID, summary: str, *, expected_version: int) -> bool:
    """Compare-and-swap on `summary_version`: a stale writer (replayed step, concurrent message) loses."""
    result = session.execute(
        update(Case)
        .where(Case.id == case_id, Case.company_id == company_id, Case.summary_version == expected_version)
        .values(summary=summary, summary_version=expected_version + 1)
    )
    session.expire_all()
    return bool(result.rowcount)  # type: ignore[attr-defined]  # CursorResult of an UPDATE


def transition(session: Session, company_id: UUID, case_id: UUID, new_state: CaseState, *, actor: str) -> None:
    case = get_case(session, company_id, case_id)
    if case.state is new_state:
        return
    assert_transition(case.state, new_state)
    session.add(
        CaseEvent(
            company_id=company_id, case_id=case_id, kind=CaseEventKind.state_change,
            from_state=case.state, to_state=new_state, actor=actor,
        )
    )  # fmt: skip
    case.state = new_state
    if new_state in (CaseState.resolved, CaseState.closed):
        case.resolved_at = case.resolved_at or func.now()
        if case.primary_person_id is not None:
            refresh_profile_deterministic(session, company_id, case.primary_person_id)
    session.flush()


def link_outbound_reply(session: Session, message_id: UUID) -> UUID | None:
    """An owner reply sent outside EstateOS (e.g. straight from Gmail) joins the open case holding its thread.
    The id comes from our own persist step; everything after is scoped to the message's company. Idempotent."""
    message = session.get(MessageRow, message_id)
    if message is None or message.direction is not Direction.outbound or not message.thread_ref:
        return None
    case_id = thread_case(session, message.company_id, message)
    if case_id is not None:
        link_message(session, message.company_id, case_id, message.id, LinkMethod.thread, 1.0)
    return case_id
