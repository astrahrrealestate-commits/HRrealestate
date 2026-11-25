"""Unit tests for Inbox thread state endpoints (/read, /done, /snooze) and validation."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.inbox.routes import (
    ThreadReadRequest,
    ThreadSnoozeRequest,
    mark_thread_done,
    mark_thread_read,
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
