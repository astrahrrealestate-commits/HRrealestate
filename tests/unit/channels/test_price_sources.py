"""PriceObservation validation, the fake price source and the composite/factory wiring."""

from datetime import date
from decimal import Decimal
from typing import Literal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.channels.prices.fake import FakePriceSource
from app.channels.prices.ports import PriceObservation, PriceSource
from app.channels.prices.search import FakeSearchClient, UnconfiguredSearchClient
from app.channels.prices.web import WebPriceSource
from app.channels.registry import search_client
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


def _build(
    setting: Literal["fake", "competitors", "web"],
    provider: Literal["none", "fake"] = "none",
    engine: Engine | None = None,
    allowed: list[str] | None = None,
) -> PriceSource:
    settings = Settings(  # type: ignore[call-arg]
        database_url="postgresql+psycopg://u:p@localhost:1/db",
        price_source=setting,
        price_search_provider=provider,
        price_allowed_domains=allowed or [],
        _env_file=None,
    )
    return build_price_source(settings, _no_session, uuid4(), None, engine=engine)


def test_build_fake_is_fake_plus_competitors() -> None:
    source = _build("fake")
    assert isinstance(source, CompositePriceSource)
    kinds = [type(s) for s in source.sources]
    assert kinds == [FakePriceSource, CompetitorRatesSource]


def test_build_competitors_only() -> None:
    source = _build("competitors")
    assert isinstance(source, CompositePriceSource)
    assert [type(s) for s in source.sources] == [CompetitorRatesSource]


def test_build_web_without_a_search_provider_names_the_setting() -> None:
    with pytest.raises(PriceSourceNotConfiguredError, match="PRICE_SEARCH_PROVIDER"):
        _build("web", "none", MagicMock())


def test_build_web_with_the_fake_provider_is_web_plus_competitors() -> None:
    source = _build("web", "fake", MagicMock(), allowed=["klusprijzen.example"])
    assert isinstance(source, CompositePriceSource)
    assert [type(s) for s in source.sources] == [WebPriceSource, CompetitorRatesSource]
    web = source.sources[0]
    assert isinstance(web, WebPriceSource)
    assert isinstance(web.search, FakeSearchClient)
    assert web.allowed_domains == ["klusprijzen.example"]


def test_build_web_needs_an_engine_for_the_extractor() -> None:
    with pytest.raises(PriceSourceNotConfiguredError, match="engine"):
        _build("web", "fake", None)


@pytest.mark.parametrize("setting", ["fake", "competitors"])
def test_other_modes_ignore_the_search_provider_and_the_engine(setting: Literal["fake", "competitors"]) -> None:
    source = _build(setting, "none", None)
    assert isinstance(source, CompositePriceSource)
    assert not any(isinstance(s, WebPriceSource) for s in source.sources)


def test_registry_maps_the_provider_to_a_search_client() -> None:
    assert isinstance(search_client(Settings(price_search_provider="fake")), FakeSearchClient)
    assert isinstance(search_client(Settings(price_search_provider="none")), UnconfiguredSearchClient)
