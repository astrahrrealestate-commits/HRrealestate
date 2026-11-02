from app.core.settings import Settings
from app.db.models import ActionRow, Case, MessageRow, RawEvent, UnderstandingRow
from app.db.session import make_engine, session_factory

settings = Settings()
engine = make_engine(str(settings.database_url))
Session = session_factory(engine)

with Session() as s:
    events = s.query(RawEvent).all()
    messages = s.query(MessageRow).all()
    cases = s.query(Case).all()
    actions = s.query(ActionRow).all()
    understandings = s.query(UnderstandingRow).all()

    print("=== DATABASE STATUS ===")
    print(f"Total RawEvents: {len(events)}")
    print(f"Total Messages: {len(messages)}")
    print(f"Total Cases: {len(cases)}")
    print(f"Total Proposed Actions: {len(actions)}")
    print(f"Total Understandings: {len(understandings)}")

    print("\n--- Last 5 Messages in Database ---")
    for m in messages[-5:]:
        subject = m.meta.get("subject", "No Subject") if isinstance(m.meta, dict) else "No Subject"
        print(f"- From: {m.sender_identity} | Subject: '{subject}' | Sent: {m.sent_at}")
        preview = m.text.replace("\n", " ")[:80] if m.text else ""
        print(f"  Preview: {preview}...")

    print("\n--- Last 3 Cases ---")
    for c in cases[-3:]:
        print(f"- Case #{c.id} | Category: {c.category} | Urgency: {c.urgency} | State: {c.state}")
        print(f"  Summary: {c.summary[:80]}...")

    print("\n--- Last 3 Proposed Actions ---")
    for a in actions[-3:]:
        payload = a.payload or {}
        print(f"- Action #{a.id} | Type: {a.type} | Status: {a.status} | Subject: {payload.get('subject', 'N/A')}")
