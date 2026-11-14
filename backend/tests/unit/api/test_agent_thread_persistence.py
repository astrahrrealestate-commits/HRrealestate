from datetime import UTC, datetime
from uuid import uuid4

from app.api.agent.routes import (
    AssistantCardData,
    CardActionData,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationSummaryItem,
    TurnReplayItem,
    UpdateConversationRequest,
    _generate_thread_title,
)
from app.llm.agents.owner_qa import CaseBrief


def test_generate_thread_title_cases():
    # 1. Leak at Keizersgracht
    brief = CaseBrief(
        case_id="case-1", label="Keizersgracht 42-A", state="open", urgency="emergency", summary="Pipe leak"
    )
    title1 = _generate_thread_title("What is the status of the water leak?", "Kevin is working on it.", [brief])
    assert "Keizersgracht" in title1
    assert "Leak" in title1

    # 2. Rent arrears
    title2 = _generate_thread_title("Who is behind on rent this month?", "Pieter Bakker owes rent.", [])
    assert "Rent" in title2 or "Arrears" in title2

    # 3. Calendar visit
    title3 = _generate_thread_title("Schedule property inspection tomorrow", "I have proposed a visit.", [])
    assert "Visit" in title3 or "Schedule" in title3

    # 4. Fallback from clean words
    title4 = _generate_thread_title("Check all building fire extinguishers", "Checked.", [])
    assert "Building" in title4 or "Fire" in title4

    # 5. Open Keizersgracht case in context must NOT overwrite unrelated queries
    assert _generate_thread_title("which is giving us most profit", "Keizersgracht 42-C", [brief]) == (
        "Property Profitability"
    )
    assert _generate_thread_title("draft a reply for this ticket", "Prepared draft", [brief]) == "Draft Tenant Reply"
    assert _generate_thread_title("how many properties do we have", "47 properties", [brief]) == "Portfolio Properties"
    assert _generate_thread_title("what are we waiting on", "Not waiting", [brief]) == "Waiting-For Radar"


def test_conversation_summary_schemas():
    item = ConversationSummaryItem(
        id=str(uuid4()),
        title="Keizersgracht Leak",
        last_turn_at=datetime.now(UTC).isoformat(),
        snippet="Kevin van Dijk dispatched",
        pinned=True,
        time_bucket="Today",
    )
    res = ConversationListResponse(conversations=[item])
    assert len(res.conversations) == 1
    assert res.conversations[0].pinned is True
    assert res.conversations[0].time_bucket == "Today"


def test_turn_replay_schema():
    action = CardActionData(
        label="Open in WhatsApp", kind="open_external", targetUrl="https://wa.me/31612345678", variant="whatsapp"
    )
    card = AssistantCardData(
        id="card-1",
        type="draft_message",
        badgeLabel="DRAFT",
        badgeColor="orange",
        title="Draft · WhatsApp",
        channel="whatsapp",
        recipient="+31612345678",
        body="Hello from EstateOS",
        actions=[action],
    )
    turn = TurnReplayItem(
        id=str(uuid4()),
        sender="assistant",
        text="I prepared a draft reply.",
        timestamp="12:30",
        steps=["Checked tickets", "Drafted reply"],
        cards=[card],
        suggestedPrompts=["Send WhatsApp now", "Make reply firmer", "Open in Inbox"],
    )
    detail = ConversationDetailResponse(
        id=str(uuid4()),
        title="Pipe Leak",
        pinned=False,
        last_turn_at=datetime.now(UTC).isoformat(),
        focus_state={"case_id": "c-123", "contractor": "Kevin"},
        turns=[turn],
    )
    assert len(detail.turns) == 1
    assert detail.turns[0].cards[0].channel == "whatsapp"
    assert detail.focus_state["contractor"] == "Kevin"


def test_update_conversation_schema():
    req = UpdateConversationRequest(title="Renamed Thread", pinned=True, hidden=False)
    assert req.title == "Renamed Thread"
    assert req.pinned is True
    assert req.hidden is False
