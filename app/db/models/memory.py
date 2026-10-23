"""T5 Preferences & Standing Memory: rules, preferences and distilled facts (spec §6.2, Task C11)."""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.settings import EMBEDDING_DIMENSIONS
from app.db.base import Base, CompanyScoped, str_enum
from app.db.enums import MemoryKind, MemoryOrigin, MemoryScope, MemoryStatus


class MemoryItem(Base, CompanyScoped):
    """T5 Standing Preferences and Rules.

    Active items with origin=owner are rendered in the proposer's <owner_preferences> block.
    """

    __tablename__ = "memory_items"
    __company_id_leading_index__ = True
    __table_args__ = (
        Index("ix_memory_items_company_status", "company_id", "status"),
        Index("ix_memory_items_scope_lookup", "company_id", "scope", "scope_id"),
        Index(
            "uq_memory_items_active",
            "company_id",
            "scope",
            "scope_id",
            func.lower(text("text")),
            unique=True,
            postgresql_where=text("status <> 'retired'"),
        ),
        Index(
            "ix_memory_items_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    scope: Mapped[MemoryScope] = mapped_column(str_enum(MemoryScope))
    scope_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    kind: Mapped[MemoryKind] = mapped_column(str_enum(MemoryKind))
    text: Mapped[str] = mapped_column(String(300))
    status: Mapped[MemoryStatus] = mapped_column(
        str_enum(MemoryStatus), default=MemoryStatus.proposed, server_default=MemoryStatus.proposed.value
    )
    origin: Mapped[MemoryOrigin] = mapped_column(str_enum(MemoryOrigin))
    source_refs: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    evidence_count: Mapped[int] = mapped_column(default=1, server_default="1")
    confidence: Mapped[float] = mapped_column(default=1.0, server_default="1.0")
    embedding: Mapped[Any | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)
    last_used_at: Mapped[datetime | None]
    valid_until: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
