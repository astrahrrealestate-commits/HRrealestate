"""Unit tests for Inbox thread state endpoints (/read, /done, /snooze) and validation."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.inbox.routes import (
    CreateGmailDraftRequest,
    ThreadReadRequest,
    ThreadReplyRequest,
    ThreadSnoozeRequest,
    create_gmail_draft,
    mark_thread_done,
    mark_thread_read,
    send_thread_reply,
    snooze_thread,
)
from app.api.v1.auth import Principal
from app.db.models.pipeline import CaseState

PRINCIPAL = Principal(company_id=uuid4(), owner_id=uuid4(), email="owner@example.test")


def _mock_session_with_case(case_obj: object | None) -> MagicMock:
    session = MagicMock()
    session.scalar.return_value = case_obj
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    session.begin.return_value.__enter__ = MagicMock(return_value=None)
    session.begin.return_value.__exit__ = MagicMock(return_value=False)
    return session


def test_mark_thread_read_and_unread() -> None:
    case_uuid = uuid4()
    case_obj = SimpleNamespace(id=case_uuid, company_id=PRINCIPAL.company_id, last_read_at=None)
    session = _mock_session_with_case(case_obj)

    with patch("app.api.inbox.routes.Session", return_value=session):
        res_read = mark_thread_read(
            f"case-{case_uuid}",
            engine=MagicMock(),
            principal=PRINCIPAL,
            req=ThreadReadRequest(read=True),
        )
        assert res_read == {"ok": True, "caseId": str(case_uuid), "isRead": True}
        assert case_obj.last_read_at is not None

        res_unread = mark_thread_read(
            str(case_uuid),
            engine=MagicMock(),
            principal=PRINCIPAL,
            req=ThreadReadRequest(read=False),
        )
        assert res_unread == {"ok": True, "caseId": str(case_uuid), "isRead": False}
        assert case_obj.last_read_at is None


def test_mark_thread_done_closes_case_and_records_event() -> None:
    case_uuid = uuid4()
    case_obj = SimpleNamespace(
        id=case_uuid,
        company_id=PRINCIPAL.company_id,
        state=CaseState.open,
        resolved_at=None,
        last_read_at=None,
        snoozed_until=datetime(2026, 12, 1, tzinfo=UTC),
    )
    session = _mock_session_with_case(case_obj)

    with patch("app.api.inbox.routes.Session", return_value=session):
        res = mark_thread_done(f"case-{case_uuid}", engine=MagicMock(), principal=PRINCIPAL)

    assert res == {"ok": True, "caseId": str(case_uuid), "status": "closed"}
    assert case_obj.state is CaseState.closed
    assert case_obj.resolved_at is not None
    assert case_obj.last_read_at is not None
    assert case_obj.snoozed_until is None
    assert session.add.called


def test_snooze_thread_persists_timestamp_and_rejects_bad_iso() -> None:
    case_uuid = uuid4()
    case_obj = SimpleNamespace(
        id=case_uuid,
        company_id=PRINCIPAL.company_id,
        snoozed_until=None,
        last_read_at=None,
    )
    session = _mock_session_with_case(case_obj)

    with patch("app.api.inbox.routes.Session", return_value=session):
        with pytest.raises(HTTPException) as bad_exc:
            snooze_thread(
                str(case_uuid),
                engine=MagicMock(),
                principal=PRINCIPAL,
                req=ThreadSnoozeRequest(until="not-a-date"),
            )
        assert bad_exc.value.status_code == 422

        res = snooze_thread(
            f"case-{case_uuid}",
            engine=MagicMock(),
            principal=PRINCIPAL,
            req=ThreadSnoozeRequest(until="2026-12-01T08:00:00+00:00"),
        )
        assert res["ok"] is True
        assert res["caseId"] == str(case_uuid)
        assert res["snoozedUntil"].startswith("2026-12-01T08:00:00")
        assert case_obj.snoozed_until == datetime(2026, 12, 1, 8, 0, tzinfo=UTC)
        assert case_obj.last_read_at is not None


def test_thread_state_returns_404_when_case_missing_and_400_on_bad_id() -> None:
    session = _mock_session_with_case(None)
    with patch("app.api.inbox.routes.Session", return_value=session):
        with pytest.raises(HTTPException) as bad_id:
            mark_thread_done("not-a-uuid", engine=MagicMock(), principal=PRINCIPAL)
        assert bad_id.value.status_code == 400

        for fn in (
            lambda: mark_thread_done(str(uuid4()), engine=MagicMock(), principal=PRINCIPAL),
            lambda: mark_thread_read(
                str(uuid4()), engine=MagicMock(), principal=PRINCIPAL, req=ThreadReadRequest(read=True)
            ),
            lambda: snooze_thread(str(uuid4()), engine=MagicMock(), principal=PRINCIPAL, req=ThreadSnoozeRequest()),
        ):
            with pytest.raises(HTTPException) as not_found:
                fn()
            assert not_found.value.status_code == 404


def test_create_gmail_draft_opens_thread_when_thread_id_present_and_compose_otherwise() -> None:
    session = _mock_session_with_case(None)
    session.scalars.return_value.first.return_value = None
    with patch("app.api.inbox.routes.Session", return_value=session):
        threaded = create_gmail_draft(
            CreateGmailDraftRequest(
                to_email="lawyer@example.nl",
                subject="Notice",
                body="Reply text",
                thread_id="19abc123",
            ),
            engine=MagicMock(),
            principal=PRINCIPAL,
        )
        assert threaded["ok"] is True
        assert threaded["threaded"] is True
        assert threaded["web_url"] == "https://mail.google.com/mail/#all/19abc123"

        fresh = create_gmail_draft(
            CreateGmailDraftRequest(
                to_email="lawyer@example.nl",
                subject="New inquiry",
                body="Hello",
            ),
            engine=MagicMock(),
            principal=PRINCIPAL,
        )
        assert fresh["ok"] is True
        assert fresh["threaded"] is False
        assert fresh["web_url"].startswith("https://mail.google.com/mail/?view=cm")


def test_send_thread_reply_creates_approved_action_and_enqueues_sender() -> None:
    case_uuid = uuid4()
    msg_uuid = uuid4()
    case_obj = SimpleNamespace(
        id=case_uuid,
        company_id=PRINCIPAL.company_id,
        state=CaseState.open,
        summary="Open inquiry",
        summary_version=1,
    )
    msg_obj = SimpleNamespace(id=msg_uuid, channel="gmail")
    session = _mock_session_with_case(None)
    session.scalar.side_effect = [case_obj, msg_obj]
    session.get.return_value = SimpleNamespace(id=PRINCIPAL.company_id, paused=False)
    added_rows: list[object] = []

    def _add(obj: object) -> None:
        if getattr(obj, "id", None) is None and hasattr(obj, "payload"):
            obj.id = uuid4()  # type: ignore[attr-defined]
        added_rows.append(obj)

    session.add.side_effect = _add
    wf_client = MagicMock()

    with (
        patch("app.api.inbox.routes.Session", return_value=session),
        patch("app.api.inbox.routes.enqueue.enqueue_execute") as mock_enqueue,
    ):
        res = send_thread_reply(
            f"case-{case_uuid}",
            ThreadReplyRequest(body="  Thank you, we will inspect this week.  ", channel="gmail"),
            engine=MagicMock(),
            client=wf_client,
            principal=PRINCIPAL,
        )

    assert res["status"] == "approved"
    assert res["decision"] == "execute"
    mock_enqueue.assert_called_once()
    assert len(added_rows) >= 3


def test_ensure_emergency_reply_adds_draft_when_model_only_escalates() -> None:
    from app.contracts import (
        Action,
        ActionType,
        Category,
        Channel,
        Entities,
        EscalatePayload,
        Suspicious,
        Understanding,
        Urgency,
    )
    from app.llm.agents.proposer import ProposerContext
    from app.pipeline.propose import FALLBACK_RATIONALE, Loaded, _ensure_emergency_reply

    cid = uuid4()
    und = Understanding(
        category=Category.maintenance,
        intent="Burst pipe",
        urgency=Urgency.emergency,
        requires_reply=True,
        entities=Entities.none(),
        suspicious=Suspicious(flag=False, reason=None),
        confidence=0.95,
        sender_role=None,
        prompt_version="understanding/v3",
    )
    loaded = Loaded(
        ctx=ProposerContext(
            case_id=cid,
            channel=Channel.gmail,
            subject="Water leak",
            message_text="Water pouring from ceiling",
            understanding=und,
            case_state="open",
            case_summary="Emergency leak",
            waiting=(),
            contractors=(),
            mode="reply",
        ),
        company_id=PRINCIPAL.company_id,
        paused=False,
    )
    esc = Action(
        type=ActionType.escalate,
        case_id=cid,
        payload=EscalatePayload(kind="escalate", reason="Emergency leak"),
        rationale="Urgent",
        context_ref=[],
        draft_version=1,
    )

    out = _ensure_emergency_reply([esc], loaded)
    assert out[0].type is ActionType.reply_draft
    assert out[0].payload.channel is Channel.gmail  # type: ignore[union-attr]
    assert out[1].type is ActionType.escalate

    # Skipped if fallback, suspicious, or no reply required
    no_reply_loaded = Loaded(
        ctx=ProposerContext(
            case_id=cid,
            channel=Channel.gmail,
            subject="Water leak",
            message_text="FYI",
            understanding=und.model_copy(update={"requires_reply": False}),
            case_state="open",
            case_summary="FYI",
            waiting=(),
            contractors=(),
            mode="reply",
        ),
        company_id=PRINCIPAL.company_id,
        paused=False,
    )
    assert _ensure_emergency_reply([esc], no_reply_loaded) == [esc]
    fallback_act = esc.model_copy(update={"rationale": FALLBACK_RATIONALE})
    assert _ensure_emergency_reply([fallback_act], loaded) == [fallback_act]


def test_get_inbox_threads_passes_sort_priority_param() -> None:
    from app.api.inbox.routes import get_inbox_threads

    session = _mock_session_with_case(None)
    session.query.return_value.filter.return_value.scalar.return_value = 0
    with (
        patch("app.api.inbox.routes.Session", return_value=session),
        patch("app.api.inbox.routes._build_live_threads", return_value=[]) as mock_build,
    ):
        get_inbox_threads(engine=MagicMock(), sort="priority", limit=100, principal=PRINCIPAL)
    mock_build.assert_called_once()
    assert mock_build.call_args.kwargs["sort"] == "priority"
    assert mock_build.call_args.kwargs["limit"] == 100
