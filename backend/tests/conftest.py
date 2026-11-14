"""Shared fixtures for unit and integration tests."""

import os
from collections.abc import Callable
from pathlib import Path

import pytest

RECORDED = Path(__file__).parent / "fixtures" / "recorded"


@pytest.fixture
def recorded() -> Callable[[str, str], bytes]:
    """Load a PII-redacted provider payload: `recorded("whatsapp", "text_message")` (see /record-fixture)."""

    def load(provider: str, scenario: str) -> bytes:
        matches = sorted((RECORDED / provider).glob(f"{scenario}.*"))
        matches = [m for m in matches if m.suffix != ".md"]
        if len(matches) != 1:
            raise FileNotFoundError(f"expected one fixture for {provider}/{scenario}, found {matches}")
        return matches[0].read_bytes()

    return load


# ---- live provider checks (`make live-check`) ----------------------------------------------------------------------
# `@pytest.mark.live("SETTING", ...)` tests call real providers. They never run by default; `--live` runs only them,
# after checking that every setting the selected tests need is configured (env or .env).


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--live", action="store_true", help="run only live provider checks (needs credentials)")


def pytest_configure(config: pytest.Config) -> None:
    """Tests run on fakes whatever a developer's `.env` selects (a real Gemini model, a real Gmail mailbox, Drive);
    only `--live` checks use the configured services. Environment variables win over `.env` in Settings; an empty
    value means unset."""
    if not config.getoption("--live", default=False):
        for name, value in {
            "LLM_MODEL": "fake",
            "GMAIL_PROVIDER": "fake",
            "WHATSAPP_PROVIDER": "fake",
            "DRIVE_PROVIDER": "fake",
            "GMAIL_CREDENTIALS_FILE": "",
            "GMAIL_SEND_CREDENTIALS_FILE": "",
            "GMAIL_REPLY_SEND_CREDENTIALS_FILE": "",
            "DRIVE_CREDENTIALS_FILE": "",
        }.items():
            os.environ[name] = value


@pytest.hookimpl(trylast=True)  # after -k / -m deselection: only the selected live tests' settings are required
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    live = bool(config.getoption("--live"))
    keep = [item for item in items if (item.get_closest_marker("live") is not None) == live]
    if len(keep) != len(items):
        config.hook.pytest_deselected(items=[item for item in items if item not in keep])
        items[:] = keep
    if live:
        from tests.live.requirements import exit_if_missing

        for item in keep:  # only live tests reach the network; everything else stays socket-free
            item.add_marker(pytest.mark.enable_socket)

        markers = [item.get_closest_marker("live") for item in keep]
        exit_if_missing([str(name) for marker in markers if marker is not None for name in marker.args])
