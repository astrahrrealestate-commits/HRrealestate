"""agent_brixx_views: read-only views that let the Super Agent see BRIXX tickets and lease facts

Revision ID: 0047
Revises: 0046
Create Date: 2026-11-17 09:00:00

The query agent reads only curated views and a few base tables. BRIXX tickets live in the `brixx` mirror
(`tst_ticket`) and the dashboard's rent, deposit and area come from the mirror at request time, so the agent saw none
of them ("tickets" meant only `cases`). `v_maintenance_tickets` unions EstateOS cases with live BRIXX tickets under one
vocabulary; `v_lease_facts` gives each lease its monthly rent, deposit and living area. Both filter by
`app.company_id` like the other views. They run with the owner's rights (no `security_invoker`; the query tool uses the
application engine, so the company filter is the guard) and are `security_barrier` so a user-written cast or function
cannot be pushed below that filter. `category` is the BRIXX ticket type name for BRIXX rows and the EstateOS category
for cases. `monthly_rent_eur` is the BRIXX contract rent, which can differ from the rent roll. A migration that drops and recreates the mirror tables must recreate these
views; `tests/integration/test_agent_views.py` fails when it does not.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEWS = ["v_maintenance_tickets", "v_lease_facts"]
COMPANY = "NULLIF(current_setting('app.company_id', true), '')::uuid"

TICKETS = f"""
CREATE OR REPLACE VIEW v_maintenance_tickets WITH (security_barrier = true) AS
SELECT
    c.company_id,
    'estateos'::text AS source,
    '#' || right(c.id::text, 6) AS ticket_ref,
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
    );
"""

FACTS = f"""
CREATE OR REPLACE VIEW v_lease_facts WITH (security_barrier = true) AS
SELECT
    l.company_id,
    l.id AS lease_id,
    u.address AS unit_address,
    u.label AS unit_label,
    tenant.display_name AS tenant_name,
    l.valid_from,
    l.valid_to,
    (current_date >= l.valid_from AND (l.valid_to IS NULL OR l.valid_to >= current_date)) AS is_active,
    rent.monthly_rent_eur,
    nullif(contract.waarborgsom, 0) AS deposit_eur,
    area.living_area_sqm
FROM leases l
JOIN units u ON u.id = l.unit_id
LEFT JOIN LATERAL (
    SELECT p.display_name
    FROM lease_parties lp JOIN people p ON p.id = lp.person_id
    WHERE lp.lease_id = l.id AND lp.role = 'tenant'
    LIMIT 1
) tenant ON true
LEFT JOIN LATERAL (
    SELECT CASE WHEN split_part(l.brixx_ref, ':', 1) ~ '^[0-9]+$' THEN split_part(l.brixx_ref, ':', 1)::bigint END AS id,
           CASE WHEN u.brixx_ref ~ '^[0-9]+$' THEN u.brixx_ref::bigint END AS unit_id
) ref ON true
LEFT JOIN brixx.prg_contract contract
    ON contract.company_id = l.company_id AND contract.prg_contractid = ref.id
LEFT JOIN LATERAL (
    SELECT round(sum(
        r.bedragex / CASE WHEN coalesce(r.dm_bedragextermijnmnd, 1) > 1 THEN r.dm_bedragextermijnmnd ELSE 1 END
    ), 2) AS monthly_rent_eur
    FROM brixx.fin_betaalregel r
    JOIN brixx.typ_huurcomponent h
        ON h.company_id = r.company_id AND h.typ_huurcomponentid = r.typ_huurcomponentid
    WHERE r.company_id = l.company_id
        AND r.prg_contractid = ref.id
        AND lower(coalesce(h.benaming, '')) LIKE 'huur%'
        AND r.bedragex > 0
        AND coalesce(r.indverwijderd, 0) = 0
        AND r._deleted_at IS NULL
        AND (r.ingangsdatum IS NULL OR (r.ingangsdatum AT TIME ZONE 'Europe/Amsterdam')::date <= current_date)
        AND (r.einddatum IS NULL OR (r.einddatum AT TIME ZONE 'Europe/Amsterdam')::date >= current_date)
) rent ON true
LEFT JOIN LATERAL (
    SELECT coalesce(nullif(s.vvo, 0), nullif(s.bvo, 0))::int AS living_area_sqm
    FROM brixx.prg_subobject s
    WHERE s.company_id = l.company_id AND s.prg_subobjectid = ref.unit_id
) area ON true
WHERE l.company_id = {COMPANY};
"""


def upgrade() -> None:
    op.execute(TICKETS)
    op.execute(FACTS)
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'estateos_readonly') THEN
            GRANT SELECT ON {", ".join(VIEWS)} TO estateos_readonly;
        END IF;
    END $$;
    """)


def downgrade() -> None:
    for view in reversed(VIEWS):
        op.execute(f"DROP VIEW IF EXISTS {view};")
