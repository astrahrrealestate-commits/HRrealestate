"""Unit tests for Super Agent strict draft cards, notice cards, and recipient resolution (WP1 + WP2).

Validates:
- _find_case_recipient correctly anchors to inbound messages and primary person identities.
- Outbound message senders (contractors) are NEVER used as recipients.
- notify_owner actions are strictly rendered as 'notice' cards, never 'draft_message'.
- reply_draft actions render strictly as 'draft_message' with live approval status.
- No hardcoded Dutch fallbacks are generated.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.api.agent.routes import _find_case_recipient, _resolve_draft_card
from app.contracts import ActionType, Channel, Direction
from app.db.enums import ActionStatus, ApprovalStatus
from app.db.models import ActionRow, Approval, Case, ChannelIdentity, MessageRow


def test_find_case_recipient_inbound_whatsapp():
    """Verify that a case with inbound WhatsApp message resolves to the tenant's WhatsApp identity."""
    comp_id = uuid4()
    person_id = uuid4()
    case_id = uuid4()
    case = Case(id=case_id, company_id=comp_id, primary_person_id=person_id)

    ident = ChannelIdentity(
        id=uuid4(),
        company_id=comp_id,
        person_id=person_id,
        channel=Channel.whatsapp,
        identity="+919456916996",
        valid_to=None,
    )
    inbound_msg = MessageRow(
        id=uuid4(),
        company_id=comp_id,
        direction=Direction.inbound,
        channel=Channel.whatsapp,
        sender_identity="+919456916996",
        sent_at=datetime.now(UTC),
    )

    mock_sess = MagicMock()
    # First query is MessageRow (inbound), second query is ChannelIdentity
    mock_sess.scalars.return_value.first.side_effect = [inbound_msg, ident]

    recip, chan, _thread_ref, reason = _find_case_recipient(mock_sess, case)
    assert recip == "+919456916996"
    assert chan == "whatsapp"
    assert reason is None


def test_find_case_recipient_inbound_gmail():
    """Verify that a case with inbound Gmail message resolves to the tenant's Gmail identity."""
    comp_id = uuid4()
    person_id = uuid4()
    case_id = uuid4()
    case = Case(id=case_id, company_id=comp_id, primary_person_id=person_id)

    ident = ChannelIdentity(
        id=uuid4(),
        company_id=comp_id,
        person_id=person_id,
        channel=Channel.gmail,
        identity="vipint9902@gmail.com",
        valid_to=None,
    )
    inbound_msg = MessageRow(
        id=uuid4(),
        company_id=comp_id,
        direction=Direction.inbound,
        channel=Channel.gmail,
        sender_identity="vipint9902@gmail.com",
        thread_ref="gmail.thread.101",
        sent_at=datetime.now(UTC),
    )

    mock_sess = MagicMock()
    mock_sess.scalars.return_value.first.side_effect = [inbound_msg, ident]

    recip, chan, thread_ref, reason = _find_case_recipient(mock_sess, case)
    assert recip == "vipint9902@gmail.com"
    assert chan == "gmail"
    assert thread_ref == "gmail.thread.101"
    assert reason is None


def test_find_case_recipient_never_uses_outbound_contractor_sender():
    """Verify that an outbound message sent to a contractor is NEVER picked as the recipient."""
    comp_id = uuid4()
    person_id = uuid4()
    case_id = uuid4()
    case = Case(id=case_id, company_id=comp_id, primary_person_id=person_id)

    tenant_ident = ChannelIdentity(
        id=uuid4(),
        company_id=comp_id,
        person_id=person_id,
        channel=Channel.whatsapp,
        identity="+919456916996",
        valid_to=None,
    )

    mock_sess = MagicMock()
    # Inbound query returns None (only outbound exists), so it falls back to tenant identity directly
    mock_sess.scalars.return_value.first.side_effect = [None, tenant_ident]

    recip, chan, _thread_ref, reason = _find_case_recipient(mock_sess, case)
    assert recip == "+919456916996"
    assert chan == "whatsapp"
    assert reason is None


def test_resolve_draft_card_strictly_distinguishes_reply_vs_notice():
    """Verify that notify_owner creates a notice card, and reply_draft creates a draft_message card."""
    mock_engine = MagicMock()
    mock_sess = MagicMock()
    mock_sess.__enter__.return_value = mock_sess

    case_id = uuid4()
    case = Case(id=case_id)

    # 1. notify_owner action
    notice_act_id = uuid4()
    notice_appr_id = uuid4()
    notice_act = ActionRow(
        id=notice_act_id,
        case_id=case_id,
        type=ActionType.notify_owner,
        status=ActionStatus.pending_approval,
        payload={"kind": "notify_owner", "text": "EstateOS could not draft a reply due to rate limit."},
    )
    notice_appr = Approval(id=notice_appr_id, action_id=notice_act_id, status=ApprovalStatus.pending)

    # 2. reply_draft action
    draft_act_id = uuid4()
    draft_appr_id = uuid4()
    draft_act = ActionRow(
        id=draft_act_id,
        case_id=case_id,
        type=ActionType.reply_draft,
        status=ActionStatus.pending_approval,
        payload={
            "channel": "whatsapp",
            "to": "+919456916996",
            "body": "Hi Vipin, the emergency plumber has been dispatched.",
        },
    )
    draft_appr = Approval(id=draft_appr_id, action_id=draft_act_id, status=ApprovalStatus.pending)

    def mock_get(model, pk):
        if model is Approval and pk == notice_appr_id:
            return notice_appr
        if model is ActionRow and pk == notice_act_id:
            return notice_act
        if model is Approval and pk == draft_appr_id:
            return draft_appr
        if model is ActionRow and pk == draft_act_id:
            return draft_act
        if model is Case and pk == case_id:
            return case
        return None

    mock_sess.get.side_effect = mock_get

    with patch("app.api.agent.routes.Session", return_value=mock_sess):
        # Test notify_owner resolution -> MUST be notice card
        notice_card = _resolve_draft_card(mock_engine, approval_ids=[str(notice_appr_id)])
        assert notice_card is not None
        assert notice_card.type == "notice"
        assert notice_card.badgeLabel == "NOTICE"
        assert "could not draft a reply" in notice_card.body

        # Test reply_draft resolution -> MUST be draft_message card
        with patch("app.api.agent.routes._find_case_recipient", return_value=("+919456916996", "whatsapp", None, None)):
            draft_card = _resolve_draft_card(mock_engine, approval_ids=[str(draft_appr_id)])
            assert draft_card is not None
            assert draft_card.type == "draft_message"
            assert draft_card.recipient == "+919456916996"
            assert "plumber has been dispatched" in draft_card.body
            assert "Beste bewoner" not in draft_card.body


def test_resolve_draft_card_reflects_live_approval_status():
    """Verify that an approved or expired action shows its live status and does not pretend to be pending."""
    mock_engine = MagicMock()
    mock_sess = MagicMock()
    mock_sess.__enter__.return_value = mock_sess

    case_id = uuid4()
    draft_act_id = uuid4()
    draft_appr_id = uuid4()

    draft_act = ActionRow(
        id=draft_act_id,
        case_id=case_id,
        type=ActionType.reply_draft,
        status=ActionStatus.executed,
        payload={"channel": "whatsapp", "to": "+919456916996", "body": "Already sent to tenant."},
    )
    draft_appr = Approval(id=draft_appr_id, action_id=draft_act_id, status=ApprovalStatus.approved)

    def mock_get(model, pk):
        if model is Approval and pk == draft_appr_id:
            return draft_appr
        if model is ActionRow and pk == draft_act_id:
            return draft_act
        return None

    mock_sess.get.side_effect = mock_get

    with patch("app.api.agent.routes.Session", return_value=mock_sess):
        card = _resolve_draft_card(mock_engine, approval_ids=[str(draft_appr_id)])
        assert card is not None
        assert card.status == "approved"
