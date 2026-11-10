"""BRIXX directory bookkeeping in `public`: GDPR tombstones and the primary keys a reconcile run has seen."""

import uuid

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CompanyScoped


class BrixxErasedRef(Base, CompanyScoped):
    """A BRIXX relatie erased under GDPR. The mirror upsert and the mapper refuse it, so no re-sync resurrects it."""

    __tablename__ = "brixx_erased_refs"
    __company_id_leading_index__ = True
    __table_args__ = (UniqueConstraint("company_id", "relatie_id"),)

    relatie_id: Mapped[int] = mapped_column(BigInteger)


class BrixxReconcileSeen(Base, CompanyScoped):
    """A primary key BRIXX listed during one reconcile run (staged per page, deleted once the table is applied)."""

    __tablename__ = "brixx_reconcile_seen"
    __company_id_leading_index__ = True
    __table_args__ = (UniqueConstraint("company_id", "run_id", "table_name", "pk"),)

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brixx_sync_runs.id", ondelete="CASCADE"), index=True)
    table_name: Mapped[str] = mapped_column(String(128))
    pk: Mapped[int] = mapped_column(BigInteger)
