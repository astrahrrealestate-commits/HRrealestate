import re
from pathlib import Path
from typing import Any

import pytest

from app.api.v1.decisions import DOC_CHOICES
from app.core.errors import UnsafeConfigurationError
from app.core.settings import Settings
from app.dev.demo_dashboard import ensure_dashboard_allowed, skip_reason


def _settings(**kw: Any) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@h/db", _env_file=None, **kw)  # type: ignore[arg-type,call-arg]


def test_fake_providers_pass() -> None:
    ensure_dashboard_allowed(_settings())


@pytest.mark.parametrize("override", [{"gmail_provider": "google"}, {"drive_provider": "google"}])
def test_real_gmail_or_drive_refuses(override: dict[str, str]) -> None:
    with pytest.raises(UnsafeConfigurationError, match="fake providers only"):
        ensure_dashboard_allowed(_settings(**override))


def test_skipped_without_session_secret() -> None:
    assert skip_reason(_settings()) is not None
    assert skip_reason(_settings(dashboard_session_secret="x" * 32)) is None


def test_documented_document_choices_match_the_code() -> None:
    text = (Path(__file__).parents[3] / "docs" / "dashboard-api.md").read_text()
    line = next(ln for ln in text.splitlines() if ln.startswith("Document choices"))
    documented = set(re.findall(r"`([a-z_]+)`", line)) - {"doc_choices"}
    assert documented == set(DOC_CHOICES)
