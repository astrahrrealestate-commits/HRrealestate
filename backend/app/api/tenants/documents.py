"""A tenant's BRIXX documents: the list for their profile and the file behind each entry.

The Tenants section only (Reports and Dashboard see the rent roll, not files, ADR 0012). The file route re-derives the
tenant's documents on the server and serves only a document that is one of them, so a document id from anywhere else
(another tenant, another company) is a 404. A file is served from our object storage, never fetched from BRIXX on the
request. Names and types come from BRIXX and are untrusted: only PDF and image types are shown inline, everything else
is a download, always with `nosniff` and a sandboxing CSP.
"""

import mimetypes
import re
import urllib.parse
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import get_engine, get_storage
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_session
from app.directory.brixx.tenant_documents import TenantDocument, tenant_documents
from app.storage.ports import ObjectStorage

router = APIRouter(prefix="/api/tenants", tags=["tenants"], dependencies=[Depends(require_section("tenants"))])

INLINE_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp"})
MAX_FILE_BYTES = 50 * 1024 * 1024
_UNSAFE_NAME = re.compile(r'[\x00-\x1f\x7f"\\/]')


class TenantDocumentItem(BaseModel):
    id: str
    title: str
    fileName: str
    category: str = Field(description="BRIXX's own label for the document")
    source: str = Field(description="Tenant, Contract, Unit or Building: what the document is attached to in BRIXX")
    sizeBytes: int | None = None
    addedOn: str | None = Field(default=None, description="dd-mm-yyyy")
    available: bool = Field(description="False until the file has been downloaded from BRIXX into storage")
    url: str | None = Field(default=None, description="Path of the file on this API; null while not available")


class TenantDocumentsResponse(BaseModel):
    documents: list[TenantDocumentItem]
    total: int
    available: int


def _item(tenant_id: UUID, doc: TenantDocument) -> TenantDocumentItem:
    return TenantDocumentItem(
        id=str(doc.document_id),
        title=doc.title,
        fileName=doc.file_name,
        category=doc.category,
        source=doc.source,
        sizeBytes=doc.size_bytes,
        addedOn=f"{doc.added_on:%d-%m-%Y}" if doc.added_on else None,
        available=doc.available,
        url=f"/api/tenants/{tenant_id}/documents/{doc.document_id}/file" if doc.available else None,
    )


def _found(session: Session, principal: Principal, tenant_id: str) -> tuple[UUID, list[TenantDocument]]:
    try:
        wanted = UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Tenant not found") from None
    docs = tenant_documents(session, principal.company_id, wanted)
    if docs is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return wanted, docs


@router.get(
    "/{tenant_id}/documents",
    response_model=TenantDocumentsResponse,
    summary="List a tenant's BRIXX documents",
    description="Documents BRIXX attaches to the tenant, their contracts, their units and the buildings, newest first.",
)
def list_tenant_documents(
    tenant_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> TenantDocumentsResponse:
    with Session(engine) as session:
        wanted, docs = _found(session, principal, tenant_id)
    items = [_item(wanted, doc) for doc in docs]
    return TenantDocumentsResponse(documents=items, total=len(items), available=sum(i.available for i in items))


def _download_name(doc: TenantDocument) -> str:
    return _UNSAFE_NAME.sub("_", doc.file_name).strip()[:200] or f"document-{doc.document_id}"


@router.get(
    "/{tenant_id}/documents/{document_id}/file",
    summary="Download or view one of a tenant's BRIXX documents",
    description="409 while the file has not been downloaded from BRIXX yet.",
)
def get_tenant_document_file(
    tenant_id: str,
    document_id: int,
    engine: Annotated[Engine, Depends(get_engine)],
    storage: Annotated[ObjectStorage, Depends(get_storage)],
    principal: Annotated[Principal, Depends(require_session)],
) -> Response:
    with Session(engine) as session:
        _, docs = _found(session, principal, tenant_id)
    doc = next((d for d in docs if d.document_id == document_id), None)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.storage_key is None:
        raise HTTPException(status_code=409, detail="This file has not been downloaded from BRIXX yet")
    if doc.size_bytes is not None and doc.size_bytes > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="This file is too large to open here")
    try:
        content = storage.get(doc.storage_key)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="File not found in storage") from exc
    name = _download_name(doc)
    disposition = "inline" if mimetypes.guess_type(name)[0] in INLINE_TYPES else "attachment"
    mime = (mimetypes.guess_type(name)[0] or "application/octet-stream").lower()
    inline = mime in INLINE_TYPES
    return Response(
        content=content,
        media_type=mime if inline else "application/octet-stream",
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{urllib.parse.quote(name)}",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Cache-Control": "private, no-store",
        },
    )
