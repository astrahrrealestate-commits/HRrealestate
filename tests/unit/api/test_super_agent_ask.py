from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.contracts import ActionType, ConciergePlan, Intent, PlanStep
from app.core.settings import Settings
from app.db.models import ActionRow, Approval, Case, Company
from app.main import create_app
from app.pipeline.concierge import StepResult
from tests.api_auth import as_owner

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
    mock_sess.get.side_effect = lambda model, ident: get_map.get((model, ident))
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
        patch("app.api.agent.routes.assemble_answer", return_value=long_answer),
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
        patch("app.api.agent.routes.assemble_answer", return_value=short_answer),
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
        patch("app.api.agent.routes.assemble_answer", return_value="Draft prepared for review."),
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
        patch("app.api.agent.routes.assemble_answer", return_value="I need more detail"),
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
        patch("app.api.agent.routes.assemble_answer", return_value="Opening waiting view"),
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

    mock_sess.get.side_effect = mock_get
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

    mock_sess.get.side_effect = mock_get
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
    mock_sess.get.return_value = None
    mock_sess.__enter__.return_value = mock_sess

    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        patch("app.api.agent.routes.run_plan", return_value=[]),
        patch(
            "app.api.agent.routes.assemble_answer",
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


def test_standing_rule_creates_proposed_memory_with_action_card():
    """Verify Issue 1.9: standing rules create proposed memory items with approval action buttons."""
    from app.db.enums import MemoryStatus

    mock_engine = MagicMock()
    app = as_owner(create_app(SETTINGS, engine=mock_engine))

    fake_memory = MagicMock()
    fake_memory.id = uuid4()
    fake_memory.text = "Always require owner signoff for repairs exceeding €500"
    fake_memory.status = MemoryStatus.proposed

    mock_sess = create_mock_session()
    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.context.memory_items.record_owner_memory", return_value=(fake_memory, None)) as mock_record,
        TestClient(app) as client,
    ):
        res = client.post(URL, json={"query": "Standing rule: Always require owner signoff for repairs exceeding €500"})
        assert res.status_code == 200
        data = res.json()
        assert "drafted a new proposed standing rule" in data["answer"]
        assert data["previewCard"] is not None
        assert data["previewCard"]["type"] == "memory_item"
        assert data["previewCard"]["badgeLabel"] == "POLICY PROPOSAL"
        assert data["previewCard"]["actionId"] == str(fake_memory.id)
        assert any(a["actionType"] == "approve_memory" for a in data["actions"])
        mock_record.assert_called_once()
        _, kwargs = mock_record.call_args
        assert kwargs.get("status") == MemoryStatus.proposed


def test_task_reminder_not_saved_as_standing_rule():
    """Verify Issue 1.9: user task reminders ('remember to call Vipin') are not treated as standing policies."""
    mock_engine = MagicMock()
    app = as_owner(create_app(SETTINGS, engine=mock_engine))

    mock_sess = create_mock_session()
    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.context.memory_items.record_owner_memory") as mock_record,
        patch("app.api.agent.routes.run_agent") as mock_run_agent,
        TestClient(app) as client,
    ):
        mock_run_agent.return_value.output = ConciergePlan(in_scope=False, steps=[], reply="I noted that down.")
        res = client.post(URL, json={"query": "Remember to call Vipin tomorrow morning"})
        assert res.status_code == 200
        mock_record.assert_not_called()


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
