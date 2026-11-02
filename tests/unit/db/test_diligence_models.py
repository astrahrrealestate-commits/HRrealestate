"""Due diligence tables (migration 0023): company scope, uniques, indexes, nullability, status vocabulary."""

from sqlalchemy import Table, UniqueConstraint

import app.db.models  # noqa: F401  (registers tables)
from app.db.base import Base
from app.db.enums import DDReviewStatus, FeedKind

DD_TABLES = ("dd_reviews", "dd_review_documents", "dd_document_reads")


def _unique_names(table: Table) -> set[str]:
    return {str(u.name) for u in table.constraints if isinstance(u, UniqueConstraint)}


def _index_columns(table: Table) -> set[tuple[str, ...]]:
    return {tuple(c.name for c in i.columns) for i in table.indexes}


def test_every_table_is_company_scoped() -> None:
    for name in DD_TABLES:
        assert name in Base.metadata.tables, name
        assert not Base.metadata.tables[name].c.company_id.nullable, name


def test_uniques_back_the_do_once_rules() -> None:
    tables = Base.metadata.tables
    assert "uq_dd_review_documents_review_id_document_id" in _unique_names(tables["dd_review_documents"])
    assert "uq_dd_document_reads_company_id_document_id_reader_version" in _unique_names(tables["dd_document_reads"])


def test_lookup_indexes_lead_with_company_id() -> None:
    tables = Base.metadata.tables
    assert ("company_id", "created_at") in _index_columns(tables["dd_reviews"])
    assert ("company_id", "review_id") in _index_columns(tables["dd_review_documents"])


def test_report_is_empty_until_the_run_finishes() -> None:
    reviews = Base.metadata.tables["dd_reviews"]
    for column in ("report", "verdict", "framework_version", "error", "completed_at", "unit_id"):
        assert reviews.c[column].nullable, column
    assert not reviews.c.run_no.nullable


def test_status_and_feed_vocabulary() -> None:
    assert [s.value for s in DDReviewStatus] == ["pending", "running", "done", "failed"]
    assert FeedKind.dd_report.value == "dd_report"
