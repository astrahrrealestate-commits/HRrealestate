"""Who rents under a BRIXX contract: the tenant and the co-tenants.

The real PRG_CONTRACT carries no PRG_RELATIEID. Its relaties are PRG_CONTRACTRELATIE rows ordered by VOLGNR (the
lowest is the tenant, the rest co-tenants); EERSTERELATIEID on the contract repeats the first one and is the fallback
when the link table is not mirrored (and PRG_RELATIEID for the doc-example shape).
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.orm import Session

from app.directory.brixx import columns as col


@dataclass(frozen=True)
class Parties:
    tenant: int | None
    co_tenants: tuple[int, ...] = field(default_factory=tuple)

    def everyone(self) -> set[int]:
        return ({self.tenant} if self.tenant is not None else set()) | set(self.co_tenants)


def contract_parties(session: Session, company_id: UUID, contracts: Iterable[col.Row]) -> dict[int, Parties]:
    """Parties per contract id, for every mirrored contract."""
    linked: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for row in col.read_mirror(session, col.CONTRACTRELATIE, company_id) or []:
        contract_id, relatie_id = col.pick_int(row, (col.CONTRACT_PK,)), col.pick_int(row, (col.RELATIE_PK,))
        if contract_id is None or relatie_id is None or col.is_ended(row):
            continue
        linked[contract_id].append((col.pick_int(row, col.ORDER) or 0, relatie_id))
    parties: dict[int, Parties] = {}
    for contract in contracts:
        contract_id = col.pick_int(contract, (col.CONTRACT_PK,))
        if contract_id is None:
            continue
        ordered = [relatie for _, relatie in sorted(linked.get(contract_id, []))]
        named = col.pick_int(contract, col.CONTRACT_TENANT)
        first = named if named is not None and (named in ordered or not ordered) else (ordered[0] if ordered else None)
        parties[contract_id] = Parties(first, tuple(r for r in dict.fromkeys(ordered[1:]) if r != first))
    return parties
