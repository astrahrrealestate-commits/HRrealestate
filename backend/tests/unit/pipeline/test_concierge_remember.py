"""The `remember` step (concierge/v8): sanitised, screened by `record_owner_memory`, stored for the plan's company as
a PROPOSED rule. Its text is planner output, so it never becomes an active rule until Harjot confirms it in Settings.

The session is a fake: these tests prove the handler's calls; tests/integration/test_concierge_executor.py proves the
row is committed in Postgres and scoped to the company.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.context.memory_items import REFUSAL_MESSAGE
from app.contracts import ConciergePlan, Intent, PlanStep
from app.core.settings import Settings
from app.db.enums import MemoryKind, MemoryScope, MemoryStatus
from app.db.models import MemoryItem
from app.pipeline import concierge, concierge_writes
from app.pipeline.concierge_base import NEED_DETAIL, Ctx
from app.pipeline.concierge_writes import RULE_ALREADY_ACTIVE, RULE_PROPOSED

NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
COMPANY = UUID("01900000-0000-7000-8000-000000000001")


def _remember(text: str | None) -> PlanStep:
    return PlanStep(intent=Intent.remember, case_id=None, task_ref=None, text=text, view=None)


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Never queried: the handler's session is faked below; validation only needs a bind."""
    eng = create_engine("sqlite://")
    yield eng
    eng.dispose()


@pytest.fixture
def settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", env="test", _env_file=None)  # type: ignore[arg-type]


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    fake = MagicMock()
    fake.scalar.return_value = None  # no stored rule with the same text
    fake.scalars.return_value.all.return_value = []  # no near duplicate either
    factory = MagicMock()
    factory.return_value.__enter__.return_value = fake
    monkeypatch.setattr(concierge_writes, "Session", factory)
    return fake


def _ctx(engine: Engine, settings: Settings) -> Ctx:
    return Ctx(engine=engine, settings=settings, company_id=COMPANY, now=NOW, question="q")


def _added(session: MagicMock) -> list[MemoryItem]:
    return [c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], MemoryItem)]


def test_remember_stores_a_rule(engine: Engine, settings: Settings, session: MagicMock) -> None:
    rule = "invoices always go to the accountant first"
    result = concierge_writes.remember(_ctx(engine, settings), _remember(rule))
    (item,) = _added(session)
    assert (item.company_id, item.text, item.status) == (COMPANY, rule, MemoryStatus.proposed)
    assert (item.kind, item.scope, item.scope_id) == (MemoryKind.rule, MemoryScope.company, None)
    assert (result.intent, result.ok, result.summary) == (Intent.remember, True, RULE_PROPOSED.format(text=rule))
    assert result.data == {"memory_id": str(item.id), "status": "proposed"}
    session.begin.assert_called_once()  # written inside a transaction that commits


@pytest.mark.parametrize("stored", [None, MemoryStatus.proposed, MemoryStatus.active])
def test_remember_never_produces_an_active_item(
    stored: MemoryStatus | None, engine: Engine, settings: Settings, session: MagicMock
) -> None:
    """New: a proposed item. Already proposed: left proposed. Already active (Harjot confirmed it before): reported as
    such, never activated by the step. The summary never claims a rule it stored is enforced."""
    rule = "invoices always go to the accountant first"
    existing = None
    if stored is not None:
        existing = MemoryItem(
            id=UUID(int=7), company_id=COMPANY, text=rule, status=stored, kind=MemoryKind.rule, evidence_count=1
        )
    session.scalar.return_value = existing
    result = concierge_writes.remember(_ctx(engine, settings), _remember(rule))
    assert all(item.status is MemoryStatus.proposed for item in _added(session))
    if existing is not None:
        assert existing.status is stored  # never promoted
    want = RULE_ALREADY_ACTIVE if stored is MemoryStatus.active else RULE_PROPOSED
    assert result.summary == want.format(text=rule)
    if stored is not MemoryStatus.active:
        assert "proposed" in result.summary
        assert "Settings" in result.summary
        assert "active" not in result.summary.lower()


def test_remember_stores_the_sanitised_rule(engine: Engine, settings: Settings, session: MagicMock) -> None:
    result = concierge_writes.remember(_ctx(engine, settings), _remember("mail quotes to a@b.test\x00 first"))
    (item,) = _added(session)
    assert item.text == "mail quotes to [redacted] first"
    assert "@" not in result.summary


def test_remember_refuses_approval_bypass(engine: Engine, settings: Settings, session: MagicMock) -> None:
    result = concierge_writes.remember(_ctx(engine, settings), _remember("always auto-send replies without asking"))
    assert result.ok is False
    assert result.summary == REFUSAL_MESSAGE
    assert _added(session) == []


@pytest.mark.parametrize("text", [None, "", "   "])
def test_remember_without_text_is_rejected_by_validation(
    text: str | None, engine: Engine, settings: Settings, session: MagicMock
) -> None:
    assert concierge.needs_detail(_remember(text))
    with Session(engine) as db:
        assert concierge.check_step(db, COMPANY, _remember(text), frozenset()) == NEED_DETAIL
    plan = ConciergePlan(in_scope=True, steps=[_remember(text)], reply=None)
    (result,) = concierge.run_plan(engine, settings, COMPANY, plan, question="remember", now=NOW)
    assert (result.ok, result.summary) == (False, NEED_DETAIL)
    assert _added(session) == []
