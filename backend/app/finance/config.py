"""Quote review thresholds from settings (kept out of the pure review modules)."""

from app.core.settings import Settings
from app.finance.review_types import Thresholds


def thresholds_from_settings(settings: Settings) -> Thresholds:
    return Thresholds(
        ok_pct=settings.finance_ok_pct,
        above_market_pct=settings.finance_above_market_pct,
        well_above_pct=settings.finance_well_above_pct,
        low_ratio=settings.finance_low_ratio,
        late_days=settings.finance_late_days,
        min_samples=settings.finance_min_samples,
        vat_rate=settings.finance_vat_rate,
    )
