"""Finance API against real Postgres: quote list/detail scoping, the stored report, recheck enqueue and 409, owner rate
cards (normalised, upsert, delete vs close), and the quote_review card in the feed."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, CSRF_HEADER, CSRF_VALUE, Principal, issue_session
from app.channels.dashboard import feed
from app.contracts.finance import PriceBasis, SnapshotBasis, Verdict
from app.core.settings import Settings
from app.db.enums import FeedKind, PersonKind, QuoteSource
from app.db.models import Company, OwnerAccount, PriceSnapshot, VendorRate
from app.finance import repo
from app.finance.repo import NewQuoteLine
from app.finance.stats import MarketStats
from app.main import create_app
from tests.integration.conftest import purge_company
from tests.integration.finance_support import DECIDED, Seeded, action, message, person, rate, seed_case

pytestmark = pytest.mark.integration
CSRF = {CSRF_HEADER: CSRF_VALUE}
STATS = MarketStats(low=Decimal(90), avg=Decimal(100), high=Decimal(110), n=3, trimmed=False, low_confidence=False)
REPORT: dict[str, Any] = {
    "verdict": "above_agreed", "late_flag": True, "low_confidence": False, "overcharge_total": "31.00",
    "lines": [{"description": "Cv ketel", "market": {"sources": [{"name": "Bouwmaat"}, {"url": "https://x.test"}]}}],
}  # fmt: skip


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], tuple[Any, ...]]] = []

    def enqueue(self, options: Any, *args: Any) -> Any:
        self.calls.append((options, args))

    def enqueue_in_transaction(self, conn_or_session: Any, options: Any, *args: Any) -> Any:
        raise AssertionError("not used")


@dataclass
class Fx:
    client: TestClient
    wf: FakeClient
    engine: Engine
    company_id: UUID
    mine: UUID  # a linked quote with two reviews
    unlinked: UUID  # a quote without a contractor
    theirs: UUID  # another company's quote
    vendor: UUID
    their_vendor: UUID
    their_rate: UUID
    case_id: UUID


def _quote(s: Session, seeded: Seeded, *, vendor: UUID | None, with_reviews: int, msg: UUID | None = None) -> UUID:
    source_id = msg or message(s, seeded.company_id, seeded.case_id, "Offerte")
    qid = repo.insert_quote(
        s, seeded.company_id, source=QuoteSource.message, source_id=source_id, quote_date=date(2026, 10, 30),
        currency="EUR", case_id=seeded.case_id, person_id=vendor, total=Decimal("131.00"),
    )  # fmt: skip
    assert qid is not None
    repo.insert_quote_lines(
        s, seeded.company_id, quote_id=qid,
        lines=[NewQuoteLine(1, "Cv ketel onderhoud", "boiler_service", Decimal("1.000"), "Uur", Decimal("131.00"))],
    )  # fmt: skip
    for i in range(with_reviews):
        report = {**REPORT, "review_id": str(i)}
        repo.insert_review(
            s, seeded.company_id, quote_id=qid, snapshot_basis=SnapshotBasis.decision_day, verdict=Verdict.above_agreed,
            overcharge=Decimal("31.00"), late_days=3, report=report,
        )  # fmt: skip
        s.flush()
    return qid


@pytest.fixture
def fx(migrated_engine: Engine, pg_url: str, committed_company: Company) -> Iterator[Fx]:
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other BV")
        s.add(other)
        s.flush()
        owner = OwnerAccount(company_id=committed_company.id, display_name="H", whatsapp_e164="+31699999993",
                             email="h@a.test")  # fmt: skip
        s.add(owner)
        mine_seed = seed_case(s, committed_company.id)
        their_seed = seed_case(s, other.id)
        mine = _quote(s, mine_seed, vendor=mine_seed.vendor_id, with_reviews=2)
        unlinked = _quote(s, mine_seed, vendor=None, with_reviews=0)
        theirs = _quote(s, their_seed, vendor=their_seed.vendor_id, with_reviews=1)
        their_rate = rate(s, other.id, their_seed.vendor_id, "boiler_service", "70.00").id
        s.commit()
    settings = Settings(database_url=pg_url, env="test", dashboard_session_secret=SecretStr("x" * 32),  # type: ignore[arg-type]
                        _env_file=None)  # fmt: skip
    principal = Principal(company_id=committed_company.id, owner_id=owner.id, email="h@a.test")
    wf = FakeClient()
    with TestClient(create_app(settings, engine=migrated_engine, workflow_client=wf)) as c:
        c.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
        yield Fx(c, wf, migrated_engine, committed_company.id, mine, unlinked, theirs, mine_seed.vendor_id,
                 their_seed.vendor_id, their_rate, mine_seed.case_id)  # fmt: skip
    purge_company(migrated_engine, other.id)


def test_list_is_scoped_newest_first_and_carries_the_latest_review(fx: Fx) -> None:
    body = fx.client.get("/api/v1/finance/quotes").json()
    assert {q["id"] for q in body} == {str(fx.mine), str(fx.unlinked)}
    assert [q["id"] for q in body] == [str(fx.unlinked), str(fx.mine)]
    mine = next(q for q in body if q["id"] == str(fx.mine))
    assert mine["vendor"]["id"] == str(fx.vendor)
    assert mine["vendor"]["name"] == "Vendor BV"
    assert mine["latest"]["verdict"] == "above_agreed"
    assert (mine["latest"]["late_days"], mine["latest"]["late_flag"]) == (3, True)
    assert mine["latest"]["overcharge_total"] == "31.00"
    assert mine["latest"]["snapshot_basis"] == "decision_day"
    assert next(q for q in body if q["id"] == str(fx.unlinked))["latest"] is None


def test_list_filters_and_cursor_paging(fx: Fx) -> None:
    by_person = fx.client.get("/api/v1/finance/quotes", params={"person_id": str(fx.vendor)}).json()
    assert [q["id"] for q in by_person] == [str(fx.mine)]
    assert fx.client.get("/api/v1/finance/quotes", params={"person_id": str(fx.their_vendor)}).json() == []
    by_case = fx.client.get("/api/v1/finance/quotes", params={"case_id": str(fx.case_id)}).json()
    assert len(by_case) == 2
    first = fx.client.get("/api/v1/finance/quotes", params={"limit": 1}).json()
    second = fx.client.get("/api/v1/finance/quotes", params={"limit": 1, "cursor": first[0]["cursor"]}).json()
    assert [first[0]["id"], second[0]["id"]] == [str(fx.unlinked), str(fx.mine)]
    assert fx.client.get("/api/v1/finance/quotes", params={"limit": 1, "cursor": second[0]["cursor"]}).json() == []


def test_detail_returns_lines_the_stored_report_and_history(fx: Fx) -> None:
    body = fx.client.get(f"/api/v1/finance/quotes/{fx.mine}").json()
    assert [(x["description"], x["quantity"], x["unit"]) for x in body["lines"]] == [
        ("Cv ketel onderhoud", "1", "hour")
    ]
    assert body["report"]["verdict"] == "above_agreed"
    assert body["report"]["lines"][0]["market"]["sources"] == [{"name": "Bouwmaat"}]  # the nameless one is dropped
    assert len(body["history"]) == 2
    assert body["history"][0]["verdict"] == "above_agreed"
    assert body["latest"]["review_id"] == body["history"][0]["id"]
    assert fx.client.get(f"/api/v1/finance/quotes/{fx.unlinked}").json()["report"] is None


def test_other_companys_and_unknown_quotes_are_404(fx: Fx) -> None:
    assert fx.client.get(f"/api/v1/finance/quotes/{fx.theirs}").status_code == 404
    assert fx.client.get(f"/api/v1/finance/quotes/{uuid4()}").status_code == 404
    assert fx.client.post(f"/api/v1/finance/quotes/{fx.theirs}/recheck", headers=CSRF).status_code == 404
    assert fx.wf.calls == []


def test_recheck_enqueues_once_for_repeated_clicks_and_409_for_unlinked(fx: Fx) -> None:
    url = f"/api/v1/finance/quotes/{fx.mine}/recheck"
    assert fx.client.post(url).status_code == 403
    first = fx.client.post(url, headers=CSRF)
    second = fx.client.post(url, headers=CSRF)
    assert (first.status_code, second.status_code) == (202, 202)
    assert first.json() == second.json() == {"quote_id": str(fx.mine), "n": 2}
    ids = {options["workflow_id"] for options, _ in fx.wf.calls}
    assert ids == {f"fin:recheck:{fx.mine}:2"}  # same id: DBOS runs it once
    options, args = fx.wf.calls[0]
    assert (options["queue_name"], options["workflow_name"]) == ("finance", "finance.recheck")
    assert args == (str(fx.mine), str(fx.company_id), 2)
    unlinked = fx.client.post(f"/api/v1/finance/quotes/{fx.unlinked}/recheck", headers=CSRF)
    assert unlinked.status_code == 409
    assert len(fx.wf.calls) == 2


def _put(fx: Fx, **change: Any) -> Any:
    body = {"person_id": str(fx.vendor), "description": "Cv ketel onderhoud", "unit": "uur", "amount": "85.00"}
    return fx.client.put("/api/v1/finance/rates", json={**body, **change}, headers=CSRF)


def test_rate_put_then_get_round_trip_with_normalised_unit_and_item_key(fx: Fx) -> None:
    put = _put(fx)
    assert put.status_code == 200
    today = datetime.now(UTC).astimezone(ZoneInfo("Europe/Amsterdam")).date().isoformat()
    row = put.json()
    assert (row["item_key"], row["unit"], row["amount"], row["currency"]) == ("boiler_service", "hour", "85.00", "EUR")
    assert (row["valid_from"], row["valid_to"], row["source"]) == (today, None, "owner")
    listed = fx.client.get("/api/v1/finance/rates", params={"person_id": str(fx.vendor)}).json()
    assert [r["id"] for r in listed] == [row["id"]]
    assert fx.client.get("/api/v1/finance/rates").json()[0]["id"] == row["id"]
    given = _put(fx, item_key="Custom_Key", description="Zomaar iets", valid_from="2026-01-01").json()
    assert given["item_key"] == "zomaar_iets"  # an invalid given key is derived from the description
    kept = _put(fx, item_key="plumbing_hourly", description="Zomaar iets", valid_from="2026-01-02").json()
    assert kept["item_key"] == "plumbing_hourly"


def test_rate_put_twice_updates_one_row(fx: Fx) -> None:
    first = _put(fx, valid_from="2026-02-01").json()
    second = _put(fx, valid_from="2026-02-01", amount="90.50").json()
    assert second["id"] == first["id"]
    with Session(fx.engine) as s:
        rows = s.scalars(select(VendorRate).where(VendorRate.person_id == fx.vendor)).all()
    assert [(r.id, r.amount) for r in rows] == [(UUID(first["id"]), Decimal("90.50"))]


def test_rate_put_rejects_bad_input_and_people_who_are_not_our_contractors(fx: Fx) -> None:
    assert _put(fx, amount="-1.00").status_code == 422
    assert _put(fx, currency="USD").status_code == 422
    assert _put(fx, valid_from="2026-03-02", valid_to="2026-03-01").status_code == 422
    assert _put(fx, person_id=str(fx.their_vendor)).status_code == 404
    assert _put(fx, person_id=str(uuid4())).status_code == 404
    with Session(fx.engine) as s, s.begin():
        tenant = person(s, fx.company_id, "Anna", PersonKind.tenant)
    assert _put(fx, person_id=str(tenant)).status_code == 404  # only contractors have agreed rates
    with Session(fx.engine) as s:
        assert s.scalar(select(func.count(VendorRate.id)).where(VendorRate.company_id == fx.company_id)) == 0


def test_delete_unreferenced_rate_removes_it(fx: Fx) -> None:
    rate_id = _put(fx).json()["id"]
    assert fx.client.delete(f"/api/v1/finance/rates/{rate_id}").status_code == 403
    done = fx.client.delete(f"/api/v1/finance/rates/{rate_id}", headers=CSRF)
    assert (done.status_code, done.json()) == (200, {"id": rate_id, "action": "deleted", "valid_to": None})
    assert fx.client.get("/api/v1/finance/rates").json() == []
    assert fx.client.delete(f"/api/v1/finance/rates/{rate_id}", headers=CSRF).status_code == 404


def test_delete_snapshot_referenced_rate_closes_it_and_keeps_the_snapshot(fx: Fx) -> None:
    with Session(fx.engine) as s, s.begin():
        seeded_action = action(s, fx.company_id, fx.case_id, fx.vendor)
        card = rate(s, fx.company_id, fx.vendor, "boiler_service", "85.00")
        assert repo.insert_snapshot(
            s, fx.company_id, action_id=seeded_action, item_key="boiler_service", unit="hour", as_of=DECIDED,
            stats=STATS, basis=PriceBasis.fake, sources=[{"name": "fake"}], rate_card=card,
        )  # fmt: skip
        card_id = card.id
    done = fx.client.delete(f"/api/v1/finance/rates/{card_id}", headers=CSRF)
    today = datetime.now(UTC).astimezone(ZoneInfo("Europe/Amsterdam")).date()
    assert done.status_code == 200
    assert done.json()["action"] == "closed"
    assert done.json()["valid_to"] == today.isoformat()
    again = fx.client.delete(f"/api/v1/finance/rates/{card_id}", headers=CSRF)
    assert (again.status_code, again.json()["action"], again.json()["valid_to"]) == (200, "closed", today.isoformat())
    with Session(fx.engine) as s:
        snap = s.scalars(select(PriceSnapshot).where(PriceSnapshot.company_id == fx.company_id)).one()
        kept = s.get(VendorRate, card_id)
    assert snap.rate_card_id == card_id
    assert kept is not None
    assert kept.valid_to == today
    assert today - kept.valid_from >= timedelta(0)


def test_cross_company_rate_id_is_404_and_untouched(fx: Fx) -> None:
    assert fx.client.delete(f"/api/v1/finance/rates/{fx.their_rate}", headers=CSRF).status_code == 404
    with Session(fx.engine) as s:
        assert s.get(VendorRate, fx.their_rate) is not None
    assert fx.client.get("/api/v1/finance/rates", params={"person_id": str(fx.their_vendor)}).json() == []


def test_feed_lists_a_quote_review_row(fx: Fx) -> None:
    with Session(fx.engine) as s, s.begin():
        feed.deliver_payload(s, fx.company_id, f"quote_review:{uuid4()}", FeedKind.quote_review, fx.mine, REPORT)
    items = fx.client.get("/api/v1/feed").json()
    card = next(i for i in items if i["kind"] == "quote_review")
    assert card["ref_id"] == str(fx.mine)
    assert card["payload"]["verdict"] == "above_agreed"
