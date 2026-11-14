"""Concierge document intents against Postgres: find, read with verified quotes, scope, safety, budget."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts import Intent
from app.core.settings import Settings
from app.db.enums import DocLinkKind
from app.db.models import Company, DocumentLink, DocumentRow
from app.llm import fakes
from app.pipeline.concierge_base import NEED_DETAIL, NOT_FOUND
from app.pipeline.document_qa import NOT_FOUND_TEXT
from app.pipeline.owner_commands import LIMIT_ANSWER
from tests.integration.concierge_support import plan as make_plan
from tests.integration.concierge_support import run, seed_case, step
from tests.integration.test_document_search import _doc

pytestmark = pytest.mark.integration
LEASE_TEXT = "De waarborgsom bedraagt twee maanden kale huur. De opzegtermijn is drie maanden."


@pytest.fixture
def settings(test_settings: Settings) -> Settings:
    return test_settings.model_copy(update={"llm_model": "fake"})


@pytest.fixture
def cid(committed_company: Company) -> UUID:
    return committed_company.id


def _add(engine: Engine, cid: UUID, title: str, text: str, case_id: UUID | None = None) -> UUID:
    with Session(engine) as s, s.begin():
        doc_id = _doc(s, cid, title=title, doc_type="lease", chunks=[text])
        if case_id:
            s.add(DocumentLink(company_id=cid, document_id=doc_id, kind=DocLinkKind.case, ref_id=case_id,
                               method="message", score=1.0))  # fmt: skip
    return doc_id


def test_find_document_lists_matches_with_safe_titles(migrated_engine: Engine, settings: Settings, cid: UUID) -> None:
    _add(migrated_engine, cid, "Huurovereenkomst Kerkstraat", LEASE_TEXT)
    _add(migrated_engine, cid, "Factuur loodgieter", "Reparatie waterleiding")
    [res] = run(migrated_engine, settings, cid, make_plan(step(Intent.find_document, text="waarborgsom huur")))
    assert res.ok
    assert res.summary.startswith("Found 1 document(s): Huurovereenkomst Kerkstraat (lease")
    assert res.data is not None
    assert [d["title"] for d in res.data["documents"]] == ["Huurovereenkomst Kerkstraat"]


def test_find_document_scoped_to_a_case(migrated_engine: Engine, settings: Settings, cid: UUID) -> None:
    case_id, _ = seed_case(migrated_engine, cid)
    mine = _add(migrated_engine, cid, "Huur van Sanne", LEASE_TEXT, case_id)
    _add(migrated_engine, cid, "Huur van iemand anders", LEASE_TEXT)
    [res] = run(migrated_engine, settings, cid, make_plan(step(Intent.find_document, text="huur", case_id=case_id)))
    assert res.data is not None
    assert [d["document_id"] for d in res.data["documents"]] == [str(mine)]


def test_find_document_needs_words_and_no_match_is_a_plain_answer(migrated_engine: Engine, settings: Settings,
                                                                  cid: UUID) -> None:  # fmt: skip
    [blank] = run(migrated_engine, settings, cid, make_plan(step(Intent.find_document, text="  ")))
    assert (blank.ok, blank.summary) == (False, NEED_DETAIL)
    [none] = run(migrated_engine, settings, cid, make_plan(step(Intent.find_document, text="paspoort")))
    assert (none.ok, none.summary) == (True, "No documents match that.")


def test_read_document_answers_with_a_verified_quote(migrated_engine: Engine, settings: Settings, cid: UUID) -> None:
    _add(migrated_engine, cid, "Huurovereenkomst", LEASE_TEXT)
    [res] = run(migrated_engine, settings, cid, make_plan(step(Intent.read_document, text="deposit")),
                question="What does the lease say about the waarborgsom?")  # fmt: skip
    assert res.ok
    assert "From Huurovereenkomst (lease" in res.summary
    assert "«De waarborgsom bedraagt twee maanden kale huur.»" in res.summary
    assert res.data is not None
    assert res.data["found"] is True
    assert res.data["quotes"][0]["title"] == "Huurovereenkomst"


def test_the_question_is_the_owners_message_not_the_models_text(migrated_engine: Engine, settings: Settings,
                                                                cid: UUID) -> None:  # fmt: skip
    _add(migrated_engine, cid, "Huurovereenkomst", LEASE_TEXT)
    [res] = run(migrated_engine, settings, cid, make_plan(step(Intent.read_document, text="irrelevant words")),
                question="opzegtermijn?")  # fmt: skip
    assert "drie maanden" in res.summary


def test_nothing_relevant_says_so(migrated_engine: Engine, settings: Settings, cid: UUID) -> None:
    [res] = run(
        migrated_engine, settings, cid, make_plan(step(Intent.read_document)), question="Wat is de waarborgsom?"
    )
    assert (res.ok, res.summary) == (False, NOT_FOUND_TEXT)


def test_a_case_scope_only_reads_that_cases_documents(migrated_engine: Engine, settings: Settings, cid: UUID) -> None:
    case_id, _ = seed_case(migrated_engine, cid)
    _add(migrated_engine, cid, "Huur van iemand anders", LEASE_TEXT)  # not linked to the case
    [res] = run(migrated_engine, settings, cid, make_plan(step(Intent.read_document, case_id=case_id)),
                question="waarborgsom?")  # fmt: skip
    assert res.ok is False
    mine = _add(migrated_engine, cid, "Huur van Sanne", LEASE_TEXT, case_id)
    [again] = run(migrated_engine, settings, cid, make_plan(step(Intent.read_document, case_id=case_id)),
                  question="waarborgsom?")  # fmt: skip
    assert again.ok
    assert again.data is not None
    assert again.data["quotes"][0]["document_id"] == str(mine)


def test_links_and_ibans_in_a_hostile_document_never_reach_the_owner(migrated_engine: Engine, settings: Settings,
                                                                    cid: UUID) -> None:  # fmt: skip
    evil = "De waarborgsom is te betalen via https://evil.example/pay op NL91ABNA0417164300 of mail pay@evil.test."
    _add(migrated_engine, cid, "Huur", evil)
    [res] = run(migrated_engine, settings, cid, make_plan(step(Intent.read_document)), question="waarborgsom betalen?")
    assert res.ok
    for needle in ("evil", "NL91", "pay@"):
        assert needle not in res.summary
    assert res.data is not None
    assert "evil" not in str(res.data)


def test_suspicious_documents_are_not_used_as_context(migrated_engine: Engine, settings: Settings, cid: UUID) -> None:
    doc_id = _add(migrated_engine, cid, "Huur", LEASE_TEXT)
    with Session(migrated_engine) as s, s.begin():
        s.get(DocumentRow, doc_id).suspicious = True  # type: ignore[union-attr]
    [res] = run(migrated_engine, settings, cid, make_plan(step(Intent.read_document)), question="waarborgsom?")
    assert (res.ok, res.summary) == (False, NOT_FOUND_TEXT)


def test_a_quote_the_model_made_up_is_not_shown(migrated_engine: Engine, settings: Settings, cid: UUID,
                                                monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    _add(migrated_engine, cid, "Huur", LEASE_TEXT)

    def liar(prompt: str) -> dict[str, object]:
        ref = fakes._ENTRY.findall(fakes._block(prompt, "excerpts"))[0][0]
        invented = "De waarborgsom bedraagt zes maanden kale huur."
        return {"found": True, "answer": "Zes maanden.", "quotes": [{"doc_ref": ref, "text": invented}]}

    monkeypatch.setattr(fakes, "_fake_doc_qa", liar)
    [res] = run(migrated_engine, settings, cid, make_plan(step(Intent.read_document)), question="waarborgsom?")
    assert (res.ok, res.summary) == (False, NOT_FOUND_TEXT)
    assert "zes" not in res.summary.lower()


def test_another_companys_documents_are_unreachable(migrated_engine: Engine, settings: Settings, cid: UUID) -> None:
    _add(migrated_engine, cid, "Huur", LEASE_TEXT)
    [res] = run(migrated_engine, settings, uuid4(), make_plan(step(Intent.read_document)), question="waarborgsom?")
    assert res.summary == NOT_FOUND_TEXT
    [listing] = run(migrated_engine, settings, uuid4(), make_plan(step(Intent.find_document, text="huur")))
    assert listing.summary == "No documents match that."


def test_a_foreign_case_id_is_rejected_before_anything_runs(migrated_engine: Engine, settings: Settings,
                                                            cid: UUID) -> None:  # fmt: skip
    [res] = run(migrated_engine, settings, cid, make_plan(step(Intent.read_document, case_id=uuid4())))
    assert (res.ok, res.summary) == (False, NOT_FOUND)


def test_budget_stop_gives_the_fixed_limit_answer(migrated_engine: Engine, settings: Settings, cid: UUID) -> None:
    _add(migrated_engine, cid, "Huur", LEASE_TEXT)
    capped = settings.model_copy(update={"llm_daily_calls_cap": 0})
    [res] = run(migrated_engine, capped, cid, make_plan(step(Intent.read_document)), question="waarborgsom?")
    assert (res.ok, res.summary) == (False, LIMIT_ANSWER)


def test_from_the_owners_words_through_the_fake_planner_to_a_quoted_answer(
    migrated_engine: Engine, settings: Settings, cid: UUID
) -> None:
    from app.contracts import ConciergePlan
    from app.llm.fakes_concierge import fake_concierge

    _add(migrated_engine, cid, "Huurovereenkomst", LEASE_TEXT)
    question = "What does the lease say about the waarborgsom?"
    planned = ConciergePlan.model_validate(fake_concierge(f"<message>\n{question}\n</message>"))
    assert [s.intent for s in planned.steps] == [Intent.read_document]
    [res] = run(migrated_engine, settings, cid, planned, question=question)
    assert res.ok
    assert "twee maanden kale huur" in res.summary


def test_find_document_with_an_unknown_case_does_not_search_the_whole_company(
    migrated_engine: Engine, settings: Settings, cid: UUID
) -> None:
    _add(migrated_engine, cid, "Huurovereenkomst", LEASE_TEXT)
    [res] = run(migrated_engine, settings, cid, make_plan(step(Intent.find_document, text="huur", case_id=uuid4())))
    assert (res.ok, res.summary) == (False, NOT_FOUND)  # rejected before any search
