"""commitments radar views: overdue days on v_waiting_radar + unified v_commitments_radar

Revision ID: 0063
Revises: 0062
Create Date: 2026-11-27 14:00:00

Extends v_waiting_radar with `is_overdue` and `overdue_days` (Amsterdam morning rule: 1 on the day it becomes due
onwards), and adds `v_commitments_radar` combining Owed by Us (`tasks` promises/reminders) and Owed by Others
(`waits`) so Astra Super Agent can query both sides in one view.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0063"
down_revision: str | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
    CREATE OR REPLACE VIEW v_waiting_radar WITH (security_invoker = true) AS
    SELECT
        w.company_id,
        w.id AS wait_id,
        w.case_id,
        u.address AS unit_address,
        p.display_name AS party_name,
        w.about,
        w.status,
        w.expected_by,
        w.chase_count,
        w.last_chased_at,
        (w.status IN ('waiting', 'escalated') AND w.expected_by <= NOW()) AS is_overdue,
        CASE
            WHEN w.status IN ('waiting', 'escalated') AND w.expected_by <= NOW()
            THEN GREATEST(1, ((NOW() AT TIME ZONE COALESCE(co.timezone, 'Europe/Amsterdam'))::date
                              - (w.expected_by AT TIME ZONE COALESCE(co.timezone, 'Europe/Amsterdam'))::date) + 1)
            ELSE 0
        END AS overdue_days
    FROM waits w
    LEFT JOIN companies co ON w.company_id = co.id
    LEFT JOIN cases c ON w.case_id = c.id
    LEFT JOIN units u ON c.unit_id = u.id
    LEFT JOIN people p ON w.party_person_id = p.id
    WHERE w.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid;
    """)

    op.execute("""
    CREATE OR REPLACE VIEW v_commitments_radar WITH (security_invoker = true) AS
    SELECT
        w.company_id,
        'owed_by_other'::text AS side,
        w.id AS item_id,
        w.case_id,
        u.address AS unit_address,
        p.display_name AS party_name,
        w.about AS title,
        w.status::text AS status,
        w.expected_by AS due_at,
        (w.status IN ('waiting', 'escalated') AND w.expected_by <= NOW()) AS is_overdue,
        CASE
            WHEN w.status IN ('waiting', 'escalated') AND w.expected_by <= NOW()
            THEN GREATEST(1, ((NOW() AT TIME ZONE COALESCE(co.timezone, 'Europe/Amsterdam'))::date
                              - (w.expected_by AT TIME ZONE COALESCE(co.timezone, 'Europe/Amsterdam'))::date) + 1)
            ELSE 0
        END AS overdue_days,
        w.chase_count
    FROM waits w
    LEFT JOIN companies co ON w.company_id = co.id
    LEFT JOIN cases c ON w.case_id = c.id
    LEFT JOIN units u ON c.unit_id = u.id
    LEFT JOIN people p ON w.party_person_id = p.id
    WHERE w.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid
      AND w.status IN ('waiting', 'escalated')

    UNION ALL

    SELECT
        t.company_id,
        'owed_by_us'::text AS side,
        t.id AS item_id,
        t.case_id,
        u.address AS unit_address,
        p.display_name AS party_name,
        t.title AS title,
        t.status::text AS status,
        t.due_at AS due_at,
        (t.due_at IS NOT NULL AND t.due_at <= NOW()) AS is_overdue,
        CASE
            WHEN t.due_at IS NOT NULL AND t.due_at <= NOW()
            THEN GREATEST(1, ((NOW() AT TIME ZONE COALESCE(co.timezone, 'Europe/Amsterdam'))::date
                              - (t.due_at AT TIME ZONE COALESCE(co.timezone, 'Europe/Amsterdam'))::date) + 1)
            ELSE 0
        END AS overdue_days,
        0 AS chase_count
    FROM tasks t
    LEFT JOIN companies co ON t.company_id = co.id
    LEFT JOIN cases c ON t.case_id = c.id
    LEFT JOIN units u ON c.unit_id = u.id
    LEFT JOIN people p ON c.primary_person_id = p.id
    WHERE t.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid
      AND t.assignee = 'owner'
      AND t.source IN ('promise', 'reminder')
      AND t.status IN ('open', 'snoozed');
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_commitments_radar;")
    op.execute("DROP VIEW IF EXISTS v_waiting_radar;")
    op.execute("""
    CREATE VIEW v_waiting_radar WITH (security_invoker = true) AS
    SELECT
        w.company_id,
        w.id AS wait_id,
        w.case_id,
        u.address AS unit_address,
        p.display_name AS party_name,
        w.about,
        w.status,
        w.expected_by,
        w.chase_count,
        w.last_chased_at
    FROM waits w
    LEFT JOIN cases c ON w.case_id = c.id
    LEFT JOIN units u ON c.unit_id = u.id
    LEFT JOIN people p ON w.party_person_id = p.id
    WHERE w.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid;
    """)
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'estateos_readonly') THEN
            GRANT SELECT ON v_waiting_radar TO estateos_readonly;
        END IF;
    END $$;
    """)
