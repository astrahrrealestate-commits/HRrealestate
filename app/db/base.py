"""Declarative base, constraint naming convention and column mixins shared by every table."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy import ForeignKey, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.core.ids import new_id

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012  (SQLAlchemy reads this class attribute)
        dict[str, Any]: JSONB,
        datetime: sa.DateTime(timezone=True),
        Decimal: sa.Numeric(12, 2),
    }


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CompanyScoped(IdMixin, CreatedAtMixin):
    """Every domain row belongs to exactly one company (CLAUDE.md invariant 4).

    Same-company consistency between related rows (e.g. message.person_id) is enforced in the repository layer, not
    by composite FKs; revisit (composite FKs or RLS) when a second customer exists.
    Tables that declare a composite index led by `company_id` set `__company_id_leading_index__ = True` to skip the
    redundant single-column index.
    """

    __company_id_leading_index__ = False

    @declared_attr
    def company_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            ForeignKey("companies.id", ondelete="RESTRICT"), index=not cls.__company_id_leading_index__
        )


class Validity:
    """Directory rows are versioned by validity window; `valid_to IS NULL` means current."""

    valid_from: Mapped[date]
    valid_to: Mapped[date | None]


def str_enum(enum_cls: type[StrEnum]) -> sa.Enum:
    """VARCHAR + CHECK (not a native PG enum): adding values later is a plain constraint change."""
    return sa.Enum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        length=32,
        name=None,  # let the metadata convention name the CHECK: ck_<table>_<column>
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )
