"""brixx ocr attempts: failed vision reads of a scanned BRIXX document

Revision ID: 0062
Revises: 0061
Create Date: 2026-11-27 13:00:00

Scanned BRIXX documents are read through vision. A version whose read keeps failing is retried on later syncs, goes
to the back of the backlog, and is given up after a few tries, so an outage or one broken file never loops forever.
BRIXX library rows skipped as "no text" before scans were read are removed (derived rows): the backlog reads them again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0062"
down_revision: str | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("brixx_documents", sa.Column("ocr_attempts", sa.Integer(), server_default="0", nullable=False))
    op.execute(
        "DELETE FROM documents WHERE brixx_document_id IS NOT NULL AND status = 'skipped' AND error = 'no text'"
    )  # chunks and links cascade (a skipped row has none)


def downgrade() -> None:
    op.drop_column("brixx_documents", "ocr_attempts")
