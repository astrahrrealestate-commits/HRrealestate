"""Propose stage (#4 + rules): proposer → rules → actions/approvals/tasks; replay-safe; fallbacks."""

from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.contracts import ActionType, Category, Channel, Direction, Entities, Suspicious, Understanding, Urgency
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.enums import ActionStatus, ApprovalStatus, LinkMethod, PersonKind
from app.db.models import ActionRow, Approval, Company, MessageRow, Person, RawEvent, TaskRow, UnderstandingRow
from app.pipeline import case_repo
from app.pipeline.propose import propose_for_message

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


def _setup(engine: Engine, cid: UUID, *, urgency: Urgency = Urgency.normal, suspicious: bool = False) -> UUID:
    und = Understanding(
        category=Category.maintenance,
        intent="Leak",
        urgency=urgency,
        entities=Entities.none(),
        suspicious=Suspicious(flag=suspicious, reason="IBAN change" if suspicious else None),
        confidence=0.9,
        prompt_version="understanding/v1",
    )
    with Session(engine) as s, s.begin():
        p = Person(company_id=cid, kind=PersonKind.tenant, display_name="Sanne", valid_from=date(2026, 1, 1))
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
    assert [a.type for a in actions] == [ActionType.reply_draft, ActionType.escalate]
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
