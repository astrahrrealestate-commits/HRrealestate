from decimal import Decimal

from app.core.settings import Settings
from app.llm.budget import CONCIERGE_PURPOSE, OWNER_QA_PURPOSE, Usage, exceeded

ZERO = Decimal(0)


def _settings(**kw: object) -> Settings:
    return Settings(database_url="postgresql+psycopg://x@localhost/x", env="test", _env_file=None, **kw)  # type: ignore[call-arg]


def _usage(**kw: object) -> Usage:
    base: dict[str, object] = {
        "spend_day": ZERO, "spend_month": ZERO, "calls_day": 0, "purpose_spend_day": ZERO, "purpose_calls_day": 0,
    }  # fmt: skip
    return Usage(**{**base, **kw})  # type: ignore[arg-type]


def test_no_limits_means_never_exceeded() -> None:
    big = _usage(spend_day=Decimal(999), spend_month=Decimal(9999), calls_day=10**6)
    assert exceeded(_settings(), "triage", big) is None


def test_each_global_limit_names_itself() -> None:
    assert exceeded(_settings(llm_daily_budget_usd="1"), "triage", _usage(spend_day=Decimal(1))) == "daily_budget"
    assert exceeded(_settings(llm_monthly_budget_usd="5"), "triage", _usage(spend_month=Decimal(6))) == "monthly_budget"
    assert exceeded(_settings(llm_daily_calls_cap=3), "triage", _usage(calls_day=3)) == "daily_calls"


def test_below_the_limit_is_fine() -> None:
    assert exceeded(_settings(llm_daily_calls_cap=3), "triage", _usage(calls_day=2)) is None


def test_owner_qa_caps_apply_only_to_owner_qa() -> None:
    s = _settings(owner_qa_daily_cap=2)
    u = _usage(purpose_calls_day=2)
    assert exceeded(s, OWNER_QA_PURPOSE, u) == "owner_qa_daily_calls"
    assert exceeded(s, "triage", u) is None


def test_concierge_caps_apply_only_to_concierge() -> None:
    s = _settings(concierge_daily_cap=2, concierge_daily_budget_usd="1")
    assert exceeded(s, CONCIERGE_PURPOSE, _usage(purpose_calls_day=2)) == "concierge_daily_calls"
    assert exceeded(s, CONCIERGE_PURPOSE, _usage(purpose_spend_day=Decimal(1))) == "concierge_daily_budget"
    assert exceeded(s, OWNER_QA_PURPOSE, _usage(purpose_calls_day=2)) is None
    assert exceeded(_settings(), CONCIERGE_PURPOSE, _usage(purpose_calls_day=99)) is None
