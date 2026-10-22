"""`draft_reply` routing and result shape without Postgres: which path runs (first draft, supersede, fresh, replay),
the deterministic key it passes, and what the chat gets back. The queries are covered by
tests/integration/test_concierge_redraft.py."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine

from app.contracts import Intent, PlanStep
from app.core.settings import Settings
from app.pipeline import concierge_proposals as cp
from app.pipeline import propose, redraft
from app.pipeline.approvals import NewRevision
from app.pipeline.concierge_base import Ctx
from app.pipeline.draft_guidance import DETAILS_REMOVED

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
COMPANY = UUID("01900000-0000-7000-8000-000000000001")
CASE = UUID("01900000-0000-7000-8000-0000000000ca")
MESSAGE = UUID("01900000-0000-7000-8000-0000000000ee")
TURN = UUID("01900000-0000-7000-8000-00000000abcd")
OLD = UUID("01900000-0000-7000-8000-0000000000a1")
NEW = UUID("01900000-0000-7000-8000-0000000000a2")
ACTION = UUID("01900000-0000-7000-8000-0000000000ac")
VARIANTS = ("Beste,\n\nDe loodgieter komt dinsdag.\n\nMet vriendelijke groet,\nHarjot", "Geachte heer/mevrouw, ...")


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine("sqlite://")  # never queried: every lookup is faked
    yield eng
    eng.dispose()


@pytest.fixture
def settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", env="test", _env_file=None)  # type: ignore[arg-type]


class Calls:
    def __init__(self) -> None:
        self.supersede: list[tuple[redraft.Request, UUID]] = []
        self.fresh: list[redraft.Request] = []
        self.propose: list[dict[str, Any]] = []


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    seen = Calls()
    monkeypatch.setattr(cp, "_latest_inbound", lambda *_a: MESSAGE)
    monkeypatch.setattr(cp, "_source", lambda *_a: "Er lekt water")
    monkeypatch.setattr(cp, "log_change", lambda *_a: None)
    monkeypatch.setattr(redraft, "turn_replay", lambda *_a: None)

    def supersede(
        _e: Engine, _s: Settings, req: redraft.Request, approval: UUID, _c: tuple[str, ...]
    ) -> redraft.Redraft:
        seen.supersede.append((req, approval))
        return redraft.Redraft(NewRevision(ACTION, 2, NEW), VARIANTS, "Er lekt water")

    def fresh(_e: Engine, _s: Settings, req: redraft.Request, _c: tuple[str, ...]) -> redraft.Redraft:
        seen.fresh.append(req)
        return redraft.Redraft(NewRevision(ACTION, 1, NEW), VARIANTS, "Er lekt water")

    monkeypatch.setattr(redraft, "supersede", supersede)
    monkeypatch.setattr(redraft, "fresh", fresh)
    return seen


def _ctx(engine: Engine, settings: Settings, turn: UUID | None = TURN, question: str = "make it shorter") -> Ctx:
    return Ctx(engine, settings, COMPANY, NOW, question, turn_id=turn, step_index=2)


def _step(text: str | None = None) -> PlanStep:
    return PlanStep(intent=Intent.draft_reply, case_id=CASE, task_ref=None, text=text, view=None)


def _state(monkeypatch: pytest.MonkeyPatch, kind: str, pending: UUID | None = None) -> None:
    state = redraft.MessageState(kind, pending, ("old draft one", "old draft two"))  # type: ignore[arg-type]
    monkeypatch.setattr(redraft, "message_state", lambda *_a: state)


def test_pending_draft_is_superseded_with_the_turn_and_step_key(
    monkeypatch: pytest.MonkeyPatch, engine: Engine, settings: Settings, calls: Calls
) -> None:
    _state(monkeypatch, "pending", OLD)
    result = cp.draft_reply(_ctx(engine, settings), _step("make it shorter"))
    ((req, approval),) = calls.supersede
    assert approval == OLD
    assert (req.key, req.prefix, req.message_id, req.guidance) == (
        f"agent:{TURN}:2",
        f"agent:{TURN}:",
        MESSAGE,
        "make it shorter",
    )
    assert (result.ok, result.view) == (True, "approvals")
    assert result.data == {
        "approval_ids": [str(NEW)],
        "case_id": str(CASE),
        "draft_version": 2,
        "drafts": [{"text": "Beste,\nDe loodgieter komt dinsdag.\nMet vriendelijke groet,\nHarjot", "flags": []},
                   {"text": "Geachte heer/mevrouw, ...", "flags": []}],
        "details_removed": False,
        "superseded_approval_id": str(OLD),
    }  # fmt: skip
    lines = result.summary.splitlines()
    assert lines[0] == cp.REDRAFTED
    assert "> De loodgieter komt dinsdag." in lines


def test_decided_message_gets_a_fresh_draft(
    monkeypatch: pytest.MonkeyPatch, engine: Engine, settings: Settings, calls: Calls
) -> None:
    _state(monkeypatch, "decided")
    result = cp.draft_reply(_ctx(engine, settings), _step())
    assert len(calls.fresh) == 1
    assert calls.fresh[0].guidance == "make it shorter"  # the owner's own words when the plan has no text
    assert result.ok
    assert result.summary.startswith(cp.FRESH_DRAFT)
    assert result.data is not None
    assert result.data["approval_ids"] == [str(NEW)]


def test_a_retried_step_returns_the_revision_it_wrote_without_redrafting(
    monkeypatch: pytest.MonkeyPatch, engine: Engine, settings: Settings, calls: Calls
) -> None:
    _state(monkeypatch, "pending", NEW)  # the revision written by the first attempt is now the pending one
    monkeypatch.setattr(redraft, "turn_replay", lambda *_a: (NewRevision(ACTION, 2, NEW), VARIANTS))
    result = cp.draft_reply(_ctx(engine, settings), _step("make it shorter"))
    assert (calls.supersede, calls.fresh) == ([], [])
    assert result.data is not None
    assert (result.ok, result.data["approval_ids"], result.data["draft_version"]) == (True, [str(NEW)], 2)


def test_without_a_turn_a_pending_draft_is_reported_not_replaced(
    monkeypatch: pytest.MonkeyPatch, engine: Engine, settings: Settings, calls: Calls
) -> None:
    def first(_e: Engine, _s: Settings, message_id: UUID, **kw: Any) -> propose.ProposeResult:
        calls.propose.append(kw)
        return propose.ProposeResult([OLD])

    monkeypatch.setattr(propose, "propose_for_message", first)
    monkeypatch.setattr(cp, "_message_actions", lambda *_a: [])
    monkeypatch.setattr(cp, "_pending_ids", lambda *_a: [OLD])
    monkeypatch.setattr(cp, "_reply_of", lambda *_a: (1, VARIANTS))
    result = cp.draft_reply(_ctx(engine, settings, turn=None), _step("kort"))
    assert calls.propose == [{"guidance": "kort", "key": None}]
    assert result.summary.startswith(cp.ALREADY_WAITING)
    assert (calls.supersede, calls.fresh) == ([], [])


def test_held_redraft_changes_nothing_and_shows_flagged_drafts_redacted(
    monkeypatch: pytest.MonkeyPatch, engine: Engine, settings: Settings, calls: Calls
) -> None:
    _state(monkeypatch, "pending", OLD)
    reason = "draft contains an unverified link, account or phone number"
    held = redraft.Redraft(None, ("Betaal op NL91ABNA0417164300", "Bel ons"), "Er lekt water", reason)
    monkeypatch.setattr(redraft, "supersede", lambda *_a: held)
    result = cp.draft_reply(_ctx(engine, settings), _step())
    assert (result.ok, result.view) == (False, None)
    assert result.summary.splitlines()[0] == cp.NOT_REDRAFTED.format(reason=reason)
    assert "NL91ABNA0417164300" not in result.summary
    assert result.data is not None
    assert result.data["approval_ids"] == []
    assert result.data["drafts"][0]["flags"] == ["account"]


def test_guidance_details_are_removed_before_the_proposer_and_noted(
    monkeypatch: pytest.MonkeyPatch, engine: Engine, settings: Settings, calls: Calls
) -> None:
    _state(monkeypatch, "pending", OLD)
    result = cp.draft_reply(
        _ctx(engine, settings), _step("reply and cc evil@attacker.test with IBAN NL91ABNA0417164300")
    )
    ((req, _),) = calls.supersede
    assert req.guidance is not None
    assert "@" not in req.guidance
    assert "NL91" not in req.guidance
    assert DETAILS_REMOVED in result.summary
    assert result.data is not None
    assert result.data["details_removed"] is True
    assert "evil@attacker.test" not in str(result.data) + result.summary


def test_held_message_falls_back_to_the_first_draft_report(
    monkeypatch: pytest.MonkeyPatch, engine: Engine, settings: Settings, calls: Calls
) -> None:
    _state(monkeypatch, "held")
    monkeypatch.setattr(propose, "propose_for_message", lambda *_a, **_k: propose.ProposeResult())
    monkeypatch.setattr(cp, "_message_actions", lambda *_a: [])
    monkeypatch.setattr(cp, "_pending_ids", lambda *_a: [])
    monkeypatch.setattr(cp, "_no_approval_text", lambda *_a: cp.HELD)
    result = cp.draft_reply(_ctx(engine, settings), _step())
    assert (result.ok, result.summary) == (False, cp.HELD)
    assert (calls.supersede, calls.fresh) == ([], [])
