"""Worker-side translation workflow (offloads CTranslate2 / SentencePiece memory from the API container)."""

from functools import lru_cache
from typing import Any
from uuid import UUID

from dbos import DBOS

from app.core.settings import get_settings
from app.core.workflow_names import TRANSLATE_TEXT
from app.translation.ct2 import Ct2Translator
from app.translation.service import translate_cached
from app.workflows.deps import get_engine


@lru_cache(maxsize=1)
def _worker_translators() -> dict[str, Ct2Translator]:
    settings = get_settings()
    return {
        "en": Ct2Translator(settings.translation_model_dir),
        "nl": Ct2Translator(settings.translation_model_dir_en_nl, engine="opus-mt-en-nl"),
    }


@DBOS.workflow(name=TRANSLATE_TEXT)
def translate_workflow(company_id: str, text: str, target: str) -> dict[str, Any] | None:
    translator = _worker_translators()[target]
    result = translate_cached(get_engine(), translator, UUID(company_id), text, target)
    if result is None:
        return None
    return {"language": result.language, "target": target, "text": result.text, "cached": result.cached}
