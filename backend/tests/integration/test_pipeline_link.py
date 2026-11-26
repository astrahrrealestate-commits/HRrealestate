"""Link step (#3): sender → person, message → case (thread, single open case, link_check, new), rolling summary."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from app.contracts import CaseState, Category, Channel, Direction, Urgency
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.enums import LinkMethod, PersonKind, WaitStatus
from app.db.models import Case, CaseLink, Company, MessageRow, Person, RawEvent, UnderstandingRow, WaitRow
from app.directory.identity import resolve_message_sender
from app.pipeline import case_repo, work_repo
from app.pipeline.link import LinkResult
from app.pipeline.link import link_message as _link_only

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
PHONE = "+31612345678"


def _message(
    engine: Engine,
    cid: UUID,
    text: str,
    *,
    category: Category = Category.maintenance,
    at: datetime = NOW,
    thread: str | None = PHONE,
    sender: str = PHONE,
    channel: Channel = Channel.whatsapp,
    meta: dict[str, Any] | None = None,
    requires_reply: bool = True,
) -> UUID:
    with Session(engine) as s, s.begin():
        raw = RawEvent(company_id=cid, provider=channel, provider_msg_id=str(new_id()), payload={})
        s.add(raw)
        s.flush()
        msg = MessageRow(
            company_id=cid,
            raw_event_id=raw.id,
            channel=channel,
            provider_msg_id=raw.provider_msg_id,
            thread_ref=thread,
            sender_identity=sender,
            direction=Direction.inbound,
            sent_at=at,
            text=text,
            meta=meta or {"contact_name": "Sanne de Vries"},
        )
        s.add(msg)
        s.flush()
        s.add(
            UnderstandingRow(
                company_id=cid,
                message_id=msg.id,
                category=category,
                urgency=Urgency.high,
                body={"intent": "Lekkage", "requires_reply": requires_reply},
                prompt_version="understanding/v2",
            )
        )
        return msg.id


def link_message(engine: Engine, settings: Settings, message_id: UUID) -> LinkResult | None:
    """What the pipeline does: the directory step resolves the sender, then the link stage runs."""
    resolve_message_sender(engine, message_id)
    return _link_only(engine, settings, message_id)


def _link(engine: Engine, cid: UUID, msg_id: UUID) -> tuple[UUID, LinkMethod]:
    with Session(engine) as s:
        row = s.scalar(select(CaseLink).where(CaseLink.company_id == cid, CaseLink.message_id == msg_id))
        assert row is not None
        return row.case_id, row.method


def test_first_message_creates_person_and_case_with_summary(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    cid = committed_company.id
    mid = _message(migrated_engine, cid, "Er lekt water uit het plafond")
    result = link_message(migrated_engine, test_settings, mid)
    assert result is not None
    assert result.method is LinkMethod.new_case
    with Session(migrated_engine) as s:
        case = s.get(Case, result.case_id)
        msg = s.get(MessageRow, mid)
        assert case is not None
        assert msg is not None
        assert (case.category, case.urgency, case.primary_person_id) == (
            Category.maintenance,
            Urgency.high,
            msg.person_id,
        )
        assert case.summary_version == 1
        assert "Er lekt water uit het plafond" in case.summary
    assert link_message(migrated_engine, test_settings, mid) == result  # replay: same answer, no new rows
    with Session(migrated_engine) as s:
        assert s.scalar(select(func.count()).select_from(Case).where(Case.company_id == cid)) == 1


def test_same_whatsapp_thread_links_to_same_case(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    cid = committed_company.id
    first = link_message(migrated_engine, test_settings, _message(migrated_engine, cid, "Lekkage"))
    second_id = _message(migrated_engine, cid, "Hier een foto", at=NOW + timedelta(hours=2))
    second = link_message(migrated_engine, test_settings, second_id)
    assert first is not None
    assert second is not None
    assert (second.case_id, second.method) == (first.case_id, LinkMethod.thread)


def test_single_open_case_of_person_without_thread(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    cid = committed_company.id
    first = link_message(migrated_engine, test_settings, _message(migrated_engine, cid, "Lekkage"))
    later = _message(migrated_engine, cid, "Nog steeds lek", at=NOW + timedelta(days=5))  # outside the 72 h window
    result = link_message(migrated_engine, test_settings, later)
    assert first is not None
    assert result is not None
    assert (result.case_id, result.method) == (first.case_id, LinkMethod.open_case)


def test_several_open_cases_go_to_link_check(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    cid = committed_company.id
    a = link_message(migrated_engine, test_settings, _message(migrated_engine, cid, "Lekkage"))
    assert a is not None
    with Session(migrated_engine) as s, s.begin():
        person = s.scalar(select(Case.primary_person_id).where(Case.id == a.case_id))
        case_repo.create_case(s, cid, person, Category.finance, Urgency.normal)
    later = _message(migrated_engine, cid, "Lekkage weer", at=NOW + timedelta(days=5), category=Category.administration)
    result = link_message(migrated_engine, test_settings, later)
    assert result is not None
    assert result.method is LinkMethod.model  # the fake picks the candidate whose summary shares a word ("lekkage")
    assert result.case_id == a.case_id


def test_spam_opens_no_case(migrated_engine: Engine, committed_company: Company, test_settings: Settings) -> None:
    mid = _message(migrated_engine, committed_company.id, "Win een iPhone", category=Category.spam)
    assert link_message(migrated_engine, test_settings, mid) is None
    with Session(migrated_engine) as s:
        assert s.scalar(select(func.count()).select_from(CaseLink).where(CaseLink.message_id == mid)) == 0


def test_answer_from_awaited_party_closes_wait_and_reopens_case(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    cid = committed_company.id
    first = link_message(migrated_engine, test_settings, _message(migrated_engine, cid, "Lekkage"))
    assert first is not None
    with Session(migrated_engine) as s, s.begin():
        case_repo.transition(s, cid, first.case_id, CaseState.waiting_on_third_party, actor="system")
        wid = work_repo.open_wait(s, cid, first.case_id, first.person_id, about="Foto", expected_by=NOW)
        s.execute(update(WaitRow).where(WaitRow.id == wid).values(created_at=NOW))
    link_message(migrated_engine, test_settings, _message(migrated_engine, cid, "Foto", at=NOW + timedelta(hours=1)))
    with Session(migrated_engine) as s:
        assert work_repo.get_wait(s, cid, wid).status is WaitStatus.received
        assert s.scalar(select(Case.state).where(Case.id == first.case_id)) is CaseState.open


def test_photo_only_message_marked_spam_still_opens_a_case(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    """A model may call an empty, attachment-only message spam; a tenant's photo must never be dropped."""
    from app.db.models import AttachmentRow

    cid = committed_company.id
    mid = _message(migrated_engine, cid, "", category=Category.spam)
    with Session(migrated_engine) as s, s.begin():
        s.add(
            AttachmentRow(
                company_id=cid,
                message_id=mid,
                s3_key="k",
                mime_type="image/jpeg",
                filename="IMG.jpg",
                size_bytes=50_000,
                sha256="0" * 64,
            )
        )
    result = link_message(migrated_engine, test_settings, mid)
    assert result is not None
    with Session(migrated_engine) as s:
        assert s.scalar(select(Case.category).where(Case.id == result.case_id)) is Category.administration


def test_mail_needing_no_reply_opens_no_case_but_joins_an_existing_thread(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = committed_company.id
    first = link_message(migrated_engine, test_settings, _message(migrated_engine, cid, "Lekkage"))
    assert first is not None

    def forbidden(_s: object, _n: object) -> None:
        raise AssertionError("no model call for mail that needs no reply")

    monkeypatch.setattr("app.llm.calls.build_model", forbidden)
    newsletter = _message(migrated_engine, cid, "Tips!", thread="news-1", requires_reply=False)
    assert link_message(migrated_engine, test_settings, newsletter) is None  # no case, nothing to look at
    thanks = _message(migrated_engine, cid, "Bedankt!", requires_reply=False, at=NOW + timedelta(hours=1))
    joined = link_message(migrated_engine, test_settings, thanks)  # same thread as the open case: history only
    assert joined is not None
    assert joined.case_id == first.case_id
    with Session(migrated_engine) as s:
        assert s.scalar(select(func.count()).select_from(Case).where(Case.company_id == cid)) == 1


def test_unreadable_message_lands_in_administration(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    """A message the understanding agent could not read has no understanding row; it opens an Administration case."""
    cid = committed_company.id
    mid = _message(migrated_engine, cid, "????")
    resolve_message_sender(migrated_engine, mid)
    with Session(migrated_engine) as s, s.begin():
        s.query(UnderstandingRow).filter(UnderstandingRow.message_id == mid).delete()
        person_id = s.scalar(select(MessageRow.person_id).where(MessageRow.id == mid))
        s.query(Person).filter(Person.id == person_id).update({Person.kind: PersonKind.tenant})  # a known tenant
    result = _link_only(migrated_engine, test_settings, mid)
    assert result is not None
    with Session(migrated_engine) as s:
        assert s.scalar(select(Case.category).where(Case.id == result.case_id)) is Category.administration
