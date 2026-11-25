from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.contracts import ActionType, ConciergePlan, Intent, PlanStep
from app.core.settings import Settings
from app.db.models import ActionRow, Approval, Case, Company
from app.main import create_app
from app.pipeline.concierge import StepResult
from tests.api_auth import as_owner, with_conversation

SETTINGS = Settings(
    database_url="postgresql+psycopg://u:p@localhost:1/db",
    env="test",
    _env_file=None,
)
URL = "/api/agent/ask"
TEST_COMP_ID = UUID("00000000-0000-0000-0000-000000000001")


def create_mock_session(comp_id=None, get_map=None):
    comp_id = comp_id or TEST_COMP_ID
    company = Company(id=comp_id, name="EstateOS Test")
    get_map = get_map or {}

    mock_sess = MagicMock()

    def mock_scalars(query):
        result = MagicMock()
        q_str = str(query).lower()
        if "from companies" in q_str:
            result.first.return_value = company
        else:
            result.first.return_value = None
        result.all.return_value = []
        return result

    mock_sess.scalars.side_effect = mock_scalars
    mock_sess.get.side_effect = with_conversation(lambda model, ident: get_map.get((model, ident)))
    mock_sess.__enter__.return_value = mock_sess
    return mock_sess


def test_long_concierge_answer_not_discarded():
    """Verify that legitimate CONCIERGE plan answers > 350 chars are not discarded by Groq."""
    long_answer = (
        "Here is the comprehensive status of your portfolio:\n"
        "1. Keizersgracht 42-A: Maintenance inspection completed on schedule. "
        "Tenant reported satisfaction with pipe repair.\n"
        "2. Singel 412: Inbound invoice received from KitchenTech B.V. for € 412,50, "
        "pending review in Financial Ledger.\n"
        "3. Prinsengracht 100: Lease agreement active until December 2027. All rental payments up to date.\n"
        "All queues are functioning within normal operational parameters."
    )
    assert len(long_answer) > 350

    mock_engine = MagicMock()
    app = as_owner(create_app(SETTINGS, engine=mock_engine))

    fake_plan = ConciergePlan(
        in_scope=True,
        steps=[PlanStep(intent=Intent.case_status, case_id=None, task_ref=None, text=None, view=None)],
        reply=None,
    )
    mock_result = StepResult(
        intent=Intent.case_status,
        ok=True,
        summary="Retrieved portfolio status",
        data={"summary": long_answer},
        view=None,
    )

    mock_sess = create_mock_session()
    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch("app.api.agent.routes.run_plan", return_value=[mock_result]),
        patch("app.api.agent.intent_responses.assemble_answer", return_value=long_answer),
        patch("app.api.agent.routes._generate_chat_answer") as mock_chat,
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = fake_plan

        res = client.post(URL, json={"query": "tell me full portfolio status"})
        assert res.status_code == 200
        data = res.json()
        assert data["answer"] == long_answer
        mock_chat.assert_not_called()


def test_short_concierge_answer_not_discarded():
    """Verify that legitimate short CONCIERGE answers (< 40 chars) are preserved and not replaced."""
    short_answer = "0 active cases in database."
    assert len(short_answer) < 40

    mock_engine = MagicMock()
    app = as_owner(create_app(SETTINGS, engine=mock_engine))

    fake_plan = ConciergePlan(
        in_scope=True,
        steps=[PlanStep(intent=Intent.case_status, case_id=None, task_ref=None, text=None, view=None)],
        reply=None,
    )
    mock_result = StepResult(
        intent=Intent.case_status,
        ok=True,
        summary="Checked case queues",
        data={"summary": short_answer},
        view=None,
    )

    mock_sess = create_mock_session()
    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch("app.api.agent.routes.run_plan", return_value=[mock_result]),
        patch("app.api.agent.intent_responses.assemble_answer", return_value=short_answer),
        patch("app.api.agent.routes._generate_chat_answer") as mock_chat,
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = fake_plan

        res = client.post(URL, json={"query": "what is the case status"})
        assert res.status_code == 200
        data = res.json()
        assert data["answer"] == short_answer
        mock_chat.assert_not_called()


def test_empty_db_no_fictional_ticket_005():
    """Verify that an empty database inquiry does not synthesize fake Ticket #005 or Pieter Floriszstraat."""
    mock_engine = MagicMock()
    app = as_owner(create_app(SETTINGS, engine=mock_engine))

    mock_sess = create_mock_session()
    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent", side_effect=Exception("offline")),
        patch("app.api.agent.routes.fake_concierge", return_value={"in_scope": False, "steps": [], "reply": None}),
        TestClient(app) as client,
    ):
        res = client.post(URL, json={"query": "what should I do first?"})
        assert res.status_code == 200
        raw_text = res.text
        assert "Pieter Floriszstraat 1 C" not in raw_text
        assert "Ticket #005" not in raw_text
        assert "4182" not in raw_text
        assert "Chahal Bouw" not in raw_text


def test_financial_query_no_fake_bas_de_graaf():
    """Verify that an inquiry about rent arrears does not return hardcoded Bas de Graaf or € 2.150."""
    mock_engine = MagicMock()
    app = as_owner(create_app(SETTINGS, engine=mock_engine))

    mock_sess = create_mock_session()
    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent", side_effect=Exception("offline")),
        patch("app.api.agent.routes.fake_concierge", return_value={"in_scope": False, "steps": [], "reply": None}),
        TestClient(app) as client,
    ):
        res = client.post(URL, json={"query": "show me rent arrears"})
        assert res.status_code == 200
        raw_text = res.text
        assert "Bas de Graaf" not in raw_text
        assert "26.13.00024" not in raw_text
        assert "€ 2.150" not in raw_text


def test_draft_card_uses_real_action_payload():
    """Verify that draft preview cards strictly extract data from real database ActionRow payload."""
    appr_id = uuid4()
    act_id = uuid4()
    case_id = uuid4()
    comp_id = TEST_COMP_ID

    real_draft_text = "Geachte huurder, wij hebben uw melding in behandeling genomen."
    mock_appr = Approval(id=appr_id, company_id=comp_id, action_id=act_id)
    mock_act = ActionRow(
        id=act_id,
        company_id=comp_id,
        case_id=case_id,
        type=ActionType.reply_draft,
        payload={
            "channel": "whatsapp",
            "to": "+31698765432",
            "body_variants": [real_draft_text],
        },
    )
    mock_case = Case(id=case_id, company_id=comp_id)

    mock_engine = MagicMock()
    app = as_owner(create_app(SETTINGS, engine=mock_engine))

    fake_plan = ConciergePlan(
        in_scope=True,
        steps=[PlanStep(intent=Intent.draft_reply, case_id=case_id, task_ref=None, text=None, view=None)],
        reply=None,
    )
    mock_result = StepResult(
        intent=Intent.draft_reply,
        ok=True,
        summary="Drafted reply",
        data={"approval_ids": [str(appr_id)]},
        view=None,
    )

    get_map = {
        (Approval, appr_id): mock_appr,
        (ActionRow, act_id): mock_act,
        (Case, case_id): mock_case,
    }
    mock_sess = create_mock_session(comp_id=comp_id, get_map=get_map)

    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch("app.api.agent.routes.run_plan", return_value=[mock_result]),
        patch("app.api.agent.intent_responses.assemble_answer", return_value="Draft prepared for review."),
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = fake_plan

        res = client.post(URL, json={"query": "draft reply for the tenant"})
        assert res.status_code == 200
        card = res.json()["previewCard"]
        assert card is not None
        assert card["actionId"] == str(act_id)
        assert card["caseId"] == str(case_id)
        assert card["body"] == real_draft_text
        assert card["recipient"] == "+31698765432"
        assert "Pieter Floriszstraat" not in card["body"]
        assert "Bas de Graaf" not in card["body"]


def test_invoice_query_does_not_trigger_rag():
    """Verify that invoice and factuur queries do not invoke document RAG (Issue #5)."""
    mock_engine = MagicMock()
    app = as_owner(create_app(SETTINGS, engine=mock_engine))

    mock_sess = create_mock_session()
    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.search_hybrid") as mock_search_hybrid,
        patch("app.api.agent.routes.run_agent", side_effect=Exception("skip")),
        patch("app.api.agent.routes.fake_concierge", return_value={"in_scope": False, "steps": [], "reply": None}),
        TestClient(app) as client,
    ):
        res = client.post(URL, json={"query": "show me the unpaid invoice from Kevin"})
        assert res.status_code == 200
        mock_search_hybrid.assert_not_called()

        res2 = client.post(URL, json={"query": "zoek de openstaande factuur"})
        assert res2.status_code == 200
        mock_search_hybrid.assert_not_called()


def test_dropped_step_surfaces_actionable_warning():
    """Verify that a step rejected due to missing case/task info surfaces actionable guidance (Issue #8)."""
    mock_engine = MagicMock()
    app = as_owner(create_app(SETTINGS, engine=mock_engine))

    fake_plan = ConciergePlan(
        in_scope=True,
        steps=[PlanStep(intent=Intent.draft_reply, case_id=None, task_ref=None, text=None, view=None)],
        reply=None,
    )
    # check_step returns NEED_DETAIL when case_id is missing for draft_reply
    mock_result = StepResult(
        intent=Intent.draft_reply,
        ok=False,
        summary="I need more detail",
        data=None,
        view=None,
    )

    mock_sess = create_mock_session()
    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch("app.api.agent.routes.run_plan", return_value=[mock_result]),
        patch("app.api.agent.intent_responses.assemble_answer", return_value="I need more detail"),
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = fake_plan

        res = client.post(URL, json={"query": "draft a reply to the tenant"})
        assert res.status_code == 200
        data = res.json()
        assert "Action Notice" in data["answer"]
        assert "Could not draft reply" in data["answer"]
        assert "Action requires a specific case or task reference" in data["answer"]
        assert any("⚠️ Could not draft reply" in s for s in data["steps"])


def test_open_view_waiting_maps_to_dashboard_not_maintenance():
    """Verify that open_view with view='waiting' always maps to Dashboard Radar even with prompt keywords (Issue #9)."""
    mock_engine = MagicMock()
    app = as_owner(create_app(SETTINGS, engine=mock_engine))

    fake_plan = ConciergePlan(
        in_scope=True,
        steps=[PlanStep(intent=Intent.open_view, case_id=None, task_ref=None, text=None, view="waiting")],
        reply=None,
    )
    mock_result = StepResult(
        intent=Intent.open_view,
        ok=True,
        summary="Navigating to waiting items",
        data=None,
        view="waiting",
    )

    mock_sess = create_mock_session()
    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch("app.api.agent.routes.run_plan", return_value=[mock_result]),
        patch("app.api.agent.intent_responses.assemble_answer", return_value="Opening waiting view"),
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = fake_plan

        # Prompt contains "repair ticket" which previously diverted navigation to Maintenance
        res = client.post(URL, json={"query": "show repair ticket radar"})
        assert res.status_code == 200
        actions = res.json()["actions"]
        assert len(actions) > 0
        nav_action = next(a for a in actions if a["actionType"] == "navigate")
        assert nav_action["payload"] == "/"
        assert nav_action["label"] == "View Waiting Radar on Dashboard"


def test_resolve_draft_card_strict_reply_draft():
    """Verify that _resolve_draft_card renders a draft_message card only for reply_draft actions with real recipient."""
    from app.api.agent.routes import _resolve_draft_card
    from app.contracts import ActionType
    from app.db.enums import ApprovalStatus
    from app.db.models import ActionRow, Approval, Case, Unit

    mock_engine = MagicMock()
    mock_sess = MagicMock()

    test_approval_id = uuid4()
    test_action_id = uuid4()
    test_case_id = uuid4()
    test_unit_id = uuid4()

    mock_appr = MagicMock(spec=Approval)
    mock_appr.id = test_approval_id
    mock_appr.action_id = test_action_id
    mock_appr.status = ApprovalStatus.pending

    mock_act = MagicMock(spec=ActionRow)
    mock_act.id = test_action_id
    mock_act.case_id = test_case_id
    mock_act.type = ActionType.reply_draft
    mock_act.payload = {
        "channel": "whatsapp",
        "body": "Hi Vipin, our emergency plumber Kevin van Dijk is en route.",
    }
    mock_act.persona_name = "Harjot v2"
    mock_act.persona_version = 2

    mock_case = MagicMock(spec=Case)
    mock_case.id = test_case_id
    mock_case.unit_id = test_unit_id

    mock_unit = MagicMock(spec=Unit)
    mock_unit.id = test_unit_id
    mock_unit.address = "Keizersgracht 42-A, Amsterdam"

    def mock_get(model, pk):
        if model is Approval and pk == test_approval_id:
            return mock_appr
        if model is ActionRow and pk == test_action_id:
            return mock_act
        if model is Case and pk == test_case_id:
            return mock_case
        if model is Unit and pk == test_unit_id:
            return mock_unit
        return None

    mock_sess.get.side_effect = with_conversation(mock_get)
    mock_sess.__enter__.return_value = mock_sess

    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes._find_case_recipient", return_value=("+31612345678", "whatsapp", None, None)),
    ):
        card = _resolve_draft_card(mock_engine, approval_ids=[str(test_approval_id)])
        assert card is not None
        assert card.type == "draft_message"
        assert card.recipient == "+31612345678"
        assert card.channel == "whatsapp"
        assert card.unitLabel == "Keizersgracht 42-A, Amsterdam"
        assert (card.personaName, card.personaVersion) == ("Harjot v2", 2)
        assert "Kevin van Dijk" in card.body


def test_resolve_draft_card_renders_notice_for_notify_owner():
    """Verify that notify_owner actions render as notice cards, never disguised as a draft message (WP2)."""
    from app.api.agent.routes import _resolve_draft_card
    from app.contracts import ActionType
    from app.db.enums import ApprovalStatus
    from app.db.models import ActionRow, Approval

    mock_engine = MagicMock()
    mock_sess = MagicMock()

    test_approval_id = uuid4()
    test_action_id = uuid4()
    test_case_id = uuid4()

    mock_appr = MagicMock(spec=Approval)
    mock_appr.id = test_approval_id
    mock_appr.action_id = test_action_id
    mock_appr.status = ApprovalStatus.pending

    mock_act = MagicMock(spec=ActionRow)
    mock_act.id = test_action_id
    mock_act.case_id = test_case_id
    mock_act.type = ActionType.notify_owner
    mock_act.payload = {
        "kind": "notify_owner",
        "text": "EstateOS could not draft a reply for a new message on this case. Please look at it yourself.",
    }

    def mock_get(model, pk):
        if model is Approval and pk == test_approval_id:
            return mock_appr
        if model is ActionRow and pk == test_action_id:
            return mock_act
        return None

    mock_sess.get.side_effect = with_conversation(mock_get)
    mock_sess.__enter__.return_value = mock_sess

    with patch("app.api.agent.routes.Session", return_value=mock_sess):
        card = _resolve_draft_card(mock_engine, approval_ids=[str(test_approval_id)])
        assert card is not None
        assert card.type == "notice"
        assert card.badgeLabel == "NOTICE"
        assert "EstateOS could not draft a reply" in card.body
        assert card.actionId == str(test_action_id)


def test_resolve_draft_card_returns_none_without_approvals():
    """Verify that without approval_ids, _resolve_draft_card returns None (no arbitrary fallback)."""
    from app.api.agent.routes import _resolve_draft_card

    mock_engine = MagicMock()
    assert _resolve_draft_card(mock_engine, approval_ids=None) is None
    assert _resolve_draft_card(mock_engine, approval_ids=[]) is None


def test_priority_inquiry_matches_urgent_case_not_newsletter():
    """Verify that asking 'What should I do first?' selects the urgent case, not the newest newsletter case."""
    from app.contracts import CaseState, Urgency

    mock_engine = MagicMock()
    app = as_owner(create_app(SETTINGS, engine=mock_engine))

    comp_id = uuid4()
    emergency_case_id = uuid4()
    newsletter_case_id = uuid4()

    mock_emergency_case = MagicMock()
    mock_emergency_case.id = emergency_case_id
    mock_emergency_case.company_id = comp_id
    mock_emergency_case.urgency = Urgency.emergency
    mock_emergency_case.state = CaseState.open
    mock_emergency_case.summary = "Tenant Vipin Tyagi reported emergency water leak at Keizersgracht 42-A"
    mock_emergency_case.unit_id = None
    mock_emergency_case.lease_id = None

    mock_newsletter_case = MagicMock()
    mock_newsletter_case.id = newsletter_case_id
    mock_newsletter_case.company_id = comp_id
    mock_newsletter_case.urgency = Urgency.normal
    mock_newsletter_case.state = CaseState.open
    mock_newsletter_case.summary = "Marketing newsletter with general market updates"
    mock_newsletter_case.unit_id = None
    mock_newsletter_case.lease_id = None

    # Database returns cases where newsletter arrived newest, followed by emergency leak
    def mock_scalars(query):
        result = MagicMock()
        q_str = str(query).lower()
        if "from companies" in q_str:
            company = MagicMock()
            company.id = comp_id
            result.first.return_value = company
        elif "from cases" in q_str:
            result.all.return_value = [mock_newsletter_case, mock_emergency_case]
            result.first.return_value = mock_newsletter_case
        else:
            result.first.return_value = None
            result.all.return_value = []
        return result

    mock_sess = MagicMock()
    mock_sess.scalars.side_effect = mock_scalars
    mock_sess.get.side_effect = with_conversation(lambda _model, _ident: None)
    mock_sess.__enter__.return_value = mock_sess

    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch("app.api.agent.routes.run_plan", return_value=[]),
        patch(
            "app.api.agent.intent_responses.assemble_answer",
            return_value="The urgent matter is the emergency water leak at Keizersgracht 42-A.",
        ),
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = ConciergePlan(
            in_scope=False, steps=[], reply="The urgent matter is the emergency water leak at Keizersgracht 42-A."
        )

        res = client.post(URL, json={"query": "What should I do first?"})
        assert res.status_code == 200
        card = res.json()["previewCard"]
        assert card is not None
        assert card["type"] == "case_summary"
        assert card["badgeLabel"] == "URGENT"
        assert card["caseId"] == str(emergency_case_id)
        assert "Keizersgracht" in card["body"]
        assert "newsletter" not in card["body"].lower()


def test_document_rag_returns_document_item_preview_card():
    """Verify that document inquiries return previewCard.type == 'document_item' with Google Drive link."""
    from app.db.models import DocumentRow

    mock_engine = MagicMock()
    app = as_owner(create_app(SETTINGS, engine=mock_engine))

    comp_id = uuid4()
    doc_id = uuid4()

    mock_hit = MagicMock()
    mock_hit.document_id = doc_id
    mock_hit.snippet = "Tenant: Vipin Tyagi. Article 1 - Monthly Rent: EUR 1,850.00."

    mock_doc = MagicMock()
    mock_doc.id = doc_id
    mock_doc.title = "Residential Lease Agreement - Keizersgracht 42-A"
    mock_doc.doc_type = "lease"
    mock_doc.drive_file_id = "18EMTSCvv6YOWzahd4ObBO3c5BxlSCH8a"
    mock_doc.drive_folder = "EstateOS/Keizersgracht 42-A/Leases/2026"

    mock_sess = create_mock_session(comp_id=comp_id, get_map={(DocumentRow, doc_id): mock_doc})

    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.search_hybrid", return_value=[mock_hit]),
        patch(
            "app.api.agent.routes._generate_chat_answer",
            return_value="Verified lease agreement for Vipin Tyagi at Keizersgracht 42-A.",
        ),
        TestClient(app) as client,
    ):
        res = client.post(URL, json={"query": "lease agreement for this case"})
        assert res.status_code == 200
        data = res.json()
        card = data["previewCard"]
        assert card is not None
        assert card["type"] == "document_item"
        assert card["badgeLabel"] == "GOOGLE DRIVE"
        assert "Keizersgracht" in card["title"]
        assert "drive.google.com" in card["targetUrl"]
        assert "whatsapp" not in (card.get("channel") or "")


def _plan(*steps: PlanStep) -> ConciergePlan:
    return ConciergePlan(in_scope=True, steps=list(steps), reply=None)


def _step(intent: Intent, *, text: str | None = None, task_ref: str | None = None) -> PlanStep:
    return PlanStep(intent=intent, case_id=None, task_ref=task_ref, text=text, view=None)


def _rule_session() -> MagicMock:
    """A fake session in which no rule is stored yet, so the real `record_owner_memory` adds a new one."""
    sess = create_mock_session()
    sess.scalar.return_value = None
    return sess


def _added_rules(sess: MagicMock) -> list:
    from app.db.models import MemoryItem

    return [c.args[0] for c in sess.add.call_args_list if isinstance(c.args[0], MemoryItem)]


def test_standing_rule_creates_proposed_memory_with_action_card():
    """Verify Issue 1.9: a standing rule the planner names (`remember`) is a proposed memory item with approval
    action buttons; the planner decides, the "Standing rule:" prefix no longer does."""
    from app.db.enums import MemoryStatus

    mock_engine = MagicMock()
    app = as_owner(create_app(SETTINGS, engine=mock_engine))

    fake_memory = MagicMock()
    fake_memory.id = UUID(int=578)
    fake_memory.text = "Always require owner signoff for repairs exceeding €500"
    fake_memory.status = MemoryStatus.proposed
    plan = _plan(_step(Intent.remember, text="Always require owner signoff for repairs exceeding €500"))

    mock_sess = create_mock_session()
    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch("app.api.agent.routes.run_plan") as mock_run_plan,
        patch("app.context.memory_items.record_owner_memory", return_value=(fake_memory, None)) as mock_record,
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = plan
        res = client.post(URL, json={"query": "Standing rule: Always require owner signoff for repairs exceeding €500"})
        assert res.status_code == 200
        data = res.json()
        assert "drafted a new proposed standing rule" in data["answer"]
        assert data["previewCard"] is not None
        assert data["previewCard"]["type"] == "memory_item"
        assert data["previewCard"]["badgeLabel"] == "POLICY PROPOSAL"
        assert data["previewCard"]["actionId"] == str(fake_memory.id)
        assert any(a["actionType"] == "approve_memory" for a in data["actions"])
        mock_run_agent.assert_called_once()
        mock_run_plan.assert_not_called()
        mock_record.assert_called_once()
        _, kwargs = mock_record.call_args
        assert kwargs.get("status") == MemoryStatus.proposed


def test_remember_intent_proposes_a_standing_rule():
    from app.db.enums import MemoryKind, MemoryScope, MemoryStatus

    app = as_owner(create_app(SETTINGS, engine=MagicMock()))
    rule = "Tenants in building A get replies in English"
    mock_sess = _rule_session()
    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch("app.api.agent.routes.run_plan") as mock_run_plan,
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = _plan(_step(Intent.remember, text=rule))
        res = client.post(URL, json={"query": "from now on tenants in building A get replies in English"})

    assert res.status_code == 200
    data = res.json()
    [stored] = _added_rules(mock_sess)
    assert (stored.text, stored.status, stored.scope, stored.kind) == (
        rule,
        MemoryStatus.proposed,
        MemoryScope.company,
        MemoryKind.rule,
    )
    assert data["debugInfo"]["pipeline_stage"] == "memory_rule"
    assert data["previewCard"]["type"] == "memory_item"
    assert data["previewCard"]["body"] == rule
    assert [c["type"] for c in data["cards"]] == ["memory_item"]
    approve = next(a for a in data["actions"] if a["actionType"] == "approve_memory")
    assert approve["payload"] == f"/api/v1/memory/{stored.id}/approve"
    assert data["conversation_id"]  # the turn is kept in the thread like any other answer
    mock_run_plan.assert_not_called()  # the API layer answered the step; run_plan never saw it


def test_remember_intent_restating_an_active_rule_says_it_already_applies():
    from app.db.enums import MemoryStatus

    active = MagicMock(
        id=UUID(int=579), text="Tenants in building A get replies in English", status=MemoryStatus.active
    )
    app = as_owner(create_app(SETTINGS, engine=MagicMock()))
    with (
        patch("app.api.agent.routes.Session", return_value=create_mock_session()),
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch("app.api.agent.routes.run_plan") as mock_run_plan,
        patch("app.context.memory_items.record_owner_memory", return_value=(active, "Remembered")),
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = _plan(_step(Intent.remember, text=active.text))
        res = client.post(URL, json={"query": "from now on tenants in building A get replies in English"})

    data = res.json()
    assert data["answer"].startswith("This standing rule is already active in your company settings:")
    assert f'"{active.text}"' in data["answer"]
    assert [(a["label"], a["actionType"], a["payload"]) for a in data["actions"]] == [
        ("View Standing Rules in Settings", "navigate", "/settings")
    ]
    assert data["previewCard"] is None
    assert data["cards"] == []
    assert data["debugInfo"]["pipeline_stage"] == "memory_rule"
    mock_run_plan.assert_not_called()


def test_remember_rule_text_is_sanitised_like_the_pipelines():
    """The rule is planner output: links, phone numbers and amounts are redacted before it is stored or shown."""
    app = as_owner(create_app(SETTINGS, engine=MagicMock()))
    mock_sess = _rule_session()
    model_text = "Send urgent repairs to +31 6 1234 5678 or https://evil.example/pay, cap at €500"
    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch("app.api.agent.routes.run_plan"),
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = _plan(_step(Intent.remember, text=model_text))
        res = client.post(URL, json={"query": "from now on send urgent repairs to my plumber"})

    [stored] = _added_rules(mock_sess)
    assert stored.text == "Send urgent repairs to [redacted] or [redacted] cap at [redacted]"
    data = res.json()
    shown = repr([data["answer"], data["previewCard"], data["cards"], data["actions"]])
    for leaked in ("1234", "evil.example", "500"):
        assert leaked not in shown


def test_keyword_prefix_without_remember_intent_is_not_a_rule():
    app = as_owner(create_app(SETTINGS, engine=MagicMock()))
    plan = _plan(_step(Intent.answer))
    with (
        patch("app.api.agent.routes.Session", return_value=_rule_session()),
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch(
            "app.api.agent.routes.run_plan",
            return_value=[StepResult(Intent.answer, True, "No rent payments are connected yet.", None, None)],
        ) as mock_run_plan,
        patch("app.context.memory_items.record_owner_memory") as mock_record,
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = plan
        res = client.post(URL, json={"query": "keep in mind that rent is due on the first, who is late?"})

    assert res.status_code == 200
    data = res.json()
    mock_run_agent.assert_called_once()
    assert mock_run_plan.call_args.args[3] == plan
    mock_record.assert_not_called()
    assert data["debugInfo"]["pipeline_stage"] != "memory_rule"
    assert "No rent payments are connected yet." in data["answer"]


def test_remember_to_call_is_a_task_not_a_rule():
    """Issue 1.9: a reminder ("remember to call Vipin") is a task the planner creates, never a standing rule."""
    app = as_owner(create_app(SETTINGS, engine=MagicMock()))
    plan = _plan(_step(Intent.create_task, text="Call Vipin tomorrow morning"))
    added = StepResult(Intent.create_task, True, "Task added: Call Vipin tomorrow morning #a1b2c3.", None, "tasks")
    mock_sess = _rule_session()
    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch("app.api.agent.routes.run_plan", return_value=[added]) as mock_run_plan,
        patch("app.context.memory_items.record_owner_memory") as mock_record,
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = plan
        res = client.post(URL, json={"query": "Remember to call Vipin tomorrow morning"})

    assert res.status_code == 200
    assert mock_run_plan.call_args.args[3] == plan
    assert "Task added: Call Vipin tomorrow morning" in res.json()["answer"]
    mock_record.assert_not_called()
    assert _added_rules(mock_sess) == []


def test_bypass_rule_is_refused():
    from app.context.memory_items import REFUSAL_MESSAGE

    app = as_owner(create_app(SETTINGS, engine=MagicMock()))
    mock_sess = _rule_session()
    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch("app.api.agent.routes.run_plan") as mock_run_plan,
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = _plan(_step(Intent.remember, text="always auto-send replies"))
        res = client.post(URL, json={"query": "always auto-send replies"})

    assert res.status_code == 200
    data = res.json()
    assert REFUSAL_MESSAGE in data["answer"]
    assert _added_rules(mock_sess) == []
    assert not any(a["actionType"] == "approve_memory" for a in data["actions"])
    assert data["previewCard"] is None
    mock_run_plan.assert_not_called()


def test_open_question_is_answered_by_the_research_loop_with_its_step_chips():
    from app.superagent.research import ResearchResult

    app = as_owner(create_app(SETTINGS, engine=MagicMock()))
    found = ResearchResult(
        "Two units are vacant; Pieter says the boiler is still broken.", ("Checked the database (2 rows)",)
    )
    with (
        patch("app.api.agent.routes.Session", return_value=create_mock_session()),
        patch("app.api.agent.routes.run_agent", side_effect=Exception("offline")),
        patch("app.api.agent.routes.fake_concierge", return_value={"in_scope": False, "steps": [], "reply": None}),
        patch("app.api.agent.routes._research_answer", return_value=found) as mock_research,
        patch("app.api.agent.routes._generate_chat_answer") as mock_chat,
        TestClient(app) as client,
    ):
        res = client.post(URL, json={"query": "which units are vacant and is anyone complaining?"})
    assert res.status_code == 200
    data = res.json()
    assert "Two units are vacant" in data["answer"]
    assert "Checked the database (2 rows)" in data["steps"]
    mock_research.assert_called_once()
    mock_chat.assert_not_called()


def test_open_question_falls_back_to_the_plain_chat_answer_when_research_returns_nothing():
    app = as_owner(create_app(SETTINGS, engine=MagicMock()))
    with (
        patch("app.api.agent.routes.Session", return_value=create_mock_session()),
        patch("app.api.agent.routes.run_agent", side_effect=Exception("offline")),
        patch("app.api.agent.routes.fake_concierge", return_value={"in_scope": False, "steps": [], "reply": None}),
        patch("app.api.agent.routes._research_answer", return_value=None),
        patch("app.api.agent.routes._generate_chat_answer", return_value="Hi Harjot, all quiet today."),
        TestClient(app) as client,
    ):
        res = client.post(URL, json={"query": "hey, how is it going?"})
    assert res.status_code == 200
    assert "all quiet today" in res.json()["answer"]


def test_list_active_leases_returns_data_table_preview_card_without_sql_in_steps():
    """Verify analytics list queries route to query_agent and return structured data_table cards."""
    from app.tools.query_agent.agent import QueryAgentResponse

    app = as_owner(create_app(SETTINGS, engine=MagicMock()))
    fake_rows = [
        {
            "Tenant": "Vipin Tyagi",
            "Property": "Keizersgracht 42-A, 1015 CR Amsterdam",
            "Lease Start": "02 Nov 2026",
            "Lease End": "31 Dec 2026",
            "Status": "Active",
        },
        {
            "Tenant": "Anouk de Jong",
            "Property": "Keizersgracht 42-B, 1015 CS Amsterdam",
            "Lease Start": "01 Jan 2025",
            "Lease End": "31 Dec 2026",
            "Status": "Active",
        },
    ]
    fake_qres = QueryAgentResponse(
        ok=True,
        answer="There are **2 active leases** across Keizersgracht 42-A and 42-B.",
        sql="SELECT tenant_name, unit_address FROM v_active_leases WHERE is_active = TRUE LIMIT 50",
        rows=fake_rows,
        row_count=2,
        duration_ms=12.4,
        columns=["Tenant", "Property", "Lease Start", "Lease End", "Status"],
        display_rows=fake_rows,
    )

    with (
        patch("app.api.agent.routes.Session", return_value=create_mock_session()),
        patch("app.tools.query_agent.agent.run_query_agent", return_value=fake_qres) as mock_qagent,
        TestClient(app) as client,
    ):
        res = client.post(URL, json={"query": "List active leases"})

    assert res.status_code == 200
    mock_qagent.assert_called_once()
    data = res.json()
    assert data["previewCard"] is not None
    assert data["previewCard"]["type"] == "data_table"
    assert data["previewCard"]["badgeLabel"] == "LEASES"
    assert len(data["previewCard"]["rows"]) == 2
    assert all("SELECT " not in s for s in data["steps"])
    assert any(a["payload"] == "/tenants" for a in data["actions"])


def test_open_tickets_and_rent_queries_never_synthesize_fake_entities():
    """Verify neither rent queries nor ticket typos ever synthesize fake hardcoded cards or contacts."""
    from app.tools.query_agent.agent import QueryAgentResponse

    app = as_owner(create_app(SETTINGS, engine=MagicMock()))
    empty_qres = QueryAgentResponse(
        ok=True,
        answer='I queried your portfolio records for *"show all open ticketes"*, but found 0 matching entries.',
        sql="SELECT * FROM v_case_overview LIMIT 50",
        rows=[],
        row_count=0,
        duration_ms=8.0,
        columns=[],
        display_rows=[],
    )

    with (
        patch("app.api.agent.routes.Session", return_value=create_mock_session()),
        patch("app.tools.query_agent.agent.run_query_agent", return_value=empty_qres),
        patch("app.api.agent.routes.run_agent", side_effect=Exception("offline")),
        patch("app.api.agent.routes.fake_concierge", return_value={"in_scope": False, "steps": [], "reply": None}),
        TestClient(app) as client,
    ):
        res_tickets = client.post(URL, json={"query": "show all open ticketes"})
        res_rent = client.post(URL, json={"query": "Who owes rent?"})

    for res in (res_tickets, res_rent):
        assert res.status_code == 200
        body = res.text
        assert "Pieter Bakker" not in body
        assert "Singel 102" not in body
        assert "Praveen Rostova" not in body
        assert "1.450" not in body


def test_clean_executive_answer_formats_case_uuids_and_iso_timestamps():
    """Verify defense-in-depth cleanup formats raw UUIDs and timestamps while keeping URLs and normal prose intact."""
    from app.api.agent.routes import _clean_executive_answer

    raw = (
        "Opening cases. **Case id**: 01a1ca59-c6cb-7e02-bd67-f86ff1b72267 | "
        "**Opened at**: 2026-11-11 11:24:03.646025+00:00\n"
        "- #c80c5a\u202f|\u202fNormal other\u202f|\u202fLease extension\n"
        "Details: https://example.com/tickets/01a1ca59-c6cb-7e02-bd67-f86ff1b72267"
    )
    cleaned = _clean_executive_answer(raw)
    assert "Opening cases" not in cleaned
    assert "**Ticket #b72267**" in cleaned
    assert "|" not in cleaned
    assert "11 Nov 2026, 12:24" in cleaned  # 11:24 UTC is 12:24 in Amsterdam
    assert "https://example.com/tickets/01a1ca59-c6cb-7e02-bd67-f86ff1b72267" in cleaned


def test_open_view_only_priority_question_triggers_research_prose():
    """Verify advisory questions planned as open_view only still invoke research prose instead of empty card copy."""
    from app.superagent.research import ResearchResult

    app = as_owner(create_app(SETTINGS, engine=MagicMock()))
    fake_plan = ConciergePlan(
        in_scope=True,
        steps=[PlanStep(intent=Intent.open_view, case_id=None, task_ref=None, text=None, view="cases")],
        reply=None,
    )
    mock_result = StepResult(
        intent=Intent.open_view,
        ok=True,
        summary="Opening cases.",
        data=None,
        view="cases",
    )
    researched = ResearchResult(
        "Start with Ticket #b72267 (Emergency water leak at Keizersgracht 42-B).",
        ("Checked active cases (3 rows)",),
    )

    with (
        patch("app.api.agent.routes.Session", return_value=create_mock_session()),
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch("app.api.agent.routes.run_plan", return_value=[mock_result]),
        patch("app.api.agent.intent_responses.assemble_answer", return_value="Opening cases."),
        patch("app.api.agent.routes._research_answer", return_value=researched) as mock_res,
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = fake_plan
        res = client.post(URL, json={"query": "What should I do first?"})

    assert res.status_code == 200
    data = res.json()
    mock_res.assert_called_once()
    assert "Start with Ticket #b72267" in data["answer"]
    assert "Checked active cases (3 rows)" in data["steps"]


def test_prioritization_query_strips_draft_intents_and_returns_ranking_cards():
    """Ranking questions like 'whome to reply first important' must never route to draft_reply."""
    from app.contracts import CaseState, Category, Urgency
    from app.superagent.research import ResearchResult

    app = as_owner(create_app(SETTINGS, engine=MagicMock()))
    comp_id = TEST_COMP_ID
    urgent_cid = uuid4()

    urgent_case = Case(
        id=urgent_cid,
        company_id=comp_id,
        category=Category.maintenance,
        urgency=Urgency.emergency,
        state=CaseState.open,
        summary="Water leak at Keizersgracht 42-B.",
    )

    def mock_scalars(query):
        res = MagicMock()
        q_str = str(query).lower()
        if "from companies" in q_str:
            res.first.return_value = Company(id=comp_id, name="EstateOS Test")
            res.all.return_value = []
        elif "from cases" in q_str:
            res.all.return_value = [urgent_case]
            res.first.return_value = urgent_case
        else:
            res.first.return_value = None
            res.all.return_value = []
        return res

    mock_sess = MagicMock()
    mock_sess.scalars.side_effect = mock_scalars
    mock_sess.get.side_effect = with_conversation(lambda _m, _k: None)
    mock_sess.__enter__.return_value = mock_sess

    bad_plan = ConciergePlan(
        in_scope=True,
        steps=[PlanStep(intent=Intent.draft_reply, case_id=urgent_cid, task_ref=None, text=None, view=None)],
        reply=None,
        suggestions=["Send WhatsApp now", "Make reply firmer", "Open in Inbox"],
    )
    researched = ResearchResult(
        "Reply to Anouk at Keizersgracht 42-B first due to the active water leak.",
        ("Checked active cases (1 row)",),
    )

    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch("app.api.agent.routes.run_plan") as mock_run_plan,
        patch("app.api.agent.routes._research_answer", return_value=researched) as mock_res,
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = bad_plan
        res = client.post(URL, json={"query": "whome to reply first important"})

    assert res.status_code == 200
    data = res.json()
    mock_run_plan.assert_not_called()
    mock_res.assert_called_once()
    assert "Keizersgracht 42-B" in data["answer"]
    assert data["previewCard"] is not None
    assert data["previewCard"]["type"] == "case_summary"
    assert "Send WhatsApp now" not in data["suggestedPrompts"]
    assert "Make reply firmer" not in data["suggestedPrompts"]


def test_multi_draft_request_expands_to_three_urgency_ordered_cards():
    """Plural requests ('give me drafted replies for these tickets') expand to up to 3 urgency-sorted draft cards."""
    from app.contracts import CaseState, Category, Urgency

    comp_id = TEST_COMP_ID
    c_emerg = uuid4()
    c_high = uuid4()
    c_norm = uuid4()

    ap_emerg, act_emerg = uuid4(), uuid4()
    ap_high, act_high = uuid4(), uuid4()
    ap_norm, act_norm = uuid4(), uuid4()

    cases_list = [
        Case(
            id=c_norm,
            company_id=comp_id,
            category=Category.administration,
            urgency=Urgency.normal,
            state=CaseState.open,
            summary="Lease renewal C",
        ),
        Case(
            id=c_high,
            company_id=comp_id,
            category=Category.maintenance,
            urgency=Urgency.high,
            state=CaseState.open,
            summary="No heating A",
        ),
        Case(
            id=c_emerg,
            company_id=comp_id,
            category=Category.maintenance,
            urgency=Urgency.emergency,
            state=CaseState.open,
            summary="Water leak B",
        ),
    ]
    get_map = {
        (Approval, ap_emerg): Approval(id=ap_emerg, company_id=comp_id, action_id=act_emerg),
        (ActionRow, act_emerg): ActionRow(
            id=act_emerg,
            company_id=comp_id,
            case_id=c_emerg,
            type=ActionType.reply_draft,
            payload={"channel": "whatsapp", "to": "+31611111111", "body_variants": ["Plumber on the way B."]},
        ),
        (Case, c_emerg): cases_list[2],
        (Approval, ap_high): Approval(id=ap_high, company_id=comp_id, action_id=act_high),
        (ActionRow, act_high): ActionRow(
            id=act_high,
            company_id=comp_id,
            case_id=c_high,
            type=ActionType.reply_draft,
            payload={"channel": "whatsapp", "to": "+31622222222", "body_variants": ["Heating tech A."]},
        ),
        (Case, c_high): cases_list[1],
        (Approval, ap_norm): Approval(id=ap_norm, company_id=comp_id, action_id=act_norm),
        (ActionRow, act_norm): ActionRow(
            id=act_norm,
            company_id=comp_id,
            case_id=c_norm,
            type=ActionType.reply_draft,
            payload={"channel": "gmail", "to": "elena@example.nl", "body_variants": ["Lease renewal C."]},
        ),
        (Case, c_norm): cases_list[0],
    }

    def mock_scalars(query):
        res = MagicMock()
        q_str = str(query).lower()
        if "from companies" in q_str:
            res.first.return_value = Company(id=comp_id, name="EstateOS Test")
            res.all.return_value = []
        elif "from cases" in q_str:
            res.all.return_value = cases_list
            res.first.return_value = cases_list[0]
        else:
            res.first.return_value = None
            res.all.return_value = []
        return res

    mock_sess = MagicMock()
    mock_sess.scalars.side_effect = mock_scalars
    mock_sess.get.side_effect = with_conversation(lambda model, pk: get_map.get((model, pk)))
    mock_sess.__enter__.return_value = mock_sess

    # Model only emitted c_norm; backend must expand to [c_emerg, c_high, c_norm]
    partial_plan = ConciergePlan(
        in_scope=True,
        steps=[PlanStep(intent=Intent.show_drafts, case_id=c_norm, task_ref=None, text=None, view=None)],
        reply=None,
    )
    appr_by_case = {c_emerg: ap_emerg, c_high: ap_high, c_norm: ap_norm}
    captured_turns: list[object] = []

    def fake_run_plan(_eng, _set, _cid, plan_obj, **_kwargs):
        captured_turns.append(_kwargs.get("turn_id"))
        return [
            StepResult(
                intent=s.intent,
                ok=True,
                summary="Draft ready\nDraft 1:\n> hi",
                data={"approval_ids": [str(appr_by_case[s.case_id])], "case_id": str(s.case_id)},
                view=None,
            )
            for s in plan_obj.steps
        ]

    app = as_owner(create_app(SETTINGS, engine=MagicMock()))
    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch("app.api.agent.routes.run_plan", side_effect=fake_run_plan) as mock_rp,
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = partial_plan
        res = client.post(URL, json={"query": "give me drafted replies for these tickets"})

    assert res.status_code == 200
    data = res.json()
    assert len(captured_turns) == 1
    assert captured_turns[0] is not None
    dispatched_plan = mock_rp.call_args[0][3]
    assert [s.case_id for s in dispatched_plan.steps] == [c_emerg, c_high, c_norm]
    assert len(data["previewCards"]) == 3
    assert [c["caseId"] for c in data["previewCards"]] == [str(c_emerg), str(c_high), str(c_norm)]
    assert "Draft 1:" not in data["answer"]
    assert "3 draft replies" in data["answer"]


def test_inline_understanding_triggered_before_draft_when_missing():
    """If an inbound message on a targeted draft case has no UnderstandingRow, run understand_message inline first."""
    from app.contracts import CaseState, Category, Urgency
    from app.db.models import MessageRow

    comp_id = TEST_COMP_ID
    case_id = uuid4()
    msg_id = uuid4()
    case_obj = Case(
        id=case_id,
        company_id=comp_id,
        category=Category.maintenance,
        urgency=Urgency.emergency,
        state=CaseState.open,
        summary="Leak",
    )
    msg_obj = MessageRow(id=msg_id, company_id=comp_id)

    def mock_scalars(query):
        res = MagicMock()
        q_str = str(query).lower()
        if "from companies" in q_str:
            res.first.return_value = Company(id=comp_id, name="EstateOS Test")
            res.all.return_value = []
        elif "from cases" in q_str:
            res.all.return_value = [case_obj]
            res.first.return_value = case_obj
        elif "from messages" in q_str:
            res.first.return_value = msg_obj
            res.all.return_value = [msg_obj]
        else:
            res.first.return_value = None
            res.all.return_value = []
        return res

    mock_sess = MagicMock()
    mock_sess.scalars.side_effect = mock_scalars
    mock_sess.get.side_effect = with_conversation(lambda _m, _k: None)
    mock_sess.__enter__.return_value = mock_sess

    draft_plan = ConciergePlan(
        in_scope=True,
        steps=[PlanStep(intent=Intent.draft_reply, case_id=case_id, task_ref=None, text=None, view=None)],
        reply=None,
    )
    app = as_owner(create_app(SETTINGS, engine=MagicMock()))
    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.understand.understand_message") as mock_understand,
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch(
            "app.api.agent.routes.run_plan",
            return_value=[StepResult(Intent.draft_reply, False, "nothing", None, None)],
        ),
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = draft_plan
        res = client.post(URL, json={"query": "draft reply for this ticket"})

    assert res.status_code == 200
    mock_understand.assert_called_once()
    assert mock_understand.call_args[0][2] == msg_id


def test_singular_open_ticket_query_routes_to_query_agent():
    """Singular phrasing like 'what open ticket i have' still triggers query_agent reliably."""
    from app.tools.query_agent.agent import QueryAgentResponse

    app = as_owner(create_app(SETTINGS, engine=MagicMock()))
    fake_rows = [
        {"Ticket": "#111111", "Unit": "Keizersgracht 42-B", "Urgency": "emergency", "State": "open"},
        {"Ticket": "#222222", "Unit": "Keizersgracht 42-A", "Urgency": "high", "State": "waiting on third party"},
    ]
    fake_qres = QueryAgentResponse(
        ok=True,
        answer="You have **2 open tickets**.",
        sql="SELECT * FROM v_case_overview LIMIT 50",
        rows=fake_rows,
        row_count=2,
        duration_ms=5.1,
        columns=["Ticket", "Unit", "Urgency", "State"],
        display_rows=fake_rows,
    )
    with (
        patch("app.api.agent.routes.Session", return_value=create_mock_session()),
        patch("app.tools.query_agent.agent.run_query_agent", return_value=fake_qres) as mock_qa,
        TestClient(app) as client,
    ):
        res = client.post(URL, json={"query": "what open ticket i have"})

    assert res.status_code == 200
    mock_qa.assert_called_once()
    assert res.json()["previewCard"]["type"] == "data_table"


def test_sanitize_suggestions_filters_unsafe_and_channel_mismatched_pills():
    """Unsafe/unsupported pills and wrong-channel suggestions are stripped and padded to 3 safe items."""
    from app.api.agent.routes import PreviewCardData, _sanitize_suggestions

    gmail_card = PreviewCardData(type="draft_message", channel="gmail", unitLabel="42-C")
    cleaned = _sanitize_suggestions(
        [
            "Send WhatsApp now",
            "Make reply firmer",
            "Draft plumber order",
            "Show leak photos",
            "Open ticket drawer",
            "Check WhatsApp",
            "Open in Inbox",
        ],
        [gmail_card],
        "give me drafted replies",
    )
    assert len(cleaned) == 3
    assert all("send whatsapp now" not in p.lower() for p in cleaned)
    assert all("firmer" not in p.lower() for p in cleaned)
    assert all("plumber order" not in p.lower() for p in cleaned)
    assert all("leak photos" not in p.lower() for p in cleaned)
    assert all("ticket drawer" not in p.lower() for p in cleaned)
    assert all("whatsapp" not in p.lower() for p in cleaned)
    assert "Open in Inbox" in cleaned
