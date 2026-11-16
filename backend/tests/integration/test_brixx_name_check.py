"""The mirror the migrations create has every table and column group the code reads (names.READS)."""

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.directory.brixx.name_check import compare, name_gaps

pytestmark = pytest.mark.integration


def test_the_migrated_mirror_satisfies_every_name_the_code_reads(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        assert name_gaps(session) == []


def test_a_missing_table_and_a_missing_column_group_are_reported() -> None:
    gaps = compare({"prg_contract": {"prg_contractid"}})
    assert "prg_relatie: table missing" in gaps
    assert any(gap.startswith("prg_contract: none of ingangsdatum") for gap in gaps)
    assert not any("prg_contractid" in gap for gap in gaps if gap.startswith("prg_contract:"))
