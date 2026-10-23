"""Memory pack for an open thread or case page (spec amendment 2026-10-22).

The conversation is read in ONE query per page: the thread's messages (channel + thread ref) or the case's linked
messages, numbered oldest first by a window function, keeping the first `FIRST` and the newest `NEWEST` (all of them
when there are at most `MAX_MESSAGES`). The case memory (directory facts, open waits, timeline, earlier drafts with the
owner's decisions and edit counts) is four more bounded queries. Every query and every join filters by `company_id`
(invariant 4). Stored text is normalised, put on one line and capped (`page_text.one_line`); direction, channel,
times, kinds and statuses are server values. A thread page shows only that thread's messages.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.contracts import Channel
from app.db.enums import PersonKind, WaitStatus
from app.db.models import (
    ActionRevision,
    ActionRow,
    Approval,
    Case,
    CaseEvent,
    CaseLink,
    Lease,
    LeaseParty,
    MessageRow,
    Person,
    Unit,
    WaitRow,
)
from app.llm.render import RAW_FACTOR
from app.pipeline.page_text import one_line, stamp

MAX_MESSAGES, FIRST, NEWEST = 30, 6, 24  # first 6 + newest 24 when a conversation is longer than 30
MAX_MESSAGE = 600
MAX_EVENTS, MAX_NOTE = 15, 120
MAX_WAITS, MAX_ABOUT = 5, 200
MAX_DRAFTS, MAX_EARLIER_DRAFT = 5, 300
MAX_LEASES, MAX_NAME, MAX_CODE = 3, 120, 40
NO_STATE = "(none)"  # an event without a from-state (the case was just opened)


@dataclass(frozen=True)
class MemoryMessage:
    seq: int  # position in the conversation, 1 = first message
    direction: str
    channel: str
    at: str
    text: str


@dataclass(frozen=True)
class Conversation:
    source: str  # "thread" or "case"
    total: int
    messages: tuple[MemoryMessage, ...]


@dataclass(frozen=True)
class PersonFact:
    name: str
    kind: str


@dataclass(frozen=True)
class LeaseFact:
    role: str
    unit: str
    start: str  # the directory row's validity window (`valid_from`/`valid_to`), not contract dates
    end: str | None  # None: the current version


@dataclass(frozen=True)
class WaitFact:
    who: str
    about: str
    expected_by: str
    chased: int


@dataclass(frozen=True)
class EventFact:
    at: str
    kind: str
    change: str  # "open -> waiting", "(none) -> open" or "-"
    actor: str
    note: str


@dataclass(frozen=True)
class DraftFact:
    action_type: str
    status: str
    draft_version: int
    decision: str  # the latest approval's status, or "none"
    edits: int  # owner edit revisions
    text: str


@dataclass(frozen=True)
class CaseMemory:
    case_id: UUID
    person: PersonFact | None
    leases: tuple[LeaseFact, ...]
    waits: tuple[WaitFact, ...]
    events: tuple[EventFact, ...]
    drafts: tuple[DraftFact, ...]


def _val(value: object) -> str:
    return str(getattr(value, "value", value))


def _numbered() -> Select[Any]:
    return select(
        MessageRow.id, MessageRow.direction, MessageRow.channel, MessageRow.sent_at,
        func.substr(MessageRow.text, 1, RAW_FACTOR * MAX_MESSAGE).label("text"),
        func.row_number().over(order_by=(MessageRow.sent_at, MessageRow.id)).label("seq"),
        func.count().over().label("total"),
    )  # fmt: skip


def _conversation(session: Session, source: str, numbered: Select[Any]) -> tuple[Conversation | None, list[UUID]]:
    inner = numbered.subquery()
    keep = or_(inner.c.seq <= FIRST, inner.c.seq > inner.c.total - NEWEST)
    rows = session.execute(select(inner).where(keep).order_by(inner.c.seq).limit(MAX_MESSAGES)).all()
    if not rows:
        return None, []
    messages = tuple(
        MemoryMessage(r.seq, _val(r.direction), _val(r.channel), stamp(r.sent_at), one_line(r.text or "", MAX_MESSAGE))
        for r in rows
    )
    return Conversation(source, int(rows[0].total), messages), [r.id for r in rows]


def thread_conversation(
    session: Session, company_id: UUID, channel: Channel, ref: str
) -> tuple[Conversation | None, list[UUID]]:
    """This thread's messages only (and their ids, to find the thread's case)."""
    thread_ref = func.coalesce(MessageRow.thread_ref, MessageRow.provider_msg_id)
    where = (MessageRow.company_id == company_id, MessageRow.channel == channel, thread_ref == ref)
    return _conversation(session, "thread", _numbered().where(*where))


def case_conversation(session: Session, company_id: UUID, case_id: UUID) -> Conversation | None:
    """The messages linked to the case, on any channel."""
    link = (CaseLink.message_id == MessageRow.id) & (CaseLink.company_id == company_id)
    numbered = _numbered().join(CaseLink, link).where(MessageRow.company_id == company_id, CaseLink.case_id == case_id)
    return _conversation(session, "case", numbered)[0]


def directory_query(company_id: UUID, case_id: UUID) -> Select[str, PersonKind, str, str, date, date | None]:
    """The case's person and that person's lease parties. Current lease versions (`valid_to IS NULL`) come first, then
    the newest; unique ids break every tie, so the MAX_LEASES kept are the same on every run."""
    return (
        select(Person.display_name, Person.kind, LeaseParty.role, Unit.label, Lease.valid_from, Lease.valid_to)
        .select_from(Case)
        .join(Person, (Person.id == Case.primary_person_id) & (Person.company_id == company_id))
        .outerjoin(LeaseParty, (LeaseParty.person_id == Person.id) & (LeaseParty.company_id == company_id))
        .outerjoin(Lease, (Lease.id == LeaseParty.lease_id) & (Lease.company_id == company_id))
        .outerjoin(Unit, (Unit.id == Lease.unit_id) & (Unit.company_id == company_id))
        .where(Case.company_id == company_id, Case.id == case_id)
        .order_by(
            Lease.valid_to.desc().nulls_first(), Lease.valid_from.desc().nulls_last(), Lease.id, LeaseParty.role,
            LeaseParty.id,
        )
        .limit(MAX_LEASES)
    )  # fmt: skip


def _directory(session: Session, company_id: UUID, case_id: UUID) -> tuple[PersonFact | None, tuple[LeaseFact, ...]]:
    """Cases carry no lease/unit ids in Phase 1, so leases come from the directory's lease parties of the person; a
    superseded or ended version is labelled with its validity, never shown as current."""
    rows = session.execute(directory_query(company_id, case_id)).all()
    if not rows:
        return None, ()
    person = PersonFact(one_line(rows[0][0], MAX_NAME), _val(rows[0][1]))
    leases = tuple(
        LeaseFact(one_line(role, MAX_CODE), one_line(unit or "unknown", MAX_NAME), start.isoformat(),
                  end.isoformat() if end else None)
        for _, _, role, unit, start, end in rows
        if role is not None and start is not None
    )  # fmt: skip
    return person, leases


def state_change(from_state: object, to_state: object) -> str:
    """`a -> b`; an event without a from-state (a new case) is `(none) -> b`; no to-state is `-`."""
    if not to_state:
        return "-"
    return f"{_val(from_state) if from_state else NO_STATE} -> {_val(to_state)}"


def _waits(session: Session, company_id: UUID, case_id: UUID) -> tuple[WaitFact, ...]:
    rows = session.execute(
        select(Person.display_name, WaitRow.about, WaitRow.expected_by, WaitRow.chase_count)
        .select_from(WaitRow)
        .outerjoin(Person, (Person.id == WaitRow.party_person_id) & (Person.company_id == company_id))
        .where(WaitRow.company_id == company_id, WaitRow.case_id == case_id, WaitRow.status == WaitStatus.waiting)
        .order_by(WaitRow.expected_by, WaitRow.id)
        .limit(MAX_WAITS)
    ).all()
    return tuple(
        WaitFact(one_line(who or "anyone", MAX_NAME), one_line(about, MAX_ABOUT), stamp(by), chased)
        for who, about, by, chased in rows
    )


def _events(session: Session, company_id: UUID, case_id: UUID) -> tuple[EventFact, ...]:
    """The last MAX_EVENTS events, oldest first."""
    rows = session.execute(
        select(
            CaseEvent.created_at, CaseEvent.kind, CaseEvent.from_state, CaseEvent.to_state, CaseEvent.actor,
            func.substr(CaseEvent.note, 1, RAW_FACTOR * MAX_NOTE),
        )
        .where(CaseEvent.company_id == company_id, CaseEvent.case_id == case_id)
        .order_by(CaseEvent.created_at.desc(), CaseEvent.id.desc())
        .limit(MAX_EVENTS)
    ).all()  # fmt: skip
    return tuple(
        EventFact(stamp(at), _val(kind), state_change(a, b), one_line(actor, MAX_CODE),
                  one_line(note or "-", MAX_NOTE) or "-")
        for at, kind, a, b, actor, note in reversed(rows)
    )  # fmt: skip


def _drafts(session: Session, company_id: UUID, case_id: UUID) -> tuple[DraftFact, ...]:
    """The case's latest MAX_DRAFTS actions, oldest first: first variant, latest approval status, edit count."""
    decision = (
        select(Approval.status)
        .where(Approval.company_id == company_id, Approval.action_id == ActionRow.id)
        .order_by(Approval.created_at.desc(), Approval.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    edits = (
        select(func.count(ActionRevision.id))
        .where(
            ActionRevision.company_id == company_id,
            ActionRevision.action_id == ActionRow.id,
            ActionRevision.edited_by.startswith("owner"),  # owner edits; agent redrafts (`agent:...`) are not edits
        )
        .scalar_subquery()
    )
    variant = func.jsonb_extract_path_text(ActionRow.payload, "body_variants", "0")  # the first variant, or NULL
    first = func.substr(variant, 1, RAW_FACTOR * MAX_EARLIER_DRAFT)
    rows = session.execute(
        select(ActionRow.type, ActionRow.status, ActionRow.draft_version, decision, edits, first)
        .where(ActionRow.company_id == company_id, ActionRow.case_id == case_id)
        .order_by(ActionRow.created_at.desc(), ActionRow.id.desc())
        .limit(MAX_DRAFTS)
    ).all()
    return tuple(
        DraftFact(_val(kind), _val(status), version, _val(dec) if dec else "none", int(n or 0),
                  one_line(text or "", MAX_EARLIER_DRAFT) or "(no draft text)")
        for kind, status, version, dec, n, text in reversed(rows)
    )  # fmt: skip


def case_memory(session: Session, company_id: UUID, case_id: UUID) -> CaseMemory:
    person, leases = _directory(session, company_id, case_id)
    waits = _waits(session, company_id, case_id)
    return CaseMemory(
        case_id, person, leases, waits, _events(session, company_id, case_id), _drafts(session, company_id, case_id)
    )
