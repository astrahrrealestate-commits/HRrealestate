"""Directory imported from BRIXX: people, their channel identities, units, leases."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts import Channel
from app.db.base import Base, CompanyScoped, Validity, str_enum
from app.db.enums import ImportStatus, PersonKind


class DirectoryImport(Base, CompanyScoped):
    __tablename__ = "directory_imports"

    source_filename: Mapped[str] = mapped_column(String(255))
    s3_key: Mapped[str] = mapped_column(String(1024))
    status: Mapped[ImportStatus] = mapped_column(str_enum(ImportStatus), default=ImportStatus.pending)
    counts: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text)


class Person(Base, CompanyScoped, Validity):
    __tablename__ = "people"
    __company_id_leading_index__ = True
    __table_args__ = (Index(None, "company_id", "brixx_ref"),)

    kind: Mapped[PersonKind] = mapped_column(str_enum(PersonKind))
    display_name: Mapped[str] = mapped_column(String(200))
    trade: Mapped[str | None] = mapped_column(String(100))
    brixx_ref: Mapped[str | None] = mapped_column(String(64))
    import_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("directory_imports.id"), index=True)


class ChannelIdentity(Base, CompanyScoped, Validity):
    """Phone/email → person. At most one *current* owner per identity; history rows may repeat."""

    __tablename__ = "channel_identities"
    __table_args__ = (
        Index(
            "uq_channel_identities_current",
            "company_id",
            "channel",
            "identity",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
    )

    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("people.id"), index=True)
    channel: Mapped[Channel] = mapped_column(str_enum(Channel))
    identity: Mapped[str] = mapped_column(String(320), index=True)


class Unit(Base, CompanyScoped, Validity):
    __tablename__ = "units"
    __company_id_leading_index__ = True
    __table_args__ = (Index(None, "company_id", "brixx_ref"),)

    label: Mapped[str] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(String(300))
    brixx_ref: Mapped[str | None] = mapped_column(String(64))
    import_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("directory_imports.id"), index=True)


class Lease(Base, CompanyScoped, Validity):
    __tablename__ = "leases"

    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"), index=True)
    brixx_ref: Mapped[str | None] = mapped_column(String(64))
    import_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("directory_imports.id"), index=True)


class LeaseParty(Base, CompanyScoped):
    __tablename__ = "lease_parties"
    __table_args__ = (UniqueConstraint("lease_id", "person_id", "role"),)

    lease_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leases.id"), index=True)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("people.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))  # tenant | co_tenant | guarantor (BRIXX vocabulary, M3)
