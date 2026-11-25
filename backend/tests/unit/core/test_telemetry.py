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


def test_sentry_scrubs_brixx_rows_and_never_sends_frame_locals() -> None:
    s = Settings(database_url=URL, sentry_dsn="https://k@o0.ingest.de.sentry.io/1", env="prod", _env_file=None)  # type: ignore[call-arg]
    with patch("app.core.telemetry.sentry_sdk.init") as init:
        init_telemetry(s)
    kwargs = init.call_args.kwargs
    assert kwargs["include_local_variables"] is False
    event = {
        "request": {"headers": {"Authorization": "Bearer secret-value"}},
        "extra": {"context": {"ZOEKID": "00001011990A", "rows": [{"naam": "Invented"}]}},
    }
    kwargs["event_scrubber"].scrub_event(event)
    flat = str(event)
    assert "secret-value" not in flat
    assert "00001011990A" not in flat
    assert "Invented" not in flat


def test_sentry_events_and_breadcrumbs_lose_chat_numbers() -> None:
    s = Settings(database_url=URL, sentry_dsn="https://k@o0.ingest.de.sentry.io/1", env="prod", _env_file=None)  # type: ignore[call-arg]
    with patch("app.core.telemetry.sentry_sdk.init") as init:
        init_telemetry(s)
    kwargs = init.call_args.kwargs
    url = "https://app.example/api/chats/+31612345678/messages"
    event = {
        "request": {"url": url, "method": "POST"},
        "breadcrumbs": {"values": [{"category": "httplib", "data": {"url": url}, "message": f"POST {url}"}]},
        "transaction": "/api/chats/%2B31612345678/read",
    }
    out = kwargs["before_send"](event, {})
    assert "31612345678" not in str(out)
    assert out["request"]["url"] == "https://app.example/api/chats/{chat_key}/messages"
    crumb = kwargs["before_breadcrumb"]({"data": {"url": url}, "message": url}, {})
    assert "31612345678" not in str(crumb)
