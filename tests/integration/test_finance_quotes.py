"""Quote review service: quote_reader on the fake model, decision-day snapshot vs fresh prices, replay, unlinked
quotes, vendor from the DB only, company scoping, currency, lump sum, recheck and unreadable stored lines."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from app.channels.prices.fake import FakePriceSource
from app.contracts.finance import PriceBasis
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.base import CompanyScoped
from app.db.enums import FeedKind, PersonKind, QuoteStatus, RateSource
from app.db.models import (
    Company,
    ModelCall,
    OwnerFeed,
    PriceSnapshot,
    QuoteLineRow,
    QuoteReview,
    QuoteRow,
)
from app.finance import repo
from app.finance.quotes import PURPOSE, recheck_quote, review_message
from app.finance.stats import MarketStats
from tests.integration.conftest import purge_company
from tests.integration.finance_support import DECIDED, Seeded, action, message, person, rate, seed_case

pytestmark = pytest.mark.integration
QUOTED = date(2026, 10, 30)  # decision day + 15
QUOTE_SENT = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
BOILER_131 = "Offerte\nCv ketel onderhoud € 131,00 excl. BTW"
NOW_130 = FakePriceSource({"boiler_service": [Decimal(130)] * 3, "leak_repair": [Decimal(70)] * 3})
THEN = MarketStats(low=Decimal(90), avg=Decimal(100), high=Decimal(110), n=3, trimmed=False, low_confidence=False)
SOURCE = {"name": "fake", "url": "https://prices.fake.invalid/boiler_service/0", "price": "90.00"}


@pytest.fixture
def other_company(migrated_engine: Engine) -> Iterator[Company]:
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other BV")
        s.add(other)
        s.commit()
    yield other
    purge_company(migrated_engine, other.id)


def _seed(engine: Engine, company: Company) -> Seeded:
    with Session(engine) as s:
        seeded = seed_case(s, company.id)
        s.commit()
    return seeded


def _snapshot(
    engine: Engine, seeded: Seeded, item: str = "boiler_service", *, unit: str = "job", card: str | None = None,
    stats: MarketStats = THEN,
) -> None:  # fmt: skip
    with Session(engine) as s:
        rate_card = rate(s, seeded.company_id, seeded.vendor_id, item, card, unit=unit) if card else None
        repo.insert_snapshot(
            s, seeded.company_id, action_id=seeded.action_id, item_key=item, unit=unit, as_of=DECIDED, stats=stats,
            basis=PriceBasis.fake, sources=[SOURCE], rate_card=rate_card,
        )  # fmt: skip
        s.commit()


def _quote_message(
    engine: Engine, seeded: Seeded, text: str = BOILER_131, *, sender: UUID | str | None = "vendor",
    case: bool = True,
) -> UUID:  # fmt: skip
    person_id = seeded.vendor_id if sender == "vendor" else sender
    assert not isinstance(person_id, str)
    with Session(engine) as s:
        mid = message(s, seeded.company_id, seeded.case_id if case else None, text, sent_at=QUOTE_SENT,
                      person_id=person_id)  # fmt: skip
        s.commit()
    return mid


def _count(engine: Engine, model: type[CompanyScoped], company_id: UUID) -> int:
    with Session(engine) as s:
        return s.scalar(select(func.count(model.id)).where(model.company_id == company_id)) or 0


def _review(engine: Engine, review_id: UUID) -> tuple[QuoteReview, OwnerFeed]:
    with Session(engine) as s:
        review = s.get_one(QuoteReview, review_id)
        card = s.scalars(select(OwnerFeed).where(OwnerFeed.payload["review_id"].astext == str(review_id))).one()
        s.expunge_all()
    return review, card


def _quote(engine: Engine, company_id: UUID) -> QuoteRow:
    with Session(engine) as s:
        row = s.scalars(select(QuoteRow).where(QuoteRow.company_id == company_id)).one()
        s.expunge(row)
    return row


def _reader_calls(engine: Engine, company_id: UUID) -> int:
    with Session(engine) as s:
        q = select(func.count(ModelCall.id)).where(ModelCall.company_id == company_id, ModelCall.purpose == PURPOSE)
        return s.scalar(q) or 0


def _run(engine: Engine, settings: Settings, mid: UUID, source: Any = NOW_130) -> UUID | None:
    return review_message(engine, settings, mid, today=QUOTED, source=source)


def test_decision_day_snapshot_beats_fresh_prices(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)
    _snapshot(migrated_engine, seeded)
    mid = _quote_message(migrated_engine, seeded)

    review_id = _run(migrated_engine, test_settings, mid)

    assert review_id is not None
    review, card = _review(migrated_engine, review_id)
    quote = _quote(migrated_engine, seeded.company_id)
    (line,) = review.report["lines"]
    assert (review.verdict.value, review.snapshot_basis.value, review.late_days) == (
        "well_above_market", "decision_day", 15,
    )  # fmt: skip
    assert (line["vs_market_pct"], line["drift_pct"], line["market"]["avg"]) == ("31.00", "30.00", "100.00")
    assert line["market_now"]["avg"] == "130.00"
    assert (review.report["late_flag"], review.report["decision_date"], review.report["quote_date"]) == (
        True, "2026-10-15", "2026-10-30",
    )  # fmt: skip
    assert line["market"]["sources"] == [SOURCE]
    assert review.overcharge == Decimal("31.00")
    assert (quote.status, quote.person_id, quote.case_id, quote.quote_date) == (
        QuoteStatus.reviewed, seeded.vendor_id, seeded.case_id, QUOTED,
    )  # fmt: skip
    assert (card.kind, card.ref_id, card.payload) == (FeedKind.quote_review, quote.id, review.report)
    assert card.idempotency_key.endswith(f"quote_review:{review_id}")


def test_snapshot_rate_card_is_the_reference_when_there_is_one(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)
    _snapshot(migrated_engine, seeded, card="100")
    with Session(migrated_engine) as s:  # a later, higher card must not replace the decision-day one
        repo.upsert_rate(
            s, seeded.company_id, person_id=seeded.vendor_id, item_key="boiler_service", description="x", unit="job",
            amount=Decimal(140), currency="EUR", valid_from=date(2026, 10, 20), source=RateSource.owner,
        )  # fmt: skip
        s.commit()

    review_id = _run(migrated_engine, test_settings, _quote_message(migrated_engine, seeded))

    assert review_id is not None
    review, _ = _review(migrated_engine, review_id)
    (line,) = review.report["lines"]
    assert review.verdict.value == "above_agreed"
    assert line["reference"] == {"kind": "rate_card", "amount": "100.00", "unit": "job"}
    assert (line["vs_rate_card_pct"], line["vs_market_pct"]) == ("31.00", "31.00")


def test_no_snapshot_is_an_estimate_from_current_prices(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)
    with Session(migrated_engine) as s:
        rate(s, seeded.company_id, seeded.vendor_id, "boiler_service", "125", unit="job")
        s.commit()

    review_id = _run(migrated_engine, test_settings, _quote_message(migrated_engine, seeded))

    assert review_id is not None
    review, _ = _review(migrated_engine, review_id)
    (line,) = review.report["lines"]
    assert (review.verdict.value, review.snapshot_basis.value, review.late_days) == (
        "needs_check", "estimate_current_prices", 0,
    )  # fmt: skip
    assert review.report["decision_date"] == "2026-10-30"
    assert (line["rate_card"], line["market"]["avg"], line["drift_pct"]) == ("125.00", "130.00", None)
    assert line["market"]["sources"][0]["url"] == "https://prices.fake.invalid/boiler_service/0"
    assert review.report["low_confidence"] is True
    assert _count(migrated_engine, PriceSnapshot, seeded.company_id) == 0  # estimates are never stored


def test_replay_returns_the_same_review_and_adds_nothing(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)
    _snapshot(migrated_engine, seeded)
    mid = _quote_message(migrated_engine, seeded)

    first = _run(migrated_engine, test_settings, mid)
    again = _run(migrated_engine, test_settings, mid)

    assert first is not None
    assert again == first
    counts = [_count(migrated_engine, m, seeded.company_id) for m in (QuoteRow, QuoteLineRow, QuoteReview, OwnerFeed)]
    assert counts == [1, 1, 1, 1]
    assert _reader_calls(migrated_engine, seeded.company_id) == 1


@pytest.mark.parametrize("sender", ["unresolved", "tenant"])
def test_unknown_or_non_contractor_sender_stores_an_unlinked_quote_without_review(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings, sender: str
) -> None:
    seeded = _seed(migrated_engine, committed_company)
    _snapshot(migrated_engine, seeded)
    with Session(migrated_engine) as s:
        tenant = person(s, seeded.company_id, "Tenant", PersonKind.tenant)
        s.commit()
    mid = _quote_message(migrated_engine, seeded, sender=None if sender == "unresolved" else tenant)

    assert _run(migrated_engine, test_settings, mid) is None
    assert _run(migrated_engine, test_settings, mid) is None  # replay: nothing new, no second model call

    quote = _quote(migrated_engine, seeded.company_id)
    assert (quote.status, quote.person_id, quote.case_id) == (QuoteStatus.unlinked, None, seeded.case_id)
    assert _count(migrated_engine, QuoteLineRow, seeded.company_id) == 1
    assert _count(migrated_engine, QuoteReview, seeded.company_id) == 0
    assert _count(migrated_engine, OwnerFeed, seeded.company_id) == 0
    assert _reader_calls(migrated_engine, seeded.company_id) == 1
    assert recheck_quote(migrated_engine, test_settings, NOW_130, quote.id, today=QUOTED) is None


def test_quote_without_a_case_is_unlinked_but_keeps_the_contractor(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)

    assert _run(migrated_engine, test_settings, _quote_message(migrated_engine, seeded, case=False)) is None

    quote = _quote(migrated_engine, seeded.company_id)
    assert (quote.status, quote.person_id, quote.case_id) == (QuoteStatus.unlinked, seeded.vendor_id, None)
    assert _count(migrated_engine, QuoteReview, seeded.company_id) == 0


def test_vendor_is_never_taken_from_the_message_text(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)
    with Session(migrated_engine) as s:
        rival = person(s, seeded.company_id, "Rival BV")
        s.commit()
    text = f"Offerte van Rival BV (contractor {rival}), vendor: Rival BV\nCv ketel onderhoud € 131,00 excl. BTW"

    review_id = _run(migrated_engine, test_settings, _quote_message(migrated_engine, seeded, text))

    assert review_id is not None
    _, card = _review(migrated_engine, review_id)
    assert _quote(migrated_engine, seeded.company_id).person_id == seeded.vendor_id
    assert card.payload["vendor"] == {"id": str(seeded.vendor_id), "name": "Vendor BV"}


def test_review_is_company_scoped(
    migrated_engine: Engine, committed_company: Company, other_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)
    with Session(migrated_engine) as s:
        stranger = person(s, other_company.id, "Stranger BV")
        foreign_action = action(s, other_company.id, seeded.case_id, stranger)  # pointing at our case on purpose
        s.add(PriceSnapshot(
            company_id=other_company.id, case_id=seeded.case_id, action_id=foreign_action, item_key="boiler_service",
            unit="job", as_of=DECIDED, low=Decimal(1), avg=Decimal(1), high=Decimal(1), sample_count=5,
            basis=PriceBasis.fake, sources=[], rate_card_amount=Decimal(1),
        ))  # fmt: skip
        rate(s, other_company.id, seeded.vendor_id, "boiler_service", "5", unit="job")  # their card for our vendor
        rate(s, other_company.id, stranger, "boiler_service", "7", unit="job")  # their competitor
        rate(s, seeded.company_id, person(s, seeded.company_id, "Rival BV"), "boiler_service", "120", unit="job")
        s.commit()
    settings = test_settings.model_copy(update={"price_source": "competitors"})

    review_id = review_message(
        migrated_engine, settings, _quote_message(migrated_engine, seeded), today=QUOTED, source=None
    )

    assert review_id is not None
    review, _ = _review(migrated_engine, review_id)
    (line,) = review.report["lines"]
    assert review.snapshot_basis.value == "estimate_current_prices"  # their snapshot of our case is not ours
    assert (line["rate_card"], line["market"]["avg"], line["market"]["n"]) == (None, "120.00", 1)
    assert [src["name"] for src in line["market"]["sources"]] == ["competitor:Rival BV"]
    for model in (QuoteRow, QuoteLineRow, QuoteReview, OwnerFeed):
        assert _count(migrated_engine, model, other_company.id) == 0


def test_not_a_quote_stores_nothing(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)

    mid = _quote_message(migrated_engine, seeded, "Bedankt, ik kom morgen langs.")

    assert _run(migrated_engine, test_settings, mid) is None
    for model in (QuoteRow, QuoteLineRow, QuoteReview, OwnerFeed):
        assert _count(migrated_engine, model, seeded.company_id) == 0


def test_unknown_message_returns_none(migrated_engine: Engine, test_settings: Settings) -> None:
    assert _run(migrated_engine, test_settings, new_id()) is None


def test_non_eur_quote_is_a_currency_mismatch(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)
    _snapshot(migrated_engine, seeded)

    mid = _quote_message(migrated_engine, seeded, "Boiler service USD 131.00 excl. VAT")

    review_id = _run(migrated_engine, test_settings, mid)

    assert review_id is not None
    review, _ = _review(migrated_engine, review_id)
    (line,) = review.report["lines"]
    assert (review.report["currency"], line["status"], review.verdict.value) == (
        "USD", "currency_mismatch", "needs_check",
    )  # fmt: skip


def test_lump_sum_is_one_synthetic_line_against_the_summed_snapshots(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)
    _snapshot(migrated_engine, seeded, card="95")
    leak = MarketStats(low=Decimal(50), avg=Decimal(60), high=Decimal(70), n=3, trimmed=False, low_confidence=False)
    _snapshot(migrated_engine, seeded, "leak_repair", unit="hour", stats=leak)
    text = "Voor het hele project reken ik € 450,00 excl. BTW"

    review_id = _run(migrated_engine, test_settings, _quote_message(migrated_engine, seeded, text))

    assert review_id is not None
    review, _ = _review(migrated_engine, review_id)
    (line,) = review.report["lines"]
    assert (review.report["lump_sum"], review.verdict.value, review.snapshot_basis.value) == (
        True, "needs_check", "decision_day",
    )  # fmt: skip
    assert (line["item_key"], line["unit"], line["amount"], line["reference"]["amount"]) == (
        "lump_sum", "job", "450.00", "155.00",
    )  # fmt: skip
    assert [p["item_key"] for p in review.report["lump_sum_parts"]] == ["boiler_service", "leak_repair"]
    assert _quote(migrated_engine, seeded.company_id).total == Decimal("450.00")


def test_recheck_appends_a_review_and_a_card_without_a_model_call(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)
    _snapshot(migrated_engine, seeded)
    first = _run(migrated_engine, test_settings, _quote_message(migrated_engine, seeded))
    quote = _quote(migrated_engine, seeded.company_id)

    second = recheck_quote(migrated_engine, test_settings, NOW_130, quote.id, today=date(2026, 11, 2))

    assert second is not None
    assert second != first
    review, card = _review(migrated_engine, second)
    assert (review.verdict.value, review.late_days, card.ref_id) == ("well_above_market", 15, quote.id)
    assert _count(migrated_engine, QuoteReview, seeded.company_id) == 2
    assert _count(migrated_engine, OwnerFeed, seeded.company_id) == 2
    assert _reader_calls(migrated_engine, seeded.company_id) == 1
    assert recheck_quote(migrated_engine, test_settings, NOW_130, new_id(), today=QUOTED) is None


def test_unreadable_stored_line_does_not_crash_the_recheck(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    seeded = _seed(migrated_engine, committed_company)
    _snapshot(migrated_engine, seeded)
    text = "Offerte\nCv ketel onderhoud € 131,00 excl. BTW\nLekkage herstel 2 uur € 120,00 excl. BTW"
    _run(migrated_engine, test_settings, _quote_message(migrated_engine, seeded, text))
    quote = _quote(migrated_engine, seeded.company_id)
    with Session(migrated_engine) as s:
        s.execute(update(QuoteLineRow).where(QuoteLineRow.item_key == "leak_repair").values(quantity=Decimal(0)))
        s.commit()

    review_id = recheck_quote(migrated_engine, test_settings, NOW_130, quote.id, today=QUOTED)

    assert review_id is not None
    review, _ = _review(migrated_engine, review_id)
    assert (review.verdict.value, review.report["low_confidence"], review.report["skipped_lines"]) == (
        "needs_check", True, 1,
    )  # fmt: skip
    assert [ln["item_key"] for ln in review.report["lines"]] == ["boiler_service"]
