"""#9 wiring: `documents.file_document` workflow. A transient failure sending the review card is retried (N9)."""

from collections.abc import Callable, Iterator
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import Engine

from app.core.errors import EstateOSError
from app.ingestion.process import IngestDeps
from app.storage.drive import MemoryDrive
from app.storage.memory import MemoryStorage
from app.workflows import documents
from app.workflows.deps import set_deps, set_drive
from tests.integration.test_documents import _attachment

pytestmark = pytest.mark.integration


class ProviderBlipError(EstateOSError):
    retryable = True


@pytest.fixture
def storage(dbos_runtime: None, migrated_engine: Engine) -> Iterator[MemoryStorage]:
    store = MemoryStorage()
    set_deps(IngestDeps(migrated_engine, store, cast(Any, None), lambda a: None, lambda p: None, "t"))  # type: ignore[arg-type, return-value]
    set_drive(MemoryDrive())
    yield store
    set_drive(None)
    set_deps(None)


def _flaky(failures: int) -> tuple[list[str], Callable[..., bool]]:
    calls: list[str] = []

    def send(company_id: str, key: str, build: object) -> bool:
        calls.append(key)
        if len(calls) <= failures:
            raise ProviderBlipError("whatsapp 503")
        return True

    return calls, send


def test_review_card_survives_a_transient_send_failure(
    storage: MemoryStorage, migrated_engine: Engine, committed_company: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    company_id: UUID = committed_company.id
    att = _attachment(migrated_engine, company_id, storage, "IMG_2041.jpg", "image/jpeg", b"\xff\xd8" + b"j" * 40_000)
    calls, send = _flaky(failures=1)
    monkeypatch.setattr(documents, "send_owner_message", send)
    assert documents.file_document_wf(str(company_id), str(att), None) == "review"
    assert calls == [f"docreview:{att}", f"docreview:{att}"]  # retried once, same idempotency key
