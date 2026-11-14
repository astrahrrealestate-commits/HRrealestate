"""API unit tests run without a database: the per-request owner re-check is patched to "still there" and the profile
lookup to "full access". Tests of either patch it again (the inner patch wins) or call `auth.owner_matches` /
`auth.access_for` directly."""

from collections.abc import Iterator
from unittest.mock import patch

import pytest

from app.api.v1.sections import Access


@pytest.fixture(autouse=True)
def _owner_row_still_exists() -> Iterator[None]:
    with patch("app.api.v1.auth.owner_matches", return_value=True):
        yield


@pytest.fixture(autouse=True)
def _profile_has_full_access() -> Iterator[None]:
    with patch("app.api.v1.auth.access_for", return_value=Access()):
        yield
