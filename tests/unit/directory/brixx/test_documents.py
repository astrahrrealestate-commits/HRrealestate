"""BRIXX document download to object storage: keys, content addressing, idempotent re-store (no database)."""

import hashlib
from uuid import UUID

import pytest
import structlog

from app.channels.brixx.fake import FakeBrixxApi
from app.core.errors import BrixxAuthError, BrixxError
from app.directory.brixx.documents import CONTENT_TYPE, document_key, fetch_and_store, is_document_table
from app.storage.memory import MemoryStorage
from app.storage.ports import StoredObject

COMPANY = UUID("018f0000-0000-7000-8000-000000000001")
PDF = b"%PDF-1.7 tenant passport scan"
SHA = hashlib.sha256(PDF).hexdigest()


class CountingStorage(MemoryStorage):
    def __init__(self) -> None:
        super().__init__()
        self.puts: list[str] = []

    def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        self.puts.append(key)
        return super().put(key, data, content_type)


def test_key_is_deterministic_per_company_document_and_content() -> None:
    assert document_key(COMPANY, 42, SHA) == f"brixx/{COMPANY}/documents/42/{SHA}"


@pytest.mark.parametrize("bad_id", [0, -1, True])
def test_key_rejects_invalid_document_ids(bad_id: int) -> None:
    with pytest.raises(BrixxError):
        document_key(COMPANY, bad_id, SHA)


@pytest.mark.parametrize("bad_sha", ["", "A" * 64, "a" * 63, "../" + "a" * 61])
def test_key_rejects_anything_but_a_sha256_hex_digest(bad_sha: str) -> None:
    with pytest.raises(ValueError):
        document_key(COMPANY, 42, bad_sha)


def test_fetch_and_store_puts_the_bytes_under_their_content_key() -> None:
    api, storage = FakeBrixxApi({}, documents={42: PDF}), CountingStorage()

    stored = fetch_and_store(api, storage, COMPANY, 42)

    assert stored == StoredObject(document_key(COMPANY, 42, SHA), len(PDF), SHA, CONTENT_TYPE)
    assert storage.get(stored.key) == PDF
    assert api.download_log == [42]


def test_same_bytes_again_store_no_second_object() -> None:
    api, storage = FakeBrixxApi({}, documents={42: PDF}), CountingStorage()
    first = fetch_and_store(api, storage, COMPANY, 42)

    again = fetch_and_store(api, storage, COMPANY, 42)

    assert again == first
    assert storage.puts == [first.key]


def test_changed_bytes_get_their_own_object() -> None:
    api, storage = FakeBrixxApi({}, documents={42: PDF}), CountingStorage()
    first = fetch_and_store(api, storage, COMPANY, 42)
    api = FakeBrixxApi({}, documents={42: PDF + b" v2"})

    second = fetch_and_store(api, storage, COMPANY, 42)

    assert second.key != first.key
    assert storage.get(first.key) == PDF  # the older version is kept
    assert len(storage.puts) == 2


def test_forbidden_download_raises_auth_error_and_stores_nothing() -> None:
    api, storage = FakeBrixxApi({}, documents={42: PDF}), CountingStorage()
    api.fail_download(42, BrixxAuthError("BRIXX rejected the token (HTTP 403)"))

    with pytest.raises(BrixxAuthError):
        fetch_and_store(api, storage, COMPANY, 42)
    assert storage.puts == []


def test_nothing_about_the_file_is_logged() -> None:
    api, storage = FakeBrixxApi({}, documents={42: PDF}), CountingStorage()
    with structlog.testing.capture_logs() as logs:
        fetch_and_store(api, storage, COMPANY, 42)
    assert all(PDF.decode() not in str(entry) for entry in logs)


@pytest.mark.parametrize(
    ("name", "expected"), [("PRG_DOCUMENT", True), ("prg_document", True), ("PRG_DOCUMENTLINK", False)]
)
def test_only_the_document_table_triggers_downloads(name: str, expected: bool) -> None:
    assert is_document_table(name) is expected
