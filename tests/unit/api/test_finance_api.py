"""Finance API without a database: auth, CSRF, rate validation, recheck enqueue by name, response cleaning."""

import ast
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.v1.auth import COOKIE, CSRF_HEADER, CSRF_VALUE, Principal, issue_session
from app.api.v1.finance_schemas import RateIn, clean_report, detail_out
from app.core.settings import Settings
from app.main import create_app

SETTINGS = Settings(
    database_url="postgresql+psycopg://u:p@localhost:1/db",  # type: ignore[arg-type]
    env="test",
    dashboard_session_secret=SecretStr("x" * 32),
    _env_file=None,
)
PRINCIPAL = Principal(company_id=uuid4(), owner_id=uuid4(), email="h@example.test")
H = {CSRF_HEADER: CSRF_VALUE}
NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
RATE = {"person_id": str(uuid4()), "description": "Cv ketel onderhoud", "unit": "uur", "amount": "85.00"}


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], tuple[Any, ...]]] = []

    def enqueue(self, options: Any, *args: Any) -> Any:
        self.calls.append((options, args))

    def enqueue_in_transaction(self, conn_or_session: Any, options: Any, *args: Any) -> Any:
        raise AssertionError("not used")


@pytest.fixture
def wf() -> FakeClient:
    return FakeClient()


@pytest.fixture
def client(wf: FakeClient) -> Iterator[TestClient]:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=wf)
    with (
        patch("app.api.v1.finance.Session", MagicMock()),
        patch("app.api.v1.finance_rates.Session", MagicMock()),
        TestClient(app) as c,
    ):
        c.cookies.set(COOKIE, issue_session(SETTINGS, PRINCIPAL, datetime.now(UTC)))
        yield c


def _quote(person_id: Any) -> SimpleNamespace:
    quote = SimpleNamespace(
        id=uuid4(), person_id=person_id, case_id=None, quote_date=date(2026, 10, 30), work_date=None, currency="EUR",
        total=Decimal("131.00"), status="received", created_at=NOW,
    )  # fmt: skip
    return SimpleNamespace(quote=quote, vendor_name="Vendor BV", lines=[], latest=None, history=[])


def test_quotes_list_requires_session(client: TestClient) -> None:
    client.cookies.clear()
    assert client.get("/api/v1/finance/quotes").status_code == 401
    assert client.get(f"/api/v1/finance/quotes/{uuid4()}").status_code == 401
    assert client.get("/api/v1/finance/rates").status_code == 401


def test_finance_writes_require_csrf_and_session(client: TestClient) -> None:
    assert client.post(f"/api/v1/finance/quotes/{uuid4()}/recheck").status_code == 403
    assert client.put("/api/v1/finance/rates", json=RATE).status_code == 403
    assert client.delete(f"/api/v1/finance/rates/{uuid4()}").status_code == 403
    client.cookies.clear()
    assert client.post(f"/api/v1/finance/quotes/{uuid4()}/recheck", headers=H).status_code == 401
    assert client.put("/api/v1/finance/rates", json=RATE, headers=H).status_code == 401
    assert client.delete(f"/api/v1/finance/rates/{uuid4()}", headers=H).status_code == 401


@pytest.mark.parametrize(
    "change",
    [
        {"amount": "-5.00"},
        {"amount": "0"},
        {"amount": "85.123"},
        {"currency": "USD"},
        {"unit": ""},
        {"description": "  "},
        {"valid_from": "2026-11-02", "valid_to": "2026-11-01"},
    ],
)
def test_rate_put_rejects_negative_and_non_eur_and_bad_input(client: TestClient, change: dict[str, str]) -> None:
    with patch("app.api.v1.finance_rates.repo.is_contractor", return_value=True):
        assert client.put("/api/v1/finance/rates", json={**RATE, **change}, headers=H).status_code == 422


def test_rate_put_rejects_a_foreign_person(client: TestClient) -> None:
    with patch("app.api.v1.finance_rates.repo.is_contractor", return_value=False) as check:
        resp = client.put("/api/v1/finance/rates", json=RATE, headers=H)
    assert resp.status_code == 404
    assert check.call_args.args[1] == PRINCIPAL.company_id  # the session's company, never one from the body


def test_rate_item_key_is_given_when_valid_else_derived() -> None:
    base = {**RATE, "person_id": uuid4()}
    assert RateIn(**base, item_key="boiler_service").resolved_item_key() == "boiler_service"
    assert RateIn(**base, item_key="Not A Key!").resolved_item_key() == "boiler_service"  # from the description
    assert RateIn(**base).resolved_item_key() == "boiler_service"


def test_recheck_unlinked_quote_is_409_and_enqueues_nothing(client: TestClient, wf: FakeClient) -> None:
    with patch("app.api.v1.finance.repo_read.get_quote", return_value=_quote(None)):
        resp = client.post(f"/api/v1/finance/quotes/{uuid4()}/recheck", headers=H)
    assert resp.status_code == 409
    assert wf.calls == []


def test_recheck_enqueues_by_name_with_a_deterministic_id(client: TestClient, wf: FakeClient) -> None:
    found = _quote(uuid4())
    with (
        patch("app.api.v1.finance.repo_read.get_quote", return_value=found),
        patch("app.api.v1.finance.repo_read.review_count", return_value=2),
    ):
        resp = client.post(f"/api/v1/finance/quotes/{found.quote.id}/recheck", headers=H)
    assert resp.status_code == 202
    assert resp.json() == {"quote_id": str(found.quote.id), "n": 2}
    options, args = wf.calls[0]
    assert options == {
        "queue_name": "finance",
        "workflow_name": "finance.recheck",
        "workflow_id": f"fin:recheck:{found.quote.id}:2",
    }
    assert args == (str(found.quote.id), str(PRINCIPAL.company_id), 2)


def test_unknown_quote_is_404(client: TestClient) -> None:
    with patch("app.api.v1.finance.repo_read.get_quote", return_value=None):
        assert client.get(f"/api/v1/finance/quotes/{uuid4()}").status_code == 404
        assert client.post(f"/api/v1/finance/quotes/{uuid4()}/recheck", headers=H).status_code == 404


def test_bad_cursor_and_limit_are_422(client: TestClient) -> None:
    assert client.get("/api/v1/finance/quotes", params={"cursor": "nope"}).status_code == 422
    assert client.get("/api/v1/finance/quotes", params={"limit": 101}).status_code == 422


def test_response_drops_sources_without_a_source_name() -> None:
    report = {
        "lines": [
            {
                "market": {
                    "sources": [
                        {"name": "Bouwmaat", "url": "https://a.test/x"},
                        {"url": "https://nameless.test/y"},
                        {"name": "  ", "url": "https://blank.test/z"},
                        "https://bare.test",
                    ]
                },
                "description": "kept as is",
            }
        ],
        "sources": [{"price": "1.00"}],
    }
    cleaned = clean_report(report)
    assert cleaned["lines"][0]["market"]["sources"] == [{"name": "Bouwmaat", "url": "https://a.test/x"}]
    assert cleaned["sources"] == []
    assert cleaned["lines"][0]["description"] == "kept as is"
    assert report["sources"] == [{"price": "1.00"}]  # the input is not mutated


def test_detail_serves_the_stored_report_cleaned() -> None:
    review = SimpleNamespace(
        id=uuid4(), verdict="ok", late_days=0, overcharge=Decimal(0), snapshot_basis="decision_day",
        report={"late_flag": True, "low_confidence": False, "market": {"sources": [{"url": "x"}]}},
    )  # fmt: skip
    found = _quote(uuid4())
    found.latest = review
    found.history = [(review.id, "ok", NOW)]
    out = detail_out(found)  # type: ignore[arg-type]
    assert out.report == {"late_flag": True, "low_confidence": False, "market": {"sources": []}}
    assert out.latest is not None
    assert (out.latest.late_flag, out.latest.low_confidence) == (True, False)
    assert [h.id for h in out.history] == [review.id]


def test_finance_api_modules_do_not_import_workflows_or_the_sender() -> None:
    for name in ("finance.py", "finance_rates.py", "finance_schemas.py", "enqueue.py"):
        tree = ast.parse((Path("app/api/v1") / name).read_text())
        mods = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        mods += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not [m for m in mods if m.startswith(("app.workflows", "app.sender"))], name
