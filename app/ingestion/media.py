"""Store inbound media/attachments content-addressed per company (same bytes → same key, stored once)."""

import hashlib
from dataclasses import dataclass
from uuid import UUID

from app.channels.text_clean import clean_filename, clean_mime
from app.storage.ports import ObjectStorage, content_key


@dataclass(frozen=True)
class AttachmentInput:
    s3_key: str
    mime_type: str
    filename: str | None
    size_bytes: int
    sha256: str


def store_attachment(
    storage: ObjectStorage, company_id: UUID, data: bytes, mime_type: str, filename: str | None
) -> AttachmentInput:
    mime_type, filename = clean_mime(mime_type), clean_filename(filename)  # provider-supplied: bounded and clean
    sha256 = hashlib.sha256(data).hexdigest()
    key = content_key(company_id, sha256)
    if not storage.exists(key):
        storage.put(key, data, mime_type)
    return AttachmentInput(s3_key=key, mime_type=mime_type, filename=filename, size_bytes=len(data), sha256=sha256)
