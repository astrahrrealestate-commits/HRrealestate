"""six categories: maintenance, finance, legal, business, administration, new_projects (+ spam)

Revision ID: 0054
Revises: 0053
Create Date: 2026-11-25 18:00:00

M13 replaces the eight case categories with the six business areas Harjot works by. Old values are mapped on
`cases.category`, `understandings.category` and the stored understanding body (`body->>'category'`), because the
proposer validates that body with the strict `Understanding` contract. The downgrade maps each new value back to one
old value; it cannot tell a complaint from a repair again.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW = ("maintenance", "finance", "legal", "business", "administration", "new_projects", "spam")
OLD = ("maintenance", "payment", "lease", "complaint", "contractor_update", "admin", "spam", "other")
UP = {
    "contractor_update": "maintenance",
    "complaint": "maintenance",
    "payment": "finance",
    "lease": "legal",
    "admin": "administration",
    "other": "administration",
}
DOWN = {"finance": "payment", "legal": "lease", "business": "admin", "administration": "admin", "new_projects": "other"}


def _remap(mapping: dict[str, str], allowed: tuple[str, ...]) -> None:
    for table in ("cases", "understandings"):
        op.drop_constraint(op.f(f"ck_{table}_category"), table, type_="check")
    for old, new in mapping.items():
        op.execute(f"UPDATE cases SET category = '{new}' WHERE category = '{old}'")
        op.execute(f"UPDATE understandings SET category = '{new}' WHERE category = '{old}'")
        op.execute(
            "UPDATE understandings SET body = jsonb_set(body, '{category}', "
            f"to_jsonb('{new}'::text)) WHERE body->>'category' = '{old}'"
        )
    values = ", ".join(f"'{v}'" for v in allowed)
    for table in ("cases", "understandings"):
        op.create_check_constraint(op.f(f"ck_{table}_category"), table, f"category IN ({values})")


def upgrade() -> None:
    _remap(UP, NEW)


def downgrade() -> None:
    _remap(DOWN, OLD)
