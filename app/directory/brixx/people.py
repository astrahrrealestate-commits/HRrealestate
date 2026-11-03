"""`PRG_RELATIE` -> `people` + `channel_identities`, upgrading identity-first people instead of duplicating them.

A relatie is matched by `brixx_ref` first, then through a current channel identity (phone -> whatsapp, email ->
gmail, normalised like inbound messages, NL region) whose person has no `brixx_ref` yet: that person (created on
first contact) is upgraded. An identity that belongs to another person is never moved. Kind: `tenant` for the
tenant of any contract; otherwise an existing kind is kept and new people are `other`. GDPR-erased relaties are
skipped. Recipients still come only from the DB identity rules (invariant 5); nothing here sends.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.contracts import Channel, normalise_identity
from app.db.brixx_erasure import erased_relatie_ids
from app.db.enums import PersonKind
from app.db.models import ChannelIdentity, Person
from app.directory.brixx import columns as col
from app.directory.brixx.map_common import MapCounts, changed, ended_on, lock_company

MAX_NAME = 200
REGION = "NL"
Identity = tuple[Channel, str]


@dataclass
class _Index:
    by_ref: dict[str, Person]
    owner_of: dict[Identity, UUID]


def contract_tenants(session: Session, company_id: UUID) -> set[int]:
    """Relatie ids that are the tenant of at least one mirrored contract."""
    contracts = col.read_mirror(session, col.CONTRACT, company_id) or []
    return {t for row in contracts if (t := col.pick_int(row, (col.RELATIE_PK,))) is not None}


def contact_identities(row: col.Row) -> list[Identity]:
    """Valid, normalised phone (whatsapp) and email (gmail) identities of a relatie row; invalid values are dropped."""
    found: list[Identity] = []
    for channel, names in ((Channel.whatsapp, col.PHONE), (Channel.gmail, col.EMAIL)):
        for name in names:
            value = col.pick(row, (name,))
            if value is None:
                continue
            try:
                identity = (channel, normalise_identity(str(value), REGION))
            except ValueError:
                continue
            if identity not in found:
                found.append(identity)
    return found


def _load(session: Session, company_id: UUID) -> _Index:
    people = session.scalars(sa.select(Person).where(Person.company_id == company_id, Person.brixx_ref.is_not(None)))
    current = session.execute(
        sa.select(ChannelIdentity.channel, ChannelIdentity.identity, ChannelIdentity.person_id).where(
            ChannelIdentity.company_id == company_id, ChannelIdentity.valid_to.is_(None)
        )
    )
    return _Index({p.brixx_ref: p for p in people if p.brixx_ref}, {(c, i): pid for c, i, pid in current})


def _upgradable(session: Session, index: _Index, identities: list[Identity]) -> Person | None:
    for identity in identities:
        owner = index.owner_of.get(identity)
        person = session.get(Person, owner) if owner is not None else None
        if person is not None and person.brixx_ref is None and person.valid_to is None:
            return person
    return None


def map_people(session: Session, company_id: UUID, today: date) -> MapCounts:
    """Create or update one person per mirrored relatie. Flushes; the caller commits."""
    lock_company(session, company_id)
    rows = col.read_mirror(session, col.RELATIE, company_id)
    if rows is None:
        return MapCounts.missing()
    erased, tenants = erased_relatie_ids(session, company_id), contract_tenants(session, company_id)
    index, outcomes = _load(session, company_id), Counter[str]()
    for row in rows:
        ref = col.pick_int(row, (col.RELATIE_PK,))
        if ref is None or ref in erased:
            outcomes["skipped"] += 1
            continue
        outcomes[_map_one(session, index, company_id, ref, row, is_tenant=ref in tenants, today=today)] += 1
    session.flush()
    return MapCounts.tally(outcomes)


def _map_one(
    session: Session, index: _Index, company_id: UUID, ref: int, row: col.Row, *, is_tenant: bool, today: date
) -> str:
    identities = contact_identities(row)
    name = col.pick_text(row, col.NAME, MAX_NAME)
    ended = col.is_ended(row)
    person = index.by_ref.get(str(ref)) or _upgradable(session, index, identities)
    if person is None:
        person = Person(
            company_id=company_id,
            kind=PersonKind.tenant if is_tenant else PersonKind.other,
            display_name=name or f"Relatie {ref}",
            brixx_ref=str(ref),
            valid_from=col.pick_date(row, col.CREATED) or today,
            valid_to=today if ended else None,
        )
        session.add(person)
        session.flush()
        outcome = "created"
    else:
        kind = PersonKind.tenant if is_tenant and person.kind == PersonKind.other else person.kind
        valid_to = ended_on(person.valid_to, ended=True, today=today) if ended else None
        values = {"brixx_ref": str(ref), "kind": kind, "valid_to": valid_to}
        outcome = "updated" if changed(person, **values, display_name=name or person.display_name) else "unchanged"
    index.by_ref[str(ref)] = person
    if not ended:
        _attach(session, index, company_id, person, identities, today)
    return outcome


def _attach(
    session: Session, index: _Index, company_id: UUID, person: Person, identities: list[Identity], today: date
) -> None:
    """Add identities nobody holds yet; race-safe on the current-identity partial unique index."""
    for channel, identity in identities:
        if (channel, identity) in index.owner_of:
            continue
        session.execute(
            postgresql.insert(ChannelIdentity)
            .values(company_id=company_id, person_id=person.id, channel=channel, identity=identity, valid_from=today)
            .on_conflict_do_nothing(
                index_elements=["company_id", "channel", "identity"], index_where=ChannelIdentity.valid_to.is_(None)
            )
        )
        index.owner_of[(channel, identity)] = person.id
