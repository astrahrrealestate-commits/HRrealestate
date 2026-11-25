"""Each mail on screen carries the name and address of its own sender, as its headers (Reply-To first) gave them."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.contracts import Category, Channel, Direction, Urgency
from app.db.enums import ActionStatus, ApprovalStatus, LinkMethod, PersonKind
from app.db.models import ActionRow, Approval, Case, CaseLink, ChannelIdentity, MessageRow, Person, RawEvent
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
