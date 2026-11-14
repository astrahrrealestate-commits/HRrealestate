"""Translate-on-demand with a Postgres cache: one model run per distinct text, direction and company (ADR 0011)."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.core.language import Language, detect_language
from app.core.texthash import normalise, source_hash
from app.db.models.translation import Translation
from app.translation.ports import Translator
from app.translation.text import translate_text

# A direction translates exactly one source language; any other detected language is left alone.
SOURCE_FOR_TARGET: dict[str, Language] = {"en": "nl", "nl": "en"}


@dataclass(frozen=True)
class Translated:
    text: str
    cached: bool
    language: Language


def lookup_translations(session: Session, company_id: UUID, texts: list[str], target: str = "en") -> dict[str, str]:
    """`{source_hash(text): translation}` for the texts already translated into `target`; one query, no model."""
    hashes = {source_hash(t) for t in texts if t.strip()}
    if not hashes:
        return {}
    rows = session.execute(
        select(Translation.source_hash, Translation.text_translated).where(
            Translation.company_id == company_id,
            Translation.source_hash.in_(hashes),
            Translation.target_lang == target,
        )
    ).all()
    return {row.source_hash: row.text_translated for row in rows}


def cached_translations(engine: Engine, company_id: UUID, texts: list[str], target: str = "en") -> dict[str, str]:
    with Session(engine) as session:
        return lookup_translations(session, company_id, texts, target)


def translate_cached(
    engine: Engine, translator: Translator, company_id: UUID, text: str, target: str = "en"
) -> Translated | None:
    """The `target`-language text for `text`, from the cache or the model; None when the text is not in the one
    source language this direction translates (Dutch for English, English for Dutch).

    The model runs outside any database transaction (it takes tenths of a second); the insert is idempotent, so two
    requests for the same text at once both succeed.
    """
    clean = normalise(text)
    language = detect_language(clean)
    if language != SOURCE_FOR_TARGET.get(target):
        return None
    key = source_hash(clean)
    hit = cached_translations(engine, company_id, [clean], target)
    if key in hit:
        return Translated(hit[key], cached=True, language=language)
    translated = translate_text(translator, clean)
    with Session(engine) as session:
        session.execute(
            insert(Translation)
            .values(
                id=new_id(),
                company_id=company_id,
                source_hash=key,
                source_lang=language,
                target_lang=target,
                text_translated=translated,
                engine=translator.engine,
            )
            .on_conflict_do_nothing(index_elements=["company_id", "source_hash", "target_lang"])
        )
        session.commit()
    return Translated(translated, cached=False, language=language)
