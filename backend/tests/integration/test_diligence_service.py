"""Due diligence service against Postgres: creating and restarting reviews, cached reads, the compiled report."""

from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from app.contracts.diligence import DDPropertyKind
from app.contracts.diligence_report import DDVerdict
from app.core.errors import DiligenceRequestError, NotFoundError
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.enums import DDReviewStatus, FeedKind
from app.db.models import Company, DDDocumentRead, DocumentRow, ModelCall, OwnerFeed
from app.diligence import repo, service
from app.diligence.framework import default_framework
from app.llm.agents.dd_reader import MAX_DOCUMENT_CHARS
from tests.integration.diligence_support import make_document

pytestmark = pytest.mark.integration
TODAY = date(2026, 10, 31)
BROCHURE = "Verkoopbrochure Kerkstraat 12\nBouwjaar: 1985\nWoonoppervlakte: 95 m2\nEnergielabel: B"
DEED = "Akte van levering\nBouwjaar: 1965\nGebruiksoppervlakte: 95 m2"


@pytest.fixture
def company_id(committed_company: Company) -> UUID:
    return committed_company.id


def _doc(engine: Engine, company_id: UUID, text: str | None, **kw: object) -> UUID:
    with Session(engine) as s, s.begin():
        return make_document(s, company_id, text, **kw)  # type: ignore[arg-type]


def _review(engine: Engine, company_id: UUID, docs: list[UUID]) -> UUID:
    return repo.create_review(
        engine, company_id, title="Kerkstraat 12", kind=DDPropertyKind.house, document_ids=docs, unit_id=None,
        max_documents=30,
    )  # fmt: skip


def _calls(engine: Engine, company_id: UUID) -> int:
    with Session(engine) as s:
        return (
            s.scalar(
                select(func.count())
                .select_from(ModelCall)
                .where(ModelCall.company_id == company_id, ModelCall.purpose == "dd_reader")
            )
            or 0
        )


def test_create_review_rejects_empty_too_many_and_foreign_documents(migrated_engine: Engine, company_id: UUID) -> None:
    doc = _doc(migrated_engine, company_id, BROCHURE)
    with pytest.raises(DiligenceRequestError):
        _review(migrated_engine, company_id, [])
    with pytest.raises(DiligenceRequestError):
        repo.create_review(migrated_engine, company_id, title="t", kind=DDPropertyKind.house,
                           document_ids=[doc, uuid4()], unit_id=None, max_documents=1)  # fmt: skip
    with pytest.raises(NotFoundError):
        _review(migrated_engine, company_id, [doc, uuid4()])
    with pytest.raises(NotFoundError):
        repo.create_review(migrated_engine, company_id, title="t", kind=DDPropertyKind.house, document_ids=[doc],
                           unit_id=uuid4(), max_documents=30)  # fmt: skip


def test_another_company_cannot_see_or_use_a_review(migrated_engine: Engine, company_id: UUID) -> None:
    review = _review(migrated_engine, company_id, [_doc(migrated_engine, company_id, BROCHURE)])
    other = new_id()
    with pytest.raises(NotFoundError):
        repo.get_review(migrated_engine, other, review)
    with pytest.raises(NotFoundError):
        repo.restart_review(migrated_engine, other, review, None, 30)
    assert repo.list_reviews(migrated_engine, other, 10) == []


def test_read_document_is_cached_per_reader_version(migrated_engine: Engine, test_settings: Settings,
                                                    company_id: UUID) -> None:  # fmt: skip
    doc = _doc(migrated_engine, company_id, BROCHURE)
    assert service.read_document(migrated_engine, test_settings, company_id, doc)
    assert service.read_document(migrated_engine, test_settings, company_id, doc)
    assert _calls(migrated_engine, company_id) == 1
    with Session(migrated_engine) as s:
        rows = s.scalars(select(DDDocumentRead).where(DDDocumentRead.document_id == doc)).all()
    assert len(rows) == 1
    assert rows[0].unverified == 0
    assert rows[0].read["doc_kind"] == "brochure"


def test_documents_that_must_not_be_read_are_skipped(migrated_engine: Engine, test_settings: Settings,
                                                     company_id: UUID) -> None:  # fmt: skip
    skipped = [
        _doc(migrated_engine, company_id, "Passport NL123", doc_type="id_document"),
        _doc(migrated_engine, company_id, None),
        _doc(migrated_engine, company_id, BROCHURE, suspicious=True),
    ]
    assert [service.read_document(migrated_engine, test_settings, company_id, d) for d in skipped] == [False] * 3
    assert _calls(migrated_engine, company_id) == 0


def _run(engine: Engine, settings: Settings, company_id: UUID, review: UUID, run_no: int = 1) -> DDVerdict | None:
    ids = service.begin_run(engine, company_id, review, run_no)
    assert ids is not None
    for d in ids:
        service.read_document(engine, settings, company_id, d)
    return service.compile_review(engine, default_framework(), company_id, review, run_no, TODAY)


def test_compile_flags_a_brochure_that_disagrees_with_the_deed(migrated_engine: Engine, test_settings: Settings,
                                                               company_id: UUID) -> None:  # fmt: skip
    docs = [_doc(migrated_engine, company_id, BROCHURE), _doc(migrated_engine, company_id, DEED)]
    review = _review(migrated_engine, company_id, docs)
    assert _run(migrated_engine, test_settings, company_id, review) is DDVerdict.red_flags
    view = repo.get_review(migrated_engine, company_id, review)
    assert view.status is DDReviewStatus.done
    assert view.report is not None
    [mismatch] = view.report.mismatches
    assert mismatch.field.value == "year_built"
    assert mismatch.kind.value == "marketing_vs_legal"
    assert {d.readable for d in view.report.documents} == {True}
    assert view.document_ids == docs


def test_compile_posts_one_feed_card_and_is_idempotent(migrated_engine: Engine, test_settings: Settings,
                                                       company_id: UUID) -> None:  # fmt: skip
    review = _review(migrated_engine, company_id, [_doc(migrated_engine, company_id, BROCHURE)])
    _run(migrated_engine, test_settings, company_id, review)
    again = service.compile_review(migrated_engine, default_framework(), company_id, review, 1, TODAY)
    assert again is DDVerdict.needs_documents
    with Session(migrated_engine) as s:
        rows = s.scalars(select(OwnerFeed).where(OwnerFeed.ref_id == review)).all()
    assert len(rows) == 1
    assert rows[0].kind is FeedKind.dd_report
    assert rows[0].payload["verdict"] == "needs_documents"
    assert "Kadaster extract" in rows[0].payload["missing"]


def test_restart_bumps_the_run_and_a_stale_run_is_ignored(migrated_engine: Engine, test_settings: Settings,
                                                          company_id: UUID) -> None:  # fmt: skip
    first = _doc(migrated_engine, company_id, BROCHURE)
    review = _review(migrated_engine, company_id, [first])
    _run(migrated_engine, test_settings, company_id, review)
    second = _doc(migrated_engine, company_id, DEED)
    assert repo.restart_review(migrated_engine, company_id, review, [first, second], 30) == 2
    assert service.begin_run(migrated_engine, company_id, review, 1) is None  # the old run is stale
    assert _run(migrated_engine, test_settings, company_id, review, 2) is DDVerdict.red_flags
    assert _calls(migrated_engine, company_id) == 2  # the first document was not read again
    view = repo.get_review(migrated_engine, company_id, review)
    assert (view.run_no, view.document_ids) == (2, [first, second])
    with Session(migrated_engine) as s:
        keys = s.scalars(select(OwnerFeed.idempotency_key).where(OwnerFeed.ref_id == review)).all()
    assert len(keys) == 2


def test_restart_while_running_is_allowed_and_makes_the_running_run_stale(migrated_engine: Engine,
                                                                          test_settings: Settings,
                                                                          company_id: UUID) -> None:  # fmt: skip
    review = _review(migrated_engine, company_id, [_doc(migrated_engine, company_id, BROCHURE)])
    service.begin_run(migrated_engine, company_id, review, 1)
    assert repo.restart_review(migrated_engine, company_id, review, None, 30) == 2
    assert service.compile_review(migrated_engine, default_framework(), company_id, review, 1, TODAY) is None
    assert _run(migrated_engine, test_settings, company_id, review, 2) is DDVerdict.needs_documents


def test_restart_clears_the_previous_report(migrated_engine: Engine, test_settings: Settings, company_id: UUID) -> None:
    review = _review(migrated_engine, company_id, [_doc(migrated_engine, company_id, BROCHURE)])
    _run(migrated_engine, test_settings, company_id, review)
    repo.restart_review(migrated_engine, company_id, review, None, 30)
    view = repo.get_review(migrated_engine, company_id, review)
    assert (view.report, view.verdict, view.framework_version) == (None, None, None)


def test_a_cached_read_is_ignored_once_the_document_is_ineligible(migrated_engine: Engine, test_settings: Settings,
                                                                  company_id: UUID) -> None:  # fmt: skip
    doc = _doc(migrated_engine, company_id, BROCHURE)
    service.read_document(migrated_engine, test_settings, company_id, doc)
    with Session(migrated_engine) as s, s.begin():
        s.execute(update(DocumentRow).where(DocumentRow.id == doc).values(doc_type="id_document"))
    assert service.read_document(migrated_engine, test_settings, company_id, doc) is False
    review = _review(migrated_engine, company_id, [doc])
    _run(migrated_engine, test_settings, company_id, review)
    report = repo.get_review(migrated_engine, company_id, review).report
    assert report is not None
    assert [d.readable for d in report.documents] == [False]


def test_a_long_document_is_flagged_as_truncated(migrated_engine: Engine, test_settings: Settings,
                                                 company_id: UUID) -> None:  # fmt: skip
    long_text = "Akte van levering\n" + "x" * (MAX_DOCUMENT_CHARS + 10)
    review = _review(migrated_engine, company_id, [_doc(migrated_engine, company_id, long_text)])
    _run(migrated_engine, test_settings, company_id, review)
    report = repo.get_review(migrated_engine, company_id, review).report
    assert report is not None
    assert "document_truncated" in {r.code for r in report.risks}


def test_fail_review_records_the_error_only_for_the_current_run(migrated_engine: Engine, company_id: UUID) -> None:
    review = _review(migrated_engine, company_id, [_doc(migrated_engine, company_id, BROCHURE)])
    service.fail_review(migrated_engine, company_id, review, 7, "stale")
    assert repo.get_review(migrated_engine, company_id, review).status is DDReviewStatus.pending
    service.fail_review(migrated_engine, company_id, review, 1, "AgentFailedError")
    view = repo.get_review(migrated_engine, company_id, review)
    assert (view.status, view.error) == (DDReviewStatus.failed, "AgentFailedError")
    assert repo.restart_review(migrated_engine, company_id, review, None, 30) == 2  # a failed review can be rerun
