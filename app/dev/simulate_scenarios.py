"""Simulate realistic scenario messages for real registered tenants (excluding Vipin Tyagi).

Inbound messages pushed through the full pipeline:
1. Anouk de Jong (WhatsApp): Emergency Maintenance ("Water is leaking from the upstairs ceiling in unit 42-B, please send a plumber urgent!")
2. Elena Rostova (Gmail): Lease Extension Query ("Hi Harjot, my lease expires next month, can we extend for another year?")
3. Lars van den Berg (WhatsApp): Payment Confirmation ("Just transferred the overdue rent for November, transaction ref #NL8892.")
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.db.enums import PipelineStatus, RawEventStatus
from app.db.models import ActionRow, Case, CaseLink, MessageRow, OwnerAccount, Person, RawEvent
from app.db.session import make_engine
from app.directory.identity import resolve_message_sender
from app.pipeline.link import link_message
from app.pipeline.propose import propose_for_message
from app.pipeline.understand import mark_pipeline_done, understand_message

log = get_logger("simulate_tenants")


def run_simulation() -> None:
    settings = get_settings()
    engine = make_engine(str(settings.database_url))

    with Session(engine) as session:
        owner = session.scalars(
            select(OwnerAccount)
            .where(OwnerAccount.email.is_not(None), OwnerAccount.email != "")
            .order_by(OwnerAccount.id.desc())
        ).first()
        if not owner:
            owner = session.scalars(select(OwnerAccount).limit(1)).first()
        if not owner:
            print("No owner account found")
            return
        company_id = owner.company_id
        print(f"Target company: {company_id} ({owner.email})")

    scenarios = [
        {
            "name": "Anouk de Jong",
            "channel": Channel.whatsapp,
            "sender_identity": "+31 6 8123 4501",
            "subject": None,
            "text": "Water is leaking from the upstairs ceiling in unit 42-B, please send a plumber urgent!",
            "type": "Emergency Maintenance",
        },
        {
            "name": "Elena Rostova",
            "channel": Channel.gmail,
            "sender_identity": "elena.rostova@estateos.nl",
            "subject": "Lease extension query - Keizersgracht 42-C",
            "text": "Hi Harjot, my lease expires next month, can we extend for another year?",
            "type": "Lease Extension",
        },
        {
            "name": "Lars van den Berg",
            "channel": Channel.whatsapp,
            "sender_identity": "+31 6 8123 4506",
            "subject": None,
            "text": "Just transferred the overdue rent for November, transaction ref #NL8892.",
            "type": "Payment Confirmation",
        },
    ]

    for item in scenarios:
        print(f"\n=======================================================")
        print(f"Injecting {item['type']} from {item['name']} ({item['channel'].value})...")
        now = datetime.now(UTC)
        raw_id = uuid4()
        msg_id = uuid4()
        provider_id = f"sim_{uuid4().hex[:16]}"

        with Session(engine) as session, session.begin():
            raw_event = RawEvent(
                id=raw_id,
                company_id=company_id,
                provider=item["channel"],
                provider_msg_id=provider_id,
                payload={"text": item["text"], "sender": item["sender_identity"]},
                status=RawEventStatus.pending,
            )
            session.add(raw_event)
            session.flush()

            msg = MessageRow(
                id=msg_id,
                raw_event_id=raw_id,
                company_id=company_id,
                channel=item["channel"],
                direction=Direction.inbound,
                provider_msg_id=provider_id,
                sender_identity=item["sender_identity"],
                text=item["text"],
                sent_at=now,
                pipeline_status=PipelineStatus.pending,
                pipeline_attempts=0,
                meta={"subject": item["subject"]} if item["subject"] else {},
            )
            session.add(msg)

        print(f"Message persisted with ID: {msg_id}")
        print("Running pipeline (Understanding -> Resolve Sender -> Linker -> Proposer)...")

        try:
            print("  1. Running Understanding Agent...")
            und_id = understand_message(engine, settings, msg_id)
            print(f"     -> UnderstandingRow ID: {und_id}")

            print("  2. Resolving Sender Identity...")
            resolve_message_sender(engine, msg_id)

            print("  3. Running Linker Agent...")
            link_res = link_message(engine, settings, msg_id)
            print(f"     -> Case ID: {link_res.case_id if link_res else 'None'}")

            print("  4. Running Proposer Agent (Gemini)...")
            prop_res = propose_for_message(engine, settings, msg_id)
            print(f"     -> Approvals created: {len(prop_res.approval_ids)}")

            print("  5. Marking Pipeline Done...")
            mark_pipeline_done(engine, msg_id)
        except Exception as e:
            print(f"Pipeline error (non-fatal): {e}")

        # Check outcomes in database
        with Session(engine) as session:
            case_id = session.scalar(
                select(CaseLink.case_id).where(CaseLink.message_id == msg_id)
            )
            case = session.get(Case, case_id) if case_id else None
            actions = session.scalars(
                select(ActionRow).where(ActionRow.context_ref.contains([msg_id]))
            ).all()

            print(f"-> Linked Case: {case_id} (Category: {case.category.value if case else 'None'}, Summary: {case.summary if case else 'None'})")
            print(f"-> Generated Actions ({len(actions)}):")
            for a in actions:
                variants = a.payload.get("body_variants", []) if a.payload else []
                print(f"   * Action Type: {a.type.value}, Status: {a.status.value}")
                for i, v in enumerate(variants):
                    print(f"     Option {i+1}: {v[:120]}...")

    print("\nSimulation complete! All 3 scenarios processed through the full AI pipeline.")


if __name__ == "__main__":
    run_simulation()
