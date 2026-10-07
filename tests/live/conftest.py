"""Live checks build adapters exactly as production does: from Settings (environment + .env)."""

import os

import pytest
from pydantic import ValidationError

from app.core.settings import Settings


@pytest.fixture
def live_settings() -> Settings:
    try:
        return Settings()
    except ValidationError:  # no DATABASE_URL configured: live checks never touch the database
        return Settings(database_url="postgresql+psycopg://unused@localhost/unused")  # type: ignore[arg-type]


@pytest.fixture
def live_mailbox() -> str:
    return os.environ["LIVE_GMAIL_MAILBOX"]
