import pytest
from pydantic import ValidationError

from app.core.settings import Settings

URL = "postgresql+psycopg://u:p@localhost:5433/db"


def test_dbos_url_strips_driver() -> None:
    s = Settings(database_url=URL, _env_file=None)  # type: ignore[call-arg]
    assert s.dbos_database_url == "postgresql://u:p@localhost:5433/db"


def test_database_url_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_rejects_non_postgres_url() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite:///x.db", _env_file=None)  # type: ignore[call-arg]


def test_secret_not_in_repr() -> None:
    s = Settings(database_url=URL, openai_api_key="sk-test-123", _env_file=None)  # type: ignore[call-arg]
    assert "sk-test-123" not in repr(s)


@pytest.mark.parametrize("name", ["GMAIL_CREDENTIALS_FILE", "S3_BUCKET", "WHATSAPP_APP_SECRET"])
def test_empty_env_values_are_unset(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """`.env.example` ships `NAME=` lines: empty must mean unset, never `Path('.')` or `''`."""
    monkeypatch.setenv(name, "")
    s = Settings(database_url=URL, _env_file=None)  # type: ignore[call-arg]
    assert getattr(s, name.lower()) is None


def test_empty_send_credentials_are_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.sender.settings import SenderSettings

    monkeypatch.setenv("GMAIL_SEND_CREDENTIALS_FILE", "")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "")
    s = SenderSettings(_env_file=None)  # type: ignore[call-arg]
    assert (s.gmail_send_credentials_file, s.whatsapp_access_token) == (None, None)
