"""Finance workflows through DBOS: the approval hook in `execute_action_wf` snapshots once per action, the pipeline
hook reviews a contractor's quote once per message, a recheck appends one review per round (fake models and prices).
"""

from typing import Any
from uuid import UUID

import pytest
from dbos import DBOS, SetWorkflowID
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.contracts import ActionType, Category, Urgency
from app.core.settings import Settings
from app.db.base import CompanyScoped
from app.db.enums import FeedKind, PersonKind
from app.db.models import AttachmentRow, Company, ModelCall, OwnerFeed, PriceSnapshot, QuoteReview, UnderstandingRow
from app.finance import quotes, snapshot
from app.workflows import actions, finance, pipeline
from tests.integration.finance_support import Seeded, action, message, person, seed_case

pytestmark = pytest.mark.integration
QUOTE_TEXT = "Offerte\nCv ketel onderhoud € 131,00 excl. BTW"
AMOUNT = {"amount": "131.00", "currency": "EUR"}


@pytest.fixture
def env(
    dbos_runtime: None, migrated_engine: Engine, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Engine:
    """Steps use the test settings (fake model, fake prices), never a developer `.env`; sends never leave."""
    monkeypatch.setattr(finance, "get_settings", lambda: test_settings)
    monkeypatch.setattr(actions, "after_execute_step", lambda action_id: None)
    monkeypatch.setattr(actions, "tell_blocked_step", lambda *a: None)
    return migrated_engine


def _seed(engine: Engine, company: Company) -> Seeded:
    with Session(engine) as s:
        seeded = seed_case(s, company.id)
        s.commit()
    return seeded


def _count(engine: Engine, model: type[CompanyScoped], company_id: UUID, *where: Any) -> int:
    with Session(engine) as s:
        return s.scalar(select(func.count(model.id)).where(model.company_id == company_id, *where)) or 0


def _workflows(prefix: str) -> list[str]:
    return [w.workflow_id for w in DBOS.list_workflows(workflow_id_prefix=prefix)]


def _execute(monkeypatch: pytest.MonkeyPatch, action_id: UUID, version: int, outcome: str) -> str:
    monkeypatch.setattr(actions, "send_step", lambda *a: [outcome, "why"])
    return str(DBOS.start_workflow(actions.execute_action_wf, str(action_id), version, False).get_result())


@pytest.mark.parametrize("outcome", ["sent", "blocked"])
def test_request_contractor_approval_produces_snapshot(
    env: Engine, committed_company: Company, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    seeded = _seed(env, committed_company)

    assert _execute(monkeypatch, seeded.action_id, 1, outcome) == outcome

    written = DBOS.retrieve_workflow(f"fin:snap:{seeded.action_id}").get_result()
    assert written == _count(env, PriceSnapshot, seeded.company_id, PriceSnapshot.action_id == seeded.action_id) > 0
    assert _count(env, ModelCall, seeded.company_id, ModelCall.purpose == snapshot.PURPOSE) == 1


def test_second_enqueue_is_deduped(env: Engine, committed_company: Company, monkeypatch: pytest.MonkeyPatch) -> None:
    seeded = _seed(env, committed_company)
    _execute(monkeypatch, seeded.action_id, 1, "sent")
    first = DBOS.retrieve_workflow(f"fin:snap:{seeded.action_id}").get_result()

    _execute(monkeypatch, seeded.action_id, 2, "sent")  # a re-approved draft version: same decision day
    assert finance.enqueue_snapshot(str(seeded.company_id), str(seeded.action_id)) is True

    assert _workflows("fin:snap:") == [f"fin:snap:{seeded.action_id}"]
    assert DBOS.retrieve_workflow(f"fin:snap:{seeded.action_id}").get_result() == first
    assert _count(env, PriceSnapshot, seeded.company_id) == first
    assert _count(env, ModelCall, seeded.company_id, ModelCall.purpose == snapshot.PURPOSE) == 1


def test_other_approvals_take_no_snapshot(
    env: Engine, committed_company: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = _seed(env, committed_company)
    with Session(env) as s:
        other = action(s, seeded.company_id, seeded.case_id, seeded.vendor_id, ActionType.notify_owner)
        s.commit()

    assert _execute(monkeypatch, other, 1, "sent") == "sent"

    assert _workflows("fin:snap:") == []


def _understood(engine: Engine, company_id: UUID, message_id: UUID, amounts: list[dict[str, str]]) -> None:
    body = {"entities": {"people": [], "unit_refs": [], "dates": [], "amounts": amounts}}
    with Session(engine) as s:
        s.add(UnderstandingRow(company_id=company_id, message_id=message_id, category=Category.maintenance,
                               urgency=Urgency.normal, body=body, prompt_version="test"))  # fmt: skip
        s.commit()


def _message_from(engine: Engine, seeded: Seeded, sender: UUID, amounts: list[dict[str, str]]) -> UUID:
    with Session(engine) as s:
        mid = message(s, seeded.company_id, seeded.case_id, QUOTE_TEXT, person_id=sender)
        s.commit()
    _understood(engine, seeded.company_id, mid, amounts)
    return mid


def _tenant(engine: Engine, company_id: UUID) -> UUID:
    with Session(engine) as s:
        tid = person(s, company_id, "Anna", PersonKind.tenant)
        s.commit()
    return tid


def test_quote_candidates_are_contractor_messages_with_an_amount_or_a_file(
    env: Engine, committed_company: Company
) -> None:
    seeded = _seed(env, committed_company)
    with_amount = _message_from(env, seeded, seeded.vendor_id, [AMOUNT])
    from_tenant = _message_from(env, seeded, _tenant(env, seeded.company_id), [AMOUNT])
    plain = _message_from(env, seeded, seeded.vendor_id, [])
    with_file = _message_from(env, seeded, seeded.vendor_id, [])
    with Session(env) as s:
        s.add(AttachmentRow(company_id=seeded.company_id, message_id=with_file, s3_key="k", mime_type="application/pdf",
                            size_bytes=10, sha256="0" * 64))  # fmt: skip
        s.commit()

    wanted = {m: finance.quote_candidate_step(str(m)) for m in (with_amount, from_tenant, plain, with_file)}

    assert wanted == {with_amount: True, from_tenant: False, plain: False, with_file: True}


def _pipeline(monkeypatch: pytest.MonkeyPatch, seeded: Seeded, mid: UUID) -> str:
    """The real pipeline body and quote hook; understanding, linking and proposals are stubbed (seeded rows)."""
    monkeypatch.setattr(pipeline, "understand_step", lambda m: "understood")
    monkeypatch.setattr(pipeline, "resolve_step", lambda m: None)
    monkeypatch.setattr(pipeline, "link_step", lambda m: str(seeded.case_id))
    monkeypatch.setattr(pipeline, "propose_step", lambda m: {"approval_ids": [], "exceptions": []})
    return str(DBOS.start_workflow(pipeline.pipeline_entry, str(mid)).get_result())


def _quote_cards(engine: Engine, company_id: UUID) -> int:
    return _count(engine, OwnerFeed, company_id, OwnerFeed.kind == FeedKind.quote_review)


def test_contractor_quote_runs_end_to_end_once(
    env: Engine, committed_company: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = _seed(env, committed_company)
    mid = _message_from(env, seeded, seeded.vendor_id, [AMOUNT])

    assert _pipeline(monkeypatch, seeded, mid) == "understood"
    review_id = DBOS.retrieve_workflow(f"fin:quote:{mid}").get_result()

    assert review_id is not None
    assert _quote_cards(env, seeded.company_id) == 1
    assert finance.enqueue_quote(str(seeded.company_id), str(mid)) is True  # deduped by id
    with SetWorkflowID(f"replay:{mid}"):  # a replay of the review under another id adds nothing
        assert DBOS.start_workflow(finance.quote_wf, str(mid)).get_result() == review_id
    assert _workflows("fin:quote:") == [f"fin:quote:{mid}"]
    assert (_quote_cards(env, seeded.company_id), _count(env, QuoteReview, seeded.company_id)) == (1, 1)
    assert _count(env, ModelCall, seeded.company_id, ModelCall.purpose == quotes.PURPOSE) == 1


@pytest.mark.parametrize("sender", ["tenant", "no_amount"])
def test_non_contractor_or_no_amount_is_not_enqueued(
    env: Engine, committed_company: Company, monkeypatch: pytest.MonkeyPatch, sender: str
) -> None:
    seeded = _seed(env, committed_company)
    if sender == "tenant":
        mid = _message_from(env, seeded, _tenant(env, seeded.company_id), [AMOUNT])
    else:
        mid = _message_from(env, seeded, seeded.vendor_id, [])

    assert _pipeline(monkeypatch, seeded, mid) == "understood"

    assert _workflows("fin:quote:") == []
    assert _quote_cards(env, seeded.company_id) == 0


def test_recheck_twice_with_the_same_round_adds_one_review(
    env: Engine, committed_company: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = _seed(env, committed_company)
    mid = _message_from(env, seeded, seeded.vendor_id, [AMOUNT])
    _pipeline(monkeypatch, seeded, mid)
    assert DBOS.retrieve_workflow(f"fin:quote:{mid}").get_result() is not None
    with Session(env) as s:
        quote_id = str(s.scalars(select(QuoteReview.quote_id).where(QuoteReview.company_id == seeded.company_id)).one())

    assert finance.enqueue_recheck(str(seeded.company_id), quote_id, 1) is True
    first = DBOS.retrieve_workflow(f"fin:recheck:{quote_id}:1").get_result()
    with SetWorkflowID(f"fin:recheck:{quote_id}:1:again"):  # a second run of round 1 reuses its review id
        again = DBOS.start_workflow(finance.recheck_wf, quote_id, str(seeded.company_id), 1).get_result()

    assert first == again is not None
    assert _count(env, QuoteReview, seeded.company_id) == 2
    assert _quote_cards(env, seeded.company_id) == 2
