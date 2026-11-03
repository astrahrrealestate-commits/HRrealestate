"""Dashboard API: the owner's writing persona (a markdown file the draft agent writes in).

Harjot reads it, edits it or uploads a replacement here; the next drafts use it and say so on the draft card.
Company comes from the session (invariant 4). The text is never run as instructions: the proposer only sees it as data
inside a `<persona>` block.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import get_engine
from app.api.v1.auth import Principal, require_csrf, require_principal
from app.context import persona
from app.db.models import OwnerPersona
from app.llm.agents.proposer import MAX_PERSONA_CHARS

router = APIRouter(prefix="/persona", tags=["persona"])

Owner = Annotated[Principal, Depends(require_principal)]
Engine_ = Annotated[Engine, Depends(get_engine)]


class PersonaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    filename: str | None
    content: str
    version: int
    is_default: bool
    updated_at: AwareDatetime
    max_chars: int = MAX_PERSONA_CHARS


class PersonaIn(BaseModel):
    content: str = Field(max_length=4 * MAX_PERSONA_CHARS)  # the exact limit is checked after trimming
    name: str | None = Field(default=None, max_length=200)
    filename: str | None = Field(default=None, max_length=300)


def _out(row: OwnerPersona) -> PersonaOut:
    return PersonaOut.model_validate(row)


@router.get("", response_model=PersonaOut)
def get_persona(who: Owner, engine: Engine_) -> PersonaOut:
    with Session(engine) as session, session.begin():
        return _out(persona.get_persona_row(session, who.company_id))


@router.put("", response_model=PersonaOut, dependencies=[Depends(require_csrf)])
def put_persona(body: PersonaIn, who: Owner, engine: Engine_) -> PersonaOut:
    try:
        with Session(engine) as session, session.begin():
            row = persona.save_persona(session, who.company_id, body.content, body.name, body.filename)
            return _out(row)
    except persona.InvalidPersonaError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/reset", response_model=PersonaOut, dependencies=[Depends(require_csrf)])
def reset_persona(who: Owner, engine: Engine_) -> PersonaOut:
    with Session(engine) as session, session.begin():
        return _out(persona.reset_persona(session, who.company_id))
