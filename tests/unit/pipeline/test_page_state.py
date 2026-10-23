"""Page pre-warm (`app.pipeline.page_state`): the page key, the reuse decision (injected clock), the scoped read, the
turn's page context and the upsert. No database: sessions are fakes, SQL is compiled."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import ANY, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError
from structlog.testing import capture_logs

from app.contracts import Channel, PageContext
from app.contracts.thread_key import encode_thread_key
from app.pipeline import page_state as ps
from app.pipeline.page_facts import CaseFact, PageFacts, facts_text

T0 = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
CASE = UUID("01900000-0000-7000-8000-000000000001")
OTHER = UUID("01900000-0000-7000-8000-000000000002")
KEY = encode_thread_key(Channel.whatsapp, "+31612345678")
RESOLVED = {"facts": "view: case\nopen case: stored", "dropped": []}


def _page(**kw: Any) -> PageContext:
    return PageContext.model_validate({"view": "case", "case_id": str(CASE), **kw})


# ---- page_key ---------------------------------------------------------------------------------------------------


def test_the_key_is_stable_and_ignores_snapshot_and_filters() -> None:
    a = _page(snapshot="Sanne · leak", filters={"status": "open"}, visible_ids=[str(OTHER)])
    b = _page(snapshot="something else entirely", visible_ids=[str(OTHER)])
    assert ps.page_key(a) == ps.page_key(b) == ps.page_key(a.model_copy())
    assert ps.page_key(a).startswith("v1:")


@pytest.mark.parametrize(
    "change",
    [
        {"view": "thread"},
        {"case_id": str(OTHER)},
        {"case_id": None},
        {"thread_key": KEY},
        {"approval_id": str(OTHER)},
        {"task_ref": "a1b2c3"},
        {"attachment_id": str(OTHER)},
        {"visible_ids": [str(OTHER)]},
    ],
)
def test_a_different_view_or_open_id_gives_a_different_key(change: dict[str, Any]) -> None:
    assert ps.page_key(_page(**change)) != ps.page_key(_page())


def test_the_same_id_in_a_different_field_gives_a_different_key() -> None:
    assert ps.page_key(_page(case_id=None, approval_id=str(CASE))) != ps.page_key(_page())


def test_visible_order_matters_because_the_facts_list_rows_in_screen_order() -> None:
    first, second = str(OTHER), str(CASE)
    assert ps.page_key(_page(visible_ids=[first, second])) != ps.page_key(_page(visible_ids=[second, first]))


def test_the_key_uses_the_validated_normal_form() -> None:
    upper = _page(task_ref="#A1B2C3", visible_ids=[str(OTHER).upper(), "#FFEE00"])
    lower = _page(task_ref="a1b2c3", visible_ids=[str(OTHER), "ffee00"])
    assert ps.page_key(upper) == ps.page_key(lower)


def test_the_key_carries_no_raw_id() -> None:
    key = ps.page_key(_page(thread_key=KEY, visible_ids=[KEY]))
    assert KEY not in key
    assert str(CASE) not in key
    assert len(key) == len("v1:") + 64


# ---- reuse decision ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("age_s", "ok"),
    [(0, True), (1, True), (119, True), (120, True), (121, False), (3600, False), (-1, True), (-6, False)],
)
def test_reuse_needs_the_same_key_within_the_ttl(age_s: int, ok: bool) -> None:
    now = T0 + timedelta(seconds=age_s)
    assert ps.reusable("v1:a", T0, "v1:a", now) is ok


def test_a_different_key_is_never_reused_even_when_fresh() -> None:
    assert ps.reusable("v1:a", T0, "v1:b", T0) is False


def test_the_ttl_is_120_seconds() -> None:
    assert timedelta(seconds=120) == ps.PAGE_TTL


# ---- the scoped read (warm_resolved) ----------------------------------------------------------------------------


def _session(row: tuple[Any, ...] | None) -> MagicMock:
    session = MagicMock()
    session.execute.return_value.one_or_none.return_value = row
    session.scalar.return_value = None  # no company change since (freshness: test_page_state_freshness.py)
    return session


def _row(page: PageContext, age_s: int = 10, resolved: Any = None) -> tuple[Any, ...]:
    return (ps.page_key(page), T0, RESOLVED if resolved is None else resolved, T0 + timedelta(seconds=age_s))


def test_fresh_matching_state_is_reused() -> None:
    page = _page()
    assert ps.warm_resolved(_session(_row(page)), uuid4(), uuid4(), page) == RESOLVED


def test_no_state_stale_state_and_another_page_are_not_reused() -> None:
    page = _page()
    assert ps.warm_resolved(_session(None), uuid4(), uuid4(), page) is None
    assert ps.warm_resolved(_session(_row(page, age_s=121)), uuid4(), uuid4(), page) is None
    assert ps.warm_resolved(_session(_row(_page(case_id=str(OTHER)))), uuid4(), uuid4(), page) is None


@pytest.mark.parametrize(
    "bad",
    [
        {"facts": 3, "dropped": []},
        {"facts": "x"},
        {"facts": "x", "dropped": [1]},
        {"facts": "", "dropped": [], "error": "KeyError"},
        ["facts"],
    ],
)
def test_a_corrupt_stored_value_is_not_reused(bad: Any) -> None:
    page = _page()
    assert ps.warm_resolved(_session(_row(page, resolved=bad)), uuid4(), uuid4(), page) is None


def test_the_read_filters_by_company_and_owner_and_uses_the_database_clock() -> None:
    session, company, owner = _session(None), uuid4(), uuid4()
    ps.warm_resolved(session, company, owner, _page())
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "agent_page_state.company_id = %(company_id_1)s::UUID" in sql
    assert "agent_page_state.owner_id = %(owner_id_1)s::UUID" in sql
    assert "now()" in sql
    assert "FOR UPDATE" not in sql
    params = stmt.compile().params
    assert (params["company_id_1"], params["owner_id_1"]) == (company, owner)


# ---- the turn's page context ------------------------------------------------------------------------------------


def test_a_warm_page_is_stored_with_the_facts_and_the_message_snapshot() -> None:
    page = _page(snapshot="the message's own snapshot", filters={"status": "open"})
    with patch.object(ps, "warm_resolved", return_value=RESOLVED) as warm:
        value = ps.turn_page_context(MagicMock(), CASE, OTHER, page)
    assert warm.call_args.args[1:] == (CASE, OTHER, page)
    assert value == {**page.model_dump(mode="json"), "resolved": RESOLVED}
    assert value["snapshot"] == "the message's own snapshot"


def test_a_cold_page_is_stored_as_the_request_alone() -> None:
    page = _page(snapshot="x")
    with patch.object(ps, "warm_resolved", return_value=None):
        assert ps.turn_page_context(MagicMock(), CASE, OTHER, page) == page.model_dump(mode="json")


# ---- warm (PUT /agent/page) -------------------------------------------------------------------------------------

FACTS = PageFacts("case", case=CaseFact(CASE, "Joris · maintenance", "open", "normal", "Broken window"))


def _warm(page: PageContext, facts: PageFacts | Exception = FACTS) -> tuple[bool, MagicMock, MagicMock]:
    session = MagicMock()
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    resolve = MagicMock(side_effect=facts) if isinstance(facts, Exception) else MagicMock(return_value=facts)
    with (
        patch.object(ps, "Session", factory),
        patch("app.pipeline.concierge_page.resolve_page_facts", resolve),
    ):
        return ps.warm(MagicMock(), CASE, OTHER, page), session, resolve


def _upsert_params(session: MagicMock) -> dict[str, Any]:
    stmt = session.execute.call_args.args[0]
    return dict(stmt.compile(dialect=postgresql.dialect()).params)


def test_warm_resolves_company_scoped_and_upserts_the_turn_shape() -> None:
    page = _page(snapshot="never stored")
    ok, session, resolve = _warm(page)
    assert ok is True
    assert resolve.call_args.args[1:] == (CASE, page)
    params = _upsert_params(session)
    assert (params["company_id"], params["owner_id"]) == (CASE, OTHER)
    assert params["page_key"] == ps.page_key(page)
    assert params["resolved"] == {"facts": facts_text(FACTS), "dropped": []}
    assert "never stored" not in str(params)


def test_foreign_ids_are_stored_as_dropped_kinds_only() -> None:
    page = _page(approval_id=str(OTHER))
    ok, session, _ = _warm(page, PageFacts("case", dropped=("case", "approval")))
    assert ok is True
    params = _upsert_params(session)
    assert params["resolved"]["dropped"] == ["case", "approval"]
    assert str(OTHER) not in params["resolved"]["facts"]
    assert str(CASE) not in params["resolved"]["facts"]


def test_the_upsert_keeps_one_row_per_owner_and_never_crosses_companies() -> None:
    _, session, _ = _warm(_page())
    sql = str(session.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (owner_id) DO UPDATE SET" in sql
    assert "page_key = excluded.page_key" in sql
    assert "resolved = excluded.resolved" in sql
    assert "resolved_at = excluded.resolved_at" in sql
    assert "agent_page_state.company_id = excluded.company_id" in sql
    assert "agent_page_state.resolved_at <= excluded.resolved_at" in sql
    assert "now()" in sql


def test_a_resolver_bug_stores_nothing_and_logs_the_type_only() -> None:
    with capture_logs() as logs:
        ok, session, _ = _warm(_page(), KeyError("Joris 0612345678"))
    assert ok is False
    session.execute.assert_not_called()
    failed = [e for e in logs if e["event"] == "dashboard.page_warm_failed"]
    assert failed == [
        {"event": "dashboard.page_warm_failed", "company_id": ANY, "error": "KeyError", "log_level": "error"}
    ]
    assert "0612345678" not in str(logs)


def test_a_transient_error_propagates_and_stores_nothing() -> None:
    with pytest.raises(OperationalError):
        _warm(_page(), OperationalError("select", {}, Exception("down")))
