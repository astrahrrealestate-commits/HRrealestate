"""GDPR erasure purges a person's BRIXX mirror rows, and a re-sync never brings them back (spec 2026-10-31 GDPR)."""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.brixx_erasure import erased_relatie_ids, purge_brixx_relatie
from app.db.enums import PersonKind
from app.db.models import Company, Person
from app.db.models.brixx_directory import BrixxErasedRef
from app.directory.brixx.upsert import upsert_page
from app.pipeline.gdpr import erase_person
from tests.integration.brixx_directory_support import RELATIE, ZRELATIE, history, relatie
from tests.integration.brixx_support import MirrorSchema, mirror_schema
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration

SYNCED = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
Tables = tuple[sa.Table, sa.Table]


@pytest.fixture
def mirror(migrated_engine: Engine) -> Iterator[MirrorSchema]:
    with mirror_schema(migrated_engine) as schema:
        yield schema


@pytest.fixture
def tables(mirror: MirrorSchema) -> Tables:
    return mirror.create(RELATIE), mirror.create(ZRELATIE)


def _seed(mirror: MirrorSchema, tables: Tables, company_id: uuid.UUID) -> uuid.UUID:
    current, past = tables
    with mirror.session() as s:
        people = [relatie(41, "Anna Testperson"), relatie(42, "Bram Example")]
        upsert_page(s, current, RELATIE, company_id, people, SYNCED)
        upsert_page(s, past, ZRELATIE, company_id, [history(1, 42, "Bram Old"), history(2, 41, "Anna Old")], SYNCED)
        person = Person(
            company_id=company_id,
            kind=PersonKind.tenant,
            display_name="Bram Example",
            brixx_ref="42",
            valid_from=date(2026, 1, 5),
        )
        s.add(person)
        s.commit()
        return person.id


def _ids(mirror: MirrorSchema, table: sa.Table, company_id: uuid.UUID) -> list[int]:
    with mirror.session() as s:
        query = sa.select(table.c.prg_relatieid).where(table.c.company_id == company_id).order_by("prg_relatieid")
        return list(s.scalars(query))


def test_erasure_purges_mirror_rows_and_resync_never_resurrects_them(
    mirror: MirrorSchema, tables: Tables, committed_company: Company
) -> None:
    cid = committed_company.id
    person_id = _seed(mirror, tables, cid)

    with mirror.session() as s:
        report = erase_person(s, cid, person_id)
        s.commit()

    current, past = tables
    assert report.brixx_rows_purged == 2
    assert _ids(mirror, current, cid) == [41]
    assert _ids(mirror, past, cid) == [41]
    with mirror.session() as s:
        assert erased_relatie_ids(s, cid) == {42}
        person = s.get(Person, person_id)
        assert person is not None
        assert person.brixx_ref is None

    with mirror.session() as s:  # the next incremental sync delivers the erased relatie again
        again = [relatie(42, "Bram Example", version=3), relatie(41, "Anna B", version=2)]
        result = upsert_page(s, current, RELATIE, cid, again, SYNCED)
        upsert_page(s, past, ZRELATIE, cid, [history(3, 42, "Bram Again")], SYNCED)
        s.commit()
    assert result.written == 1
    assert _ids(mirror, current, cid) == [41]
    assert _ids(mirror, past, cid) == [41]


def test_purge_is_idempotent_and_tenant_scoped(
    mirror: MirrorSchema, tables: Tables, committed_company: Company, migrated_engine: Engine
) -> None:
    cid = committed_company.id
    _seed(mirror, tables, cid)
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other BV")
        s.add(other)
        s.commit()
    try:
        with mirror.session() as s:
            upsert_page(s, tables[0], RELATIE, other.id, [relatie(42, "Someone Else")], SYNCED)
            s.commit()
        purged = []
        for _ in range(2):
            with mirror.session() as s:
                purged.append(purge_brixx_relatie(s, cid, 42))
                s.commit()
        assert purged == [2, 0]
        with mirror.session() as s:
            count = sa.select(sa.func.count()).select_from(BrixxErasedRef).where(BrixxErasedRef.company_id == cid)
            assert s.scalar(count) == 1
            assert erased_relatie_ids(s, other.id) == set()
        assert _ids(mirror, tables[0], other.id) == [42]
    finally:
        purge_company(migrated_engine, other.id)


def test_purge_without_mirror_tables_still_records_the_tombstone(
    committed_company: Company, migrated_engine: Engine
) -> None:
    cid = committed_company.id
    with Session(migrated_engine) as s:  # no `brixx` schema in this database (the Phase B migration creates it)
        assert purge_brixx_relatie(s, cid, 77) == 0
        s.commit()
        assert erased_relatie_ids(s, cid) == {77}
