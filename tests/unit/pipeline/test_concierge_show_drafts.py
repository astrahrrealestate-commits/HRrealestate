"""Unit tests for Concierge `show_drafts` intent (Phase 2 / WP5 + WP6).

Validates:
- show_drafts without case_id returns NEED_DETAIL.
- show_drafts with pending reply_draft returns StepResult with view=None and approval_ids in data.
- show_drafts keeps the owner in chat rather than redirecting to inbox.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine

from app.contracts import ActionType, Intent, PlanStep
from app.db.models import ActionRow
from app.pipeline import concierge_proposals as cp
from app.pipeline.concierge_base import NEED_DETAIL, Ctx


@pytest.fixture
def mock_ctx():
    eng = create_engine("sqlite://")
    settings = MagicMock()
    comp_id = uuid4()
    return Ctx(
        engine=eng,
        settings=settings,
        company_id=comp_id,
        now=datetime.now(UTC),
        question="show me the drafted messages for this",
    )


def test_show_drafts_requires_case_id(mock_ctx):
    step = PlanStep(intent=Intent.show_drafts, case_id=None, task_ref=None, text=None, view=None)
    result = cp.show_drafts(mock_ctx, step)
    assert not result.ok
    assert result.summary == NEED_DETAIL


def test_show_drafts_returns_pending_reply_draft(mock_ctx):
    case_id = uuid4()
    appr_id = uuid4()
    act_id = uuid4()
    msg_id = uuid4()

    mock_sess = MagicMock()
    mock_sess.__enter__.return_value = mock_sess
    # 1. _latest_inbound returns msg_id
    mock_sess.scalar.return_value = msg_id

    mock_act = ActionRow(
        id=act_id,
        company_id=mock_ctx.company_id,
        case_id=case_id,
        type=ActionType.reply_draft,
        draft_version=1,
        payload={"channel": "whatsapp", "body_variants": ["Hi, plumber is on the way."]},
    )
    # scalars for _message_actions and _pending_ids
    mock_sess.scalars.side_effect = [
        [mock_act],  # _message_actions
        [appr_id],  # _pending_ids
    ]
    # execute for _reply_of
    mock_sess.execute.return_value.first.return_value = (appr_id, 1, {"body_variants": ["Hi, plumber is on the way."]})

    mock_ctx.engine.connect = MagicMock()
    with (
        patch("app.pipeline.concierge_proposals.Session", return_value=mock_sess),
        patch("app.pipeline.concierge_proposals._source", return_value="whatsapp"),
    ):
        step = PlanStep(intent=Intent.show_drafts, case_id=case_id, task_ref=None, text=None, view=None)
        res = cp.show_drafts(mock_ctx, step)
        assert res.ok
        assert res.view is None  # CRITICAL: Must NOT redirect to inbox! Keeps user in chat!
        assert res.data is not None
        assert res.data["approval_ids"] == [str(appr_id)]
        assert res.data["case_id"] == str(case_id)


def test_show_drafts_auto_drafts_when_no_pending_reply_exists(mock_ctx):
    """When inbound exists without pending reply_draft (e.g. only a notice), show_drafts runs draft_reply."""
    case_id = uuid4()
    msg_id = uuid4()
    new_appr_id = uuid4()

    mock_sess = MagicMock()
    mock_sess.__enter__.return_value = mock_sess
    mock_sess.scalar.return_value = msg_id
    mock_sess.scalars.side_effect = [
        [],  # _message_actions
        [],  # case fallback ActionRow query
        [],  # _pending_ids
    ]

    draft_result = cp.StepResult(
        intent=Intent.show_drafts,
        ok=True,
        summary="Reply drafted.",
        data={"approval_ids": [str(new_appr_id)], "case_id": str(case_id)},
        view="approvals",
    )

    mock_ctx.engine.connect = MagicMock()
    with (
        patch("app.pipeline.concierge_proposals.Session", return_value=mock_sess),
        patch("app.pipeline.concierge_proposals.draft_reply", return_value=draft_result) as mock_draft,
    ):
        step = PlanStep(intent=Intent.show_drafts, case_id=case_id, task_ref=None, text=None, view=None)
        res = cp.show_drafts(mock_ctx, step)

    mock_draft.assert_called_once_with(mock_ctx, step)
    assert res.ok
    assert res.view is None  # Still keeps owner in chat
    assert res.data == {"approval_ids": [str(new_appr_id)], "case_id": str(case_id)}
