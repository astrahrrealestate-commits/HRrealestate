"""PriceObservation validation, the fake price source and the composite/factory wiring."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.channels.prices.fake import FakePriceSource
from app.channels.prices.ports import PriceObservation, PriceSource
from app.core.errors import PriceSourceNotConfiguredError
from app.core.settings import Settings
from app.finance.competitors import CompetitorRatesSource
from app.finance.sources import CompositePriceSource, build_price_source

AS_OF = date(2026, 10, 31)


def _obs(
    *,
    amount: Decimal = Decimal("50"),
    source: str = "shop",
    url: str | None = "https://example.nl/p",
) -> PriceObservation:
    return PriceObservation(amount=amount, unit="hour", vat_included=False, source=source, url=url, observed_on=AS_OF)


def _no_session() -> Session:
    raise AssertionError("no session expected")


def test_fake_is_deterministic_and_every_observation_has_a_source() -> None:
    a = FakePriceSource().lookup("plumber_hourly", "hour", AS_OF)
    b = FakePriceSource().lookup("plumber_hourly", "hour", AS_OF)
    assert a == b
    assert len(a) == 5
    assert all(o.source == "fake" and o.url and o.unit == "hour" and o.observed_on == AS_OF for o in a)
    assert all(not o.vat_included and o.amount > 0 for o in a)
    assert a != FakePriceSource().lookup("electrician_hourly", "hour", AS_OF)


def test_fake_uses_the_table_when_the_key_is_present() -> None:
    table = {"k": [Decimal("10"), Decimal("20")]}
    got = FakePriceSource(table).lookup("k", "piece", AS_OF)
    assert [o.amount for o in got] == [Decimal("10"), Decimal("20")]
    assert all(o.unit == "piece" for o in got)


def test_observation_without_source_is_rejected() -> None:
    with pytest.raises(ValueError, match="source"):
        _obs(source="  ")


def test_observation_rejects_non_positive_amount() -> None:
    with pytest.raises(ValueError, match="amount"):
        _obs(amount=Decimal("0"))


@pytest.mark.parametrize("source", ["owner", "competitor:Jansen"])
def test_url_may_be_missing_for_owner_and_competitor(source: str) -> None:
    assert _obs(source=source, url=None).url is None


@pytest.mark.parametrize("url", [None, "", "ftp://x.nl/p", "not a url"])
def test_url_is_required_for_other_sources(url: str | None) -> None:
    with pytest.raises(ValueError, match="url"):
        _obs(source="shop", url=url)


def test_composite_concatenates_in_order() -> None:
    first = FakePriceSource({"k": [Decimal("1")]})
    second = FakePriceSource({"k": [Decimal("2"), Decimal("3")]})
    got = CompositePriceSource([first, second]).lookup("k", "hour", AS_OF)
    assert [o.amount for o in got] == [Decimal("1"), Decimal("2"), Decimal("3")]


def _build(setting: Literal["fake", "competitors", "web"]) -> PriceSource:
    settings = Settings(  # type: ignore[call-arg]
        database_url="postgresql+psycopg://u:p@localhost:1/db", price_source=setting, _env_file=None
    )
    return build_price_source(settings, _no_session, uuid4(), None)


def test_build_fake_is_fake_plus_competitors() -> None:
    source = _build("fake")
    assert isinstance(source, CompositePriceSource)
    kinds = [type(s) for s in source.sources]
    assert kinds == [FakePriceSource, CompetitorRatesSource]


def test_build_competitors_only() -> None:
    source = _build("competitors")
    assert isinstance(source, CompositePriceSource)
    assert [type(s) for s in source.sources] == [CompetitorRatesSource]


def test_build_web_is_not_configured_yet() -> None:
    with pytest.raises(PriceSourceNotConfiguredError):
        _build("web")
