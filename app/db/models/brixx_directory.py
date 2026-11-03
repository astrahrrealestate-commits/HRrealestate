"""BRIXX directory bookkeeping in `public`: GDPR tombstones for erased relaties."""

from sqlalchemy import BigInteger, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CompanyScoped


class BrixxErasedRef(Base, CompanyScoped):
    """A BRIXX relatie erased under GDPR. The mirror upsert and the mapper refuse it, so no re-sync resurrects it."""

    __tablename__ = "brixx_erased_refs"
    __company_id_leading_index__ = True
    __table_args__ = (UniqueConstraint("company_id", "relatie_id"),)

    relatie_id: Mapped[int] = mapped_column(BigInteger)
