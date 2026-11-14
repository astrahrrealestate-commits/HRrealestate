"""Which mirrored PRG_DOCUMENT rows still need a download: SQL shape only (execution: integration tests)."""

from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.channels.brixx.models import BrixxField, BrixxTable
from app.core.errors import BrixxError
from app.directory.brixx.document_candidates import candidates_query, version_expression
from app.directory.brixx.schema import build_table

COMPANY = UUID("018f0000-0000-7000-8000-000000000001")


def _table(*fields: BrixxField, name: str = "PRG_DOCUMENT") -> sa.Table:
    pk = BrixxField(1, "PRG_DOCUMENTID", "NUMBER", True, None, None)
    return build_table(BrixxTable(name, "PRG_DOCUMENTID", (pk, *fields)), sa.MetaData())


def _sql(element: sa.ColumnElement[str] | sa.Select[int, str]) -> str:
    return str(element.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


VERSIENR = BrixxField(2, "VERSIENR", "NUMBER", False, None, None)
UPD_TS = BrixxField(3, "UPDDATETIME", "TIMESTAMP(6)", False, None, None)
UPD_DATE = BrixxField(3, "UPDDATETIME", "DATE", False, None, None)
UPD_TEXT = BrixxField(3, "UPDDATETIME", "VARCHAR(30)", False, None, None)


def test_version_combines_versienr_and_upddatetime_in_utc() -> None:
    sql = _sql(version_expression(_table(VERSIENR, UPD_TS)))
    assert "CAST(brixx.prg_document.versienr AS TEXT)" in sql
    assert "timezone('UTC', brixx.prg_document.upddatetime)" in sql  # independent of the session time zone


@pytest.mark.parametrize("field", [UPD_DATE, UPD_TEXT])
def test_version_reads_dates_and_text_without_session_dependence(field: BrixxField) -> None:
    sql = _sql(version_expression(_table(field)))
    assert "upddatetime" in sql
    assert "timezone(" not in sql


def test_a_table_without_version_columns_has_one_constant_version() -> None:
    assert "'-'" in _sql(version_expression(_table()))


def test_candidates_are_company_scoped_live_unsettled_rows_in_key_order() -> None:
    sql = _sql(candidates_query(_table(VERSIENR, UPD_TS), COMPANY, 500))
    assert f"brixx.prg_document.company_id = '{COMPANY}'" in sql.replace("::UUID", "")
    assert f"brixx_documents.company_id = '{COMPANY}'" in sql.replace("::UUID", "")
    assert "brixx.prg_document._deleted_at IS NULL" in sql
    assert "NOT (EXISTS" in sql
    assert "brixx_documents.attempts >= 3" in sql  # failed versions out of attempts are settled too
    assert "ORDER BY brixx.prg_document.prg_documentid" in sql
    assert sql.rstrip().endswith("LIMIT 500")


def test_candidates_refuse_a_non_positive_limit() -> None:
    with pytest.raises(BrixxError):
        candidates_query(_table(), COMPANY, 0)
