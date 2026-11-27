"""Erasure of a person's BRIXX library documents (M13). Their chunks and links cascade. The BRIXX tombstone that
`erase_person` writes keeps the backlog from reading them again; a contract shared with a co-tenant is indexed again
for the people still on it."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.enums import DocLinkKind
from app.db.models import DocumentLink, DocumentRow


def erase_brixx_documents(session: Session, company_id: UUID, person_id: UUID) -> int:
    linked = select(DocumentLink.document_id).where(
        DocumentLink.company_id == company_id,
        DocumentLink.kind == DocLinkKind.person,
        DocumentLink.ref_id == person_id,
    )
    res = session.execute(
        delete(DocumentRow).where(
            DocumentRow.company_id == company_id,
            DocumentRow.brixx_document_id.is_not(None),
            DocumentRow.id.in_(linked),
        )
    )
    return int(res.rowcount)  # type: ignore[attr-defined]
