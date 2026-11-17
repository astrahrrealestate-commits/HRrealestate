"""case_brixx_ref: link maintenance cases to BRIXX tickets

Revision ID: 0048
Revises: 0047
Create Date: 2026-11-17 11:35:00

Adds `brixx_ref` to `cases` table so inbound tenant messages reporting maintenance
can be linked directly to an existing BRIXX ERP work order (TST_TICKET).
Updates view `v_maintenance_tickets` to deduplicate and join linked cases.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COMPANY = "NULLIF(current_setting('app.company_id', true), '')::uuid"

TICKETS = f"""
CREATE OR REPLACE VIEW v_maintenance_tickets WITH (security_barrier = true) AS
SELECT
    c.company_id,
    CASE WHEN c.brixx_ref IS NOT NULL THEN 'linked'::text ELSE 'estateos'::text END AS source,
    COALESCE('BRIXX-' || c.brixx_ref, '#' || right(c.id::text, 6)) AS ticket_ref,
    u.address AS unit_address,
    p.display_name AS tenant_name,
    NULL::text AS contractor_name,
    c.summary AS title,
    c.category::text AS category,
    c.urgency::text AS urgency,
    c.state::text AS status,
    (c.state::text IN ('open', 'waiting_on_owner', 'waiting_on_third_party')) AS is_open,
    c.opened_at,
    c.resolved_at AS closed_at
FROM cases c
LEFT JOIN units u ON c.unit_id = u.id
LEFT JOIN people p ON c.primary_person_id = p.id
WHERE c.company_id = {COMPANY}
UNION ALL
SELECT
    t.company_id,
    'brixx'::text,
    'BRIXX-' || t.tst_ticketid::text,
    u.address,
    tenant.display_name,
    contractor.display_name,
    t.titel,
    ty.benaming,
    CASE WHEN t.indurgent = 1 THEN 'high' ELSE 'normal' END,
    CASE
        WHEN done.closed THEN 'completed'
        WHEN t.dienstverlenerid IS NOT NULL OR upper(coalesce(t.dmticketstatus, '')) LIKE '%DIENSTVERLENER%'
            THEN 'dispatched'
        ELSE 'scheduled'
    END,
    NOT done.closed,
    t.newdatetime,
    t.datumgesloten
FROM brixx.tst_ticket t
CROSS JOIN LATERAL (
    SELECT t.datumgesloten IS NOT NULL
        OR upper(coalesce(t.dmticketstatus, '')) ~ '(AFGEHANDELD|GESLOTEN|AFGEROND|GEANNULEERD)' AS closed
) done
LEFT JOIN units u ON u.company_id = t.company_id AND u.brixx_ref = t.prg_subobjectid::text
LEFT JOIN people tenant ON tenant.company_id = t.company_id AND tenant.brixx_ref = t.prg_relatieid::text
LEFT JOIN people contractor ON contractor.company_id = t.company_id AND contractor.brixx_ref = t.dienstverlenerid::text
LEFT JOIN brixx.typ_tickettype ty ON ty.company_id = t.company_id AND ty.typ_tickettypeid = t.typ_tickettypeid
WHERE t.company_id = {COMPANY}
    AND coalesce(t.indverwijderd, 0) = 0
    AND t._deleted_at IS NULL
    AND NOT EXISTS (
        SELECT 1 FROM brixx_erased_refs e WHERE e.company_id = t.company_id AND e.relatie_id = t.prg_relatieid
    )
    AND NOT EXISTS (
        SELECT 1 FROM cases c2 WHERE c2.company_id = t.company_id AND c2.brixx_ref = t.tst_ticketid::text
    );
"""


def upgrade() -> None:
    op.add_column("cases", sa.Column("brixx_ref", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_cases_company_id_brixx_ref",
        "cases",
        ["company_id", "brixx_ref"],
        unique=False,
        postgresql_where=sa.text("brixx_ref IS NOT NULL"),
    )
    op.execute(TICKETS)


def downgrade() -> None:
    op.drop_index("ix_cases_company_id_brixx_ref", table_name="cases")
    op.drop_column("cases", "brixx_ref")
