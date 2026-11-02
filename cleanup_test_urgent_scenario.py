import os
import uuid

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.models.directory import LeaseParty, Person
from app.db.models.ingestion import MessageRow

COMPANY_ID = uuid.UUID("01a1341b-2e4e-7073-b44e-40a7bc9e8e2a")
TEST_TAG = "test_planner_eval"


def run():
    engine = create_engine(get_settings().sqlalchemy_url)
    with Session(engine) as session, session.begin():
        print("Cleaning up test scenario entities...")

        # Find test messages by tag
        test_msgs = session.scalars(select(MessageRow).where(MessageRow.company_id == COMPANY_ID)).all()
        for m in test_msgs:
            if m.meta and m.meta.get("tag") == TEST_TAG:
                session.execute(text("DELETE FROM understandings WHERE message_id = :mid"), {"mid": m.id})
                session.execute(text("DELETE FROM case_links WHERE message_id = :mid"), {"mid": m.id})
                session.delete(m)
                session.execute(text("DELETE FROM raw_events WHERE id = :rid"), {"rid": m.raw_event_id})

        # Find test people by brixx_ref
        test_people = session.scalars(
            select(Person).where(Person.company_id == COMPANY_ID, Person.brixx_ref == TEST_TAG)
        ).all()
        for p in test_people:
            # Delete leases & parties
            parties = session.scalars(select(LeaseParty).where(LeaseParty.person_id == p.id)).all()
            for lp in parties:
                session.execute(text("DELETE FROM leases WHERE id = :lid"), {"lid": lp.lease_id})
                session.delete(lp)
            # Delete channel identities
            session.execute(text("DELETE FROM channel_identities WHERE person_id = :pid"), {"pid": p.id})
            session.delete(p)

        # Delete test cases created with test IDs
        test_case_ids = [
            uuid.UUID("01a1818b-1111-7000-8000-000000000001"),
            uuid.UUID("01a1818b-2222-7000-8000-000000000002"),
            uuid.UUID("01a1818b-3333-7000-8000-000000000003"),
        ]
        for cid in test_case_ids:
            session.execute(text("DELETE FROM case_links WHERE case_id = :cid"), {"cid": cid})
            session.execute(text("DELETE FROM case_events WHERE case_id = :cid"), {"cid": cid})
            session.execute(text("DELETE FROM cases WHERE id = :cid"), {"cid": cid})

        print("Cleanup completed successfully! Only core records remain.")


if __name__ == "__main__":
    run()
