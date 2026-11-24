from pathlib import Path
from urllib.parse import parse_qs, urlparse

import boto3
import pytest

from app.storage.local import LocalStorage
from app.storage.memory import MemoryStorage
from app.storage.ports import MAX_PRESIGN_TTL_S
from app.storage.s3 import S3Storage


def _expires(url: str, name: str) -> int:
    return int(parse_qs(urlparse(url).query)[name][0])


def test_memory_clamps_ttl() -> None:
    url = MemoryStorage().presigned_url("media/a/b", 99999)
    assert _expires(url, "expires_in") == MAX_PRESIGN_TTL_S


def test_local_clamps_ttl(tmp_path: Path) -> None:
    assert _expires(LocalStorage(tmp_path).presigned_url("media/a", 0), "expires_in") == 1


def test_s3_presign_is_local_and_clamped() -> None:
    client = boto3.client("s3", region_name="eu-central-1", aws_access_key_id="k", aws_secret_access_key="s")
    url = S3Storage(client, "bucket").presigned_url("media/a/b", 3600)
    assert _expires(url, "X-Amz-Expires") == MAX_PRESIGN_TTL_S


def test_invalid_key_rejected() -> None:
    with pytest.raises(ValueError):
        MemoryStorage().presigned_url("../x", 10)


def test_local_url_is_relative_and_hides_server_path(tmp_path: Path) -> None:
    url = LocalStorage(tmp_path).presigned_url("media/a/b", 60)
    assert url.startswith("/dev-storage/media/a/b?")
    assert str(tmp_path) not in url


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def test_memory_presign_carries_forced_type_and_disposition() -> None:
    url = MemoryStorage().presigned_url(
        "media/a/b", 60, content_type="application/octet-stream", disposition="attachment; filename*=UTF-8''x"
    )
    query = _query(url)
    assert query["response-content-type"] == ["application/octet-stream"]
    assert query["response-content-disposition"] == ["attachment; filename*=UTF-8''x"]
    assert _expires(url, "expires_in") == 60


def test_local_presign_carries_forced_type_and_disposition(tmp_path: Path) -> None:
    url = LocalStorage(tmp_path).presigned_url("media/a/b", 60, content_type="image/png", disposition="inline")
    assert _query(url)["response-content-type"] == ["image/png"]
    assert _query(url)["response-content-disposition"] == ["inline"]


def test_s3_presign_signs_the_response_overrides() -> None:
    client = boto3.client("s3", region_name="eu-central-1", aws_access_key_id="k", aws_secret_access_key="s")
    url = S3Storage(client, "bucket").presigned_url(
        "media/a/b", 60, content_type="application/octet-stream", disposition="attachment"
    )
    query = _query(url)
    assert query["response-content-type"] == ["application/octet-stream"]
    assert query["response-content-disposition"] == ["attachment"]


def test_presign_without_overrides_adds_no_response_params() -> None:
    assert "response-content-type" not in _query(MemoryStorage().presigned_url("media/a/b", 60))
