"""the read-only analytics role never sees Chats-only WhatsApp messages

Revision ID: 0052
Revises: 0051
Create Date: 2026-11-25 13:00:00

The Super Agent's custom query agent reads `messages` (and `v_message_stats`) as `estateos_readonly`. A WhatsApp chat
that lives only in Chats (`pipeline_status = 'skipped'`, ADR 0015) must stay out of what the AI can read. A RESTRICTIVE
row-level-security policy on that one role does it for the base table and for every view over it (the views are
`security_invoker`). Every other role keeps full access through the permissive policy; the table owner (the app and the
migrations) bypasses row security as before.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY messages_all_roles ON messages FOR ALL USING (true) WITH CHECK (true)")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'estateos_readonly') THEN
                CREATE POLICY messages_readonly_no_chat_only ON messages AS RESTRICTIVE FOR SELECT
                    TO estateos_readonly USING (pipeline_status <> 'skipped');
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS messages_readonly_no_chat_only ON messages")
    op.execute("DROP POLICY IF EXISTS messages_all_roles ON messages")
    op.execute("ALTER TABLE messages DISABLE ROW LEVEL SECURITY")
