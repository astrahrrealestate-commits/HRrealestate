"""M10 document linking against Postgres: message evidence, directory matches, ambiguity, owner links, scoping."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import CaseState, Category, Channel, Direction, Urgency
from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.db.enums import DocLinkKind, LinkMethod, PersonKind
from app.db.models import (
    AttachmentRow,
    Case,
    CaseLink,
    Company,
    DocumentLink,
    DocumentRow,
    Lease,
    LeaseParty,
    MessageRow,
    Person,
    RawEvent,
    Unit,
)
from app.pipeline.document_links import link_document

pytestmark = pytest.mark.integration
SENT = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


@dataclass
class World:
    company_id: UUID
    anna: UUID
    unit_2: UUID
    unit_1: UUID
    lease: UUID
    case: UUID
    sender: UUID


def _world(engine: Engine, company: Company) -> World:
    cid = company.id
    with Session(engine) as s, s.begin():
        anna = Person(company_id=cid, kind=PersonKind.tenant, display_name="Anna de Vries", valid_from=date(2025, 1, 1))
        sender = Person(
            company_id=cid, kind=PersonKind.contractor, display_name="Jan Bakker", valid_from=date(2025, 1, 1)
        )
        u1 = Unit(
            company_id=cid, label="Kerkstraat 12-1", address="Kerkstraat 12-1, Amsterdam", valid_from=date(2025, 1, 1)
        )
        u2 = Unit(
            company_id=cid, label="Kerkstraat 12-2", address="Kerkstraat 12-2, Amsterdam", valid_from=date(2025, 1, 1)
        )
        s.add_all([anna, sender, u1, u2])
        s.flush()
        lease = Lease(company_id=cid, unit_id=u2.id, valid_from=date(2025, 1, 1))
        s.add(lease)
        s.flush()
        s.add(LeaseParty(company_id=cid, lease_id=lease.id, person_id=anna.id, role="tenant"))
        case = Case(company_id=cid, unit_id=None, lease_id=None, primary_person_id=None, state=CaseState.open,
                    category=Category.maintenance, urgency=Urgency.normal)  # fmt: skip
        s.add(case)
        s.flush()
        return World(cid, anna.id, u2.id, u1.id, lease.id, case.id, sender.id)


def _document(engine: Engine, w: World, facts: dict[str, object] | None, *, with_case: bool = True) -> UUID:
    """A document whose message came from the contractor `sender`; returns the attachment id."""
    with Session(engine) as s, s.begin():
        raw = RawEvent(company_id=w.company_id, provider=Channel.gmail, provider_msg_id=str(new_id()), payload={})
        s.add(raw)
        s.flush()
        msg = MessageRow(company_id=w.company_id, raw_event_id=raw.id, channel=Channel.gmail,
                         provider_msg_id=raw.provider_msg_id, thread_ref="t", sender_identity="j@example.test",
                         direction=Direction.inbound, sent_at=SENT, text="bijlage", meta={},
                         person_id=w.sender)  # fmt: skip
        s.add(msg)
        s.flush()
        if with_case:
            s.add(CaseLink(company_id=w.company_id, case_id=w.case, message_id=msg.id, method=LinkMethod.thread))
        att = AttachmentRow(company_id=w.company_id, message_id=msg.id, s3_key="k", mime_type="application/pdf",
                            filename="x.pdf", size_bytes=9, sha256="0" * 64)  # fmt: skip
        s.add(att)
        s.flush()
        s.add(DocumentRow(company_id=w.company_id, attachment_id=att.id, doc_type="lease", title="Huur",
                          file_name="x.pdf", confidence=0.9, facts=facts))  # fmt: skip
        return att.id


def _links(engine: Engine, cid: UUID) -> set[tuple[str, UUID, str]]:
    with Session(engine) as s:
        rows = s.scalars(select(DocumentLink).where(DocumentLink.company_id == cid)).all()
        return {(r.kind.value, r.ref_id, r.method) for r in rows}


@pytest.fixture
def w(migrated_engine: Engine, committed_company: Company) -> World:
    return _world(migrated_engine, committed_company)


def test_message_evidence_links_sender_and_case(migrated_engine: Engine, w: World) -> None:
    att = _document(migrated_engine, w, None)
    out = link_document(migrated_engine, w.company_id, att)
    assert out.unresolved == []
    assert _links(migrated_engine, w.company_id) == {
        ("person", w.sender, "message"),
        ("case", w.case, "message"),
    }


def test_case_brings_its_unit_lease_and_primary_person(migrated_engine: Engine, w: World) -> None:
    with Session(migrated_engine) as s, s.begin():
        case = s.get(Case, w.case)
        assert case is not None
        case.unit_id, case.lease_id, case.primary_person_id = w.unit_2, w.lease, w.anna
    link_document(migrated_engine, w.company_id, _document(migrated_engine, w, None))
    got = _links(migrated_engine, w.company_id)
    assert {("unit", w.unit_2, "case"), ("lease", w.lease, "case"), ("person", w.anna, "case")} <= got


def test_reader_names_and_address_link_person_unit_and_active_lease(migrated_engine: Engine, w: World) -> None:
    facts = {"parties": [{"name": "Anna de Vries", "role": "tenant"}, {"name": "H. Singh", "role": "landlord"}],
             "unit_hint": "Kerkstraat 12-2, Amsterdam", "start_date": None, "end_date": None,
             "key_facts": []}  # fmt: skip
    out = link_document(migrated_engine, w.company_id, _document(migrated_engine, w, facts, with_case=False))
    assert out.unresolved == []
    got = _links(migrated_engine, w.company_id)
    assert ("person", w.anna, "fuzzy") in got
    assert ("unit", w.unit_2, "fuzzy") in got
    assert ("lease", w.lease, "fuzzy") in got


def test_tenant_name_alone_places_the_document_in_their_unit(migrated_engine: Engine, w: World) -> None:
    facts = {"parties": [{"name": "Anna de Vries", "role": "tenant"}], "unit_hint": None, "start_date": None,
             "end_date": None, "key_facts": []}  # fmt: skip
    link_document(migrated_engine, w.company_id, _document(migrated_engine, w, facts, with_case=False))
    got = _links(migrated_engine, w.company_id)
    assert ("unit", w.unit_2, "lease") in got
    assert ("lease", w.lease, "lease") in got


def test_ambiguous_address_links_nothing_and_is_reported(migrated_engine: Engine, w: World) -> None:
    facts = {"parties": [], "unit_hint": "Kerkstraat 12", "start_date": None, "end_date": None, "key_facts": []}
    out = link_document(migrated_engine, w.company_id, _document(migrated_engine, w, facts, with_case=False))
    assert out.unresolved == ["unit: Kerkstraat 12"]
    assert not {k for k, _, _ in _links(migrated_engine, w.company_id)} & {"unit", "lease"}


def test_unknown_tenant_is_reported_not_guessed(migrated_engine: Engine, w: World) -> None:
    facts = {"parties": [{"name": "Pieter Jansen", "role": "tenant"}], "unit_hint": None, "start_date": None,
             "end_date": None, "key_facts": []}  # fmt: skip
    out = link_document(migrated_engine, w.company_id, _document(migrated_engine, w, facts, with_case=False))
    assert out.unresolved == ["person: Pieter Jansen"]


def _owner_row(engine: Engine, w: World, att: UUID, ref: UUID, method: str) -> None:
    with Session(engine) as s, s.begin():
        doc = s.scalar(select(DocumentRow).where(DocumentRow.attachment_id == att))
        assert doc is not None
        s.add(DocumentLink(company_id=w.company_id, document_id=doc.id, kind=DocLinkKind.person, ref_id=ref,
                           method=method, score=1.0))  # fmt: skip


def test_relinking_is_idempotent(migrated_engine: Engine, w: World) -> None:
    att = _document(migrated_engine, w, None)
    link_document(migrated_engine, w.company_id, att)
    first = _links(migrated_engine, w.company_id)
    link_document(migrated_engine, w.company_id, att)
    assert _links(migrated_engine, w.company_id) == first


def test_owner_link_survives_relinking(migrated_engine: Engine, w: World) -> None:
    att = _document(migrated_engine, w, None)
    _owner_row(migrated_engine, w, att, w.anna, "owner")
    link_document(migrated_engine, w.company_id, att)
    assert ("person", w.anna, "owner") in _links(migrated_engine, w.company_id)


def test_a_removed_link_is_not_resurrected(migrated_engine: Engine, w: World) -> None:
    att = _document(migrated_engine, w, None)
    _owner_row(migrated_engine, w, att, w.sender, "removed")  # the owner said: not this sender
    link_document(migrated_engine, w.company_id, att)
    got = _links(migrated_engine, w.company_id)
    assert ("person", w.sender, "removed") in got
    assert ("person", w.sender, "message") not in got


def test_other_company_cannot_link_it(migrated_engine: Engine, w: World) -> None:
    att = _document(migrated_engine, w, None)
    with pytest.raises(NotFoundError):
        link_document(migrated_engine, new_id(), att)
