from decimal import Decimal
from typing import Any

import pytest

from app.core.settings import Settings
from app.finance.config import thresholds_from_settings
from app.finance.review_types import Thresholds

_VALID: dict[str, Any] = {
    "ok_pct": Decimal(5),
    "above_market_pct": Decimal(15),
    "well_above_pct": Decimal(30),
    "low_ratio": Decimal("0.5"),
    "late_days": 7,
    "min_samples": 3,
    "vat_rate": Decimal("0.21"),
}


def test_thresholds_from_settings_uses_the_finance_defaults() -> None:
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", _env_file=None)  # type: ignore[arg-type]

    assert thresholds_from_settings(settings) == Thresholds(**_VALID)


@pytest.mark.parametrize(
    "override",
    [
        {"low_ratio": Decimal(0)},
        {"low_ratio": Decimal(1)},
        {"ok_pct": Decimal(-1)},
        {"ok_pct": Decimal(15)},
        {"above_market_pct": Decimal(30)},
        {"late_days": 0},
        {"min_samples": 0},
        {"vat_rate": Decimal("-0.01")},
        {"vat_rate": Decimal(1)},
    ],
)
def test_thresholds_reject_inconsistent_values(override: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        Thresholds(**{**_VALID, **override})
