"""ObjectStorage contract: every adapter (memory, local, s3) must behave identically."""

import hashlib
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import boto3
import pytest
from moto import mock_aws

from app.core.errors import NotFoundError
from app.storage.local import LocalStorage
from app.storage.memory import MemoryStorage
from app.storage.ports import ObjectStorage, content_key, validate_key
from app.storage.s3 import S3Storage

COMPANY = UUID("01900000-0000-7000-8000-000000000001")


@pytest.fixture(params=["memory", "local", "s3"])
def storage(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[ObjectStorage]:
    if request.param == "memory":
        yield MemoryStorage()
    elif request.param == "local":
        yield LocalStorage(tmp_path / "store")
    else:
        with mock_aws():
            client = boto3.client("s3", region_name="eu-central-1")
            client.create_bucket(
                Bucket="estateos-test", CreateBucketConfiguration={"LocationConstraint": "eu-central-1"}
            )
            yield S3Storage(client=client, bucket="estateos-test")


def test_put_get_round_trip(storage: ObjectStorage) -> None:
    data = b"%PDF-1.7 Mietvertrag"
    obj = storage.put("media/x/doc.pdf", data, "application/pdf")
    assert obj.key == "media/x/doc.pdf"
    assert obj.size == len(data)
    assert obj.sha256 == hashlib.sha256(data).hexdigest()
    assert obj.content_type == "application/pdf"
    assert storage.get("media/x/doc.pdf") == data
    assert storage.exists("media/x/doc.pdf")


def test_put_same_key_is_idempotent(storage: ObjectStorage) -> None:
    storage.put("k/a", b"same", "text/plain")
    storage.put("k/a", b"same", "text/plain")
    assert storage.get("k/a") == b"same"


def test_missing_key(storage: ObjectStorage) -> None:
    assert not storage.exists("nope/x")
    with pytest.raises(NotFoundError):
        storage.get("nope/x")


@pytest.mark.parametrize("bad", ["", "/abs", "a/../b", "..", "a//b", "a\\b", "a/./b", "a/b/"])
def test_bad_keys_rejected(storage: ObjectStorage, bad: str) -> None:
    with pytest.raises(ValueError):
        storage.put(bad, b"x", "text/plain")
    with pytest.raises(ValueError):
        validate_key(bad)


def test_content_key_is_company_scoped_and_content_addressed() -> None:
    sha = hashlib.sha256(b"x").hexdigest()
    key = content_key(COMPANY, sha)
    assert key == f"media/{COMPANY}/{sha[:2]}/{sha}"
    with pytest.raises(ValueError):
        content_key(COMPANY, "not-a-sha")
