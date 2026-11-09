"""GET /api/inbox/attachments/{id}: scoped to the signed-in owner's company, never active content on the API origin."""

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.v1.auth import Principal
from app.core.settings import Settings
from app.db.models import (
    ActionRow,
    Approval,
    AttachmentRow,
    Case,
    CaseEvent,
    CaseLink,
    Company,
    MessageRow,
    OwnerFeed,
    RawEvent,
    Send,
    TaskRow,
    UnderstandingRow,
)  # fmt: skip
from app.db.models.pipeline import ActionRevision
from app.main import create_app
from app.storage.memory import MemoryStorage
from tests.api_auth import as_owner
from tests.integration.test_inbox_maintenance_approve import _seed

pytestmark = pytest.mark.integration
PDF = b"%PDF-1.7 lease"


@dataclass
class Files:
    client: TestClient
    mine: dict[str, UUID]
    theirs: UUID


def _company(
    engine: Engine, storage: MemoryStorage, name: str, files: dict[str, tuple[str, str, bytes]]
) -> tuple[UUID, dict[str, UUID]]:
    ids: dict[str, UUID] = {}
    with Session(engine) as s:
        company = Company(name=name)
        s.add(company)
        s.flush()
        company_id = company.id
        _seed(s, company, suspicious=False)
        message_id = s.scalars(select(MessageRow.id).where(MessageRow.company_id == company_id)).one()
        for label, (mime, filename, data) in files.items():
            key = f"att/{company_id}/{label}"
            storage.put(key, data, mime)
            row = AttachmentRow(
                company_id=company_id, message_id=message_id, s3_key=key, mime_type=mime, filename=filename,
                size_bytes=len(data), sha256=uuid4().hex + uuid4().hex,
            )  # fmt: skip
            s.add(row)
            s.flush()
            ids[label] = row.id
        s.commit()
    return company_id, ids


def _purge(engine: Engine, company_id: UUID) -> None:
    with Session(engine) as s:
        for model in (
            AttachmentRow, OwnerFeed, ActionRevision, UnderstandingRow, CaseLink, MessageRow, RawEvent, Approval, Send,
            TaskRow, ActionRow, CaseEvent, Case,
        ):  # fmt: skip
            s.query(model).filter(model.company_id == company_id).delete(synchronize_session=False)
        s.query(Company).filter(Company.id == company_id).delete()
        s.commit()


@pytest.fixture
def files(migrated_engine: Engine, pg_url: str) -> Iterator[Files]:
    storage = MemoryStorage()
    mine_company, mine = _company(
        migrated_engine, storage, "Files A",
        {
            "pdf": ("application/pdf", "lease.pdf", PDF),
            "html": ("text/html", 'evil".html', b"<script>alert(1)</script>"),
            "svg": ("image/svg+xml", "x.svg", b"<svg onload=alert(1)/>"),
            "png": ("image/png", "scan.png", b"\x89PNG"),
        },
    )  # fmt: skip
    their_company, theirs = _company(migrated_engine, storage, "Files B", {"pdf": ("application/pdf", "b.pdf", PDF)})
    settings = Settings(database_url=pg_url, env="test", _env_file=None)  # type: ignore[call-arg]
    owner = Principal(company_id=mine_company, owner_id=uuid4(), email="harjot@example.test")
    app = as_owner(create_app(settings, engine=migrated_engine, workflow_client=None, storage=storage), owner)
    with TestClient(app) as client:
        yield Files(client, mine, theirs["pdf"])
    _purge(migrated_engine, mine_company)
    _purge(migrated_engine, their_company)


def _get(f: Files, label: str) -> tuple[int, dict[str, str], bytes]:
    r = f.client.get(f"/api/inbox/attachments/{f.mine[label]}")
    return r.status_code, dict(r.headers), r.content


def test_another_companys_attachment_is_not_found(files: Files) -> None:
    assert files.client.get(f"/api/inbox/attachments/{files.theirs}").status_code == 404


def test_the_owners_own_pdf_still_opens_in_the_browser(files: Files) -> None:
    status, headers, body = _get(files, "pdf")
    assert (status, body) == (200, PDF)
    assert headers["content-type"] == "application/pdf"
    assert headers["content-disposition"].startswith("inline")
    assert headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("label", ["html", "svg"])
def test_active_content_is_never_rendered_on_the_api_origin(files: Files, label: str) -> None:
    status, headers, _ = _get(files, label)
    assert status == 200
    assert headers["content-type"] == "application/octet-stream"
    assert headers["content-disposition"].startswith("attachment")
    assert headers["x-content-type-options"] == "nosniff"


def test_a_hostile_filename_cannot_break_out_of_the_header(files: Files) -> None:
    _, headers, _ = _get(files, "html")
    disposition = headers["content-disposition"]
    assert '"evil"' not in disposition
    assert "\n" not in disposition
    assert "filename*=UTF-8''evil%22.html" in disposition
