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


@pytest.mark.parametrize("source", ["competitors", "web"])
def test_prod_accepts_a_real_price_source(source: str) -> None:
    assert not any("price_source" in p for p in production_problems(_s(env="prod", price_source=source)))


def test_dev_allows_the_fake_price_source() -> None:
    assert production_problems(_s(env="dev")) == []
