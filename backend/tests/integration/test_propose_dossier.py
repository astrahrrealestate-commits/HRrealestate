"""Proposer v6 from the dossier (M13 T9): drafts to Harjot's standard, never a canned or generic reply."""

import re
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.inbox.routes import _build_drafts
from app.contracts import ActionType, Category, Entities, Suspicious, Understanding, Urgency
from app.core.settings import Settings
from app.db.enums import PersonKind
from app.db.models import ActionRow, Company, ModelCall, UnderstandingRow
from app.llm import fakes
from app.llm.agents.proposer import proposer_spec
from app.pipeline.propose import NO_USABLE_DRAFT, load_message, propose_for_message
from tests.integration.conversation_support import add_case, add_mail, add_person

pytestmark = pytest.mark.integration
ANOUK, JAN = "anouk@example.test", "jan@bouw.test"
SIGN = "\n\nMet vriendelijke groet,\nHarjot"
GENERIC = "Beste,\n\nDank voor uw bericht. Wij komen er zo snel mogelijk op terug." + SIGN
GOOD = "Beste Anouk,\n\nSinds wanneer lekt de kraan, en bent u donderdag thuis?" + SIGN
Fake = Callable[[str], dict[str, object]]


@pytest.fixture
def settings(test_settings: Settings) -> Settings:
    return test_settings.model_copy(update={"llm_model": "fake"})


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    prompts: list[str] = []
    original = fakes.fake_proposer

    def spy(prompt: str) -> dict[str, object]:
        prompts.append(prompt)
        return original(prompt)

    monkeypatch.setattr(fakes, "fake_proposer", spy)
    return prompts


def _answers(
    monkeypatch: pytest.MonkeyPatch, *replies: list[str] | None, commitments: list[str] | None = None
) -> list[str]:
    """The fake proposer answers each call with the next variants (None: escalate only); returns the prompts."""
    prompts: list[str] = []

    def fake(prompt: str) -> dict[str, object]:
        variants = replies[min(len(prompts), len(replies) - 1)]
        prompts.append(prompt)
        case_id = prompt.split("case_id: ", 1)[1].split("\n", 1)[0]
        actions: list[dict[str, Any]] = [
            {"type": "escalate", "case_id": case_id, "payload": {"kind": "escalate", "reason": "Lek"},
             "rationale": "Emergency", "context_ref": [], "draft_version": 1}
        ]  # fmt: skip
        if variants is not None:
            payload = {"kind": "reply_draft", "channel": "gmail", "subject": None, "body_variants": variants,
                       "commitments": commitments or []}  # fmt: skip
            actions.insert(0, {"type": "reply_draft", "case_id": case_id, "payload": payload, "rationale": "Reply",
                               "context_ref": [], "draft_version": 1})  # fmt: skip
        return {"actions": actions}

    monkeypatch.setattr(fakes, "fake_proposer", fake)
    return prompts


def _understood(engine: Engine, cid: UUID, mid: UUID, urgency: Urgency = Urgency.normal) -> None:
    und = Understanding(
        category=Category.maintenance, intent="Lekkage", urgency=urgency, requires_reply=True, entities=Entities.none(),
        suspicious=Suspicious(flag=False, reason=None), confidence=0.9, sender_role=None, needs_research=False,
        research_questions=[], prompt_version="understanding/v4",
    )  # fmt: skip
    with Session(engine) as s, s.begin():
        s.add(UnderstandingRow(company_id=cid, message_id=mid, category=und.category, urgency=und.urgency,
                               body=und.model_dump(mode="json"), prompt_version=und.prompt_version))  # fmt: skip


def _mail(engine: Engine, cid: UUID, text: str = "De kraan lekt.", urgency: Urgency = Urgency.normal) -> UUID:
    anouk = add_person(engine, cid, "Anouk", ANOUK)
    case = add_case(engine, cid, anouk)
    add_mail(engine, cid, "Eerder: de kraan druppelt.", sender=ANOUK, person_id=anouk, case_id=case, days_ago=3)
    mid = add_mail(engine, cid, text, sender=ANOUK, person_id=anouk, case_id=case)
    _understood(engine, cid, mid, urgency)
    return mid


def _actions(engine: Engine, cid: UUID) -> list[ActionRow]:
    with Session(engine) as s:
        return list(s.scalars(select(ActionRow).where(ActionRow.company_id == cid)))


def test_propose_uses_v6_with_the_dossier_and_records_its_messages(
    migrated_engine: Engine, committed_company: Company, settings: Settings, seen: list[str]
) -> None:
    cid = committed_company.id
    mid = _mail(migrated_engine, cid)
    propose_for_message(migrated_engine, settings, mid)
    assert "<current_message>" in seen[0]
    assert "Eerder: de kraan druppelt." in seen[0]
    with Session(migrated_engine) as s:
        call = s.scalars(select(ModelCall).where(ModelCall.company_id == cid, ModelCall.purpose == "proposer")).one()
    assert call.prompt_version == "v6"
    assert mid in call.message_ids
    assert len(call.message_ids) == 2


def test_owner_redraft_uses_v6_with_the_dossier(migrated_engine: Engine, committed_company: Company) -> None:
    mid = _mail(migrated_engine, committed_company.id)
    loaded = load_message(migrated_engine, mid)
    assert loaded is not None
    assert proposer_spec(loaded.ctx).prompt.key == "proposer/v6"
    assert any("Eerder: de kraan druppelt." in block for block in loaded.ctx.dossier)


def test_role_comes_from_the_mails_sender_not_the_case(migrated_engine: Engine, committed_company: Company) -> None:
    cid = committed_company.id
    anouk = add_person(migrated_engine, cid, "Anouk", ANOUK)
    jan = add_person(migrated_engine, cid, "Jan", JAN, PersonKind.contractor)
    case = add_case(migrated_engine, cid, anouk)
    mid = add_mail(migrated_engine, cid, "Ik kan dinsdag komen.", sender=JAN, person_id=jan, case_id=case)
    _understood(migrated_engine, cid, mid)
    loaded = load_message(migrated_engine, mid)
    assert loaded is not None
    assert loaded.ctx.sender_kind == "contractor"


def test_maintenance_without_brixx_ticket_gets_no_acknowledgement_instruction(
    migrated_engine: Engine, committed_company: Company, settings: Settings, seen: list[str]
) -> None:
    mid = _mail(migrated_engine, committed_company.id)
    propose_for_message(migrated_engine, settings, mid)
    assert "BRIXX work order: none yet" in seen[0]
    without_persona = re.sub(r"<persona>.*?</persona>", "", seen[0], flags=re.S)  # Harjot's own style guide
    assert "acknowledg" not in without_persona.lower()


def test_a_generic_draft_is_redrafted_then_dropped(
    migrated_engine: Engine, committed_company: Company, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = committed_company.id
    prompts = _answers(monkeypatch, [GENERIC, GENERIC])
    propose_for_message(migrated_engine, settings, _mail(migrated_engine, cid))
    assert len(prompts) == 2
    assert "<quality_feedback>" in prompts[1]
    kinds = sorted(a.type for a in _actions(migrated_engine, cid))
    assert kinds == sorted([ActionType.escalate, ActionType.notify_owner])
    [note] = [a for a in _actions(migrated_engine, cid) if a.type is ActionType.notify_owner]
    assert note.payload["text"] == NO_USABLE_DRAFT


def test_a_generic_first_draft_is_replaced_by_the_retry(
    migrated_engine: Engine, committed_company: Company, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = committed_company.id
    prompts = _answers(monkeypatch, [GENERIC, GENERIC], [GOOD, GOOD + " "])
    propose_for_message(migrated_engine, settings, _mail(migrated_engine, cid))
    assert len(prompts) == 2
    [reply] = [a for a in _actions(migrated_engine, cid) if a.type is ActionType.reply_draft]
    assert reply.payload["body_variants"][0] == GOOD


def test_generic_variants_are_dropped_when_two_good_ones_remain(
    migrated_engine: Engine, committed_company: Company, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = committed_company.id
    prompts = _answers(monkeypatch, [GOOD, GENERIC, GOOD + " Tot donderdag!"])
    propose_for_message(migrated_engine, settings, _mail(migrated_engine, cid))
    assert len(prompts) == 1
    [reply] = [a for a in _actions(migrated_engine, cid) if a.type is ActionType.reply_draft]
    assert GENERIC not in reply.payload["body_variants"]


def test_commitments_are_stored_on_the_payload(
    migrated_engine: Engine, committed_company: Company, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = committed_company.id
    _answers(monkeypatch, [GOOD, GOOD + " "], commitments=["Plumber on Thursday"])
    propose_for_message(migrated_engine, settings, _mail(migrated_engine, cid))
    [reply] = [a for a in _actions(migrated_engine, cid) if a.type is ActionType.reply_draft]
    assert reply.payload["commitments"] == ["Plumber on Thursday"]


def test_an_emergency_without_a_model_draft_offers_none(
    migrated_engine: Engine, committed_company: Company, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = committed_company.id
    _answers(monkeypatch, None)
    propose_for_message(migrated_engine, settings, _mail(migrated_engine, cid, urgency=Urgency.emergency))
    assert [a.type for a in _actions(migrated_engine, cid)] == [ActionType.escalate]


def test_the_fake_proposer_writes_drafts_that_pass_the_standard(
    migrated_engine: Engine, committed_company: Company, settings: Settings
) -> None:
    cid = committed_company.id
    propose_for_message(migrated_engine, settings, _mail(migrated_engine, cid))
    [reply] = [a for a in _actions(migrated_engine, cid) if a.type is ActionType.reply_draft]
    assert len(reply.payload["body_variants"]) >= 2


def test_inbox_without_a_proposal_offers_no_draft_text_and_no_confidence() -> None:
    assert _build_drafts(None, "Anouk") == ([], [], None)
