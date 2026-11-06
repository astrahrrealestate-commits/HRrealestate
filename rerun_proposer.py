import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.models import ActionRow
from app.pipeline.propose import _persist, _prepare, _run_proposer
from app.workflows.deps import get_engine

msg_id = uuid.UUID("c5505255-4256-4976-b5ae-f035cf5df0b7")
engine = get_engine()
settings = get_settings()

# 1. Clean up old actions
with Session(engine) as session, session.begin():
    old_actions = session.query(ActionRow).filter(ActionRow.context_ref.contains([msg_id])).all()
    old_action_ids = [str(a.id) for a in old_actions]
    if old_action_ids:
        in_clause = ", ".join(f"'{aid}'" for aid in old_action_ids)
        session.execute(text(f"DELETE FROM tasks WHERE action_id IN ({in_clause})"))
        session.execute(text(f"DELETE FROM approvals WHERE action_id IN ({in_clause})"))
        session.execute(text(f"DELETE FROM action_revisions WHERE action_id IN ({in_clause})"))
        session.execute(text(f"DELETE FROM actions WHERE id IN ({in_clause})"))
        print(f"Deleted {len(old_action_ids)} old action(s).")

loaded = _prepare(engine, msg_id, replay=False)

# 2. Call LLM proposer with retry if rate limited
actions = None
for attempt in range(3):
    try:
        print(f"\n[Attempt {attempt + 1}] Running Proposer Agent with Groq LLM...")
        actions = _run_proposer(engine, settings, loaded)
        print(f"-> SUCCESS! Generated {len(actions)} actions.")
        break
    except Exception as e:
        print(f"-> Attempt {attempt + 1} failed: {e}. Waiting 10s...")
        time.sleep(10)

if not actions:
    print("Failed to generate actions.")
    exit(1)

# 3. Persist actions and open approvals in DB
with Session(engine) as session, session.begin():
    res = _persist(session, loaded, msg_id, actions, None)
    print("\nPersisted to database:")
    print(f"Approval IDs: {res.approval_ids}")
    print(f"Exceptions: {res.exceptions}")

# 4. Display generated drafts
with Session(engine) as session:
    rows = session.query(ActionRow).filter(ActionRow.context_ref.contains([msg_id])).all()
    print(f"\n--- {len(rows)} REAL DRAFTS IN DATABASE ---")
    for r in rows:
        print(f"\n[Action: {r.type}] (Status: {r.status})")
        p = r.payload
        if "body_variants" in p:
            print("Variants:")
            for idx, var in enumerate(p["body_variants"], 1):
                clean_text = var.replace("\n", " ").strip()
                print(f"  ({idx}) {clean_text[:110]}...")
        elif "text" in p:
            print(f"Text: {p['text']}")
        elif "reason" in p:
            print(f"Reason: {p['reason']}")
