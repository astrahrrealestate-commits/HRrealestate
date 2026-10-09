"""Guards that import-linter cannot express (it skips ancestor packages of forbidden modules)."""

import ast
from pathlib import Path

import pytest

from app.core.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "package",
    [
        "app/channels/__init__.py",
        "app/channels/whatsapp/__init__.py",
        "app/channels/gmail/__init__.py",
        "app/channels/google_chat/__init__.py",
    ],
)
def test_channel_package_inits_import_nothing(package: str) -> None:
    tree = ast.parse((ROOT / package).read_text())
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)]


def test_global_settings_hold_no_send_capable_credentials() -> None:
    fields = set(Settings.model_fields)
    assert not {f for f in fields if "media_token" in f or "access_token" in f or f.startswith("gmail_send")}
