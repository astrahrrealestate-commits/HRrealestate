"""Dashboard API: global search for the ⌘K palette (people, units, cases, documents).

Read-only and company-scoped through the session principal (invariant 4). Titles come from tenant-derived text and are
returned as data; the SPA renders them as plain text.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import get_engine
from app.api.v1.auth import Principal, require_principal
from app.api.v1.ratelimit import search_limit
from app.db.enums import PersonKind
from app.pipeline.global_search import HitKind, global_search

router = APIRouter(tags=["search"])
Owner = Annotated[Principal, Depends(require_principal)]
Engine_ = Annotated[Engine, Depends(get_engine)]


class SearchHitOut(BaseModel):
    kind: HitKind
    id: UUID
    title: str
    subtitle: str | None
    person_kind: PersonKind | None


class SearchOut(BaseModel):
    hits: list[SearchHitOut]


@router.get("/search", response_model=SearchOut, dependencies=[Depends(search_limit)])
def search(who: Owner, engine: Engine_, q: Annotated[str, Query()] = "") -> SearchOut:
    with Session(engine) as session:
        hits = global_search(session, who.company_id, q)
    return SearchOut(
        hits=[
            SearchHitOut(kind=h.kind, id=h.id, title=h.title, subtitle=h.subtitle, person_kind=h.person_kind)
            for h in hits
        ]
    )
