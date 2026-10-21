"""Split a document's extracted text into searchable chunks (M10). Pure, plus one idempotent insert."""

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import DocumentChunk

CHUNK_CHARS = 3200  # about 800 tokens
MIN_TAIL = 400  # a shorter last piece is merged into the previous chunk


def chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Paragraph-aware split: chunks are at most `size` characters, never empty, in reading order."""
    pieces: list[str] = []
    current = ""
    for paragraph in (p.strip() for p in text.split("\n\n")):
        while len(paragraph) > size:  # one huge paragraph: cut on whitespace near the limit
            cut = paragraph.rfind(" ", 0, size)
            if cut <= 0:
                cut = size
            if current:
                pieces.append(current)
                current = ""
            pieces.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        if not paragraph:
            continue
        if current and len(current) + len(paragraph) + 2 > size:
            pieces.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        pieces.append(current)
    if len(pieces) > 1 and len(pieces[-1]) < MIN_TAIL and len(pieces[-2]) + len(pieces[-1]) + 2 <= size:
        pieces[-2:] = [f"{pieces[-2]}\n\n{pieces[-1]}"]
    return [p for p in pieces if p]


def store_chunks(session: Session, company_id: UUID, document_id: UUID, text: str) -> int:
    """Insert the chunks inside the caller's transaction; a repeat is a no-op (unique document_id + ord)."""
    rows = [
        {"company_id": company_id, "document_id": document_id, "ord": i, "text": piece}
        for i, piece in enumerate(chunk_text(text))
    ]
    if rows:
        session.execute(
            insert(DocumentChunk).values(rows).on_conflict_do_nothing(index_elements=["document_id", "ord"])
        )
    return len(rows)
