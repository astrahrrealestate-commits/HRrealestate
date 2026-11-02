"""`dd:{review_id}:{run_no}` workflow: reads, compiles, goes stale on a restart, and records a failure."""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts.diligence import DDPropertyKind
from app.core.errors import AgentFailedError, BudgetExceededError
from app.db.enums import DDReviewStatus
from app.diligence import repo, service
from app.workflows import diligence
from tests.integration.diligence_support import make_document

pytestmark = pytest.mark.integration
BROCHURE = "Verkoopbrochure Kerkstraat 12\nBouwjaar: 1985\nWoonoppervlakte: 95 m2"
DEED = "Akte van levering\nBouwjaar: 1965"


@pytest.fixture
def company_id(dbos_runtime: None, committed_company: Any) -> UUID:
    return committed_company.id  # type: ignore[no-any-return]


def _review(engine: Engine, company_id: UUID) -> UUID:
    with Session(engine) as s, s.begin():
        docs = [make_document(s, company_id, BROCHURE), make_document(s, company_id, DEED)]
    return repo.create_review(
        engine, company_id, title="Kerkstraat 12", kind=DDPropertyKind.house, document_ids=docs, unit_id=None,
        max_documents=30,
    )  # fmt: skip


def test_workflow_reads_compiles_and_reports_the_verdict(migrated_engine: Engine, company_id: UUID) -> None:
    review = _review(migrated_engine, company_id)
    assert diligence.dd_review_wf(str(company_id), str(review), 1) == "red_flags"
    view = repo.get_review(migrated_engine, company_id, review)
    assert view.status is DDReviewStatus.done
    assert view.report is not None
    assert [m.field.value for m in view.report.mismatches] == ["year_built"]


def test_a_restarted_review_makes_the_old_run_stale(migrated_engine: Engine, company_id: UUID) -> None:
    review = _review(migrated_engine, company_id)
    repo.restart_review(migrated_engine, company_id, review, None, 30)
    assert diligence.dd_review_wf(str(company_id), str(review), 1) == "stale"
    assert repo.get_review(migrated_engine, company_id, review).status is DDReviewStatus.pending
    assert diligence.dd_review_wf(str(company_id), str(review), 2) == "red_flags"


def test_a_document_the_model_cannot_read_degrades_to_unreadable(
    migrated_engine: Engine, company_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = _review(migrated_engine, company_id)

    def garbage(*_args: object) -> bool:
        raise AgentFailedError("model returned garbage")

    monkeypatch.setattr(service, "read_document", garbage)
    assert diligence.dd_review_wf(str(company_id), str(review), 1) == "needs_documents"
    report = repo.get_review(migrated_engine, company_id, review).report
    assert report is not None
    assert "unreadable_documents" in {r.code for r in report.risks}


def test_a_spent_budget_fails_the_review_instead_of_a_misleading_report(
    migrated_engine: Engine, company_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = _review(migrated_engine, company_id)

    def spent(*_args: object) -> bool:
        raise BudgetExceededError("daily")

    monkeypatch.setattr(service, "read_document", spent)
    assert diligence.dd_review_wf(str(company_id), str(review), 1) == "failed"
    view = repo.get_review(migrated_engine, company_id, review)
    assert (view.status, view.error) == (DDReviewStatus.failed, "BudgetExceededError")
