"""What a Dashboard or Reports profile gets from the inbox and the ticket list: the headline, not what was said."""

import pytest

from app.api.inbox.summary import headline_only, safe_name
from app.api.maintenance.routes import MaintenanceTicketItem, _without_contact_and_messages


def _thread() -> dict[str, object]:
    return {
        "id": "case-1",
        "title": "Leak in 4B",
        "aiSummary": "Water from the ceiling",
        "unit": "4B",
        "status": "needs_approval",
        "lastMessageSnippet": "hi, it is Anouk, my phone is 0611111111",
        "sourceIdentifier": "Gmail · anouk@mail.test",
        "sender": {"name": "Anouk", "contact": "anouk@mail.test", "role": "Tenant", "unit": "4B"},
        "aiUnderstanding": {"problem": "leak", "customFacts": [{"label": "Phone", "value": "0611111111"}]},
        "gmailDrafts": [{"body": "Dear Anouk"}],
        "whatsappDrafts": [{"body": "Hoi Anouk"}],
        "attachments": [{"name": "photo.jpg"}],
        "messages": [{"body": "hi, it is Anouk"}],
        "externalThreadId": "+31611111111",
        "externalMessageId": "wamid.ABC",
        "gmailThreadSecret": "a field nobody listed",
    }


def test_the_headline_stays_and_what_was_said_goes() -> None:
    out = headline_only(_thread())
    assert (out["id"], out["title"], out["aiSummary"], out["unit"], out["status"]) == (
        "case-1",
        "Leak in 4B",
        "Water from the ceiling",
        "4B",
        "needs_approval",
    )
    assert (out["lastMessageSnippet"], out["sourceIdentifier"]) == ("", "")
    assert out["sender"] == {"name": "Anouk", "contact": "", "role": "Tenant", "unit": "4B"}
    assert out["aiUnderstanding"] == {"problem": "leak"}
    assert [out[k] for k in ("gmailDrafts", "whatsappDrafts", "attachments", "messages")] == [[], [], [], []]


def test_fields_nobody_listed_and_provider_ids_never_get_through() -> None:
    out = headline_only(_thread())
    assert "gmailThreadSecret" not in out
    assert (out["externalThreadId"], out["externalMessageId"]) == ("", "")


@pytest.mark.parametrize("name", ["+31611111111", "anouk@mail.test", "0611 111 111", ""])
def test_a_sender_named_after_their_number_or_email_shows_as_unknown(name: str) -> None:
    thread = _thread() | {"sender": {"name": name, "contact": name, "role": "Tenant", "unit": "4B"}}
    assert headline_only(thread)["sender"]["name"] == "Unknown contact"


def test_a_real_name_stays() -> None:
    assert safe_name("Anouk de Vries") == "Anouk de Vries"


def test_the_original_thread_is_not_changed() -> None:
    thread = _thread()
    headline_only(thread)
    assert thread["messages"] == [{"body": "hi, it is Anouk"}]


def test_a_ticket_keeps_its_status_and_budget_but_loses_phones_notes_and_drafts() -> None:
    ticket = MaintenanceTicketItem(
        id="t1", ticketNumber="#005", issueTitle="Leak", unitLabel="4B", tenantName="Anouk", tenantPhone="0611111111",
        category="plumbing", contractorName="Bakker", contractorTrade="plumber", contractorPhone="0622222222",
        contractorEmail="bakker@x.test", urgency="high", status="pending_approval", slaRemaining="2h",
        poBudgetCap="500", reportedAt="2026-11-01", notes="gate code 1234", originalMessage="help",
        tenantDraft="we are on it", contractorDraft="please come",
    )  # fmt: skip
    out = _without_contact_and_messages(ticket)
    assert out.tenantName == "Anouk"
    kept = (out.ticketNumber, out.status, out.poBudgetCap, out.contractorName)
    assert kept == ("#005", "pending_approval", "500", "Bakker")
    assert (out.tenantPhone, out.contractorPhone, out.contractorEmail, out.notes) == ("", None, None, "")
    assert (out.originalMessage, out.tenantDraft, out.contractorDraft) == (None, None, None)
