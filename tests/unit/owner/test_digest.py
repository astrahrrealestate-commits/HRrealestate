"""Unit tests for the morning digest email renderer and rules."""

from uuid import uuid4

from app.contracts import Urgency
from app.owner.digest import DigestCaseReply, DigestData, render_digest_email


def test_empty_digest_has_no_items() -> None:
    data = DigestData(
        company_id=uuid4(),
        company_name="Test Immo",
        date_label="Friday, 09 October 2026",
        kind="daily",
        ignored_count=5,
    )
    assert not data.has_items


def test_digest_with_replies_renders_clean_text_and_html() -> None:
    reply = DigestCaseReply(
        case_id=uuid4(),
        approval_id=uuid4(),
        action_id=uuid4(),
        who="Sanne de Vries",
        category="maintenance",
        urgency=Urgency.emergency,
        situation="Water leak in bathroom ceiling",
        drafts=("Beste Sanne, we sturen direct een loodgieter.", "Beste Sanne, kunt u de hoofdkraan dichtdraaien?"),
        thread_id="thread-abc-123",
    )
    data = DigestData(
        company_id=uuid4(),
        company_name="Test Immo",
        date_label="Friday, 09 October 2026",
        kind="daily",
        replies=(reply,),
        decisions=("request contractor: Roof repair",),
        tasks_due=("Follow up on meter reading",),
        waiting_on_others=("Inspection report (1 reminders sent)",),
        exceptions=("Suspicious IBAN change detected",),
        ignored_count=12,
    )
    assert data.has_items

    subject, text_body, html_body = render_digest_email(data)

    assert "Daily Briefing" in subject
    assert "09 October 2026" in subject

    # Text body checks
    assert "Needs your reply" in text_body
    assert "[EMERGENCY] Sanne de Vries · maintenance" in text_body
    assert "https://mail.google.com/mail/u/0/#inbox/thread-abc-123" in text_body
    assert "Draft 1:\n    Beste Sanne, we sturen direct een loodgieter." in text_body
    assert "Decisions waiting" in text_body
    assert "Roof repair" in text_body
    assert "Tasks due" in text_body
    assert "Waiting on others" in text_body
    assert "Exceptions" in text_body
    assert "12 message(s) ignored (newsletters, receipts, spam)." in text_body

    # HTML body checks
    assert "<html>" in html_body
    assert "badge-emergency" in html_body
    assert "Sanne de Vries" in html_body
    assert "Open thread in Gmail →" in html_body
    assert "12 message(s) ignored" in html_body
