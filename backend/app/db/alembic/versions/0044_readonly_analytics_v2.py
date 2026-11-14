"""readonly_analytics_v2: financial, profit, rates, waits, documents, and audit read-only views

Revision ID: 0044
Revises: 0043
Create Date: 2026-11-13 11:00:00

Extends curated read-only analytics views for the Super Agent Query Agent with EUR-normalized
rent ledger, monthly summaries, unit profitability, waiting radar, vendor rates, documents,
and PII-safe approval/send audit views filtered strictly by `app.company_id`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_VIEWS = [
    "v_rent_ledger",
    "v_monthly_rent_summary",
    "v_unit_profitability",
    "v_waiting_radar",
    "v_vendor_rates",
    "v_documents_overview",
    "v_approval_audit",
    "v_send_stats",
]

ADDITIONAL_BASE_TABLES = [
    "actions",
    "case_links",
    "quotes",
    "quote_lines",
    "quote_reviews",
    "tenant_rent_payments",
    "monthly_rent_summaries",
    "vendor_rates",
    "price_snapshots",
    "waits",
    "documents",
    "document_links",
    "person_profiles",
    "understandings",
    "dd_reviews",
    "memory_items",
    "approvals",
    "sends",
]


def upgrade() -> None:
    # 1. Rent Ledger (EUR normalized, joined with unit & tenant)
    op.execute("""
    CREATE OR REPLACE VIEW v_rent_ledger WITH (security_invoker = true) AS
    SELECT
        trp.company_id,
        trp.id AS rent_payment_id,
        trp.unit_id,
        trp.lease_id,
        trp.tenant_id,
        trp.billing_month,
        trp.invoice_number,
        u.address AS unit_address,
        u.label AS unit_label,
        p.display_name AS tenant_name,
        ROUND(trp.contract_rent_cents / 100.0, 2) AS contract_rent_eur,
        ROUND(trp.amount_paid_cents / 100.0, 2) AS amount_paid_eur,
        ROUND(GREATEST(trp.contract_rent_cents - trp.amount_paid_cents, 0) / 100.0, 2) AS overdue_eur,
        trp.status,
        trp.overdue_days,
        trp.due_date,
        trp.paid_at,
        trp.payment_method
    FROM tenant_rent_payments trp
    JOIN units u ON trp.unit_id = u.id
    JOIN people p ON trp.tenant_id = p.id
    WHERE trp.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid;
    """)

    # 2. Monthly Rent Summary (EUR normalized)
    op.execute("""
    CREATE OR REPLACE VIEW v_monthly_rent_summary WITH (security_invoker = true) AS
    SELECT
        mrs.company_id,
        mrs.billing_month,
        ROUND(mrs.total_scheduled_rent_cents / 100.0, 2) AS scheduled_eur,
        ROUND(mrs.total_collected_rent_cents / 100.0, 2) AS collected_eur,
        ROUND(mrs.total_overdue_rent_cents / 100.0, 2) AS overdue_eur,
        mrs.collection_rate_pct,
        mrs.total_tenants_count,
        mrs.paid_tenants_count,
        mrs.overdue_tenants_count
    FROM monthly_rent_summaries mrs
    WHERE mrs.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid;
    """)

    # 3. Unit Profitability (CTE-aggregated; falls back cleanly to zero maintenance cost if `quotes` is absent)
    op.execute("""
    DO $$
    BEGIN
        IF to_regclass('public.quotes') IS NOT NULL THEN
            EXECUTE $view$
            CREATE OR REPLACE VIEW v_unit_profitability WITH (security_invoker = true) AS
            WITH rent_by_unit AS (
                SELECT
                    trp.unit_id,
                    ROUND(COALESCE(SUM(trp.contract_rent_cents), 0) / 100.0, 2) AS scheduled_rent_eur,
                    ROUND(COALESCE(SUM(trp.amount_paid_cents), 0) / 100.0, 2) AS collected_rent_eur,
                    ROUND(
                        COALESCE(SUM(GREATEST(trp.contract_rent_cents - trp.amount_paid_cents, 0)), 0) / 100.0,
                        2
                    ) AS overdue_rent_eur,
                    COUNT(*) AS rent_invoices_count
                FROM tenant_rent_payments trp
                WHERE trp.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid
                GROUP BY trp.unit_id
            ),
            cost_by_unit AS (
                SELECT
                    c.unit_id,
                    ROUND(COALESCE(SUM(q.total), 0)::numeric, 2) AS maintenance_cost_eur,
                    COUNT(q.id) AS quotes_count
                FROM quotes q
                JOIN cases c ON q.case_id = c.id
                WHERE q.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid
                  AND c.unit_id IS NOT NULL
                GROUP BY c.unit_id
            )
            SELECT
                u.company_id,
                u.id AS unit_id,
                u.address AS unit_address,
                u.label AS unit_label,
                CASE
                    WHEN CURRENT_DATE >= u.valid_from AND (u.valid_to IS NULL OR CURRENT_DATE <= u.valid_to)
                    THEN true ELSE false
                END AS is_active,
                COALESCE(r.scheduled_rent_eur, 0)::numeric(12, 2) AS scheduled_rent_eur,
                COALESCE(r.collected_rent_eur, 0)::numeric(12, 2) AS collected_rent_eur,
                COALESCE(r.overdue_rent_eur, 0)::numeric(12, 2) AS overdue_rent_eur,
                COALESCE(m.maintenance_cost_eur, 0)::numeric(12, 2) AS maintenance_cost_eur,
                (COALESCE(r.collected_rent_eur, 0) - COALESCE(m.maintenance_cost_eur, 0))::numeric(12, 2)
                    AS net_profit_eur,
                CASE
                    WHEN COALESCE(r.collected_rent_eur, 0) > 0
                    THEN ROUND(
                        ((r.collected_rent_eur - COALESCE(m.maintenance_cost_eur, 0)) / r.collected_rent_eur) * 100.0,
                        2
                    )
                    ELSE NULL
                END AS margin_pct,
                COALESCE(r.rent_invoices_count, 0)::integer AS rent_invoices_count,
                COALESCE(m.quotes_count, 0)::integer AS quotes_count
            FROM units u
            LEFT JOIN rent_by_unit r ON u.id = r.unit_id
            LEFT JOIN cost_by_unit m ON u.id = m.unit_id
            WHERE u.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid;
            $view$;
        ELSE
            EXECUTE $view$
            CREATE OR REPLACE VIEW v_unit_profitability WITH (security_invoker = true) AS
            WITH rent_by_unit AS (
                SELECT
                    trp.unit_id,
                    ROUND(COALESCE(SUM(trp.contract_rent_cents), 0) / 100.0, 2) AS scheduled_rent_eur,
                    ROUND(COALESCE(SUM(trp.amount_paid_cents), 0) / 100.0, 2) AS collected_rent_eur,
                    ROUND(
                        COALESCE(SUM(GREATEST(trp.contract_rent_cents - trp.amount_paid_cents, 0)), 0) / 100.0,
                        2
                    ) AS overdue_rent_eur,
                    COUNT(*) AS rent_invoices_count
                FROM tenant_rent_payments trp
                WHERE trp.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid
                GROUP BY trp.unit_id
            )
            SELECT
                u.company_id,
                u.id AS unit_id,
                u.address AS unit_address,
                u.label AS unit_label,
                CASE
                    WHEN CURRENT_DATE >= u.valid_from AND (u.valid_to IS NULL OR CURRENT_DATE <= u.valid_to)
                    THEN true ELSE false
                END AS is_active,
                COALESCE(r.scheduled_rent_eur, 0)::numeric(12, 2) AS scheduled_rent_eur,
                COALESCE(r.collected_rent_eur, 0)::numeric(12, 2) AS collected_rent_eur,
                COALESCE(r.overdue_rent_eur, 0)::numeric(12, 2) AS overdue_rent_eur,
                0.00::numeric(12, 2) AS maintenance_cost_eur,
                COALESCE(r.collected_rent_eur, 0)::numeric(12, 2) AS net_profit_eur,
                CASE
                    WHEN COALESCE(r.collected_rent_eur, 0) > 0 THEN 100.00::numeric(12, 2)
                    ELSE NULL
                END AS margin_pct,
                COALESCE(r.rent_invoices_count, 0)::integer AS rent_invoices_count,
                0::integer AS quotes_count
            FROM units u
            LEFT JOIN rent_by_unit r ON u.id = r.unit_id
            WHERE u.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid;
            $view$;
        END IF;
    END $$;
    """)

    # 4. Waiting Radar (Open & historical waiting-for items joined with cases, units, and counterparty)
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
        w.last_chased_at
    FROM waits w
    LEFT JOIN cases c ON w.case_id = c.id
    LEFT JOIN units u ON c.unit_id = u.id
    LEFT JOIN people p ON w.party_person_id = p.id
    WHERE w.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid;
    """)

    # 5. Vendor Rate Cards (Agreed contractor rates joined with people; empty typed view if `vendor_rates` is absent)
    op.execute("""
    DO $$
    BEGIN
        IF to_regclass('public.vendor_rates') IS NOT NULL THEN
            EXECUTE $view$
            CREATE OR REPLACE VIEW v_vendor_rates WITH (security_invoker = true) AS
            SELECT
                vr.company_id,
                vr.id AS rate_card_id,
                vr.person_id,
                p.display_name AS contractor_name,
                p.trade,
                vr.item_key,
                vr.description,
                vr.unit,
                vr.amount,
                vr.currency,
                vr.source,
                vr.valid_from,
                vr.valid_to
            FROM vendor_rates vr
            JOIN people p ON vr.person_id = p.id
            WHERE vr.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid;
            $view$;
        ELSE
            EXECUTE $view$
            CREATE OR REPLACE VIEW v_vendor_rates WITH (security_invoker = true) AS
            SELECT
                NULL::uuid AS company_id,
                NULL::uuid AS rate_card_id,
                NULL::uuid AS person_id,
                NULL::varchar(200) AS contractor_name,
                NULL::varchar(100) AS trade,
                NULL::varchar(100) AS item_key,
                NULL::varchar(200) AS description,
                NULL::varchar(30) AS unit,
                NULL::numeric(12, 2) AS amount,
                NULL::varchar(3) AS currency,
                NULL::varchar(32) AS source,
                NULL::date AS valid_from,
                NULL::date AS valid_to
            WHERE false;
            $view$;
        END IF;
    END $$;
    """)

    # 6. Documents Overview (Filed documents + entity links)
    op.execute("""
    CREATE OR REPLACE VIEW v_documents_overview WITH (security_invoker = true) AS
    SELECT
        d.company_id,
        d.id AS document_id,
        d.doc_type,
        d.title,
        d.file_name,
        d.status,
        d.confidence,
        d.document_date,
        d.summary,
        d.suspicious,
        dl.kind AS linked_kind,
        dl.ref_id AS linked_ref_id
    FROM documents d
    LEFT JOIN document_links dl ON d.id = dl.document_id
    WHERE d.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid;
    """)

    # 7. Approval Audit (PII-free operational view of approvals & actions)
    op.execute("""
    CREATE OR REPLACE VIEW v_approval_audit WITH (security_invoker = true) AS
    SELECT
        ap.company_id,
        ap.id AS approval_id,
        ap.action_id,
        ac.case_id,
        ac.type AS action_type,
        ap.status,
        ap.choice,
        ap.draft_version,
        ap.decided_at,
        ap.created_at
    FROM approvals ap
    JOIN actions ac ON ap.action_id = ac.id
    WHERE ap.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid;
    """)

    # 8. Outbound Send Stats (PII-free operational view; excludes target email/phone and error traces)
    op.execute("""
    CREATE OR REPLACE VIEW v_send_stats WITH (security_invoker = true) AS
    SELECT
        s.company_id,
        s.action_id,
        s.channel,
        s.status,
        s.attempted_at,
        s.created_at
    FROM sends s
    WHERE s.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid;
    """)

    # 9. Grant SELECT to estateos_readonly for all new views and existing base tables
    views_list = ", ".join(NEW_VIEWS)
    tables_array = ", ".join(f"'{t}'" for t in ADDITIONAL_BASE_TABLES)
    op.execute(f"""
    DO $$
    DECLARE
        tbl text;
    BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'estateos_readonly') THEN
            GRANT SELECT ON {views_list} TO estateos_readonly;
            FOREACH tbl IN ARRAY ARRAY[{tables_array}] LOOP
                IF to_regclass('public.' || tbl) IS NOT NULL THEN
                    EXECUTE format('GRANT SELECT ON %I TO estateos_readonly', tbl);
                END IF;
            END LOOP;
        END IF;
    END $$;
    """)


def downgrade() -> None:
    for view in reversed(NEW_VIEWS):
        op.execute(f"DROP VIEW IF EXISTS {view};")
