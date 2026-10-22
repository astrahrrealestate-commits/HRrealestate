"""The memory pack against real Postgres: the conversation window (first 6 + newest 24), the case memory (directory,
open waits, timeline, earlier drafts with the owner's decision and edits), company scoping on every query, a thread
page that never shows another thread's text, and a statement count that does not grow with the messages (no N+1)."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from app.contracts import ActionType, CaseState, Category, Channel, Direction, PageContext, Urgency
from app.core.ids import new_id
from app.db.enums import ActionStatus, ApprovalStatus, CaseEventKind, LinkMethod, PersonKind
from app.db.models import (
    ActionRevision,
    ActionRow,
    Approval,
    Case,
    CaseEvent,
    CaseLink,
    Company,
    Lease,
    LeaseParty,
    MessageRow,
    Person,
    RawEvent,
    Unit,
    WaitRow,
)
from app.pipeline.page_facts import facts_text, resolve_page_facts
from app.pipeline.read_repo import encode_thread_key
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


@dataclass(frozen=True)
class World:
    cid: UUID
    case_id: UUID
    main_key: str  # the long thread, linked to the case
    side_key: str  # a second thread of the same case
    secret: str


def _messages(s: Session, cid: UUID, person: Person, ref: str, texts: list[str], case_id: UUID, start: int = 0) -> None:
    for i, text in enumerate(texts):
        raw = RawEvent(company_id=cid, provider=Channel.whatsapp, provider_msg_id=str(new_id()), payload={})
        s.add(raw)
        s.flush()
        msg = MessageRow(
            company_id=cid, raw_event_id=raw.id, channel=Channel.whatsapp, provider_msg_id=raw.provider_msg_id,
            thread_ref=ref, sender_identity="+31600000000", person_id=person.id, text=text,
            direction=Direction.inbound if i % 2 == 0 else Direction.outbound,
            sent_at=T0 + timedelta(minutes=start + i),
        )  # fmt: skip
        s.add(msg)
        s.flush()
        s.add(CaseLink(company_id=cid, case_id=case_id, message_id=msg.id, method=LinkMethod.thread, confidence=None))


def _directory(s: Session, cid: UUID, secret: str) -> Person:
    person = Person(company_id=cid, kind=PersonKind.tenant, display_name=f"Sanne {secret}", valid_from=date(2024, 1, 1))
    unit = Unit(company_id=cid, label=f"A-12 {secret}", valid_from=date(2024, 1, 1))
    s.add_all([person, unit])
    s.flush()
    lease = Lease(company_id=cid, unit_id=unit.id, valid_from=date(2024, 2, 1))
    old = Lease(company_id=cid, unit_id=unit.id, valid_from=date(2025, 1, 1), valid_to=date(2025, 6, 30))  # superseded
    s.add_all([lease, old])
    s.flush()
    s.add(LeaseParty(company_id=cid, lease_id=lease.id, person_id=person.id, role="tenant"))
    s.add(LeaseParty(company_id=cid, lease_id=old.id, person_id=person.id, role="tenant"))
    return person


def _work(s: Session, cid: UUID, case_id: UUID, secret: str) -> None:
    s.add(WaitRow(company_id=cid, case_id=case_id, about=f"offerte {secret}", expected_by=T0 + timedelta(days=3)))
    s.add(
        CaseEvent(
            company_id=cid, case_id=case_id, kind=CaseEventKind.state_change, from_state=None,
            to_state=CaseState.open, note=None, actor="system", created_at=T0 - timedelta(minutes=1),
        )
    )  # fmt: skip
    s.add(
        CaseEvent(
            company_id=cid, case_id=case_id, kind=CaseEventKind.state_change, from_state=CaseState.open,
            to_state=CaseState.waiting_on_third_party, note=f"note {secret}", actor="owner", created_at=T0,
        )
    )  # fmt: skip
    action = ActionRow(
        company_id=cid, case_id=case_id, type=ActionType.reply_draft, payload={"body_variants": [f"draft {secret}"]},
        rationale="r", context_ref=[], draft_version=2, status=ActionStatus.pending_approval,
    )  # fmt: skip
    s.add(action)
    s.flush()
    s.add(Approval(company_id=cid, action_id=action.id, draft_version=1, status=ApprovalStatus.edited))
    s.add(ActionRevision(company_id=cid, action_id=action.id, draft_version=2, payload={}, edited_by="owner"))


def _seed(engine: Engine, cid: UUID, secret: str, count: int) -> World:
    with Session(engine) as s, s.begin():
        person = _directory(s, cid, secret)
        case = Case(company_id=cid, primary_person_id=person.id, category=Category.maintenance, urgency=Urgency.high)
        s.add(case)
        s.flush()
        main, side = f"main-{secret}-{new_id()}", f"side-{secret}-{new_id()}"
        _messages(s, cid, person, main, [f"main {i:02d} {secret}" for i in range(1, count + 1)], case.id)
        _messages(s, cid, person, side, [f"SIDETHREAD {secret}"], case.id, start=100)
        _work(s, cid, case.id, secret)
        keys = encode_thread_key(Channel.whatsapp, main), encode_thread_key(Channel.whatsapp, side)
        return World(cid, case.id, *keys, secret)


@pytest.fixture
def worlds(migrated_engine: Engine, committed_company: Company) -> Iterator[tuple[World, World]]:
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Foreign BV")
        s.add(other)
        s.commit()
    try:  # a failed seed still removes the foreign company (committed_company purges its own)
        mine = _seed(migrated_engine, committed_company.id, "MINEONLY", 40)
        theirs = _seed(migrated_engine, other.id, "THEIRSONLY", 3)
        yield mine, theirs
    finally:
        purge_company(migrated_engine, other.id)


def _page(**kw: Any) -> PageContext:
    return PageContext.model_validate({"view": "thread", **kw})


def test_thread_page_reads_a_window_of_that_thread_and_its_case_memory(
    migrated_engine: Engine, worlds: tuple[World, World]
) -> None:
    mine = worlds[0]
    with Session(migrated_engine) as s:
        facts = resolve_page_facts(s, mine.cid, _page(thread_key=mine.main_key))
    assert facts.conversation is not None
    assert (facts.conversation.source, facts.conversation.total) == ("thread", 40)
    assert [m.seq for m in facts.conversation.messages] == [*range(1, 7), *range(17, 41)]
    assert facts.thread is not None
    assert facts.thread.case_id == mine.case_id
    assert facts.thread_case is not None
    assert facts.memory is not None
    assert facts.memory.case_id == mine.case_id
    text = facts_text(facts)
    for expected in ("main 40 MINEONLY", "main 01 MINEONLY", "  person: Sanne MINEONLY | tenant", "unit A-12 MINEONLY",
                     "| valid from 2024-02-01 | current", "| valid from 2025-01-01 | not current since 2025-06-30",
                     "(none) -> open | system", "offerte MINEONLY", "open -> waiting_on_third_party | owner",
                     "draft_version 2 | owner decision edited | edits 1 | draft MINEONLY"):  # fmt: skip
        assert expected in text, expected
    assert text.index("| current") < text.index("| not current since")  # the current version first
    assert "main 10 MINEONLY" not in text  # outside the window
    assert "SIDETHREAD" not in text  # never another thread's text, even of the same case
    assert "THEIRSONLY" not in text


def test_case_page_reads_the_case_messages_of_every_thread(
    migrated_engine: Engine, worlds: tuple[World, World]
) -> None:
    mine = worlds[0]
    with Session(migrated_engine) as s:
        facts = resolve_page_facts(s, mine.cid, _page(view="case", case_id=str(mine.case_id)))
    assert facts.conversation is not None
    assert (facts.conversation.source, facts.conversation.total) == ("case", 41)
    text = facts_text(facts)
    assert "SIDETHREAD MINEONLY" in text  # the newest case message
    assert "THEIRSONLY" not in text


def test_foreign_thread_and_case_are_dropped_without_any_memory(
    migrated_engine: Engine, worlds: tuple[World, World]
) -> None:
    mine, theirs = worlds
    with Session(migrated_engine) as s:
        facts = resolve_page_facts(s, mine.cid, _page(thread_key=theirs.main_key, case_id=str(theirs.case_id)))
    assert (facts.case, facts.thread, facts.thread_case, facts.conversation, facts.memory) == (None,) * 5
    assert facts.dropped == ("case", "thread")
    text = facts_text(facts)
    for leaked in ("THEIRSONLY", str(theirs.case_id), theirs.main_key):
        assert leaked not in text


def _count_statements(engine: Engine, run: Any) -> int:
    seen: list[str] = []

    def count(*args: Any) -> None:
        seen.append(str(args[2]))

    event.listen(engine, "before_cursor_execute", count)
    try:
        run()
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return len(seen)


def test_statement_count_does_not_grow_with_the_messages(migrated_engine: Engine, worlds: tuple[World, World]) -> None:
    """40 messages (mine) and 3 messages (theirs, read as their own company) take the same number of statements."""

    def resolve(w: World) -> int:
        def run() -> None:
            with Session(migrated_engine) as s:
                resolve_page_facts(s, w.cid, _page(view="case", case_id=str(w.case_id), thread_key=w.main_key))

        return _count_statements(migrated_engine, run)

    mine, theirs = worlds
    long_thread, short_thread = resolve(mine), resolve(theirs)
    assert long_thread == short_thread
    assert long_thread <= 12  # case + label, thread window + its case, case memory (4); no per-message query
