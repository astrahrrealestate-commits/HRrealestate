"""What the engine is given per document: the verified read, or none when the document could not be read."""

from dataclasses import dataclass
from uuid import UUID

from app.contracts.diligence import DDDocRead


@dataclass(frozen=True)
class DocInput:
    document_id: UUID
    title: str  # the library title, shown when there is no read
    read: DDDocRead | None  # None: no text, an identity document, or the reader failed
