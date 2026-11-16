"""`PRG_CONTRACTVHE` + `PRG_CONTRACT` -> `leases` + `lease_parties` (one lease per contract VHE row).

A BRIXX contract can cover several VHEs over changing periods; each contract-VHE link becomes one lease of that unit,
`brixx_ref = "<contractid>:<contractvheid>"`. Validity: the link's start/end, else the contract's; an ended link or
contract (reconcile or `INDVERWIJDERD`) ends no later than today. The contract's relatie is the `tenant` party; a
changed tenant replaces the old tenant party. Co-tenants and guarantors need the Phase B metadata (not mapped yet).
Links whose unit or contract is not mapped are skipped. Flushes; the caller commits.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.db.brixx_erasure import erased_relatie_ids
from app.db.models import Lease, LeaseParty, Person, Unit
from app.directory.brixx import columns as col
from app.directory.brixx.map_common import MapCounts, changed, ended_on, lock_company
from app.directory.brixx.parties import Parties, contract_parties

TENANT = "tenant"
CO_TENANT = "co_tenant"


def lease_ref(contract_id: int, link_id: int) -> str:
    return f"{contract_id}:{link_id}"


def lease_period(link: col.Row, contract: col.Row, today: date) -> tuple[date, date | None]:
    start = col.pick_date(link, col.START) or col.pick_date(contract, col.START) or col.pick_date(link, col.CREATED)
    end = col.pick_date(link, col.END) or col.pick_date(contract, col.END)
    return start or today, ended_on(end, ended=col.is_ended(link) or col.is_ended(contract), today=today)


def _refs(session: Session, model: type[Person] | type[Unit], company_id: UUID) -> dict[str, UUID]:
    rows = session.execute(
        sa.select(model.brixx_ref, model.id).where(model.company_id == company_id, model.brixx_ref.is_not(None))
    )
    return {ref: key for ref, key in rows if ref}


@dataclass(frozen=True)
class _Context:
    company_id: UUID
    today: date
    contracts: dict[int, col.Row]
    parties: dict[int, Parties]
    units: dict[str, UUID]
    people: dict[str, UUID]
    erased: set[int]
    leases: dict[str, Lease]


def map_leases(session: Session, company_id: UUID, today: date) -> MapCounts:
    lock_company(session, company_id)
    links = col.read_mirror(session, col.CONTRACTVHE, company_id)
    contracts = col.read_mirror(session, col.CONTRACT, company_id)
    if links is None or contracts is None:
        return MapCounts.missing()
    existing = session.scalars(sa.select(Lease).where(Lease.company_id == company_id, Lease.brixx_ref.is_not(None)))
    context = _Context(
        company_id,
        today,
        {k: row for row in contracts if (k := col.pick_int(row, (col.CONTRACT_PK,))) is not None},
        contract_parties(session, company_id, contracts),
        _refs(session, Unit, company_id),
        _refs(session, Person, company_id),
        erased_relatie_ids(session, company_id),
        {lease.brixx_ref: lease for lease in existing if lease.brixx_ref},
    )
    outcomes = Counter(_map_link(session, context, link) for link in links)
    session.flush()
    return MapCounts.tally(outcomes)


def _map_link(session: Session, ctx: _Context, link: col.Row) -> str:
    link_id, contract_id = col.pick_int(link, (col.CONTRACTVHE_PK,)), col.pick_int(link, (col.CONTRACT_PK,))
    contract = ctx.contracts.get(contract_id) if contract_id is not None else None
    unit_id = ctx.units.get(str(col.pick_int(link, (col.VHE_PK,))))
    if link_id is None or contract_id is None or contract is None or unit_id is None:
        return "skipped"
    start, end = lease_period(link, contract, ctx.today)
    ref = lease_ref(contract_id, link_id)
    lease = ctx.leases.get(ref)
    if lease is None:
        lease = Lease(company_id=ctx.company_id, unit_id=unit_id, brixx_ref=ref, valid_from=start, valid_to=end)
        session.add(lease)
        session.flush()
        ctx.leases[ref] = lease
        outcome = "created"
    else:
        outcome = "updated" if changed(lease, unit_id=unit_id, valid_from=start, valid_to=end) else "unchanged"
    parties = ctx.parties.get(contract_id, Parties(None))
    _set_role(session, ctx, lease.id, TENANT, [parties.tenant] if parties.tenant is not None else [])
    _set_role(session, ctx, lease.id, CO_TENANT, list(parties.co_tenants))
    return outcome


def _set_role(session: Session, ctx: _Context, lease_id: UUID, role: str, relaties: list[int]) -> None:
    """Exactly these mapped, non-erased relaties in `role` on the lease (unique (lease, person, role) makes the
    insert idempotent); anyone else in that role is removed."""
    people = [ctx.people[str(r)] for r in relaties if r not in ctx.erased and str(r) in ctx.people]
    stale = sa.delete(LeaseParty).where(
        LeaseParty.company_id == ctx.company_id, LeaseParty.lease_id == lease_id, LeaseParty.role == role
    )
    session.execute(stale.where(LeaseParty.person_id.not_in(people)) if people else stale)
    for person_id in people:
        session.execute(
            postgresql.insert(LeaseParty)
            .values(company_id=ctx.company_id, lease_id=lease_id, person_id=person_id, role=role)
            .on_conflict_do_nothing(index_elements=["lease_id", "person_id", "role"])
        )
