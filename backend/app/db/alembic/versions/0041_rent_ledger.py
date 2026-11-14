"""rent ledger: tenant_rent_payments and monthly_rent_summaries

Revision ID: 0041
Revises: 0040
Create Date: 2026-11-11 12:00:00

The Money page's rent ledger (one row per lease and billing month) and its pre-aggregated monthly roll-up.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PAYMENTS = "tenant_rent_payments"
SUMMARIES = "monthly_rent_summaries"


def _base_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _company_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["company_id"], ["companies.id"], name=op.f(f"fk_{table}_company_id_companies"), ondelete="RESTRICT"
    )


def _fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [f"{target}.id"], name=op.f(f"fk_{table}_{column}_{target}"))


def upgrade() -> None:
    op.create_table(
        PAYMENTS,
        *_base_columns(),
        sa.Column("invoice_number", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("lease_id", sa.Uuid(), nullable=False),
        sa.Column("billing_month", sa.Date(), nullable=False),
        sa.Column("contract_rent_cents", sa.BigInteger(), nullable=False),
        sa.Column("amount_paid_cents", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("overdue_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("payment_method", sa.String(length=50), server_default="SEPA Direct Debit", nullable=False),
        sa.Column("transaction_reference", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        _company_fk(PAYMENTS),
        _fk(PAYMENTS, "tenant_id", "people"),
        _fk(PAYMENTS, "unit_id", "units"),
        _fk(PAYMENTS, "lease_id", "leases"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{PAYMENTS}")),
        sa.UniqueConstraint("company_id", "lease_id", "billing_month", name="uq_tenant_monthly_rent"),
    )
    op.create_index(op.f(f"ix_{PAYMENTS}_invoice_number"), PAYMENTS, ["invoice_number"])
    op.create_index(op.f(f"ix_{PAYMENTS}_tenant_id"), PAYMENTS, ["tenant_id"])
    op.create_index(op.f(f"ix_{PAYMENTS}_unit_id"), PAYMENTS, ["unit_id"])
    op.create_index(op.f(f"ix_{PAYMENTS}_lease_id"), PAYMENTS, ["lease_id"])
    op.create_index("ix_rent_company_month", PAYMENTS, ["company_id", "billing_month"])
    op.create_index("ix_rent_status", PAYMENTS, ["company_id", "status"])
    op.create_index("ix_rent_tenant", PAYMENTS, ["company_id", "tenant_id"])

    op.create_table(
        SUMMARIES,
        *_base_columns(),
        sa.Column("billing_month", sa.Date(), nullable=False),
        sa.Column("total_scheduled_rent_cents", sa.BigInteger(), nullable=False),
        sa.Column("total_collected_rent_cents", sa.BigInteger(), nullable=False),
        sa.Column("total_overdue_rent_cents", sa.BigInteger(), nullable=False),
        sa.Column("total_tenants_count", sa.Integer(), nullable=False),
        sa.Column("paid_tenants_count", sa.Integer(), nullable=False),
        sa.Column("overdue_tenants_count", sa.Integer(), nullable=False),
        sa.Column("collection_rate_pct", sa.Numeric(5, 2), nullable=False),
        _company_fk(SUMMARIES),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{SUMMARIES}")),
        sa.UniqueConstraint("company_id", "billing_month", name="uq_monthly_rent_summary"),
    )
    op.create_index("ix_rent_summary_month", SUMMARIES, ["company_id", "billing_month"])


def downgrade() -> None:
    op.drop_table(SUMMARIES)
    op.drop_table(PAYMENTS)
