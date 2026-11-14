from datetime import date

import pytest
from pydantic import ValidationError

from app.contracts import DocType, DocumentClassification


def test_document_classification_limits() -> None:
    DocumentClassification(doc_type=DocType.invoice, title="Factuur loodgieter", document_date=None, confidence=0.9)
    DocumentClassification(doc_type=DocType.lease, title="t" * 80, document_date=date(2026, 1, 1), confidence=0.0)
    with pytest.raises(ValidationError):
        DocumentClassification(doc_type=DocType.other, title="t" * 81, document_date=None, confidence=0.5)
    with pytest.raises(ValidationError):
        DocumentClassification(doc_type=DocType.other, title="  ", document_date=None, confidence=0.5)
    with pytest.raises(ValidationError):
        DocumentClassification(doc_type=DocType.other, title="x", document_date=None, confidence=1.2)


def test_doc_types_are_stable_db_values() -> None:
    assert [t.value for t in DocType] == [
        "lease", "invoice", "quote", "id_document", "insurance", "certificate", "correspondence", "photo", "other",
    ]  # fmt: skip
