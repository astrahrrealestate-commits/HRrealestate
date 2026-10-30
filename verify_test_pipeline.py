"""Comprehensive pipeline inspection script for live test emails.

Checks the complete lifecycle:
1. RawEvent (Webhook Ingestion)
2. MessageRow (Normalized text & attachments)
3. Person (Identity Directory resolution)
4. UnderstandingRow (UNDERSTANDING Agent: category, urgency, entities)
5. Case & CaseLink (Context Linking & LINK_CHECK / CASE_SUMMARY Agents)
6. ActionRow & Approval (PROPOSER Agent: drafts, PO limits, work orders)
7. ModelCalls (Langfuse / LLM token cost & latency log)
"""

from datetime import UTC, datetime
from sqlalchemy import select
from app.core.settings import Settings
from app.db.session import make_engine, session_factory
from app.db.models import (
    RawEvent,
    MessageRow,
    Person,
    UnderstandingRow,
    Case,
    CaseLink,
    ActionRow,
    Approval,
    ModelCall,
)

settings = Settings()
engine = make_engine(str(settings.database_url))
Session = session_factory(engine)


def inspect_pipeline():
    with Session() as s:
        print("================================================================")
        print("           ESTATEOS PIPELINE & AGENT VERIFICATION               ")
        print("================================================================")
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"Timestamp: {now}\n")

        # 1. Total counts
        events = s.query(RawEvent).all()
        messages = s.query(MessageRow).all()
        persons = s.query(Person).all()
        understandings = s.query(UnderstandingRow).all()
        cases = s.query(Case).all()
        actions = s.query(ActionRow).all()
        approvals = s.query(Approval).all()
        model_calls = s.query(ModelCall).all()

        print("--- 1. DATABASE ROW TOTALS ---")
        print(f"* Inbound RawEvents:     {len(events)}")
        print(f"* Normalized Messages:   {len(messages)}")
        print(f"* Resolved Persons:      {len(persons)}")
        print(f"* AI Understandings:     {len(understandings)}")
        print(f"* Active Cases:          {len(cases)}")
        print(f"* Proposed Actions:      {len(actions)}")
        print(f"* Pending Approvals:     {len(approvals)}")
        print(f"* LLM Agent Calls:       {len(model_calls)}\n")

        # 2. Latest Messages and their Agent Pipeline Results
        print("--- 2. LATEST MESSAGES & AGENT TRACES (LAST 3) ---")
        latest_msgs = messages[-3:] if messages else []
        if not latest_msgs:
            print("No messages received yet. Send a test email and run again.")
            return

        for idx, m in enumerate(latest_msgs, 1):
            subject = m.meta.get("subject", "No Subject") if isinstance(m.meta, dict) else "No Subject"
            from_name = m.meta.get("from_name", "Unknown") if isinstance(m.meta, dict) else "Unknown"
            person = s.get(Person, m.person_id) if m.person_id else None
            person_name = person.display_name if person else "Unresolved"
            person_kind = person.kind.value if person else "N/A"

            und = s.scalar(select(UnderstandingRow).where(UnderstandingRow.message_id == m.id))
            link = s.scalar(select(CaseLink).where(CaseLink.message_id == m.id))
            case = s.get(Case, link.case_id) if link else None

            case_actions = s.scalars(
                select(ActionRow).where(ActionRow.context_ref.contains([m.id]))
            ).all()

            print(f"\n[Message #{idx}] ID: {m.id}")
            print(f"  * Sender: {from_name} <{m.sender_identity}> (Channel: {m.channel.value})")
            print(f"  * Subject: \"{subject}\"")
            print(f"  * Text Snippet: {m.text[:120].replace(chr(10), ' ')}...")
            print(f"  * Identity Directory: Resolved to '{person_name}' (Role: {person_kind})")

            # Agent 1: Understanding
            if und:
                body = und.body or {}
                entities = body.get("entities", {})
                print(f"  [OK] Agent UNDERSTANDING:")
                print(f"    - Category: {und.category.value} | Urgency: {und.urgency.value}")
                print(f"    - Requires Reply: {body.get('requires_reply')} | Sentiment: {body.get('sentiment')}")
                if entities:
                    print(f"    - Entities: {entities}")
            else:
                print(f"  [--] Agent UNDERSTANDING: Not run or pending")

            # Agent 2 & 3: Linking & Summary
            if case:
                print(f"  [OK] Agent LINK_CHECK & CASE_SUMMARY:")
                print(f"    - Linked to Case: #{case.id} (Category: {case.category.value})")
                print(f"    - Rolling Summary: \"{case.summary}\"")
            else:
                print(f"  [--] Context Linking: Not linked to a case")

            # Agent 4: Proposer
            if case_actions:
                print(f"  [OK] Agent PROPOSER:")
                for a in case_actions:
                    payload = a.payload or {}
                    variants = payload.get("body_variants") or []
                    print(f"    - Action Type: {a.type.value} | Status: {a.status.value}")
                    if variants:
                        print(f"    - Generated {len(variants)} Reply Drafts:")
                        for v_idx, v in enumerate(variants, 1):
                            clean_v = v.replace('\n', ' ')[:90]
                            print(f"      [{v_idx}] {clean_v}...")
            else:
                print(f"  [--] Agent PROPOSER: No actions proposed yet")

        # 3. LLM Model Calls Log
        print("\n--- 3. LLM MODEL CALL METRICS (LAST 3 CALLS) ---")
        for mc in model_calls[-3:]:
            print(f"* Agent: {mc.agent_name:<15} | Tokens: {mc.total_tokens:<5} | Latency: {mc.latency_ms}ms | Cost: ${mc.estimated_cost_usd or 0:.5f}")

        print("\n================================================================")
        print("All checks completed. If any row is missing, check server logs.")
        print("================================================================")


if __name__ == "__main__":
    inspect_pipeline()
