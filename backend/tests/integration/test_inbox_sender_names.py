"""Each mail on screen carries the name and address of its own sender, as its headers (Reply-To first) gave them."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Category, Channel, Direction, Urgency
from app.db.enums import ActionStatus, ApprovalStatus, LinkMethod, PersonKind
from app.db.models import (
    ActionRow,
    Approval,
    Case,
    CaseLink,
    ChannelIdentity,
    Lease,
    LeaseParty,
    MessageRow,
    OwnerAccount,
    Person,
    RawEvent,
    Unit,
)
from tests.integration.test_inbox_maintenance_approve import T0, World, world  # noqa: F401

pytestmark = pytest.mark.integration


def _add_mail(s: Session, w: World, sender: str, minutes: int, **meta: str) -> None:
    raw = RawEvent(company_id=w.company, provider=Channel.gmail, provider_msg_id=f"m-{uuid4()}", payload={})
    s.add(raw)
    s.flush()
    thread_ref = s.query(MessageRow.thread_ref).filter(MessageRow.company_id == w.company).limit(1).scalar()
    msg = MessageRow(
        company_id=w.company, raw_event_id=raw.id, channel=Channel.gmail, provider_msg_id=raw.provider_msg_id,
        thread_ref=thread_ref, sender_identity=sender, direction=Direction.inbound,
        sent_at=T0 + timedelta(minutes=minutes), text=f"van {sender}", meta=meta,
    )  # fmt: skip
    s.add(msg)
    s.flush()
    s.add(CaseLink(company_id=w.company, case_id=w.case, message_id=msg.id, method=LinkMethod.thread))


def test_every_mail_shows_its_own_sender_and_the_thread_shows_the_latest(world: World) -> None:  # noqa: F811
    with Session(world.engine) as s:
        saved = Person(company_id=world.company, kind=PersonKind.other, display_name="Harjot", valid_from=T0.date())
        s.add(saved)
        s.flush()
        s.get(Case, world.case).primary_person_id = saved.id  # type: ignore[union-attr]
        _add_mail(s, world, "jan@example.test", 1, from_name="Jan de Vries")
        _add_mail(s, world, "piet@example.test", 2, header_from="harjot@example.test")
        s.commit()
        person_id = saved.id
    try:
        [thread] = world.client.get("/api/inbox/threads").json()["threads"]
        shown = [(m["senderName"], m["senderContact"]) for m in thread["messages"]]
        assert shown == [
            ("x@y.test", "x@y.test"),
            ("Jan de Vries", "jan@example.test"),
            ("piet@example.test", "piet@example.test"),
        ]
        assert (thread["sender"]["name"], thread["sender"]["contact"]) == ("piet@example.test", "piet@example.test")
        assert "Dear piet@example.test" not in str(thread["gmailDrafts"])

        emails = world.client.get(f"/api/contacts/{person_id}/communications").json()["emails"]
        assert {(e["sender"], e["senderEmail"]) for e in emails} >= {("Jan de Vries", "jan@example.test")}
    finally:
        with Session(world.engine) as s:
            s.query(Case).filter(Case.id == world.case).update({"primary_person_id": None})
            s.query(Person).filter(Person.id == person_id).delete()
            s.commit()


def test_a_saved_contact_is_named_before_the_pipeline_has_linked_the_message(world: World) -> None:  # noqa: F811
    number = "+31612345678"
    with Session(world.engine) as s:
        saved = Person(company_id=world.company, kind=PersonKind.tenant, display_name="Anouk", valid_from=T0.date())
        s.add(saved)
        s.flush()
        s.add(
            ChannelIdentity(
                company_id=world.company,
                person_id=saved.id,
                channel=Channel.whatsapp,
                identity=number,
                valid_from=T0.date(),
            )
        )
        raw = RawEvent(company_id=world.company, provider=Channel.whatsapp, provider_msg_id=f"w-{uuid4()}", payload={})
        s.add(raw)
        s.flush()
        msg = MessageRow(
            company_id=world.company, raw_event_id=raw.id, channel=Channel.whatsapp,
            provider_msg_id=raw.provider_msg_id, thread_ref=number, sender_identity=number,
            direction=Direction.inbound, sent_at=T0 + timedelta(minutes=5), text="hoi", meta={"contact_name": "A."},
        )  # fmt: skip
        s.add(msg)
        s.flush()
        s.add(CaseLink(company_id=world.company, case_id=world.case, message_id=msg.id, method=LinkMethod.thread))
        s.commit()
        person_id = saved.id
    try:
        [thread] = world.client.get("/api/inbox/threads").json()["threads"]
        assert (thread["sender"]["name"], thread["messages"][-1]["senderName"]) == ("Anouk", "Anouk")
    finally:
        with Session(world.engine) as s:
            s.query(ChannelIdentity).filter(ChannelIdentity.person_id == person_id).delete()
            s.query(Person).filter(Person.id == person_id).delete()
            s.commit()


def test_two_cases_sharing_a_thread_do_not_break_the_inbox(world: World) -> None:  # noqa: F811
    """A message is linked to one case only, so the thread auto-link must skip what another case already holds."""
    with Session(world.engine) as s:
        other = Case(company_id=world.company, category=Category.other, urgency=Urgency.low, summary="o")
        s.add(other)
        s.flush()
        _add_mail(s, world, "jan@example.test", 1, from_name="Jan")
        moved = (
            s.query(MessageRow).filter(MessageRow.company_id == world.company, MessageRow.text.contains("jan@")).one()
        )
        s.query(CaseLink).filter(CaseLink.message_id == moved.id).update({"case_id": other.id})
        s.commit()
    assert world.client.get("/api/inbox/threads").status_code == 200


def _drafts(w: World) -> str:
    [thread] = w.client.get("/api/inbox/threads").json()["threads"]
    return str(thread["gmailDrafts"]) + str(thread["whatsappDrafts"])


def test_a_cancelled_reply_is_never_offered_again(world: World) -> None:  # noqa: F811
    with Session(world.engine) as s:
        action = s.get(ActionRow, world.action)
        assert action is not None
        action.payload = {**action.payload, "body_variants": ["Beste Harjot, geheim", "B"]}
        s.commit()
    assert "geheim" in _drafts(world)
    with Session(world.engine) as s:
        s.get(ActionRow, world.action).status = ActionStatus.superseded  # type: ignore[union-attr]
        s.query(Approval).filter(Approval.id == world.approval).update({"status": ApprovalStatus.expired})
        s.commit()
    assert "geheim" not in _drafts(world)


def test_on_a_repaired_case_a_draft_written_to_an_earlier_sender_is_not_shown(world: World) -> None:  # noqa: F811
    with Session(world.engine) as s:
        action = s.get(ActionRow, world.action)
        assert action is not None
        action.payload = {**action.payload, "body_variants": ["Beste X, geheim", "B"]}
        _add_mail(s, world, "jan@example.test", 1, reattributed_from="us@example.test")  # the draft answers x@y.test
        s.commit()
    assert "geheim" not in _drafts(world)


@dataclass
class HarjotCase:
    """An old shared case under Harjot, with a repaired forward from `sender` as its latest mail."""

    harjot: UUID
    tenant: UUID
    sender_person: UUID
    unit: UUID


def _harjot_case(w: World, sender: str, *, sender_is_tenant: bool, **meta: str) -> HarjotCase:
    with Session(w.engine) as s:
        harjot = Person(company_id=w.company, kind=PersonKind.other, display_name="Harjot", valid_from=T0.date())
        tenant = Person(company_id=w.company, kind=PersonKind.tenant, display_name="Jan", valid_from=T0.date())
        unit = Unit(company_id=w.company, label="Singel 1", valid_from=T0.date())
        s.add_all([harjot, tenant, unit, OwnerAccount(company_id=w.company, display_name="Harjot",
                   whatsapp_e164="+31600000009", email="harjot@example.test")])  # fmt: skip
        s.flush()
        writer = tenant
        if not sender_is_tenant:
            writer = Person(company_id=w.company, kind=PersonKind.other, display_name=sender, valid_from=T0.date())
            s.add(writer)
        lease = Lease(company_id=w.company, unit_id=unit.id, valid_from=T0.date())
        s.add(lease)
        s.flush()
        s.add(LeaseParty(company_id=w.company, lease_id=lease.id, person_id=tenant.id, role="tenant"))
        for person, address in ((harjot, "harjot@example.test"), (writer, sender)):
            s.add(ChannelIdentity(company_id=w.company, person_id=person.id, channel=Channel.gmail, identity=address,
                                  valid_from=T0.date()))  # fmt: skip
        s.get(Case, w.case).primary_person_id = harjot.id  # type: ignore[union-attr]
        _add_mail(s, w, sender, 1, reattributed_from="harjot@example.test", **meta)
        s.query(MessageRow).filter(MessageRow.company_id == w.company, MessageRow.sender_identity == sender).update(
            {"person_id": writer.id}
        )
        s.commit()
        return HarjotCase(harjot.id, tenant.id, writer.id, unit.id)


def _drop(w: World) -> None:
    with Session(w.engine) as s:
        s.query(Case).filter(Case.id == w.case).update({"primary_person_id": None})
        s.query(MessageRow).filter(MessageRow.company_id == w.company).update({"person_id": None})
        for model in (OwnerAccount, LeaseParty, Lease, ChannelIdentity, Person, Unit):
            s.query(model).filter(model.company_id == w.company).delete(synchronize_session=False)
        s.commit()


def _thread(w: World) -> dict[str, Any]:
    [thread] = w.client.get("/api/inbox/threads").json()["threads"]
    return thread  # type: ignore[no-any-return]


def test_the_label_and_flat_are_those_of_the_sender_shown(world: World) -> None:  # noqa: F811
    _harjot_case(world, "jan@example.test", sender_is_tenant=True, from_name="Jan de Vries")
    try:
        thread = _thread(world)
        assert (thread["sender"]["name"], thread["recipientRole"], thread["audience"]) == (
            "Jan de Vries", "tenant", "tenants",
        )  # fmt: skip
        assert (thread["unit"], thread["sender"]["unit"]) == ("Singel 1", "Singel 1")
        assert thread["isUnregisteredSender"] is False
    finally:
        _drop(world)


def test_an_unknown_sender_gets_the_pass_label_and_no_placeholder_flat(world: World) -> None:  # noqa: F811
    _harjot_case(world, "kees@gmail.com", sender_is_tenant=False, sender_role_pass="legal")
    try:
        thread = _thread(world)
        assert (thread["recipientRoleDetail"], thread["unit"], thread["sender"]["unit"]) == ("Legal", "", "")
        assert not thread["subject"].endswith("- ")
        assert "Unit" not in [fact["label"] for fact in thread["aiUnderstanding"]["customFacts"]]
    finally:
        _drop(world)


def test_link_to_tenant_moves_the_sender_shown_never_the_case_contact(world: World) -> None:  # noqa: F811
    made = _harjot_case(world, "jan.prive@gmail.com", sender_is_tenant=False)
    try:
        r = world.client.post(f"/api/inbox/threads/case-{world.case}/link-tenant",
                              json={"tenant_id": str(made.tenant), "message_id": _thread(world)["senderMessageId"]},
                              headers={"X-EstateOS-Client": "web"})  # fmt: skip
        assert r.status_code == 200, r.text
        with Session(world.engine) as s:
            held = dict(s.execute(select(ChannelIdentity.identity, ChannelIdentity.person_id).where(
                ChannelIdentity.company_id == world.company, ChannelIdentity.valid_to.is_(None))).all())  # fmt: skip
            assert held["jan.prive@gmail.com"] == made.tenant
            assert held["harjot@example.test"] == made.harjot
            assert s.get(Case, world.case).primary_person_id == made.harjot  # type: ignore[union-attr]
    finally:
        _drop(world)


def test_link_to_tenant_refuses_to_move_one_of_our_own_addresses(world: World) -> None:  # noqa: F811
    made = _harjot_case(world, "jan@example.test", sender_is_tenant=True)
    try:
        with Session(world.engine) as s:  # Harjot's own note is now the latest mail
            _add_mail(s, world, "harjot@example.test", 9)
            mine = s.query(MessageRow).filter(MessageRow.company_id == world.company)
            mine.filter(MessageRow.sender_identity == "harjot@example.test").update({"person_id": made.harjot})
            s.commit()
        r = world.client.post(f"/api/inbox/threads/case-{world.case}/link-tenant",
                              json={"tenant_id": str(made.tenant), "message_id": _thread(world)["senderMessageId"]},
                              headers={"X-EstateOS-Client": "web"})  # fmt: skip
        assert r.status_code == 409
        with Session(world.engine) as s:
            row = s.scalar(select(ChannelIdentity.person_id).where(
                ChannelIdentity.company_id == world.company, ChannelIdentity.identity == "harjot@example.test",
                ChannelIdentity.valid_to.is_(None)))  # fmt: skip
            assert row == made.harjot
    finally:
        _drop(world)


def _link(w: World, tenant: UUID, message_id: str | None) -> int:
    body = {"tenant_id": str(tenant), **({"message_id": message_id} if message_id else {})}
    url = f"/api/inbox/threads/case-{w.case}/link-tenant"
    return int(w.client.post(url, json=body, headers={"X-EstateOS-Client": "web"}).status_code)


def _holder(w: World, address: str) -> UUID | None:
    with Session(w.engine) as s:
        return s.scalar(
            select(ChannelIdentity.person_id).where(
                ChannelIdentity.company_id == w.company,
                ChannelIdentity.identity == address,
                ChannelIdentity.valid_to.is_(None),
            )
        )


def test_link_to_tenant_is_refused_when_the_screen_is_stale_or_names_no_mail(world: World) -> None:  # noqa: F811
    made = _harjot_case(world, "piet@gmail.com", sender_is_tenant=False)
    try:
        seen = _thread(world)["senderMessageId"]
        with Session(world.engine) as s:
            _add_mail(s, world, "later@gmail.com", 9)
            s.commit()
        assert _link(world, made.tenant, seen) == 409
        assert _link(world, made.tenant, None) == 422
        assert _holder(world, "piet@gmail.com") == made.sender_person
    finally:
        _drop(world)


def test_link_to_tenant_never_falls_back_to_the_case_contact(world: World) -> None:  # noqa: F811
    made = _harjot_case(world, "piet@gmail.com", sender_is_tenant=False)
    try:
        with Session(world.engine) as s:
            s.get(Case, world.case).primary_person_id = made.sender_person  # type: ignore[union-attr]
            _add_mail(s, world, "niemand@gmail.com", 9)  # nobody in the directory wrote this
            s.commit()
        assert _link(world, made.tenant, _thread(world)["senderMessageId"]) == 400
        assert _holder(world, "piet@gmail.com") == made.sender_person
    finally:
        _drop(world)


@pytest.mark.parametrize("kind", [PersonKind.tenant, PersonKind.contractor])
def test_link_to_tenant_only_moves_an_unclassified_contact(world: World, kind: PersonKind) -> None:  # noqa: F811
    made = _harjot_case(world, "piet@gmail.com", sender_is_tenant=False)
    try:
        with Session(world.engine) as s:
            s.get(Person, made.sender_person).kind = kind  # type: ignore[union-attr]
            s.commit()
        assert _link(world, made.tenant, _thread(world)["senderMessageId"]) == 409
        assert _holder(world, "piet@gmail.com") == made.sender_person
    finally:
        _drop(world)


def test_link_to_tenant_only_targets_a_tenant(world: World) -> None:  # noqa: F811
    made = _harjot_case(world, "piet@gmail.com", sender_is_tenant=False)
    try:
        assert _link(world, made.harjot, _thread(world)["senderMessageId"]) == 400
        assert _holder(world, "piet@gmail.com") == made.sender_person
    finally:
        _drop(world)


def test_a_writer_never_replaces_the_flat_the_case_is_about(world: World) -> None:  # noqa: F811
    _harjot_case(world, "jan@example.test", sender_is_tenant=True)
    try:
        with Session(world.engine) as s:
            other = Unit(company_id=world.company, label="Prinsengracht 9", valid_from=T0.date())
            s.add(other)
            s.flush()
            s.get(Case, world.case).unit_id = other.id  # type: ignore[union-attr]
            s.commit()
        assert _thread(world)["unit"] == "Prinsengracht 9"
    finally:
        with Session(world.engine) as s:
            s.query(Case).filter(Case.id == world.case).update({"unit_id": None})
            s.commit()
        _drop(world)


def test_a_stranger_does_not_borrow_the_case_contacts_label(world: World) -> None:  # noqa: F811
    made = _harjot_case(world, "jan@example.test", sender_is_tenant=True)
    try:
        with Session(world.engine) as s:
            s.get(Case, world.case).primary_person_id = made.tenant  # type: ignore[union-attr]
            _add_mail(s, world, "vreemde@gmail.com", 9)
            s.commit()
        assert _thread(world)["recipientRole"] == "contact"
    finally:
        _drop(world)


def test_link_to_tenant_never_moves_a_contact_saved_with_a_category(world: World) -> None:  # noqa: F811
    """A saved legal, VvE or business contact is kind `other` with a trade."""
    made = _harjot_case(world, "notaris@example.test", sender_is_tenant=False)
    try:
        with Session(world.engine) as s:
            s.get(Person, made.sender_person).trade = "legal"  # type: ignore[union-attr]
            s.commit()
        assert _link(world, made.tenant, _thread(world)["senderMessageId"]) == 409
        assert _holder(world, "notaris@example.test") == made.sender_person
    finally:
        _drop(world)
