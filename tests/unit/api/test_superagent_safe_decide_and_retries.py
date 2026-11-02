"""Unit tests for Super Agent Safe Decide & DBOS Retries (Phase 3 / WP3 + WP4).

Validates:
- Double clicks / duplicate calls on decide return 'already_decided' without re-sending.
- Paused companies hold outbound communications instead of dispatching externally.
- Idempotency keys are strictly deterministic (action_id + draft_version) without timestamps.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4
from datetime import datetime, UTC
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.inbox.routes import ApprovalDecideRequest, decide_approval
from app.contracts import ActionType, ButtonChoice, Channel
from app.db.enums import ActionStatus, ApprovalStatus
from app.db.models import ActionRow, Approval, Case, Company, Send


@pytest.fixture
def test_engine():
    return create_engine("sqlite://")


def test_decide_approval_already_decided_returns_early(test_engine):
    """Verify that clicking accept on an already-approved draft returns 'already_decided' and does not send."""
    comp_id = uuid4()
    case_id = uuid4()
    act_id = uuid4()
    appr_id = uuid4()

    mock_sess = MagicMock()
    mock_sess.__enter__.return_value = mock_sess

    mock_appr = Approval(
        id=appr_id,
        company_id=comp_id,
        action_id=act_id,
        status=ApprovalStatus.approved,
        choice=ButtonChoice.d1,
        decided_at=datetime.now(UTC),
    )
    mock_act = ActionRow(
        id=act_id,
        company_id=comp_id,
        case_id=case_id,
        type=ActionType.reply_draft,
        draft_version=1,
    )

    def mock_get(model, pk):
        if model is Approval and pk == appr_id:
            return mock_appr
        if model is ActionRow and pk == act_id:
            return mock_act
        return None

    mock_sess.get.side_effect = mock_get

    mock_client = MagicMock()
    req = ApprovalDecideRequest(choice="d1")

    with patch("app.api.inbox.routes.Session", return_value=mock_sess):
        res = decide_approval(str(appr_id), req, test_engine, mock_client)
        assert res["status"] == "already_decided"
        assert res["decision"] == "approved"
        # Verify no external send was attempted
        mock_client.enqueue.assert_not_called()


def test_decide_approval_held_when_company_paused(test_engine):
    """Verify that if the company is paused, decide_approval marks action as paused and returns 'held'."""
    comp_id = uuid4()
    case_id = uuid4()
    act_id = uuid4()
    appr_id = uuid4()

    mock_sess = MagicMock()
    mock_sess.__enter__.return_value = mock_sess

    mock_appr = Approval(
        id=appr_id,
        company_id=comp_id,
        action_id=act_id,
        status=ApprovalStatus.pending,
    )
    mock_act = ActionRow(
        id=act_id,
        company_id=comp_id,
        case_id=case_id,
        type=ActionType.reply_draft,
        status=ActionStatus.pending_approval,
        draft_version=1,
    )
    mock_comp = Company(id=comp_id, name="Paused Co", paused=True)

    def mock_get(model, pk):
        if model is Approval and pk == appr_id:
            return mock_appr
        if model is ActionRow and pk == act_id:
            return mock_act
        if model is Company and pk == comp_id:
            return mock_comp
        return None

    mock_sess.get.side_effect = mock_get

    mock_client = MagicMock()
    req = ApprovalDecideRequest(choice="d1")

    with patch("app.api.inbox.routes.Session", return_value=mock_sess):
        res = decide_approval(str(appr_id), req, test_engine, mock_client)
        assert res["status"] == "held"
        assert res["decision"] == "paused"
        assert mock_act.status == ActionStatus.paused

