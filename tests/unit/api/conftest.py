"""API unit tests run without a database: the per-request owner re-check is patched to "still there".
Tests of the re-check itself patch it again (the inner patch wins) or call `auth.owner_matches` directly."""

from collections.abc import Iterator
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _owner_row_still_exists() -> Iterator[None]:
    with patch("app.api.v1.auth.owner_matches", return_value=True):
        yield
