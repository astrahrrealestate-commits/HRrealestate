"""Unit tests for the distiller DBOS workflow (Task C11)."""

import inspect
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.workflows import distiller

NOW = datetime(2026, 10, 23, 2, 0, tzinfo=UTC)
COMPANIES_STEP = inspect.unwrap(distiller.companies_step)
DISTILL_STEP = inspect.unwrap(distiller.distill_company_step)
CRON_WORKFLOW = inspect.unwrap(distiller.distiller_cron)


def test_companies_step() -> None:
    c1, c2 = uuid4(), uuid4()
    mock_session = MagicMock()
    mock_session.scalars.return_value.all.return_value = [c1, c2]

    with (
        patch("app.workflows.distiller.get_engine"),
        patch("app.workflows.distiller.Session") as mock_session_cls,
    ):
        mock_session_cls.return_value.__enter__.return_value = mock_session
        result = COMPANIES_STEP()

    assert result == [str(c1), str(c2)]


def test_distill_company_step() -> None:
    company_id = uuid4()
    mock_session = MagicMock()

    with (
        patch("app.workflows.distiller.get_engine"),
        patch("app.workflows.distiller.Session") as mock_session_cls,
        patch("app.workflows.distiller.distill_company", return_value=(2, 1)) as mock_distill,
    ):
        mock_session_cls.return_value.__enter__.return_value = mock_session
        result = DISTILL_STEP(str(company_id), NOW.isoformat())

    assert result == {"proposed": 2, "retired": 1}
    mock_distill.assert_called_once()


def test_distiller_cron() -> None:
    with (
        patch("app.workflows.distiller.companies_step", return_value=["c1", "c2"]),
        patch("app.workflows.distiller.distill_company_step") as mock_step,
    ):
        CRON_WORKFLOW(NOW, None)

    assert mock_step.call_count == 2
