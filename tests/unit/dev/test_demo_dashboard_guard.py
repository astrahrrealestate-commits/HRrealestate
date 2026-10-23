import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

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


def test_real_whatsapp_refuses() -> None:
    with pytest.raises(UnsafeConfigurationError, match="whatsapp_provider"):
        ensure_dashboard_allowed(_settings(whatsapp_provider="360dialog"))


def test_skipped_unless_auth_provider_is_fake() -> None:
    real = _settings(dashboard_session_secret="x" * 32, dashboard_auth_provider="google")
    assert skip_reason(real) == "dashboard auth provider is not fake"


def test_compose_default_secret_is_caught_by_the_prod_rule() -> None:
    text = (Path(__file__).parents[3] / "docker" / "compose.yml").read_text()
    default = re.search(r"DASHBOARD_SESSION_SECRET: \$\{DASHBOARD_SESSION_SECRET:-([^}]+)\}", text)
    assert default is not None
    assert default.group(1).lower().startswith("dev-only")
    assert len(default.group(1)) >= 32  # long enough to boot in dev


def test_failing_restore_does_not_mask_the_scenario_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from uuid import uuid4

    from app.dev import demo_dashboard as dd

    calls: list[str] = []

    def boom_scenario(*_a: object) -> list[str]:
        raise TimeoutError("scenario failed")

    def boom_restore(*_a: object) -> None:
        calls.append("restore")
        raise RuntimeError("db gone")

    monkeypatch.setattr(dd, "prepare", lambda *_a: dd.Previous(dd.OutboundMode.draft, ()))
    monkeypatch.setattr(dd, "_scenario", boom_scenario)
    monkeypatch.setattr(dd, "restore", boom_restore)
    with pytest.raises(TimeoutError, match="scenario failed"):
        dd.run_dashboard(MagicMock(), MagicMock(), uuid4(), timeout=1)
    assert calls == ["restore"]


def test_prepare_returns_previous_state_and_restore_writes_it_back() -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    from app.contracts import InteractiveChannel
    from app.dev import demo_dashboard as dd

    owner = SimpleNamespace(id=uuid4(), interactive_channel=InteractiveChannel.whatsapp, email="harjot@example.test")
    session = MagicMock()
    session.scalar.return_value = dd.OutboundMode.draft
    session.execute.return_value.all.return_value = [owner]
    with patch.object(dd, "Session") as factory:
        factory.return_value.__enter__.return_value = session
        previous = dd.prepare(MagicMock(), uuid4())
        assert previous == dd.Previous(
            dd.OutboundMode.draft, ((owner.id, InteractiveChannel.whatsapp, "harjot@example.test"),)
        )
        writes_after_prepare = session.execute.call_count
        dd.restore(MagicMock(), uuid4(), previous)
    assert writes_after_prepare == 3  # read owners, set company, set owners
    assert session.execute.call_count == 3 + 2  # restore: company + one owner
