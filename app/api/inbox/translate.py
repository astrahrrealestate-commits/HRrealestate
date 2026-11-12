"""Translation on demand (ADR 0011): translate one text either way, and mark thread messages/drafts with what is
cached."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import get_engine, get_translators
from app.api.v1.auth import Principal, require_session
from app.api.v1.session_limits import translate_limit
from app.core.errors import TranslationUnavailableError
from app.core.language import detect_language
from app.core.texthash import source_hash
from app.translation.ports import Translator
from app.translation.service import lookup_translations, translate_cached

router = APIRouter()


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    target: Literal["en", "nl"] = "en"


@router.post(
    "/translate",
    dependencies=[Depends(translate_limit)],
    summary="Translate between Dutch and English (local model, cached)",
    description="The model runs once per distinct text, direction and company; text already in the target language "
    "comes back with text null.",
)
def translate(
    body: TranslateRequest,
    engine: Annotated[Engine, Depends(get_engine)],
    translators: Annotated[dict[str, Translator], Depends(get_translators)],
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, Any]:
    try:
        result = translate_cached(engine, translators[body.target], principal.company_id, body.text, body.target)
    except TranslationUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Translation is not available on this server yet.") from exc
    if result is None:
        return {"language": detect_language(body.text), "target": body.target, "text": None, "cached": False}
    return {"language": result.language, "target": body.target, "text": result.text, "cached": result.cached}


def annotate_translations(
    session: Session, company_id: UUID, messages: list[dict[str, Any]], drafts: list[dict[str, Any]]
) -> None:
    """Add `language` to every message and draft, and the cached translation where it exists: English for Dutch
    texts (`bodyEnglish` / `englishMeaning`) and Dutch for English texts (`bodyDutch` / `dutchMeaning`). Reads the
    cache only: listing a thread never runs the model."""
    items = [(m, "body") for m in messages] + [(d, "text") for d in drafts]
    for item, key in items:
        item["language"] = detect_language(item[key])
    dutch = [i[k] for i, k in items if i["language"] == "nl"]
    english = [i[k] for i, k in items if i["language"] == "en"]
    to_en = lookup_translations(session, company_id, dutch, target="en")
    to_nl = lookup_translations(session, company_id, english, target="nl")
    for message in messages:
        if message["language"] == "nl" and (text := to_en.get(source_hash(message["body"]))) is not None:
            message["bodyEnglish"] = text
        if message["language"] == "en" and (text := to_nl.get(source_hash(message["body"]))) is not None:
            message["bodyDutch"] = text
    for draft in drafts:
        if draft["language"] == "nl" and (text := to_en.get(source_hash(draft["text"]))) is not None:
            draft["englishMeaning"] = text
        if draft["language"] == "en" and (text := to_nl.get(source_hash(draft["text"]))) is not None:
            draft["dutchMeaning"] = text
