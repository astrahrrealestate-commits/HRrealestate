"""Decision-day snapshot service: job items via the fake model, fake/competitor prices, rate cards, cap, replay."""

from collections.abc import Callable, Iterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.channels.prices.fake import FakePriceSource
from app.contracts import ActionType
from app.contracts.finance import PriceBasis
from app.core.errors import EstateOSError, NotFoundError, SnapshotNotApplicableError
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.enums import RateSource
from app.db.models import Company, ModelCall, PriceSnapshot
from app.finance import repo
from app.finance.snapshot import PURPOSE, take_snapshot
from app.finance.sources import build_price_source
from tests.integration.conftest import purge_company
from tests.integration.finance_support import DECIDED, Seeded, action, message, person, rate, seed_case

pytestmark = pytest.mark.integration
TABLE = {"boiler_service": [Decimal(100), Decimal(110), Decimal(120)], "leak_repair": [Decimal(50), Decimal(70)]}


def _seed(engine: Engine, company: Company) -> Seeded:
    with Session(engine) as s:
        seeded = seed_case(s, company.id)
        s.commit()
    return seeded


def _snapshots(engine: Engine, company_id: object) -> list[PriceSnapshot]:
    with Session(engine) as s:
        q = select(PriceSnapshot).where(PriceSnapshot.company_id == company_id).order_by(PriceSnapshot.item_key)
        return list(s.scalars(q))


def _factory(engine: Engine) -> Callable[[], Session]:
    return lambda: Session(engine)


@pytest.fixture
def other_company(migrated_engine: Engine) -> Iterator[Company]:
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other BV")
        s.add(other)
        s.commit()
    yield other
    purge_company(migrated_engine, other.id)


def test_snapshot_stores_aggregated_prices_and_the_vendor_rate_card(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)
    with Session(migrated_engine) as s:
        card = rate(s, seeded.company_id, seeded.vendor_id, "boiler_service", "95.00", unit="klus").id
        s.commit()

    out = take_snapshot(migrated_engine, test_settings, FakePriceSource(TABLE), seeded.action_id, today=DECIDED)

    boiler, leak = _snapshots(migrated_engine, seeded.company_id)
    assert (out.skipped_cap, out.skipped_no_data, sorted(out.written)) == (0, 0, sorted([boiler.id, leak.id]))
    assert (boiler.case_id, boiler.action_id, boiler.as_of, boiler.unit) == (
        seeded.case_id, seeded.action_id, DECIDED, "job",
    )  # fmt: skip
    assert (boiler.low, boiler.avg, boiler.high, boiler.sample_count, boiler.basis) == (
        Decimal(100), Decimal(110), Decimal(120), 3, PriceBasis.fake,
    )  # fmt: skip
    assert (boiler.rate_card_amount, boiler.rate_card_id) == (Decimal("95.00"), card)
    assert boiler.sources[0] == {
        "name": "fake", "url": "https://prices.fake.invalid/boiler_service/0", "price": "100.00",
        "observed_on": "2026-10-15",
    }  # fmt: skip
    assert (leak.unit, leak.avg, leak.sample_count, leak.rate_card_id) == ("hour", Decimal(60), 2, None)


def test_job_items_run_through_the_fake_model_and_write_a_model_call(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)

    take_snapshot(migrated_engine, test_settings, FakePriceSource(TABLE), seeded.action_id, today=DECIDED)

    with Session(migrated_engine) as s:
        calls = list(s.scalars(select(ModelCall).where(ModelCall.company_id == seeded.company_id)))
    assert [(c.purpose, c.prompt_name, c.error) for c in calls] == [(PURPOSE, "job_items", None)]
    assert "Lekkage herstel" in calls[0].input["prompt"]


def test_snapshot_replay_adds_no_rows(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)
    source = FakePriceSource(TABLE)

    first = take_snapshot(migrated_engine, test_settings, source, seeded.action_id, today=DECIDED)
    again = take_snapshot(migrated_engine, test_settings, source, seeded.action_id, today=DECIDED)

    assert len(first.written) == 2
    assert (again.written, again.skipped_cap, again.skipped_no_data) == ([], 0, 0)
    assert len(_snapshots(migrated_engine, seeded.company_id)) == 2
    with Session(migrated_engine) as s:
        calls = s.scalar(select(func.count(ModelCall.id)).where(ModelCall.company_id == seeded.company_id))
    assert calls == 1  # the replay does not ask the model again


def test_snapshot_is_company_scoped_and_ignores_the_vendor_and_other_companies(
    migrated_engine: Engine, committed_company: Company, other_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)
    with Session(migrated_engine) as s:
        rate(s, seeded.company_id, seeded.vendor_id, "leak_repair", "999")  # the vendor is not the market
        repo.upsert_rate(  # stored as `hour`: write-time normalisation lets the competitor source match it
            s, seeded.company_id, person_id=person(s, seeded.company_id, "Rival BV"), item_key="leak_repair",
            description="Lekkage", unit="uur", amount=Decimal(80), currency="eur", valid_from=date(2026, 1, 1),
            source=RateSource.owner,
        )  # fmt: skip
        rate(s, other_company.id, person(s, other_company.id, "Stranger BV"), "leak_repair", "10")
        message(s, other_company.id, seeded.case_id, "Schilderwerk in de gang.")  # another company's text
        s.commit()
    settings = test_settings.model_copy(update={"price_source": "competitors"})
    source = build_price_source(settings, _factory(migrated_engine), seeded.company_id, seeded.vendor_id)

    out = take_snapshot(migrated_engine, settings, source, seeded.action_id, today=DECIDED)

    (leak,) = _snapshots(migrated_engine, seeded.company_id)
    assert (out.written, out.skipped_no_data) == ([leak.id], 1)  # boiler_service: no competitor has a rate
    assert (leak.item_key, leak.low, leak.avg, leak.high, leak.basis) == (
        "leak_repair", Decimal(80), Decimal(80), Decimal(80), PriceBasis.competitor,
    )  # fmt: skip
    assert leak.rate_card_amount == Decimal(999)  # the vendor's own card is the rate card, not a market price
    assert [e["name"] for e in leak.sources] == ["competitor:Rival BV"]
    assert _snapshots(migrated_engine, other_company.id) == []
    with Session(migrated_engine) as s:
        assert repo.current_rate(s, other_company.id, seeded.vendor_id, "leak_repair", "hour", DECIDED) is None


def test_daily_cap_skips_the_remaining_items(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)
    with Session(migrated_engine) as s:
        second = action(s, seeded.company_id, seeded.case_id, seeded.vendor_id)
        s.commit()
    capped = test_settings.model_copy(update={"finance_daily_lookup_cap": 1})
    source = FakePriceSource(TABLE)

    first = take_snapshot(migrated_engine, capped, source, seeded.action_id, today=DECIDED)
    full = take_snapshot(migrated_engine, capped, source, second, today=DECIDED)

    assert (len(first.written), first.skipped_cap) == (1, 1)
    assert (full.written, full.skipped_cap) == ([], 2)
    with Session(migrated_engine) as s:
        assert repo.lookups_today(s, seeded.company_id, DECIDED) == 1


def test_unknown_or_non_contractor_action_raises(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)
    with Session(migrated_engine) as s:
        reply = action(s, seeded.company_id, seeded.case_id, seeded.vendor_id, ActionType.reply_draft)
        s.commit()
    source = FakePriceSource(TABLE)

    with pytest.raises(NotFoundError):
        take_snapshot(migrated_engine, test_settings, source, new_id(), today=DECIDED)
    with pytest.raises(SnapshotNotApplicableError) as err:
        take_snapshot(migrated_engine, test_settings, source, reply, today=DECIDED)
    assert isinstance(err.value, EstateOSError)
    assert _snapshots(migrated_engine, seeded.company_id) == []
