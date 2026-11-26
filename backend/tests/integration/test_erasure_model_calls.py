"""Erasure reaches the model-call log (M13): prompts and outputs that carried the person's words are blanked."""

from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import Channel
from app.core.settings import Settings
from app.db.models import Company, ModelCall
from app.llm.agents.understanding import UNDERSTANDING, understanding_prompt
from app.llm.calls import CallContext, run_agent
from app.pipeline.gdpr import erase_person
from app.pipeline.gdpr_calls import ERASED_CALL
from tests.integration.conversation_support import add_mail, add_person

pytestmark = pytest.mark.integration
ANOUK, BRAM = "anouk@example.test", "bram@example.test"
SECRET = "Mijn medische situatie maakt de trap onmogelijk voor mij."


@pytest.fixture
def settings(test_settings: Settings) -> Settings:
    return test_settings.model_copy(update={"llm_model": "fake"})


def _call(engine: Engine, settings: Settings, cid: UUID, text: str, message_ids: tuple[UUID, ...] = ()) -> UUID:
    ctx = CallContext(cid, "triage", message_ids=message_ids)
    return run_agent(engine, settings, UNDERSTANDING, understanding_prompt(text, Channel.gmail), ctx).model_call_id


def _row(engine: Engine, call_id: UUID) -> ModelCall:
    with Session(engine) as s:
        return s.scalars(select(ModelCall).where(ModelCall.id == call_id)).one()


def _erase(engine: Engine, cid: UUID, person_id: UUID) -> None:
    with Session(engine) as s, s.begin():
        erase_person(s, cid, person_id)


def test_the_message_ids_of_a_call_are_recorded(
    migrated_engine: Engine, committed_company: Company, settings: Settings
) -> None:
    cid = committed_company.id
    anouk = add_person(migrated_engine, cid, "Anouk de Vries", ANOUK)
    mid = add_mail(migrated_engine, cid, SECRET, sender=ANOUK, person_id=anouk)
    assert _row(migrated_engine, _call(migrated_engine, settings, cid, SECRET, (mid,))).message_ids == [mid]


def test_erasure_blanks_calls_tagged_with_the_persons_messages(
    migrated_engine: Engine, committed_company: Company, settings: Settings
) -> None:
    cid = committed_company.id
    anouk = add_person(migrated_engine, cid, "Anouk de Vries", ANOUK)
    mid = add_mail(migrated_engine, cid, "Kort.", sender=ANOUK, person_id=anouk)
    call = _call(migrated_engine, settings, cid, "Kort.", (mid,))
    _erase(migrated_engine, cid, anouk)
    row = _row(migrated_engine, call)
    assert (row.input, row.output, row.error) == (ERASED_CALL, ERASED_CALL, None)


def test_erasure_blanks_untagged_calls_that_quote_the_person_or_name_them(
    migrated_engine: Engine, committed_company: Company, settings: Settings
) -> None:
    """Owner commands, the Super Agent and briefings put a person's words in prompts without message ids."""
    cid = committed_company.id
    anouk = add_person(migrated_engine, cid, "Anouk de Vries", ANOUK)
    add_mail(migrated_engine, cid, SECRET, sender=ANOUK, person_id=anouk)
    quoted = _call(migrated_engine, settings, cid, f"Samenvatting: {SECRET}")
    by_address = _call(migrated_engine, settings, cid, f"Schrijf aan {ANOUK.upper()} over de borg")
    by_name = _call(migrated_engine, settings, cid, "Wat vroeg Anouk de Vries gisteren?")
    _erase(migrated_engine, cid, anouk)
    survived = [n for n, c in (("quoted", quoted), ("address", by_address), ("name", by_name))
                if _row(migrated_engine, c).input != ERASED_CALL]  # fmt: skip
    assert survived == []


def test_erasure_keeps_other_peoples_and_other_companies_calls(
    migrated_engine: Engine, committed_company: Company, settings: Settings
) -> None:
    cid = committed_company.id
    anouk = add_person(migrated_engine, cid, "Anouk de Vries", ANOUK)
    bram = add_person(migrated_engine, cid, "Bram", BRAM)
    add_mail(migrated_engine, cid, SECRET, sender=ANOUK, person_id=anouk)
    bram_mid = add_mail(migrated_engine, cid, "De verwarming doet het niet.", sender=BRAM, person_id=bram)
    kept = _call(migrated_engine, settings, cid, "De verwarming doet het niet.", (bram_mid,))
    with Session(migrated_engine) as s, s.begin():
        other = Company(name="Ander")
        s.add(other)
        s.flush()
        other_id = other.id
    elsewhere = _call(migrated_engine, settings, other_id, SECRET)
    _erase(migrated_engine, cid, anouk)
    assert "verwarming" in str(_row(migrated_engine, kept).input)
    assert SECRET in str(_row(migrated_engine, elsewhere).input)
    with Session(migrated_engine) as s, s.begin():
        s.query(ModelCall).filter(ModelCall.company_id == other_id).delete()
        s.query(Company).filter(Company.id == other_id).delete()


def test_a_one_word_name_is_not_used_to_blank_calls(
    migrated_engine: Engine, committed_company: Company, settings: Settings
) -> None:
    cid = committed_company.id
    bram = add_person(migrated_engine, cid, "Bram", BRAM)
    add_mail(migrated_engine, cid, "Ok", sender=BRAM, person_id=bram)
    unrelated = _call(migrated_engine, settings, cid, "Bram Stoker schreef Dracula.")
    _erase(migrated_engine, cid, bram)
    assert "Dracula" in str(_row(migrated_engine, unrelated).input)


def test_a_wildcard_in_an_address_matches_only_itself(
    migrated_engine: Engine, committed_company: Company, settings: Settings
) -> None:
    cid = committed_company.id
    odd = add_person(migrated_engine, cid, "Odd", "a_b%c@example.test")
    add_mail(migrated_engine, cid, "Ok", sender="a_b%c@example.test", person_id=odd)
    lookalike = _call(migrated_engine, settings, cid, "Mail van axbyyc@example.test")
    _erase(migrated_engine, cid, odd)
    assert "axbyyc" in str(_row(migrated_engine, lookalike).input)


def test_pipeline_calls_for_a_message_record_its_id(
    migrated_engine: Engine, committed_company: Company, settings: Settings
) -> None:
    from app.directory.identity import resolve_message_sender
    from app.pipeline.link import link_message
    from app.pipeline.understand import understand_message

    cid = committed_company.id
    anouk = add_person(migrated_engine, cid, "Anouk de Vries", ANOUK)
    mid = add_mail(migrated_engine, cid, "De kraan lekt in de keuken.", sender=ANOUK, person_id=anouk)
    understand_message(migrated_engine, settings, mid)
    resolve_message_sender(migrated_engine, mid)
    link_message(migrated_engine, settings, mid)
    with Session(migrated_engine) as s:
        rows = s.execute(select(ModelCall.purpose, ModelCall.message_ids).where(ModelCall.company_id == cid)).all()
    assert rows
    assert all(ids == [mid] for _, ids in rows), rows


def test_erasure_clears_other_peoples_memory_that_names_the_person(
    migrated_engine: Engine, committed_company: Company, settings: Settings
) -> None:
    from app.db.models import PersonProfile

    cid = committed_company.id
    anouk = add_person(migrated_engine, cid, "Anouk de Vries", ANOUK)
    jan = add_person(migrated_engine, cid, "Jan", "jan@bouw.test")
    add_mail(migrated_engine, cid, "Ok", sender=ANOUK, person_id=anouk)
    memory = {"summary": "Werkt bij Anouk de Vries", "commitments": [], "preferences": [], "open_issues": []}
    other = {"summary": "Anders", "commitments": [], "preferences": [], "open_issues": []}
    bram = add_person(migrated_engine, cid, "Bram", BRAM)
    with Session(migrated_engine) as s, s.begin():
        s.add(PersonProfile(company_id=cid, person_id=jan, memory=memory))
        s.add(PersonProfile(company_id=cid, person_id=bram, memory=other))
    _erase(migrated_engine, cid, anouk)
    with Session(migrated_engine) as s:
        rows = dict(s.execute(select(PersonProfile.person_id, PersonProfile.memory)).tuples().all())
    assert rows[jan] is None
    assert rows[bram] == other


def test_a_stock_phrase_in_the_persons_mail_blanks_nobody_elses_calls(
    migrated_engine: Engine, committed_company: Company, settings: Settings
) -> None:
    cid = committed_company.id
    anouk = add_person(migrated_engine, cid, "Anouk", ANOUK)
    add_mail(migrated_engine, cid, "Ok\nVerzonden vanaf mijn iPhone", sender=ANOUK, person_id=anouk)
    add_mail(migrated_engine, cid, "Ja\nMet vriendelijke groeten, Anouk", sender=ANOUK, person_id=anouk)
    kept = _call(
        migrated_engine, settings, cid, "Bram: lekkage.\nVerzonden vanaf mijn iPhone\nMet vriendelijke groeten,"
    )
    _erase(migrated_engine, cid, anouk)
    assert "lekkage" in str(_row(migrated_engine, kept).input)


def test_a_call_tagged_with_other_messages_is_judged_by_its_tags(
    migrated_engine: Engine, committed_company: Company, settings: Settings
) -> None:
    """Tagged calls list every message in their prompt; only untagged ones are searched by text."""
    cid = committed_company.id
    anouk = add_person(migrated_engine, cid, "Anouk de Vries", ANOUK)
    bram = add_person(migrated_engine, cid, "Bram", BRAM)
    add_mail(migrated_engine, cid, SECRET, sender=ANOUK, person_id=anouk)
    bram_mid = add_mail(migrated_engine, cid, "Mijn buurvrouw Anouk de Vries klaagt.", sender=BRAM, person_id=bram)
    tagged = _call(migrated_engine, settings, cid, "Mijn buurvrouw Anouk de Vries klaagt.", (bram_mid,))
    _erase(migrated_engine, cid, anouk)
    assert "buurvrouw" in str(_row(migrated_engine, tagged).input)
