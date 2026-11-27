"""JSON reads are compressed: the inbox list is ~180 KB raw and is re-fetched every few seconds by an open page."""

from unittest.mock import MagicMock

from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.settings import Settings
from app.main import create_app

BIG = "tenant mail " * 500


def _client() -> TestClient:
    settings = Settings(  # type: ignore[call-arg]
        database_url="postgresql+psycopg://u:p@localhost:1/db",
        env="test",
        dashboard_session_secret=SecretStr("x" * 32),
        _env_file=None,
    )
    app = create_app(settings, engine=MagicMock(), workflow_client=MagicMock())
    app.add_api_route("/_test/big", lambda: PlainTextResponse(BIG))
    app.add_api_route("/_test/events", lambda: StreamingResponse(iter([BIG]), media_type="text/event-stream"))
    return TestClient(app)


def test_large_response_is_gzipped_when_the_client_accepts_it() -> None:
    with _client() as client:
        res = client.get("/_test/big", headers={"Accept-Encoding": "gzip"})
        assert res.headers.get("content-encoding") == "gzip"
        assert res.text == BIG


def test_event_stream_is_never_compressed() -> None:
    # The Super Agent streams its answer; buffering it into a gzip block would hold back the first words.
    with _client() as client:
        res = client.get("/_test/events", headers={"Accept-Encoding": "gzip"})
        assert "content-encoding" not in res.headers
