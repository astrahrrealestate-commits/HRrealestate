"""Cached Dutch to English translations, keyed by the text (ADR 0011): one model run per distinct text and company."""

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CompanyScoped


class Translation(Base, CompanyScoped):
    """The English for one source text. Messages, drafts and any other text share it. The source is not stored (the
    hash identifies it), but this English copy is personal text too: `erase_person` deletes it with the messages."""

    __tablename__ = "translations"
    __company_id_leading_index__ = True
    __table_args__ = (UniqueConstraint("company_id", "source_hash"),)

    source_hash: Mapped[str] = mapped_column(String(64))  # sha256 of the normalised source text
    source_lang: Mapped[str] = mapped_column(String(8))
    text_en: Mapped[str] = mapped_column(Text)
    engine: Mapped[str] = mapped_column(String(64))
