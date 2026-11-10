"""Dutch to English on demand (ADR 0011): translate one text, and mark thread messages/drafts with what is cached."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import get_engine, get_translator
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


@router.post(
    "/translate",
    dependencies=[Depends(translate_limit)],
    summary="Translate Dutch text to English (local model, cached)",
    description="The model runs once per distinct text and company; English text comes back with textEn null.",
)
def translate(
    body: TranslateRequest,
    engine: Annotated[Engine, Depends(get_engine)],
    translator: Annotated[Translator, Depends(get_translator)],
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, Any]:
    try:
        result = translate_cached(engine, translator, principal.company_id, body.text)
    except TranslationUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Translation is not available on this server yet.") from exc
    if result is None:
        return {"language": detect_language(body.text), "textEn": None, "cached": False}
    return {"language": result.language, "textEn": result.text_en, "cached": result.cached}


def annotate_translations(
    session: Session, company_id: UUID, messages: list[dict[str, Any]], drafts: list[dict[str, Any]]
) -> None:
    """Add `language` to every message and draft, and the cached English (`bodyEnglish` / `englishMeaning`) where it
    exists. Reads the cache only: listing a thread never runs the model, and only Dutch texts are looked up."""
    for item, key in [(m, "body") for m in messages] + [(d, "text") for d in drafts]:
        item["language"] = detect_language(item[key])
    dutch = [i[k] for i, k in [(m, "body") for m in messages] + [(d, "text") for d in drafts] if i["language"] == "nl"]
    cache = lookup_translations(session, company_id, dutch)
    for message in messages:
        if (english := cache.get(source_hash(message["body"]))) is not None and message["language"] == "nl":
            message["bodyEnglish"] = english
    for draft in drafts:
        if (english := cache.get(source_hash(draft["text"]))) is not None and draft["language"] == "nl":
            draft["englishMeaning"] = english
