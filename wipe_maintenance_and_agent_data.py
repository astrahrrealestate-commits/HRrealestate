import os

from dotenv import load_dotenv

load_dotenv("d:/estateos/realestateos/.env")

from sqlalchemy import create_engine, text


def wipe():
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as conn:
        print("Starting complete maintenance, messaging, and Super Agent wipe...")

        # 1. Super Agent Conversations & Turns
        conn.execute(text("UPDATE agent_conversations SET summary_through = NULL"))
        conn.execute(text("DELETE FROM agent_turns"))
        conn.execute(text("DELETE FROM agent_conversations"))
        conn.execute(text("DELETE FROM agent_page_state"))
        conn.execute(text("DELETE FROM memory_items"))
        print("[OK] Cleared Super Agent turns, conversations, page states, and memory items.")

        # 2. Tasks, Approvals, Action Revisions, Actions
        conn.execute(text("DELETE FROM tasks"))
        conn.execute(text("DELETE FROM approvals"))
        conn.execute(text("DELETE FROM action_revisions"))
        conn.execute(text("DELETE FROM actions"))
        print("[OK] Cleared all tasks, approvals, and actions.")

        # 3. Cases, Case Links, Case Events
        conn.execute(text("DELETE FROM case_links"))
        conn.execute(text("DELETE FROM case_events"))
        conn.execute(text("DELETE FROM cases"))
        print("[OK] Cleared all maintenance cases and case events (0 tickets remaining).")

        # 4. Documents & Ingestion: Documents, Attachments, Understandings, RAG Chunks, Messages, Raw Events
        conn.execute(text("DELETE FROM drive_reorg_items"))
        conn.execute(text("DELETE FROM document_chunks"))
        conn.execute(text("DELETE FROM document_links"))
        conn.execute(text("DELETE FROM documents"))
        conn.execute(text("DELETE FROM understandings"))
        conn.execute(text("DELETE FROM attachments"))
        conn.execute(text("DELETE FROM message_chunks"))
        conn.execute(text("DELETE FROM message_index_state"))
        conn.execute(text("DELETE FROM messages"))
        conn.execute(text("DELETE FROM raw_events"))
        print("[OK] Cleared all documents, messages, understandings, attachments, and raw events.")

        # 5. Delete test entities tagged with 'test_planner_eval'
        conn.execute(
            text("""
            DELETE FROM lease_parties
            WHERE person_id IN (SELECT id FROM people WHERE brixx_ref = 'test_planner_eval')
        """)
        )
        conn.execute(
            text("""
            DELETE FROM leases
            WHERE brixx_ref = 'test_planner_eval'
        """)
        )
        conn.execute(
            text("""
            DELETE FROM channel_identities
            WHERE person_id IN (SELECT id FROM people WHERE brixx_ref = 'test_planner_eval')
        """)
        )
        conn.execute(
            text("""
            DELETE FROM people
            WHERE brixx_ref = 'test_planner_eval'
        """)
        )
        print("[OK] Cleared all temporary test-tagged people and leases.")

        print("\n--- Verification of Database State ---")
        for table in [
            "cases",
            "messages",
            "actions",
            "approvals",
            "agent_turns",
            "agent_conversations",
            "memory_items",
        ]:
            count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()
            print(f"Table '{table}': {count} rows")

        units_count = conn.execute(text("SELECT count(*) FROM units")).scalar()
        people_count = conn.execute(text("SELECT count(*) FROM people")).scalar()
        owner_count = conn.execute(text("SELECT count(*) FROM owner_accounts")).scalar()
        print(f"Preserved units: {units_count} units")
        print(f"Preserved directory people: {people_count} people")
        print(f"Preserved owner accounts: {owner_count} owner")


if __name__ == "__main__":
    wipe()
