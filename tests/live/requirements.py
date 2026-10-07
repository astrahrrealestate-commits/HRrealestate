"""Which settings a live test needs and which are missing. Values are only checked for presence, never printed."""

import contextlib
import os
from collections.abc import Callable, Iterable, Mapping

import pytest
from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings

from app.channels.whatsapp.media_settings import WhatsAppMediaSettings
from app.core.settings import Settings
from app.sender.settings import SenderSettings

Configured = Callable[[str], bool]


def _present(value: object) -> bool:
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    if isinstance(value, str):
        return value.strip() not in ("", "fake")  # a provider still set to its fake is not configured for live
    return bool(value)  # None, {} and [] are unset


def configured_from(environ: Mapping[str, str], *settings: BaseSettings) -> Configured:
    """`LIVE_*` names come from the shell environment only. Real settings are judged by their parsed value (env or
    .env), so e.g. an exported `WHATSAPP_MEDIA_TOKENS={}` still counts as missing."""

    def configured(name: str) -> bool:
        if name.startswith("LIVE_"):
            return _present(environ.get(name))
        return any(_present(getattr(s, name.lower(), None)) for s in settings)

    return configured


def missing(required: Iterable[str], configured: Configured) -> list[str]:
    return sorted({name for name in required if not configured(name)})


def exit_if_missing(required: Iterable[str]) -> None:
    """Stop the live run before any provider call when settings are missing (exit code 2, names only)."""
    sources: list[BaseSettings] = [SenderSettings(), WhatsAppMediaSettings()]
    with contextlib.suppress(ValidationError):  # e.g. no DATABASE_URL: live checks do not need the database
        sources.append(Settings())
    absent = missing(required, configured_from(os.environ, *sources))
    if absent:
        pytest.exit(f"live-check: missing {', '.join(absent)} (see docs/go-live-channels.md)", returncode=2)
