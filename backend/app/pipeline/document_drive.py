"""#9 Uploading a planned document to Drive (M10): the file, its description and searchable properties, then `filed`.

The plan (name, folder, reserved Drive id) is already in Postgres. Retries reuse the file Drive has under the
attachment's app property, so a second attempt never uploads a second copy.
"""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from app.core.errors import EstateOSError
from app.core.logging import get_logger
from app.db.enums import DocumentStatus
from app.db.models import DocumentRow
from app.pipeline.document_layout import UNSORTED, description, drive_properties
from app.pipeline.document_policy import name_date, parse_name
from app.storage.drive import CONTENT_PROPERTY, DriveStore, content_value
from app.storage.ports import ObjectStorage

log = get_logger(__name__)


def _unit_and_day(plan: DocumentRow) -> tuple[str | None, date]:
    """The unit folder name and the date the plan already carries (folder `EstateOS/<unit>/<kind>/<year>`)."""
    parts = (plan.drive_folder or "").split("/")
    unit = parts[1] if len(parts) > 1 and parts[1] != UNSORTED else None
    return unit, name_date(plan.file_name) or plan.created_at.date()


def _party_of(name: str) -> str | None:
    """`YYYY-MM-DD_<kind>_<party>_<title>.<ext>`: the party slug, for Drive's own search."""
    parsed = parse_name(name)
    return parsed[2] if parsed and parsed[2] != "unknown" else None


@dataclass(frozen=True)
class ContentKey:
    """The file's content hash, stored on the Drive file. With `reuse` (reloaded mail, M13) a file with the same
    content already in Drive is used instead of a second upload."""

    sha256: str = ""
    reuse: bool = False


def _existing(drive: DriveStore, company_id: UUID, attachment_id: UUID, content: ContentKey) -> str | None:
    file_id = drive.find_by_attachment(attachment_id)
    if file_id is not None or not (content.reuse and content.sha256):
        return file_id
    return drive.find_by_sha256(company_id, content.sha256)


def upload_planned(engine: Engine, drive: DriveStore, storage: ObjectStorage, company_id: UUID, attachment_id: UUID,
                   s3_key: str, mime_type: str, plan: DocumentRow,
                   content: ContentKey | None = None) -> None:  # fmt: skip
    if plan.drive_file_id is None or plan.drive_folder is None:
        raise EstateOSError(f"pending document {plan.id} has no reserved Drive id or folder")
    content = content or ContentKey()
    file_id = _existing(drive, company_id, attachment_id, content)
    if file_id is None:
        folder = drive.ensure_folder(tuple(plan.drive_folder.split("/")))
        unit, day = _unit_and_day(plan)
        props = drive_properties(plan.doc_type, unit, _party_of(plan.file_name), day)
        if content.sha256:
            props[CONTENT_PROPERTY] = content_value(company_id, content.sha256)
        file_id = drive.upload(
            plan.drive_file_id, folder, plan.file_name, mime_type, storage.get(s3_key), attachment_id,
            description=description(plan.title, plan.summary), properties=props,
        )  # fmt: skip
    with Session(engine) as session, session.begin():
        session.execute(
            update(DocumentRow)
            .where(DocumentRow.id == plan.id, DocumentRow.company_id == company_id)
            .where(DocumentRow.status == DocumentStatus.pending)
            .values(status=DocumentStatus.filed, drive_file_id=file_id)
        )
    log.info("documents.filed", attachment_id=str(attachment_id), doc_type=plan.doc_type)
