import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from dotenv import load_dotenv

# Ensure .env is loaded
load_dotenv(Path(__file__).resolve().parent / ".env")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.contracts import Channel, Direction
from app.core.settings import get_settings
from app.db.enums import PipelineStatus, RawEventStatus
from app.db.models import RawEvent, MessageRow
from app.workflows.pipeline import understand_step, resolve_step, link_step, propose_step, done_step
from app.tools.message_rag import index_message

COMPANY_ID = uuid.UUID("01a1341b-2e4e-7073-b44e-40a7bc9e8e2a")

email_subject = "Urgent: Severe water pipe leak under kitchen sink - Keizersgracht 42-A"
email_body = """Hello Suryansh,

A major water leak just started under the kitchen sink at Keizersgracht 42-A. Water is spraying from the main shut-off valve and pooling across the wooden floor. I placed a bucket, but it's overflowing quickly.

Please send plumber Kevin urgently before it damages the floor and the apartment below!

Best regards,
Vipin Tyagi
+919456916996"""

engine = create_engine(get_settings().sqlalchemy_url)

raw_event_id = uuid.uuid4()
message_id = uuid.uuid4()
provider_msg_id = f"gmail-msg-{uuid.uuid4().hex[:12]}"

with Session(engine) as session, session.begin():
    # 1. Create RawEvent
    raw = RawEvent(
        id=raw_event_id,
        company_id=COMPANY_ID,
        provider="gmail",
        provider_msg_id=provider_msg_id,
        received_at=datetime.now(UTC),
        payload={
            "id": provider_msg_id,
            "threadId": provider_msg_id,
            "from": "vipint9902@gmail.com",
            "to": "tyagisurya.04@gmail.com",
            "subject": email_subject,
            "snippet": email_body[:100],
            "body": email_body,
        },
        status=RawEventStatus.processed,
    )
    session.add(raw)
    session.flush()

    # 2. Create MessageRow
    msg = MessageRow(
        id=message_id,
        raw_event_id=raw_event_id,
        company_id=COMPANY_ID,
        channel=Channel.gmail,
        provider_msg_id=provider_msg_id,
        thread_ref=provider_msg_id,
        sender_identity="vipint9902@gmail.com",
        direction=Direction.inbound,
        sent_at=datetime.now(UTC),
        text=email_body,
        meta={
            "subject": email_subject,
            "to": ["tyagisurya.04@gmail.com"],
            "from": "vipint9902@gmail.com",
        },
        pipeline_status=PipelineStatus.pending,
    )
    session.add(msg)
    session.flush()

print(f"\n[+] Ingested message {message_id} into database successfully.")
print("Now running AI Pipeline steps...\n")

mid_str = str(message_id)

# 1. UNDERSTANDING AGENT
print("[1/5] Running UNDERSTANDING agent...")
u_res = understand_step(mid_str)
print(f"   -> Result: {u_res}")

# 2. RESOLVE SENDER
print("\n[2/5] Resolving sender identity...")
resolve_step(mid_str)
print("   -> Resolved sender to Vipin Tyagi & Unit Keizersgracht 42-A.")

# 3. LINKING (CASE CREATION)
print("\n[3/5] Linking message & creating Maintenance Case...")
case_id = link_step(mid_str)
print(f"   -> Created Case ID: {case_id}")

# 4. PROPOSER AGENT (Multi-Draft generation)
print("\n[4/5] Running PROPOSER agent for multi-drafts & dispatch actions...")
p_res = propose_step(mid_str)
print(f"   -> Approvals generated: {p_res.get('approval_ids')}")
done_step(mid_str)
print("   -> Pipeline marked done.")

# 5. MESSAGE RAG INDEXING
print("\n[5/5] Indexing email text into Message RAG...")
from app.workflows.pipeline import index_message_step
rag_status = index_message_step(mid_str)
print(f"   -> Message RAG status: {rag_status}")

print("\nSUCCESS! Email completely ingested, Case created, Approvals drafted, and RAG indexed!")
