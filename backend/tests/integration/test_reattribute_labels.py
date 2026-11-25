"""The one-time label pass: one model call for each case's latest mail whose sender the directory cannot place."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import Category, Channel, Direction, SenderRole, Suspicious, Urgency
from app.core.errors import AgentFailedError, BudgetExceededError
from app.core.settings import Settings
from app.db.enums import LinkMethod, PersonKind
from app.db.models import (
    Case,
    CaseLink,
    Company,
    MessageRow,
    ModelCall,
    OwnerAccount,
    Person,
    RawEvent,
    UnderstandingRow,
)
from app.llm.calls import CallResult
from app.workflows import reattribute_labels
from app.workflows.reattribute_labels import MAX_FAILURES_IN_A_ROW, label_candidates, label_senders
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration
T0 = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
OURS = "harjot@labels.example.test"


@dataclass
class World:
    engine: Engine
    company: UUID
    settings: Settings


def _mail(
    s: Session, w: World, case: UUID, sender: str, minutes: int, *, person: UUID | None = None,
    channel: Channel = Channel.gmail, direction: Direction = Direction.inbound, **meta: Any,
) -> UUID:  # fmt: skip
    raw = RawEvent(company_id=w.company, provider=channel, provider_msg_id=f"l-{uuid4()}", payload={})
    s.add(raw)
    s.flush()
    row = MessageRow(
        company_id=w.company, raw_event_id=raw.id, channel=channel, provider_msg_id=raw.provider_msg_id,
        thread_ref=f"t-{uuid4()}", sender_identity=sender, direction=direction,
        sent_at=T0 + timedelta(minutes=minutes), text="Namens onze client schrijf ik u.", person_id=person,
        meta={"subject": "Brief", **meta},
    )  # fmt: skip
    s.add(row)
    s.flush()
    s.add(CaseLink(company_id=w.company, case_id=case, message_id=row.id, method=LinkMethod.thread))
    return row.id


def _case(s: Session, w: World) -> UUID:
    case = Case(company_id=w.company, category=Category.administration, urgency=Urgency.low, summary="")
    s.add(case)
    s.flush()
    return case.id


@pytest.fixture
def world(migrated_engine: Engine, pg_url: str) -> Iterator[World]:
    with Session(migrated_engine) as s:
        company = Company(name="Labels")
        s.add(company)
        s.flush()
        s.add(OwnerAccount(company_id=company.id, display_name="H", whatsapp_e164="+31600000002", email=OURS))
        s.commit()
        cid = company.id
    settings = Settings(database_url=pg_url, env="test", llm_model="fake", _env_file=None)  # type: ignore[call-arg]
    yield World(migrated_engine, cid, settings)
    with Session(migrated_engine) as s:
        for model in (UnderstandingRow, ModelCall, OwnerAccount):
            s.query(model).filter(model.company_id == cid).delete()
        s.commit()
    purge_company(migrated_engine, cid)


@pytest.fixture
def answers(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Replaces the model: each call is recorded; `answers[0]` says what it returns or raises."""
    real = reattribute_labels.run_agent
    script: list[Any] = [{"sender_role": SenderRole.legal}]
    calls: list[str] = []

    def fake(engine: Engine, settings: Settings, spec: Any, prompt: str, ctx: Any) -> CallResult[Any]:
        calls.append(prompt)
        if isinstance(script[0], Exception):
            raise script[0]
        base = real(engine, settings, spec, prompt, ctx)
        output = base.output.model_copy(update={"category": Category.administration, **script[0]})
        return CallResult(output=output, model_call_id=base.model_call_id)

    monkeypatch.setattr(reattribute_labels, "run_agent", fake)
    script.append(calls)
    return script


def _meta(w: World, message_id: UUID) -> dict[str, Any]:
    with Session(w.engine) as s:
        row = s.get(MessageRow, message_id)
        assert row is not None
        return row.meta


def test_only_the_latest_mail_of_a_case_from_an_unplaced_sender_is_labelled_once(
    world: World, answers: list[Any]
) -> None:
    with Session(world.engine) as s:
        tenant = Person(company_id=world.company, kind=PersonKind.tenant, display_name="T", valid_from=T0.date())
        s.add(tenant)
        s.flush()
        unknown = _case(s, world)
        older = _mail(s, world, unknown, "oud@example.test", 1)
        latest = _mail(s, world, unknown, "advocaat@example.test", 2)
        _mail(s, world, unknown, "info@example.test", 3, direction=Direction.outbound)
        skipped = [
            _mail(s, world, _case(s, world), "huurder@example.test", 1, person=tenant.id),
            _mail(s, world, _case(s, world), OURS, 1),
            _mail(s, world, _case(s, world), "+31612345678", 1, channel=Channel.whatsapp),
            _mail(s, world, _case(s, world), "al@example.test", 1, sender_role_pass="vve"),
        ]
        s.commit()
    with Session(world.engine) as s:
        assert label_candidates(s, world.company) == [latest]
    report = label_senders(world.engine, world.settings, world.company)
    assert (report.labelled, report.failed, report.stopped) == (1, 0, None)
    [prompt] = answers[1]
    assert "From: advocaat@example.test" in prompt
    assert _meta(world, latest)["sender_role_pass"] == "legal"
    assert all(_meta(world, m).get("sender_role_pass") in (None, "vve") for m in [older, *skipped])
    assert label_senders(world.engine, world.settings, world.company).labelled == 0
    assert len(answers[1]) == 1
    with Session(world.engine) as s:  # nothing else is written: no understanding row, case or state change
        assert s.scalars(select(UnderstandingRow.id).where(UnderstandingRow.company_id == world.company)).all() == []


def test_mail_already_given_a_role_at_ingestion_is_not_asked_again_unless_it_was_repaired(
    world: World, answers: list[Any]
) -> None:
    with Session(world.engine) as s:
        wanted = []
        for repaired in (False, True):
            meta = {"reattributed_from": {"sender": OURS}} if repaired else {}
            message = _mail(s, world, _case(s, world), f"v{int(repaired)}@example.test", 1, **meta)
            s.add(UnderstandingRow(company_id=world.company, message_id=message, category=Category.administration,
                                   urgency=Urgency.low, body={"sender_role": "vve"},
                                   prompt_version="understanding/v3"))  # fmt: skip
            if repaired:
                wanted.append(message)
        s.commit()
        assert label_candidates(s, world.company) == wanted


@pytest.mark.parametrize(
    "flag", [{"suspicious": Suspicious(flag=True, reason="phishing")}, {"category": Category.spam}]
)
def test_flagged_or_spam_mail_gets_no_label(world: World, answers: list[Any], flag: dict[str, Any]) -> None:
    answers[0] = {"sender_role": SenderRole.legal, **flag}
    with Session(world.engine) as s:
        message = _mail(s, world, _case(s, world), "x@example.test", 1)
        s.commit()
    label_senders(world.engine, world.settings, world.company)
    assert _meta(world, message)["sender_role_pass"] is None


def test_the_ai_limit_stops_the_pass_and_a_later_run_finishes_it(world: World, answers: list[Any]) -> None:
    with Session(world.engine) as s:
        message = _mail(s, world, _case(s, world), "y@example.test", 1)
        s.commit()
    answers[0] = BudgetExceededError("daily AI limit reached")
    report = label_senders(world.engine, world.settings, world.company)
    assert report.labelled == 0
    assert "daily AI limit reached" in (report.stopped or "")
    assert "sender_role_pass" not in _meta(world, message)
    answers[0] = {"sender_role": SenderRole.business}
    assert label_senders(world.engine, world.settings, world.company).labelled == 1


def test_repeated_model_failures_stop_the_pass(world: World, answers: list[Any]) -> None:
    with Session(world.engine) as s:
        for n in range(MAX_FAILURES_IN_A_ROW + 2):
            _mail(s, world, _case(s, world), f"f{n}@example.test", 1)
        s.commit()
    answers[0] = AgentFailedError("model down")
    report = label_senders(world.engine, world.settings, world.company)
    assert report.failed == MAX_FAILURES_IN_A_ROW
    assert report.stopped
    assert len(answers[1]) == MAX_FAILURES_IN_A_ROW


def test_a_run_makes_at_most_the_allowed_calls_and_says_what_is_left(world: World, answers: list[Any]) -> None:
    with Session(world.engine) as s:
        for n in range(3):
            _mail(s, world, _case(s, world), f"m{n}@example.test", n)
        s.commit()
    first = label_senders(world.engine, world.settings, world.company, max_calls=2)
    assert (first.labelled, first.remaining, len(answers[1])) == (2, 1, 2)
    again = label_senders(world.engine, world.settings, world.company, max_calls=2)
    assert (again.labelled, again.remaining, len(answers[1])) == (1, 0, 3)
