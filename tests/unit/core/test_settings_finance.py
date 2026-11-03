"""Quote checker settings (spec 2026-10-31): thresholds, price source, and the prod refusal of the fake source."""

from decimal import Decimal
from typing import Any

import pytest
from pydantic import PostgresDsn

from app.core.settings import Settings
from app.core.startup import production_problems

URL = "postgresql+psycopg://u:p@localhost:5433/db"


def _s(**kw: Any) -> Settings:
    return Settings(database_url=PostgresDsn(URL), _env_file=None, **kw)


def test_finance_defaults() -> None:
    s = _s()
    assert s.finance_ok_pct == Decimal(5)
    assert s.finance_above_market_pct == Decimal(15)
    assert s.finance_well_above_pct == Decimal(30)
    assert s.finance_low_ratio == Decimal("0.5")
    assert s.finance_late_days == 7
    assert s.finance_min_samples == 3
    assert s.finance_vat_rate == Decimal("0.21")
    assert s.finance_daily_lookup_cap == 40
    assert s.price_source == "fake"


def test_prod_refuses_the_fake_price_source() -> None:
    assert any("price_source" in p for p in production_problems(_s(env="prod")))


def test_prod_accepts_the_competitors_price_source() -> None:
    problems = production_problems(_s(env="prod", price_source="competitors"))
    assert not any("price_source" in p or "price_search_provider" in p for p in problems)


@pytest.mark.parametrize("provider", ["none", "fake"])
def test_prod_refuses_the_web_source_without_a_real_search_provider(provider: str) -> None:
    problems = production_problems(_s(env="prod", price_source="web", price_search_provider=provider))
    assert any("price_search_provider" in p and repr(provider) in p and "web" in p for p in problems)


@pytest.mark.parametrize("provider", ["none", "fake"])
def test_prod_ignores_the_search_provider_unless_the_web_source_is_selected(provider: str) -> None:
    problems = production_problems(_s(env="prod", price_source="competitors", price_search_provider=provider))
    assert not any("price_search_provider" in p for p in problems)


def test_dev_allows_web_with_the_fake_search_provider() -> None:
    assert production_problems(_s(env="dev", price_source="web", price_search_provider="fake")) == []


def test_price_search_defaults() -> None:
    s = _s()
    assert s.price_search_provider == "none"
    assert s.price_allowed_domains == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", []),
        ("bouwmaterialen.example", ["bouwmaterialen.example"]),
        (" A.example , b.example/ ,, ", ["a.example", "b.example"]),
    ],
)
def test_price_allowed_domains_parse_a_comma_list(
    raw: str, expected: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRICE_ALLOWED_DOMAINS", raw)
    assert _s().price_allowed_domains == expected


def test_price_allowed_domains_reject_a_wildcard_or_scheme() -> None:
    for bad in ("*.example", "https://a.example"):
        with pytest.raises(ValueError, match="PRICE_ALLOWED_DOMAINS"):
            _s(price_allowed_domains=[bad])


def test_dev_allows_the_fake_price_source() -> None:
    assert production_problems(_s(env="dev")) == []
