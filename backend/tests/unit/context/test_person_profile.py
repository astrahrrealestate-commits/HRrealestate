"""Unit tests for person profiles and tenant memory (Task C10)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from app.context.person_profile import (
    get_or_create_profile,
    mark_stale,
    person_profile_line,
    refresh_profile_deterministic,
    update_case_counts,
)
from app.contracts import Category, Channel, Entities, Suspicious, Understanding, Urgency
from app.db.enums import PersonKind
from app.db.models import Person, PersonProfile
from app.llm.agents.link_check import CandidateCase, link_check_prompt
from app.llm.agents.proposer import Contractor, ProposerContext, proposer_prompt


def test_person_profile_line_formatting() -> None:
    assert person_profile_line(None) is None

    empty = PersonProfile(
        id=uuid4(),
        company_id=uuid4(),
        person_id=uuid4(),
        language="nl",
        preferred_channel="whatsapp",
        summary="   ",
        open_cases=0,
        closed_cases=0,
        profile_version=1,
    )
    assert person_profile_line(empty) is None

    profile = PersonProfile(
        id=uuid4(),
        company_id=uuid4(),
        person_id=uuid4(),
        language="nl",
        preferred_channel="whatsapp",
        summary="Sanne de Vries (tenant): 1 open case, 2 closed cases.",
        open_cases=1,
        closed_cases=2,
        profile_version=1,
    )
    line = person_profile_line(profile)
    assert line == "Profile (nl, whatsapp): Sanne de Vries (tenant): 1 open case, 2 closed cases."


def test_get_or_create_profile_existing() -> None:
    session = MagicMock()
    company_id = uuid4()
    person_id = uuid4()
    existing = PersonProfile(
        id=uuid4(),
        company_id=company_id,
        person_id=person_id,
        language="en",
        preferred_channel="gmail",
        summary="Existing profile",
        open_cases=0,
        closed_cases=0,
        profile_version=1,
    )
    session.scalar.return_value = existing

    result = get_or_create_profile(session, company_id, person_id)
    assert result is existing
    session.add.assert_not_called()


def test_get_or_create_profile_new() -> None:
    session = MagicMock()
    company_id = uuid4()
    person_id = uuid4()
    session.scalar.return_value = None

    result = get_or_create_profile(session, company_id, person_id)
    assert result.company_id == company_id
    assert result.person_id == person_id
    assert result.language == "nl"
    assert result.preferred_channel == "whatsapp"
    assert result.profile_version == 1
    session.add.assert_called_once_with(result)
    session.flush.assert_called_once()


def test_mark_stale() -> None:
    session = MagicMock()
    company_id = uuid4()
    person_id = uuid4()
    profile = PersonProfile(
        id=uuid4(),
        company_id=company_id,
        person_id=person_id,
        language="nl",
        preferred_channel="whatsapp",
        summary="",
        open_cases=0,
        closed_cases=0,
        profile_version=1,
        last_contact_at=None,
    )
    session.scalar.return_value = profile

    sent_at = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    mark_stale(session, company_id, person_id, sent_at)

    assert profile.source_max_message_at == sent_at
    assert profile.last_contact_at == sent_at


def test_update_case_counts() -> None:
    session = MagicMock()
    company_id = uuid4()
    person_id = uuid4()
    session.scalar.side_effect = [3, 7]  # open=3, closed=7

    open_c, closed_c = update_case_counts(session, company_id, person_id)
    assert open_c == 3
    assert closed_c == 7


def test_refresh_profile_deterministic() -> None:
    session = MagicMock()
    company_id = uuid4()
    person_id = uuid4()

    profile = PersonProfile(
        id=uuid4(),
        company_id=company_id,
        person_id=person_id,
        language="nl",
        preferred_channel="whatsapp",
        summary="old summary",
        open_cases=0,
        closed_cases=0,
        profile_version=1,
    )
    person = Person(
        id=person_id,
        company_id=company_id,
        display_name="Jan Jansen",
        kind=PersonKind.tenant,
    )

    # session.scalar for get_or_create_profile, then for person, then counts in update_case_counts
    session.scalar.side_effect = [profile, person, 2, 4]
    latest_time = datetime(2026, 10, 23, 14, 0, tzinfo=UTC)
    session.execute.return_value.first.return_value = (Channel.whatsapp, latest_time)

    refreshed = refresh_profile_deterministic(session, company_id, person_id)
    assert refreshed.open_cases == 2
    assert refreshed.closed_cases == 4
    assert refreshed.preferred_channel == "whatsapp"
    assert refreshed.last_contact_at == latest_time
    assert refreshed.summary == "Jan Jansen (tenant): 2 open case(s), 4 closed case(s)."
    assert refreshed.profile_version == 2


def test_link_check_prompt_includes_person_profile() -> None:
    cand = CandidateCase(case_id=uuid4(), category=Category.maintenance, summary="Leak", last_message_at=None)
    profile_line = "Profile (nl, whatsapp): Jan Jansen (tenant): 1 open case."
    prompt = link_check_prompt("Still leaking", Category.maintenance, [cand], person_profile=profile_line)

    assert profile_line in prompt
    assert "<data>" in prompt
    assert "candidate:" in prompt


def test_proposer_prompt_includes_person_profile() -> None:
    und = Understanding(
        category=Category.maintenance,
        urgency=Urgency.normal,
        intent="fix leak",
        requires_reply=True,
        entities=Entities.none(),
        suspicious=Suspicious(flag=False, reason=None),
        confidence=0.9,
        sender_role=None,
        prompt_version="understanding/v2",
    )
    profile_line = "Profile (nl, whatsapp): Jan Jansen (tenant): 1 open case."
    ctx = ProposerContext(
        case_id=uuid4(),
        channel=Channel.gmail,
        subject="Water leak",
        message_text="Water is dripping",
        understanding=und,
        case_state="open",
        case_summary="Leak ongoing",
        waiting=(),
        contractors=(Contractor(uuid4(), "Plumber Bob", "plumber"),),
        mode="reply",
        person_profile=profile_line,
    )
    prompt = proposer_prompt(ctx)
    assert "<person_profile>\nProfile (nl, whatsapp): Jan Jansen (tenant): 1 open case.\n</person_profile>" in prompt
