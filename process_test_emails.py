import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Ensure .env is always loaded from realestateos root regardless of where python is invoked
load_dotenv(Path(__file__).resolve().parent / ".env")

from sqlalchemy import select
from sqlalchemy.orm import Session
from app.workflows.deps import get_engine
from app.db.models.ingestion import MessageRow
from app.workflows.pipeline import done_step, link_step, propose_step, resolve_step, understand_step

engine = get_engine()
with Session(engine) as session:
    pending_messages = session.scalars(
        select(MessageRow).where(MessageRow.pipeline_status == "pending")
    ).all()

if not pending_messages:
    print("\n[!] No pending messages found in the database.")
    print("    (The database was cleared previously. If you sent a new email, sync it, or seed test messages first.)")
    sys.exit(0)

print(f"\nFound {len(pending_messages)} pending message(s) to process through AI Pipeline...\n")

for msg in pending_messages:
    mid = str(msg.id)
    print("==========================================")
    print(f"Processing Message {mid} from {msg.sender_identity}")
    print("==========================================")

    # 1. UNDERSTANDING AGENT
    print("[1/4] Running UNDERSTANDING agent...")
    try:
        u_res = understand_step(mid)
        print(f"   -> Result: {u_res}")
    except Exception as e:
        print(f"   -> Understanding error: {e}")
        continue
    time.sleep(1)

    # 2. RESOLVE SENDER
    print("[2/4] Resolving sender identity...")
    try:
        resolve_step(mid)
    except Exception as e:
        print(f"   -> Resolve error: {e}")

    # 3. LINKING (Case Creation / Linking)
    print("[3/4] Linking message to Case...")
    case_id = None
    try:
        case_id = link_step(mid)
        print(f"   -> Linked Case ID: {case_id}")
    except Exception as e:
        print(f"   -> Linking error: {e}")
    time.sleep(1)

    # 4. PROPOSER AGENT (Multi-Draft generation)
    if case_id:
        print("[4/4] Running PROPOSER agent for multi-drafts...")
        try:
            p_res = propose_step(mid)
            print(f"   -> Generated Approvals: {p_res.get('approval_ids')}")
            print(f"   -> Exceptions: {p_res.get('exceptions')}")
            done_step(mid)
            print("   -> Pipeline marked done.")
        except Exception as e:
            print(f"   -> Proposer error: {e}")

    print("\nMessage completed!")

print("\nALL PENDING MESSAGES PROCESSED SUCCESSFULLY!")
