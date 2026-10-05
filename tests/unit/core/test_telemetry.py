from unittest.mock import patch

from app.core.settings import Settings
from app.core.telemetry import init_telemetry

URL = "postgresql+psycopg://u:p@localhost:5433/db"


def test_sentry_noop_without_dsn() -> None:
    with patch("app.core.telemetry.sentry_sdk.init") as init:
        init_telemetry(Settings(database_url=URL, _env_file=None))  # type: ignore[call-arg]
    init.assert_not_called()


def test_sentry_init_without_pii_when_dsn_set() -> None:
    s = Settings(database_url=URL, sentry_dsn="https://k@o0.ingest.de.sentry.io/1", env="prod", _env_file=None)  # type: ignore[call-arg]
    with patch("app.core.telemetry.sentry_sdk.init") as init:
        init_telemetry(s)
    kwargs = init.call_args.kwargs
    assert kwargs["send_default_pii"] is False
    assert kwargs["environment"] == "prod"
