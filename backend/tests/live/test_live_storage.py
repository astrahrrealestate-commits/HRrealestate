"""S3 go-live check: the configured bucket accepts, returns and reports one small object (overwritten each run)."""

import pytest

from app.core.settings import Settings
from app.storage.factory import build_storage


@pytest.mark.live("S3_BUCKET")
def test_bucket_round_trip(live_settings: Settings) -> None:
    storage = build_storage(live_settings.model_copy(update={"storage_backend": "s3"}))
    stored = storage.put("live-check/probe.txt", b"estateos live-check", "text/plain")
    assert stored.size == len(b"estateos live-check")
    assert storage.exists("live-check/probe.txt")
    assert storage.get("live-check/probe.txt") == b"estateos live-check"
