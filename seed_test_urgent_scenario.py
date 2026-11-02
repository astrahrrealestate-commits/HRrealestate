import os
import uuid
from datetime import UTC, datetime

from dotenv import load_dotenv

# Ensure .env is loaded regardless of working directory
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.contracts import Category, Channel, Direction, Urgency
from app.contracts.case_state import CaseState
from app.core.settings import get_settings
from app.db.enums import DeliveryStatus, LinkMethod, PersonKind, PipelineStatus, RawEventStatus
from app.db.models.directory import ChannelIdentity, Lease, LeaseParty, Person, Unit
from app.db.models.ingestion import MessageRow, RawEvent
from app.db.models.pipeline import Case, CaseLink, UnderstandingRow

COMPANY_ID = uuid.UUID("01a1341b-2e4e-7073-b44e-40a7bc9e8e2a")
TEST_TAG = "test_planner_eval"


def run():
    engine = create_engine(get_settings().sqlalchemy_url)
    with Session(engine) as session, session.begin():
        print("Preparing 3 tagged urgent test cases...")

        # 1. Look up existing units
        units = session.scalars(select(Unit).where(Unit.company_id == COMPANY_ID)).all()
        unit_map = {u.address: u for u in units}

        u1 = unit_map.get("Keizersgracht 42-A") or units[0]
        u2 = unit_map.get("Pieter Floriszstraat 1 C") or (units[1] if len(units) > 1 else units[0])
        u3 = unit_map.get("Prinsengracht 192") or (units[2] if len(units) > 2 else units[0])

        today = datetime.now(UTC).date()

        # 2. Check / Setup Persons
        # Tenant 1: Vipin Tyagi
        p1 = session.scalars(
            select(Person).where(Person.company_id == COMPANY_ID, Person.display_name == "Vipin Tyagi")
        ).first()
        if not p1:
            p1 = Person(
                id=uuid.uuid4(),
                company_id=COMPANY_ID,
                display_name="Vipin Tyagi",
                kind=PersonKind.tenant,
                brixx_ref=TEST_TAG,
                valid_from=today,
            )
            session.add(p1)
            session.flush()
            session.add(
                ChannelIdentity(
                    id=uuid.uuid4(),
                    company_id=COMPANY_ID,
                    person_id=p1.id,
                    channel=Channel.whatsapp,
                    identity="+919456916996",
                    valid_from=today,
                )
            )

        # Tenant 2: Sanne de Vries
        p2 = session.scalars(
            select(Person).where(Person.company_id == COMPANY_ID, Person.display_name == "Sanne de Vries")
        ).first()
        l2_id = None
        if not p2:
            p2 = Person(
                id=uuid.uuid4(),
                company_id=COMPANY_ID,
                display_name="Sanne de Vries",
                kind=PersonKind.tenant,
                brixx_ref=TEST_TAG,
                valid_from=today,
            )
            session.add(p2)
            session.flush()
            session.add(
                ChannelIdentity(
                    id=uuid.uuid4(),
                    company_id=COMPANY_ID,
                    person_id=p2.id,
                    channel=Channel.whatsapp,
                    identity="+31655123456",
                    valid_from=today,
                )
            )
            session.add(
                ChannelIdentity(
                    id=uuid.uuid4(),
                    company_id=COMPANY_ID,
                    person_id=p2.id,
                    channel=Channel.gmail,
                    identity="sanne.devries@example.nl",
                    valid_from=today,
                )
            )
            # Lease for Unit 2
            l2 = Lease(id=uuid.uuid4(), company_id=COMPANY_ID, unit_id=u2.id, brixx_ref=TEST_TAG, valid_from=today)
            session.add(l2)
            session.flush()
            l2_id = l2.id
            session.add(
                LeaseParty(id=uuid.uuid4(), company_id=COMPANY_ID, lease_id=l2.id, person_id=p2.id, role="tenant")
            )
        else:
            lp2 = session.scalars(select(LeaseParty).where(LeaseParty.person_id == p2.id)).first()
            if lp2:
                l2_id = lp2.lease_id

        # Tenant 3: Lucas van Dijk
        p3 = session.scalars(
            select(Person).where(Person.company_id == COMPANY_ID, Person.display_name == "Lucas van Dijk")
        ).first()
        l3_id = None
        if not p3:
            p3 = Person(
                id=uuid.uuid4(),
                company_id=COMPANY_ID,
                display_name="Lucas van Dijk",
                kind=PersonKind.tenant,
                brixx_ref=TEST_TAG,
                valid_from=today,
            )
            session.add(p3)
            session.flush()
            session.add(
                ChannelIdentity(
                    id=uuid.uuid4(),
                    company_id=COMPANY_ID,
                    person_id=p3.id,
                    channel=Channel.whatsapp,
                    identity="+31655987654",
                    valid_from=today,
                )
            )
            session.add(
                ChannelIdentity(
                    id=uuid.uuid4(),
                    company_id=COMPANY_ID,
                    person_id=p3.id,
                    channel=Channel.gmail,
                    identity="lucas.vandijk@example.nl",
                    valid_from=today,
                )
            )
            # Lease for Unit 3
            l3 = Lease(id=uuid.uuid4(), company_id=COMPANY_ID, unit_id=u3.id, brixx_ref=TEST_TAG, valid_from=today)
            session.add(l3)
            session.flush()
            l3_id = l3.id
            session.add(
                LeaseParty(id=uuid.uuid4(), company_id=COMPANY_ID, lease_id=l3.id, person_id=p3.id, role="tenant")
            )
        else:
            lp3 = session.scalars(select(LeaseParty).where(LeaseParty.person_id == p3.id)).first()
            if lp3:
                l3_id = lp3.lease_id

        session.flush()

        # 3. Create or Update the 3 Cases with Inbound Trigger Messages
        cases_data = [
            {
                "case_id": uuid.UUID("01a1818b-1111-7000-8000-000000000001"),
                "unit": u1,
                "person": p1,
                "lease_id": None,
                "summary": "[TEST] Critical ceiling leak dripping onto live fuse box",
                "urgency": Urgency.emergency,
                "state": CaseState.open,
                "sender": "+919456916996",
                "body": "WATER IS POURING FROM THE CEILING DIRECTLY ONTO THE FUSE BOX! Sparking occurred. Please send emergency help immediately!",
                "channel": Channel.whatsapp,
            },
            {
                "case_id": uuid.UUID("01a1818b-2222-7000-8000-000000000002"),
                "unit": u2,
                "person": p2,
                "lease_id": l2_id,
                "summary": "[TEST] Total kitchen power loss - refrigerator unpowered",
                "urgency": Urgency.emergency,
                "state": CaseState.open,
                "sender": "+31655123456",
                "body": "Hi, all sockets in the kitchen suddenly went dead after a loud pop. Refrigerator has been off for 4 hours and all food is spoiling.",
                "channel": Channel.whatsapp,
            },
            {
                "case_id": uuid.UUID("01a1818b-3333-7000-8000-000000000003"),
                "unit": u3,
                "person": p3,
                "lease_id": l3_id,
                "summary": "[TEST] Central heating boiler failure - pressure 0.3 bar",
                "urgency": Urgency.high,
                "state": CaseState.open,
                "sender": "+31655987654",
                "body": "Good morning, our central heating completely stopped. Boiler displays F22 error and pressure is 0.3 bar. House is freezing cold.",
                "channel": Channel.whatsapp,
            },
        ]

        for item in cases_data:
            c = session.get(Case, item["case_id"])
            if not c:
                c = Case(
                    id=item["case_id"],
                    company_id=COMPANY_ID,
                    unit_id=item["unit"].id,
                    lease_id=item["lease_id"],
                    state=item["state"],
                    category=Category.maintenance,
                    urgency=item["urgency"],
                    summary=item["summary"],
                    primary_person_id=item["person"].id,
                    opened_at=datetime.now(UTC),
                )
                session.add(c)
            else:
                c.unit_id = item["unit"].id
                c.lease_id = item["lease_id"]
                c.state = item["state"]
                c.category = Category.maintenance
                c.urgency = item["urgency"]
                c.summary = item["summary"]
                c.primary_person_id = item["person"].id

            session.flush()

            # Create Inbound RawEvent & MessageRow
            raw_id = uuid.uuid4()
            msg_id = uuid.uuid4()
            provider_msg_id = f"test-wa-{c.id}"

            # Remove previous test messages if re-running
            old_raw = session.scalars(
                select(RawEvent).where(RawEvent.company_id == COMPANY_ID, RawEvent.provider_msg_id == provider_msg_id)
            ).first()
            if old_raw:
                session.execute(
                    text(
                        "DELETE FROM understandings WHERE message_id IN (SELECT id FROM messages WHERE raw_event_id = :rid)"
                    ),
                    {"rid": old_raw.id},
                )
                session.execute(
                    text(
                        "DELETE FROM case_links WHERE message_id IN (SELECT id FROM messages WHERE raw_event_id = :rid)"
                    ),
                    {"rid": old_raw.id},
                )
                session.execute(text("DELETE FROM messages WHERE raw_event_id = :rid"), {"rid": old_raw.id})
                session.delete(old_raw)
                session.flush()

            raw = RawEvent(
                id=raw_id,
                company_id=COMPANY_ID,
                provider=item["channel"],
                provider_msg_id=provider_msg_id,
                payload={"from": item["sender"], "text": item["body"], "test": True},
                received_at=datetime.now(UTC),
                status=RawEventStatus.processed,
            )
            session.add(raw)
            session.flush()

            msg = MessageRow(
                id=msg_id,
                company_id=COMPANY_ID,
                raw_event_id=raw_id,
                channel=item["channel"],
                provider_msg_id=provider_msg_id,
                thread_ref=item["sender"],
                sender_identity=item["sender"],
                direction=Direction.inbound,
                sent_at=datetime.now(UTC),
                text=item["body"],
                person_id=item["person"].id,
                delivery_status=DeliveryStatus.delivered,
                pipeline_status=PipelineStatus.done,
                meta={"tag": TEST_TAG, "urgency": str(item["urgency"].value)},
            )
            session.add(msg)
            session.flush()

            # Add UnderstandingRow so proposal/draft pipeline knows it is ready to reply
            und = UnderstandingRow(
                id=uuid.uuid4(),
                company_id=COMPANY_ID,
                message_id=msg.id,
                category=Category.maintenance,
                urgency=item["urgency"],
                body={
                    "category": "maintenance",
                    "intent": item["summary"].replace("[TEST] ", ""),
                    "urgency": str(item["urgency"].value),
                    "requires_reply": True,
                    "entities": {
                        "people": [item["person"].display_name],
                        "unit_refs": [item["unit"].address],
                        "dates": [],
                        "amounts": [],
                    },
                    "suspicious": {"flag": False, "reason": None},
                    "confidence": 0.99,
                    "prompt_version": "understanding/v1",
                },
                prompt_version="understanding/v1",
            )
            session.add(und)
            session.flush()

            # Link message to case
            cl = CaseLink(company_id=COMPANY_ID, case_id=c.id, message_id=msg.id, method=LinkMethod.new_case)
            session.add(cl)

        print("[OK] Successfully seeded 3 tagged urgent test cases across 3 tenants and units!")


if __name__ == "__main__":
    run()
