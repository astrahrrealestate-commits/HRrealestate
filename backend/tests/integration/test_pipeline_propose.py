"""Propose stage (#4 + rules): proposer → rules → actions/approvals/tasks; replay-safe; fallbacks."""

from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.contracts import (
    ActionType,
    Category,
    Channel,
    Direction,
    Entities,
    SenderRole,
    Suspicious,
    Understanding,
    Urgency,
)
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.enums import ActionStatus, ApprovalStatus, LinkMethod, PersonKind
from app.db.models import ActionRow, Approval, Company, MessageRow, Person, RawEvent, TaskRow, UnderstandingRow
from app.pipeline import case_repo
from app.pipeline.propose import load_message, propose_for_message

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


def _setup(
    engine: Engine,
    cid: UUID,
    *,
    urgency: Urgency = Urgency.normal,
    suspicious: bool = False,
    requires_reply: bool = True,
    person_kind: PersonKind = PersonKind.tenant,
    sender_role: SenderRole | None = None,
) -> UUID:
    und = Understanding(
        category=Category.maintenance,
        intent="Leak",
        urgency=urgency,
        requires_reply=requires_reply,
        entities=Entities.none(),
        suspicious=Suspicious(flag=suspicious, reason="IBAN change" if suspicious else None),
        confidence=0.9,
        sender_role=sender_role,
        prompt_version="understanding/v2",
    )
    with Session(engine) as s, s.begin():
        p = Person(company_id=cid, kind=person_kind, display_name="Sanne", valid_from=date(2026, 1, 1))
        raw = RawEvent(company_id=cid, provider=Channel.gmail, provider_msg_id=str(new_id()), payload={})
        s.add_all([p, raw])
        s.flush()
        msg = MessageRow(
            company_id=cid,
            raw_event_id=raw.id,
            channel=Channel.gmail,
            provider_msg_id=raw.provider_msg_id,
            thread_ref="t1",
            sender_identity="sanne@example.test",
            direction=Direction.inbound,
            sent_at=NOW,
            text="Er lekt water",
            person_id=p.id,
            meta={"subject": "Lekkage"},
        )
        s.add(msg)
        s.flush()
        s.add(
            UnderstandingRow(
                company_id=cid,
                message_id=msg.id,
                category=und.category,
                urgency=und.urgency,
                body=und.model_dump(mode="json"),
                prompt_version=und.prompt_version,
            )
        )
        case_id = case_repo.create_case(s, cid, p.id, Category.maintenance, urgency)
        case_repo.link_message(s, cid, case_id, msg.id, LinkMethod.new_case, None)
        return msg.id


def _actions(engine: Engine, cid: UUID) -> list[ActionRow]:
    with Session(engine) as s:
        return list(s.scalars(select(ActionRow).where(ActionRow.company_id == cid).order_by(ActionRow.created_at)))


def test_reply_and_escalation_await_approval_with_tasks(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    cid = committed_company.id
    mid = _setup(migrated_engine, cid, urgency=Urgency.emergency)
    result = propose_for_message(migrated_engine, test_settings, mid)
    actions = _actions(migrated_engine, cid)
    # One transaction writes both, so created_at ties: the order between them is not part of the behaviour.
    assert sorted(a.type for a in actions) == sorted([ActionType.reply_draft, ActionType.escalate])
    assert all(a.status is ActionStatus.pending_approval and a.context_ref == [mid] for a in actions)
    assert len(result.approval_ids) == 2
    with Session(migrated_engine) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(Approval)
                .where(Approval.company_id == cid, Approval.status == ApprovalStatus.pending)
            )
            == 2
        )
        assert s.scalar(select(func.count()).select_from(TaskRow).where(TaskRow.company_id == cid)) == 2
    again = propose_for_message(migrated_engine, test_settings, mid)  # replay: no second proposal
    assert sorted(again.approval_ids) == sorted(result.approval_ids)
    assert len(_actions(migrated_engine, cid)) == 2


def test_suspicious_message_becomes_exception_without_approvals(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    cid = committed_company.id
    result = propose_for_message(migrated_engine, test_settings, _setup(migrated_engine, cid, suspicious=True))
    assert result.approval_ids == []
    assert result.exceptions == 1
    assert {a.status for a in _actions(migrated_engine, cid)} == {ActionStatus.exception}


def test_paused_company_stores_paused_actions(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    cid = committed_company.id
    mid = _setup(migrated_engine, cid)
    with Session(migrated_engine) as s, s.begin():
        company = s.get(Company, cid)
        assert company is not None
        company.paused = True
    assert propose_for_message(migrated_engine, test_settings, mid).approval_ids == []
    assert {a.status for a in _actions(migrated_engine, cid)} == {ActionStatus.paused}


def test_failed_proposer_falls_back_to_owner_notice(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"actions": []})])

    monkeypatch.setattr("app.llm.calls.build_model", lambda _s, _n: FunctionModel(broken))
    cid = committed_company.id
    result = propose_for_message(migrated_engine, test_settings, _setup(migrated_engine, cid))
    [action] = _actions(migrated_engine, cid)
    assert action.type is ActionType.notify_owner
    assert "could not draft" in action.payload["text"].lower()
    assert len(result.approval_ids) == 1


def test_reply_channel_comes_from_the_message_not_the_model(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def wrong_channel(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        action = {
            "type": "reply_draft",
            "case_id": str(new_id()),
            "rationale": "r",
            "context_ref": [],
            "draft_version": 1,
            "payload": {"kind": "reply_draft", "channel": "whatsapp", "subject": None, "body_variants": ["A", "B"]},
        }
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"actions": [action]})])

    monkeypatch.setattr("app.llm.calls.build_model", lambda _s, _n: FunctionModel(wrong_channel))
    cid = committed_company.id
    propose_for_message(migrated_engine, test_settings, _setup(migrated_engine, cid))  # a gmail message
    [action] = _actions(migrated_engine, cid)
    assert action.payload["channel"] == "gmail"


def test_mail_that_needs_no_reply_gets_no_proposal_no_draft_and_no_model_call(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(_s: object, _n: object) -> None:
        raise AssertionError("the proposer must not be called for mail that needs no reply")

    monkeypatch.setattr("app.llm.calls.build_model", forbidden)
    cid = committed_company.id
    result = propose_for_message(migrated_engine, test_settings, _setup(migrated_engine, cid, requires_reply=False))
    assert (result.approval_ids, result.exceptions) == ([], 0)
    assert _actions(migrated_engine, cid) == []


def test_suspicious_mail_is_still_flagged_even_if_it_needs_no_reply(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    """A phishing mail that "needs no reply" must still reach Harjot as an exception, never vanish."""
    cid = committed_company.id
    mid = _setup(migrated_engine, cid, suspicious=True, requires_reply=False)
    result = propose_for_message(migrated_engine, test_settings, mid)
    assert result.exceptions == 1
    assert {a.status for a in _actions(migrated_engine, cid)} == {ActionStatus.exception}


def test_the_proposer_is_told_who_wrote_from_the_directory_then_the_models_role(
    migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    stranger = load_message(migrated_engine, _setup(migrated_engine, cid, person_kind=PersonKind.other))
    lawyer = load_message(
        migrated_engine, _setup(migrated_engine, cid, person_kind=PersonKind.other, sender_role=SenderRole.legal)
    )
    tenant = load_message(
        migrated_engine, _setup(migrated_engine, cid, person_kind=PersonKind.tenant, sender_role=SenderRole.legal)
    )
    assert stranger is not None
    assert lawyer is not None
    assert tenant is not None
    assert (stranger.ctx.sender_kind, lawyer.ctx.sender_kind) == ("contact", "legal")
    assert tenant.ctx.sender_kind == "tenant"  # the directory beats the model's role


def test_a_draft_to_a_lawyer_carries_a_review_note_and_a_tenant_draft_does_not(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    cid = committed_company.id
    propose_for_message(
        migrated_engine,
        test_settings,
        _setup(migrated_engine, cid, person_kind=PersonKind.other, sender_role=SenderRole.legal),
    )
    legal = [a for a in _actions(migrated_engine, cid) if a.type is ActionType.reply_draft]
    assert legal
    assert all("legal sender" in a.rationale.lower() for a in legal)
    assert all(a.status is ActionStatus.pending_approval for a in legal)  # flagged, still his to approve


def test_a_tenant_draft_carries_no_review_note(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    cid = committed_company.id
    propose_for_message(
        migrated_engine, test_settings, _setup(migrated_engine, cid, sender_role=SenderRole.legal)
    )  # a tenant in the directory is a tenant, whatever the model called the sender
    replies = [a for a in _actions(migrated_engine, cid) if a.type is ActionType.reply_draft]
    assert replies
    assert all("legal sender" not in a.rationale.lower() for a in replies)


def test_owner_authored_mail_is_never_drafted(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    cid = committed_company.id
    mid = _setup(migrated_engine, cid, urgency=Urgency.emergency)
    with Session(migrated_engine) as s, s.begin():
        msg = s.get_one(MessageRow, mid)
        msg.meta = {**msg.meta, "owner_authored": True}
    assert propose_for_message(migrated_engine, test_settings, mid).approval_ids == []
    assert _actions(migrated_engine, cid) == []
    assert load_message(migrated_engine, mid) is None  # an owner-requested redraft has nobody to write to either
