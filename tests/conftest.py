"""Shared fixtures for unit and integration tests."""

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
