"""Erasure reaches what was derived from a person's mail (M13): understandings, attachment text and Astra's turns."""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import Category, Urgency
from app.contracts.understanding import Understanding
from app.db.models import (
    AgentConversation,
    AgentTurn,
    AttachmentRow,
    Company,
    DocumentChunk,
    DocumentRow,
    OwnerAccount,
    UnderstandingRow,
)
from app.pipeline.gdpr import erase_person
from app.pipeline.gdpr_derived import ERASED_LABEL, ERASED_TEXT
from tests.integration.conversation_support import add_attachment, add_mail, add_owner, add_person

pytestmark = pytest.mark.integration
ANOUK, BRAM = "anouk@example.test", "bram@example.test"


def _erase(engine: Engine, cid: UUID, person_id: UUID) -> None:
    with Session(engine) as s, s.begin():
        erase_person(s, cid, person_id)


def _body(who: str) -> dict[str, Any]:
    return {
        "category": "maintenance", "intent": f"{who} meldt een lekkende kraan", "urgency": "normal",
        "requires_reply": True, "confidence": 0.9, "sender_role": "tenant", "needs_research": True,
        "entities": {"people": [who], "unit_refs": ["Singel 1"], "dates": ["1 sep"], "amounts": []},
        "suspicious": {"flag": False, "reason": None},
        "research_questions": [f"Wat zei {who} eerder over de kraan?"], "waiting_side": "owner",
        "open_obligation": f"Loodgieter sturen naar {who}", "expected_days": 3, "prompt_version": "understanding/v4",
    }  # fmt: skip


def _understanding(engine: Engine, cid: UUID, mid: UUID, who: str) -> None:
    with Session(engine) as s, s.begin():
        s.add(UnderstandingRow(
            company_id=cid, message_id=mid, category=Category.maintenance, urgency=Urgency.normal, body=_body(who),
            prompt_version="understanding/v4", research={"findings": [f"{who} meldde dit al in mei"]},
        ))  # fmt: skip


def _understanding_of(engine: Engine, mid: UUID) -> UnderstandingRow:
    with Session(engine) as s:
        return s.scalars(select(UnderstandingRow).where(UnderstandingRow.message_id == mid)).one()


def test_erasure_clears_the_research_and_free_text_of_the_persons_understandings(
    migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    anouk, bram = add_person(migrated_engine, cid, "Anouk", ANOUK), add_person(migrated_engine, cid, "Bram", BRAM)
    mine = add_mail(migrated_engine, cid, "De kraan lekt.", sender=ANOUK, person_id=anouk)
    theirs = add_mail(migrated_engine, cid, "Mijn kraan ook.", sender=BRAM, person_id=bram)
    _understanding(migrated_engine, cid, mine, "Anouk")
    _understanding(migrated_engine, cid, theirs, "Bram")
    _erase(migrated_engine, cid, anouk)
    row = _understanding_of(migrated_engine, mine)
    assert row.research is None
    assert "Anouk" not in str(row.body)
    assert Understanding.model_validate(row.body).category is Category.maintenance  # still readable by the inbox
    kept = _understanding_of(migrated_engine, theirs)
    assert kept.research is not None
    assert kept.body["intent"] == "Bram meldt een lekkende kraan"


def _document(engine: Engine, cid: UUID, attachment_id: UUID) -> UUID:
    with Session(engine) as s, s.begin():
        doc = DocumentRow(
            company_id=cid, attachment_id=attachment_id, doc_type="medical", title="Verklaring van Anouk",
            file_name="verklaring.pdf", confidence=0.9, summary="Anouk kan de trap niet op.",
            facts={"condition": "knie"},
        )  # fmt: skip
        s.add(doc)
        s.flush()
        s.add(DocumentChunk(company_id=cid, document_id=doc.id, ord=0, text="Anouk kan de trap niet op."))
        return doc.id


def test_erasure_clears_the_text_read_from_the_persons_attachments(
    migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    anouk = add_person(migrated_engine, cid, "Anouk", ANOUK)
    mid = add_mail(migrated_engine, cid, "Zie bijlage.", sender=ANOUK, person_id=anouk)
    att = add_attachment(migrated_engine, cid, mid, "verklaring.pdf", "Anouk kan de trap niet op.")
    doc_id = _document(migrated_engine, cid, att)
    _erase(migrated_engine, cid, anouk)
    with Session(migrated_engine) as s:
        assert s.scalars(select(AttachmentRow.extracted_text).where(AttachmentRow.id == att)).one() is None
        doc = s.scalars(select(DocumentRow).where(DocumentRow.id == doc_id)).one()
        assert (doc.title, doc.summary, doc.facts, doc.doc_embedding) == (ERASED_TEXT, None, None, None)
        assert s.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc_id)).all() == []


def _source(mid: UUID, label: str) -> dict[str, Any]:
    return {"kind": "message", "ref": str(mid), "label": label, "href": None}


def _turn(engine: Engine, cid: UUID, answer: str, sources: list[dict[str, Any]]) -> tuple[UUID, UUID]:
    with Session(engine) as s, s.begin():
        owner = s.scalars(select(OwnerAccount.id).where(OwnerAccount.company_id == cid)).first()
        assert owner is not None
        conv = AgentConversation(company_id=cid, owner_id=owner, summary=f"Over: {answer}")
        s.add(conv)
        s.flush()
        result = {"intent": "answer", "ok": True, "summary": answer, "view": None,
                  "data": {"steps": ["Searched messages (1 match)"], "sources": sources}}  # fmt: skip
        turn = AgentTurn(company_id=cid, conversation_id=conv.id, text="Wat zei de huurder?", results=[result],
                         answer=answer)  # fmt: skip
        s.add(turn)
        s.flush()
        conv.summary_through = turn.id
        return conv.id, turn.id


def test_erasure_blanks_astra_turns_that_cite_the_persons_messages(
    migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    add_owner(migrated_engine, cid)
    anouk, bram = add_person(migrated_engine, cid, "Anouk", ANOUK), add_person(migrated_engine, cid, "Bram", BRAM)
    mine = add_mail(migrated_engine, cid, "De kraan lekt.", sender=ANOUK, person_id=anouk)
    theirs = add_mail(migrated_engine, cid, "Mijn kraan ook.", sender=BRAM, person_id=bram)
    both = [_source(mine, "Anouk, gmail, 1 sep"), _source(theirs, "Bram, gmail, 2 sep")]
    conv, cited = _turn(migrated_engine, cid, "Anouk en Bram melden een lekkende kraan.", both)
    other_conv, other = _turn(migrated_engine, cid, "Bram meldt een lekkende kraan.", both[1:])
    _erase(migrated_engine, cid, anouk)
    with Session(migrated_engine) as s:
        turn = s.scalars(select(AgentTurn).where(AgentTurn.id == cited)).one()
        assert turn.answer == ERASED_TEXT
        assert turn.results is not None
        assert turn.results[0]["summary"] == ERASED_TEXT
        assert [x["label"] for x in turn.results[0]["data"]["sources"]] == [ERASED_LABEL, "Bram, gmail, 2 sep"]
        chat = s.scalars(select(AgentConversation).where(AgentConversation.id == conv)).one()
        assert (chat.summary, chat.summary_through) == ("", None)  # rebuilt from the blanked turns
        kept = s.scalars(select(AgentTurn).where(AgentTurn.id == other)).one()
        assert kept.answer == "Bram meldt een lekkende kraan."
        kept_chat = s.scalars(select(AgentConversation).where(AgentConversation.id == other_conv)).one()
        assert kept_chat.summary == "Over: Bram meldt een lekkende kraan."
