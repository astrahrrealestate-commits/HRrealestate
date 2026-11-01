"""readonly_analytics: curated views with security_invoker = true and estateos_readonly role

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-31 16:15:00

Creates curated views for the Custom Query Agent and configures the unprivileged role.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEWS = [
    "v_active_leases",
    "v_case_overview",
    "v_task_overview",
    "v_scheduled_visits",
    "v_message_stats",
]

BASE_BUSINESS_TABLES = [
    "cases",
    "units",
    "people",
    "leases",
    "lease_parties",
    "tasks",
    "calendar_events",
    "messages",
]


def upgrade() -> None:
    # 1. Create Views WITH (security_invoker = true)
    op.execute("""
    CREATE OR REPLACE VIEW v_active_leases WITH (security_invoker = true) AS
    SELECT 
        l.company_id,
        l.id AS lease_id,
        u.address AS unit_address,
        u.label AS unit_label,
        p.display_name AS tenant_name,
        l.valid_from,
        l.valid_to,
        CASE 
            WHEN CURRENT_DATE >= l.valid_from AND (l.valid_to IS NULL OR CURRENT_DATE <= l.valid_to) 
            THEN true ELSE false 
        END AS is_active
    FROM leases l
    JOIN units u ON l.unit_id = u.id
    LEFT JOIN lease_parties lp ON l.id = lp.lease_id
    LEFT JOIN people p ON lp.person_id = p.id;
    """)

    op.execute("""
    CREATE OR REPLACE VIEW v_case_overview WITH (security_invoker = true) AS
    SELECT 
        c.company_id,
        c.id AS case_id,
        u.address AS unit_address,
        p.display_name AS tenant_name,
        c.category,
        c.urgency,
        c.state,
        c.opened_at,
        c.summary
    FROM cases c
    LEFT JOIN units u ON c.unit_id = u.id
    LEFT JOIN people p ON c.primary_person_id = p.id;
    """)

    op.execute("""
    CREATE OR REPLACE VIEW v_task_overview WITH (security_invoker = true) AS
    SELECT 
        t.company_id,
        t.id AS task_id,
        t.case_id,
        t.title,
        t.priority,
        t.status,
        t.due_at,
        t.snoozed_until,
        t.done_at
    FROM tasks t;
    """)

    op.execute("""
    CREATE OR REPLACE VIEW v_scheduled_visits WITH (security_invoker = true) AS
    SELECT 
        ce.company_id,
        ce.id AS event_id,
        ce.case_id,
        ce.title,
        ce.location AS unit_address,
        ce.start_time,
        ce.end_time,
        ce.status,
        ce.event_type,
        CASE WHEN ce.lockbox_code IS NOT NULL AND ce.lockbox_code != '' THEN true ELSE false END AS has_lockbox
    FROM calendar_events ce;
    """)

    op.execute("""
    CREATE OR REPLACE VIEW v_message_stats WITH (security_invoker = true) AS
    SELECT 
        m.company_id,
        m.channel,
        m.direction,
        m.pipeline_status,
        m.sent_at,
        m.created_at,
        m.person_id
    FROM messages m;
    """)

    # 2. Configure estateos_readonly role
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'estateos_readonly') THEN
            CREATE ROLE estateos_readonly WITH LOGIN PASSWORD 'estateos_readonly_safe';
        END IF;
    END
    $$;
    """)

    op.execute("ALTER ROLE estateos_readonly SET default_transaction_read_only = on;")
    op.execute("ALTER ROLE estateos_readonly SET statement_timeout = '4000';")
    op.execute("ALTER ROLE estateos_readonly SET lock_timeout = '1000';")

    op.execute("GRANT USAGE ON SCHEMA public TO estateos_readonly;")
    
    # Views grants
    op.execute("""
    GRANT SELECT ON 
        v_active_leases, 
        v_case_overview, 
        v_task_overview, 
        v_scheduled_visits, 
        v_message_stats 
    TO estateos_readonly;
    """)

    # Base table grants required for security_invoker views
    tables_list = ", ".join(BASE_BUSINESS_TABLES)
    op.execute(f"GRANT SELECT ON {tables_list} TO estateos_readonly;")


def downgrade() -> None:
    for view in reversed(VIEWS):
        op.execute(f"DROP VIEW IF EXISTS {view};")
    op.execute("REVOKE ALL ON SCHEMA public FROM estateos_readonly;")
