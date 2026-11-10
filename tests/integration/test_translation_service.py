"""Translation cache against real Postgres: one model run per distinct text and company, English skipped."""

from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.db.models import Company
from app.db.models.translation import Translation
from app.translation.service import cached_translations, source_hash, translate_cached

pytestmark = pytest.mark.integration

DUTCH = "Goedemorgen, de verwarming werkt niet meer."


class CountingTranslator:
    engine = "fake-nl-en"

    def __init__(self) -> None:
        self.segments: list[str] = []

    def translate(self, segments: list[str]) -> list[str]:
        self.segments.extend(segments)
        return [f"EN({s})" for s in segments]


@pytest.fixture
def companies(migrated_engine: Engine) -> Iterator[tuple[UUID, UUID]]:
    with Session(migrated_engine) as s:
        a, b = Company(name="A"), Company(name="B")
        s.add_all([a, b])
        s.commit()
        ids = (a.id, b.id)
    yield ids
    with Session(migrated_engine) as s:
        s.query(Translation).filter(Translation.company_id.in_(ids)).delete(synchronize_session=False)
        s.query(Company).filter(Company.id.in_(ids)).delete(synchronize_session=False)
        s.commit()


def test_dutch_text_is_translated_and_stored(migrated_engine: Engine, companies: tuple[UUID, UUID]) -> None:
    a, _ = companies
    tr = CountingTranslator()
    result = translate_cached(migrated_engine, tr, a, DUTCH)
    assert result is not None
    assert (result.text_en, result.cached, result.language) == (f"EN({DUTCH})", False, "nl")
    with Session(migrated_engine) as s:
        row = s.scalars(select(Translation).where(Translation.company_id == a)).one()
    assert (row.text_en, row.engine, row.source_lang) == (f"EN({DUTCH})", "fake-nl-en", "nl")


def test_second_request_for_same_text_does_not_run_the_model(
    migrated_engine: Engine, companies: tuple[UUID, UUID]
) -> None:
    a, _ = companies
    tr = CountingTranslator()
    translate_cached(migrated_engine, tr, a, DUTCH)
    again = translate_cached(migrated_engine, tr, a, f"  {DUTCH}\n")  # whitespace is not a different text
    assert again is not None
    assert again.cached is True
    assert tr.segments == [DUTCH]


def test_cache_is_per_company(migrated_engine: Engine, companies: tuple[UUID, UUID]) -> None:
    a, b = companies
    tr = CountingTranslator()
    translate_cached(migrated_engine, tr, a, DUTCH)
    assert cached_translations(migrated_engine, b, [DUTCH]) == {}
    translate_cached(migrated_engine, tr, b, DUTCH)
    assert tr.segments == [DUTCH, DUTCH]
    with Session(migrated_engine) as s:
        assert s.scalar(select(func.count()).select_from(Translation).where(Translation.company_id.in_(companies))) == 2


def test_english_text_is_not_translated_or_stored(migrated_engine: Engine, companies: tuple[UUID, UUID]) -> None:
    a, _ = companies
    tr = CountingTranslator()
    assert translate_cached(migrated_engine, tr, a, "Thanks, the heating works again.") is None
    assert tr.segments == []
    assert cached_translations(migrated_engine, a, ["Thanks, the heating works again."]) == {}


def test_cached_translations_maps_texts_in_one_query(migrated_engine: Engine, companies: tuple[UUID, UUID]) -> None:
    a, _ = companies
    tr = CountingTranslator()
    translate_cached(migrated_engine, tr, a, DUTCH)
    found = cached_translations(migrated_engine, a, [DUTCH, "Onbekende tekst over de huur."])
    assert found == {source_hash(DUTCH): f"EN({DUTCH})"}


def test_cached_translations_are_keyed_by_hash_so_whitespace_variants_both_resolve(
    migrated_engine: Engine, companies: tuple[UUID, UUID]
) -> None:
    a, _ = companies
    translate_cached(migrated_engine, CountingTranslator(), a, DUTCH)
    found = cached_translations(migrated_engine, a, [DUTCH, f"{DUTCH}\n"])
    assert found == {source_hash(DUTCH): f"EN({DUTCH})"}


def test_text_that_is_not_dutch_is_not_translated_or_stored(
    migrated_engine: Engine, companies: tuple[UUID, UUID]
) -> None:
    a, _ = companies
    tr = CountingTranslator()
    assert translate_cached(migrated_engine, tr, a, "Bonjour, le chauffage ne marche pas.") is None
    assert tr.segments == []
