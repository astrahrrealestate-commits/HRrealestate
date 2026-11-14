"""Pure parts of BRIXX document bookkeeping (the SQL paths run in tests/integration/test_brixx_documents.py)."""

from unittest.mock import MagicMock
from uuid import UUID

import pytest

from app.db.enums import BrixxDocumentStatus
from app.directory.brixx.document_state import claim_versions, counts_by_status, record_unstored

COMPANY = UUID("018f0000-0000-7000-8000-000000000001")


def test_counts_include_every_status() -> None:
    counts = counts_by_status([(BrixxDocumentStatus.stored, 4), (BrixxDocumentStatus.forbidden, 1)])
    assert counts == {
        BrixxDocumentStatus.pending: 0,
        BrixxDocumentStatus.stored: 4,
        BrixxDocumentStatus.forbidden: 1,
        BrixxDocumentStatus.failed: 0,
    }


def test_nothing_to_claim_touches_no_database() -> None:
    session = MagicMock()
    assert claim_versions(session, COMPANY, []) == []
    session.execute.assert_not_called()


@pytest.mark.parametrize("status", [BrixxDocumentStatus.pending, BrixxDocumentStatus.stored])
def test_only_forbidden_or_failed_are_unstored_outcomes(status: BrixxDocumentStatus) -> None:
    session = MagicMock()
    with pytest.raises(ValueError):
        record_unstored(session, COMPANY, 7, "v1", status, "BrixxError")
    session.execute.assert_not_called()
