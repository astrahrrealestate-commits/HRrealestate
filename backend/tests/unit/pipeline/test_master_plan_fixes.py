"""Unit tests for Urgent+Latest sorting, period slicing, Radar dedup, and fast outbound triage."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.contracts import ActionType, CaseState, Category, OutboundTriage, Urgency, WaitingSide
from app.llm.tiers import tier_of
from app.pipeline import next_actions
from app.pipeline.next_actions_items import matches_period, period_key
from app.pipeline.next_actions_sources import RankedItem
from app.pipeline.outbound_understand import apply_outbound_triage


def _action(
    *,
    urgency: Urgency,
    last_at: datetime,
    due_at: datetime | None = None,
    kind: str = "reply_needed",
) -> next_actions.NextAction:
    return next_actions.NextAction(
        id=f"act-{uuid4()}",
        category=Category.maintenance,
        kind=kind,  # type: ignore[arg-type]
        title="Test action",
        why="Because",
        urgency=urgency,
        due_at=due_at,
        case_id=uuid4(),
        approval_id=None,
        prepared=None,
        target_url="/inbox",
        last_at=last_at,
    )


def test_rank_key_orders_urgency_then_latest_newest_first() -> None:
    now = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
    old_urgent = RankedItem(
        _action(urgency=Urgency.high, last_at=now - timedelta(days=60), kind="approve_draft"),
        now - timedelta(days=60),
    )
    new_urgent = RankedItem(
        _action(urgency=Urgency.high, last_at=now - timedelta(hours=2), kind="reply_needed"),
        now - timedelta(hours=2),
    )
    emergency = RankedItem(
        _action(urgency=Urgency.emergency, last_at=now - timedelta(days=5)),
        now - timedelta(days=5),
    )
    overdue_early = RankedItem(
        _action(urgency=Urgency.high, last_at=now - timedelta(days=5), due_at=now - timedelta(days=3)),
        now - timedelta(days=5),
    )
    overdue_late = RankedItem(
        _action(urgency=Urgency.high, last_at=now - timedelta(days=2), due_at=now - timedelta(days=1)),
        now - timedelta(days=2),
    )
    normal = RankedItem(_action(urgency=Urgency.normal, last_at=now), now)

    ordered = sorted(
        [old_urgent, normal, overdue_late, new_urgent, emergency, overdue_early],
        key=next_actions._rank_key,
    )
    assert [item.action.id for item in ordered] == [
        emergency.action.id,
        overdue_early.action.id,
        overdue_late.action.id,
        new_urgent.action.id,
        old_urgent.action.id,
        normal.action.id,
    ]


def test_matches_period_supports_week_month_and_year() -> None:
    ref = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
    nov = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)
    october = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
    prev_year = datetime(2025, 12, 20, 10, 0, tzinfo=UTC)

    assert matches_period(nov, "all", ref) is True
    assert matches_period(nov, "this_week", ref) is True
    assert matches_period(october, "this_week", ref) is False
    assert matches_period(october, "2026-10", ref) is True
    assert matches_period(nov, "2026-10", ref) is False
    assert matches_period(october, "2026", ref) is True
    assert matches_period(prev_year, "2026", ref) is False
    assert period_key(october) == "2026-10"


def test_outbound_triage_uses_fast_tier_and_applies_waiting_side() -> None:
    assert tier_of("outbound_triage") == "fast"

    cid, case_id, person_id = uuid4(), uuid4(), uuid4()
    msg = SimpleNamespace(sent_at=datetime(2026, 11, 28, 10, 0, tzinfo=UTC))
    case = SimpleNamespace(
        id=case_id,
        company_id=cid,
        state=CaseState.open,
        primary_person_id=person_id,
    )
    session = MagicMock()
    session.get.return_value = SimpleNamespace(timezone="Europe/Amsterdam")

    with (
        patch("app.pipeline.outbound_understand.case_repo.get_case", return_value=case),
        patch("app.pipeline.outbound_understand.case_repo.transition") as mock_trans,
        patch("app.pipeline.outbound_understand.work_repo.record_owner_promise") as mock_promise,
    ):
        apply_outbound_triage(
            session,
            company_id=cid,
            case_id=case_id,
            msg=msg,  # type: ignore[arg-type]
            triage=OutboundTriage(
                waiting_side=WaitingSide.owner,
                open_obligation="Send signed addendum Friday",
                expected_days=3,
                expected_date=None,
                resolved=False,
                prompt_version="outbound_triage/v1",
            ),
        )
        mock_trans.assert_called_once_with(session, cid, case_id, CaseState.waiting_on_owner, actor="system")
        mock_promise.assert_called_once()

    with (
        patch("app.pipeline.outbound_understand.case_repo.get_case", return_value=case),
        patch("app.pipeline.outbound_understand.case_repo.close_case_pending") as mock_close,
        patch("app.pipeline.outbound_understand.case_repo.transition") as mock_trans,
    ):
        apply_outbound_triage(
            session,
            company_id=cid,
            case_id=case_id,
            msg=msg,  # type: ignore[arg-type]
            triage=OutboundTriage(
                waiting_side=WaitingSide.none,
                open_obligation=None,
                expected_days=None,
                expected_date=None,
                resolved=True,
                prompt_version="outbound_triage/v1",
            ),
        )
        mock_close.assert_called_once_with(session, cid, case_id)
        mock_trans.assert_called_once_with(session, cid, case_id, CaseState.resolved, actor="system")


def test_record_dispatch_only_sets_waiting_immediately_for_contractor_requests() -> None:
    from app.api.inbox import decide

    cid, case_id = uuid4(), uuid4()
    case_reply = SimpleNamespace(id=case_id, company_id=cid, state=CaseState.open, summary="Inquiry", summary_version=0)
    action_reply = SimpleNamespace(id=uuid4(), type=ActionType.reply_draft, payload={"channel": "gmail"})
    session = MagicMock()
    session.get.return_value = SimpleNamespace(outbound_mode=None)

    decide.record_dispatch(session, case_reply, action_reply, datetime(2026, 11, 28, 12, 0, tzinfo=UTC))  # type: ignore[arg-type]
    assert case_reply.state is CaseState.open
    assert "Contractor dispatch" not in case_reply.summary
