"""BRIXX directory mapper: mirror -> people/identities/units/leases, identity-first upgrade, idempotent, tenant-scoped.

Synthetic mirror rows only (invented names, numbers and addresses).
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.channels.brixx.fake import FakeBrixxApi, FakeTable
from app.contracts import Channel
from app.db.brixx_erasure import purge_brixx_relatie
from app.db.enums import PersonKind
from app.db.models import ChannelIdentity, Company, Lease, LeaseParty, Person, Unit
from app.directory.brixx.mapper import map_directory
from app.directory.brixx.upsert import upsert_page
from app.directory.identity import resolve_person
from app.workflows import brixx_sync
from app.workflows.deps import set_brixx_api
from tests.integration.brixx_directory_support import (
    CONTRACT,
    CONTRACTVHE,
    DIRECTORY_TABLES,
    OBJECT,
    RELATIE,
    VHE,
    contract,
    contract_vhe,
    obj,
    relatie,
    vhe,
)
from tests.integration.brixx_support import MirrorSchema, mirror_schema

pytestmark = pytest.mark.integration

TODAY = date(2026, 11, 3)
SYNCED = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)
PHONE = "+31612345678"  # invented: NL mobile range, normalised as inbound WhatsApp ids are

MIRROR_ROWS = {
    RELATIE.name: [
        relatie(1, "Anna Testperson", mobielnr="06-12345678", email="Anna@Example.test"),
        relatie(2, "Bram Example"),
        relatie(3, "Cor Former", indverwijderd=1),
        relatie(4, "Dirk Erased"),
    ],
    OBJECT.name: [obj(10, "OBJ-10")],
    VHE.name: [vhe(100, 10, "A"), vhe(101, 10, "B", straatnm="Zijstraat", huisnr="2", plaatsnm="Voorbeeldstad")],
    CONTRACT.name: [contract(500, 1, "2026-02-01"), contract(501, 4, "2026-01-01")],
    CONTRACTVHE.name: [
        contract_vhe(900, 500, 100),
        contract_vhe(901, 500, 101, "2026-03-01", indverwijderd=1),
        contract_vhe(902, 501, 100),
        contract_vhe(903, 500, 999),  # unknown VHE: skipped
    ],
}


class Env:
    def __init__(self, mirror: MirrorSchema, company_id: uuid.UUID) -> None:
        self.mirror = mirror
        self.company_id = company_id
        self.tables = {info.name: mirror.create(info) for info in DIRECTORY_TABLES}

    def load(self, rows: dict[str, list[dict[str, object]]], company_id: uuid.UUID | None = None) -> None:
        infos = {info.name: info for info in DIRECTORY_TABLES}
        with self.mirror.session() as s:
            for name, page in rows.items():
                upsert_page(s, self.tables[name], infos[name], company_id or self.company_id, page, SYNCED)
            s.commit()

    def map(self, company_id: uuid.UUID | None = None) -> dict[str, dict[str, int]]:
        with self.mirror.session() as s:
            counts = map_directory(s, company_id or self.company_id, TODAY)
            s.commit()
        return {part: c.as_dict() for part, c in counts.items()}

    def session(self) -> Session:
        return Session(self.mirror.engine, expire_on_commit=False)


@pytest.fixture
def env(migrated_engine: Engine, committed_company: Company) -> Iterator[Env]:
    with mirror_schema(migrated_engine) as mirror:
        yield Env(mirror, committed_company.id)


def _people(s: Session, company_id: uuid.UUID) -> dict[str | None, Person]:
    return {p.brixx_ref: p for p in s.scalars(sa.select(Person).where(Person.company_id == company_id))}


def test_mapper_fills_directory_and_upgrades_identity_first_person(env: Env) -> None:
    with env.session() as s:
        first_contact = resolve_person(s, env.company_id, Channel.whatsapp, PHONE, "Anna (WhatsApp)", today=TODAY)
        s.commit()
    with env.session() as s:
        purge_brixx_relatie(s, env.company_id, 4)  # erased: the upsert already refuses the row ...
        s.commit()
    env.load(MIRROR_ROWS)
    with env.mirror.session() as s:  # ... and the mapper refuses it too, even if a row slipped into the mirror
        table = env.tables[RELATIE.name]
        s.execute(sa.insert(table).values(company_id=env.company_id, prg_relatieid=4, weergavenaam="Dirk Erased"))
        s.commit()

    counts = env.map()

    assert counts["people"]["created"] == 2  # Bram and Cor; Anna is upgraded, Dirk is erased
    assert counts["people"]["skipped"] == 1
    with env.session() as s:
        people = _people(s, env.company_id)
        anna = people["1"]
        assert anna.id == first_contact
        assert (anna.kind, anna.display_name, anna.valid_to) == (PersonKind.tenant, "Anna Testperson", None)
        assert (people["2"].kind, people["2"].valid_to) == (PersonKind.other, None)
        assert people["3"].valid_to == TODAY
        assert "4" not in people
        identities = s.execute(
            sa.select(ChannelIdentity.channel, ChannelIdentity.identity).where(ChannelIdentity.person_id == anna.id)
        ).all()
        assert set(identities) == {(Channel.whatsapp, PHONE), (Channel.gmail, "anna@example.test")}

        units = {u.brixx_ref: u for u in s.scalars(sa.select(Unit).where(Unit.company_id == env.company_id))}
        assert (units["100"].label, units["100"].address) == ("A", "Teststraat 10, 1000 AA Voorbeeldstad")
        assert units["101"].address == "Zijstraat 2, Voorbeeldstad"

        leases = {
            lease.brixx_ref: lease for lease in s.scalars(sa.select(Lease).where(Lease.company_id == env.company_id))
        }
        assert set(leases) == {"500:900", "500:901", "501:902"}
        assert (leases["500:900"].unit_id, leases["500:900"].valid_from, leases["500:900"].valid_to) == (
            units["100"].id, date(2026, 2, 1), None,
        )  # fmt: skip
        assert (leases["500:901"].valid_from, leases["500:901"].valid_to) == (date(2026, 3, 1), TODAY)
        parties = s.execute(sa.select(LeaseParty.lease_id, LeaseParty.person_id, LeaseParty.role)).all()
        mine = {(lease_id, person_id, role) for lease_id, person_id, role in parties if lease_id in {
            leases["500:900"].id, leases["500:901"].id, leases["501:902"].id}}  # fmt: skip
        assert mine == {(leases["500:900"].id, anna.id, "tenant"), (leases["500:901"].id, anna.id, "tenant")}


def test_second_run_changes_nothing_and_updates_flow_through(env: Env) -> None:
    env.load(MIRROR_ROWS)
    env.map()

    again = env.map()
    assert all(part["created"] == 0 and part["updated"] == 0 for part in again.values())

    env.load(
        {
            RELATIE.name: [relatie(2, "Bram Renamed", version=2)],
            CONTRACT.name: [contract(500, 2, "2026-02-01", versienr=2)],
        }
    )
    changed = env.map()
    assert changed["people"]["updated"] == 1
    with env.session() as s:
        people = _people(s, env.company_id)
        assert people["2"].display_name == "Bram Renamed"
        lease = s.scalars(
            sa.select(Lease).where(Lease.company_id == env.company_id, Lease.brixx_ref == "500:900")
        ).one()
        tenants = s.scalars(sa.select(LeaseParty.person_id).where(LeaseParty.lease_id == lease.id)).all()
        assert tenants == [people["2"].id]  # the old tenant party was replaced


def test_mapping_is_tenant_scoped(env: Env, migrated_engine: Engine) -> None:
    from tests.integration.conftest import purge_company

    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other BV")
        s.add(other)
        s.commit()
    try:
        env.load(MIRROR_ROWS)
        env.load({RELATIE.name: [relatie(1, "Someone Else")]}, company_id=other.id)
        env.map()
        env.map(company_id=other.id)
        with env.session() as s:
            assert set(_people(s, other.id)) == {"1"}
            assert _people(s, other.id)["1"].display_name == "Someone Else"
            assert _people(s, env.company_id)["1"].display_name == "Anna Testperson"
    finally:
        purge_company(migrated_engine, other.id)


def test_brixx_ref_is_unique_per_company(env: Env) -> None:
    with env.session() as s:
        for _ in range(2):
            s.add(Person(company_id=env.company_id, kind=PersonKind.other, display_name="X", brixx_ref="7",
                         valid_from=TODAY))  # fmt: skip
        with pytest.raises(IntegrityError):
            s.flush()


def test_missing_mirror_tables_map_nothing(committed_company: Company, migrated_engine: Engine) -> None:
    with Session(migrated_engine) as s:  # no `brixx` schema here
        counts = map_directory(s, committed_company.id, TODAY)
        s.commit()
    assert all(c.missing_table for c in counts.values())


def test_sync_run_maps_the_directory(dbos_runtime: None, env: Env) -> None:
    from app.workflows.deps import set_engine

    set_engine(env.mirror.engine)
    infos = {info.name: info for info in DIRECTORY_TABLES}
    api = FakeBrixxApi({name: FakeTable(infos[name], rows) for name, rows in MIRROR_ROWS.items()}, page_size=2)
    set_brixx_api(api)
    try:
        brixx_sync.sync_all(datetime(2026, 11, 3, 9, 0, tzinfo=UTC), None)
    finally:
        set_brixx_api(None)
    with env.session() as s:
        assert set(_people(s, env.company_id)) == {"1", "2", "3", "4"}
        units = s.scalars(sa.select(Unit.brixx_ref).where(Unit.company_id == env.company_id)).all()
        assert sorted(u for u in units if u) == ["100", "101"]
