"""Unit tests for `_build_drafts` and `_assemble_thread` mail formatting & draft/sent isolation."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.api.inbox import routes
from app.api.inbox.routes import _assemble_thread, _build_drafts, _PreparedCase
from app.api.inbox.thread_batch import ThreadDetailsBatch, ThreadMessagesBatch
from app.context.sender_label import SenderKind, SenderLabel
from app.contracts import ActionType, CaseState, Category, Channel, Direction, OutboundMode, Urgency
from app.core.settings import Settings
from app.db.enums import ActionStatus, ApprovalStatus, SendStatus

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit settings: the thread reads the owner's address, and a unit test must not need a developer's env."""
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", _env_file=None)  # type: ignore[call-arg]
    monkeypatch.setattr(routes, "get_settings", lambda: settings)


def _prep(company_id, case_id, messages, *, sender_email="tenant@example.test") -> _PreparedCase:
    case = SimpleNamespace(
        id=case_id,
        company_id=company_id,
        category=Category.maintenance,
        urgency=Urgency.normal,
        state=CaseState.open,
        brixx_ref=None,
        unit_id=None,
        primary_person_id=None,
        summary="Lekkage",
        last_read_at=None,
        snoozed_until=None,
    )
    inbound = [m for m in messages if m.direction != Direction.outbound]
    tenant_msg = inbound[-1] if inbound else messages[0]
    latest_msg = messages[-1]
    label = SenderLabel(
        kind=SenderKind.tenant,
        audience="tenants",
        recipient_role="tenant",
        role_detail="Tenant",
    )
    return _PreparedCase(
        case=case,
        messages=messages,
        tenant_msg=tenant_msg,
        latest_msg=latest_msg,
        sender_email=sender_email,
        sender_name="Sanne",
        person=None,
        sender_label=label,
        raw_unit_label="Singel 1",
        channel_str="gmail",
    )


def _msg(company_id, *, direction=Direction.inbound, minutes=0, subject="Lekkage", to=None, cc=None, text="Hallo"):
    return SimpleNamespace(
        id=uuid4(),
        company_id=company_id,
        channel=Channel.gmail,
        direction=direction,
        sent_at=NOW + timedelta(minutes=minutes),
        sender_identity="harjot@hr.nl" if direction == Direction.outbound else "tenant@example.test",
        provider_msg_id=f"gm-{uuid4().hex[:6]}",
        thread_ref="thr-1",
        text=text,
        meta={
            "subject": subject,
            "mailbox": "info@hr.nl",
            "to": to if to is not None else ["info@hr.nl"],
            "cc": cc if cc is not None else [],
        },
    )


def test_build_drafts_caps_variants_at_two() -> None:
    action = SimpleNamespace(
        persona_name="Harjot",
        persona_version=1,
        payload={"body_variants": ["Draft 1", "Draft 2", "Draft 3"], "commitments": []},
    )
    gmail, whatsapp, persona = _build_drafts(action, "Sanne")
    assert len(gmail) == 2
    assert len(whatsapp) == 2
    assert [d["text"] for d in gmail] == ["Draft 1", "Draft 2"]
    assert persona == {"actingAs": "Harjot", "name": "Harjot", "version": 1}


def test_draft_mode_sends_and_non_reply_sends_never_appear_as_sent_messages() -> None:
    cid, case_id = uuid4(), uuid4()
    m1 = _msg(cid, minutes=0)
    prep = _prep(cid, case_id, [m1])
    company = SimpleNamespace(outbound_mode=OutboundMode.draft)
    msg_batch = ThreadMessagesBatch(
        company=company,
        company_units=[],
        msgs_by_case={case_id: [m1]},
        people_by_id={},
        units_by_id={},
        lease_party_ids=set(),
        und_by_msg_id={},
        saved_names={m1.id: "Sanne"},
        sender_person_by_msg={},
        unit_by_person={},
    )
    reply_act = SimpleNamespace(
        id=uuid4(),
        type=ActionType.reply_draft,
        status=ActionStatus.pending_approval,
        payload={"body_variants": ["Optie 1", "Optie 2"], "commitments": []},
        context_ref=[m1.id],
        persona_name="Harjot",
        persona_version=1,
    )
    notify_act = SimpleNamespace(
        id=uuid4(),
        type=ActionType.notify_owner,
        status=ActionStatus.executed,
        payload={"text": "Note for owner"},
        context_ref=[m1.id],
        persona_name=None,
        persona_version=None,
    )
    approval = SimpleNamespace(id=uuid4(), status=ApprovalStatus.pending, choice=None)
    # Even if a Send row exists (e.g. from notify_owner or a Gmail draft creation in draft mode),
    # it must NOT appear in `messages` as a sent reply from Harjot.
    draft_send = SimpleNamespace(
        id=uuid4(),
        action_id=reply_act.id,
        channel=Channel.gmail,
        status=SendStatus.sent,
        attempted_at=NOW + timedelta(minutes=5),
        target="tenant@example.test",
    )
    owner_send = SimpleNamespace(
        id=uuid4(),
        action_id=notify_act.id,
        channel=Channel.dashboard,
        status=SendStatus.sent,
        attempted_at=NOW + timedelta(minutes=1),
        target="owner:1",
    )
    details = ThreadDetailsBatch(
        actions_by_case={case_id: [reply_act, notify_act]},
        approvals_by_action={reply_act.id: [approval]},
        sends_by_action={reply_act.id: [draft_send], notify_act.id: [owner_send]},
        attachments_by_msg={},
        docs_by_att={},
        leases_by_unit_key={},
    )
    thread = _assemble_thread(prep, msg_batch, details, company_tz=ZoneInfo("Europe/Amsterdam"), now_dt=NOW)
    assert thread["status"] == "needs_approval"
    assert len(thread["gmailDrafts"]) == 2
    assert len(thread["messages"]) == 1
    assert thread["messages"][0]["to"] == ["info@hr.nl"]
    assert thread["messages"][0]["subject"] == "Lekkage"


def test_multiturn_thread_with_prior_owner_reply_still_offers_new_pending_draft() -> None:
    cid, case_id = uuid4(), uuid4()
    m1 = _msg(cid, minutes=0, text="Eerste vraag")
    m2 = _msg(cid, direction=Direction.outbound, minutes=10, text="Eerder antwoord", to=["tenant@example.test"])
    m3 = _msg(cid, minutes=20, text="Nieuwe vraag van huurder", cc=["partner@example.test"])
    prep = _prep(cid, case_id, [m1, m2, m3])
    company = SimpleNamespace(outbound_mode=OutboundMode.draft)
    msg_batch = ThreadMessagesBatch(
        company=company,
        company_units=[],
        msgs_by_case={case_id: [m1, m2, m3]},
        people_by_id={},
        units_by_id={},
        lease_party_ids=set(),
        und_by_msg_id={},
        saved_names={m1.id: "Sanne", m3.id: "Sanne"},
        sender_person_by_msg={},
        unit_by_person={},
    )
    reply_act = SimpleNamespace(
        id=uuid4(),
        type=ActionType.reply_draft,
        status=ActionStatus.pending_approval,
        payload={"body_variants": ["Nieuwe concept 1", "Nieuwe concept 2"], "commitments": []},
        context_ref=[m3.id],
        persona_name="Harjot",
        persona_version=1,
    )
    approval = SimpleNamespace(id=uuid4(), status=ApprovalStatus.pending, choice=None)
    details = ThreadDetailsBatch(
        actions_by_case={case_id: [reply_act]},
        approvals_by_action={reply_act.id: [approval]},
        sends_by_action={},
        attachments_by_msg={},
        docs_by_att={},
        leases_by_unit_key={},
    )
    thread = _assemble_thread(prep, msg_batch, details, company_tz=ZoneInfo("Europe/Amsterdam"), now_dt=NOW)
    assert thread["status"] == "needs_approval"
    assert [d["text"] for d in thread["gmailDrafts"]] == ["Nieuwe concept 1", "Nieuwe concept 2"]
    assert thread["messages"][-1]["cc"] == ["partner@example.test"]
    assert thread["isRead"] is False
