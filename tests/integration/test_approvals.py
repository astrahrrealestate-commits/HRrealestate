"""Approvals: one live approval per draft version, button decisions (idempotent), owner edit → new revision."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts import ActionType, ButtonChoice, Category, Urgency
from app.db.enums import ActionStatus, ApprovalStatus, TaskStatus
from app.db.models import ActionRevision, ActionRow, Approval, Company, TaskRow
from app.pipeline import approvals, case_repo

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
PAYLOAD = {"kind": "reply_draft", "channel": "gmail", "subject": "Re: Lekkage", "body_variants": ["A", "B", "C"]}


def _action(db: Session, company: Company) -> ActionRow:
    case_id = case_repo.create_case(db, company.id, None, Category.maintenance, Urgency.high)
    a = ActionRow(
        company_id=company.id, case_id=case_id, type=ActionType.reply_draft, payload=PAYLOAD, rationale="r",
        context_ref=[], status=ActionStatus.pending_approval,
    )  # fmt: skip
    db.add(a)
    db.flush()
    return a


def test_open_is_idempotent_and_creates_owner_task(db: Session, company: Company) -> None:
    action = _action(db, company)
    first = approvals.open_approval(db, company.id, action.id, 1, urgency=Urgency.high, now=NOW)
    assert approvals.open_approval(db, company.id, action.id, 1, urgency=Urgency.high, now=NOW) == first
    task = db.scalar(select(TaskRow).where(TaskRow.action_id == action.id))
    assert task is not None
    assert (task.assignee, task.source, task.status) == ("owner", "approval", TaskStatus.open)


def test_choose_draft_approves_once(db: Session, company: Company) -> None:
    action = _action(db, company)
    aid = approvals.open_approval(db, company.id, action.id, 1, urgency=Urgency.normal, now=NOW)
    d = approvals.decide(db, company.id, aid, ButtonChoice.d2, at=NOW)
    assert (d.kind, d.action_id, d.draft_version, d.variant) == ("execute", action.id, 1, 1)
    again = approvals.decide(db, company.id, aid, ButtonChoice.d3, at=NOW)  # duplicate / late tap
    assert (again.kind, again.variant) == ("execute", 1)  # first decision stands
    db.refresh(action)
    assert action.status is ActionStatus.approved
    assert db.scalar(select(TaskRow.status).where(TaskRow.action_id == action.id)) is TaskStatus.done


def test_reject(db: Session, company: Company) -> None:
    action = _action(db, company)
    aid = approvals.open_approval(db, company.id, action.id, 1, urgency=Urgency.low, now=NOW)
    assert approvals.decide(db, company.id, aid, ButtonChoice.rej, at=NOW).kind == "rejected"
    db.refresh(action)
    assert action.status is ActionStatus.rejected


def test_edit_then_text_creates_revision_and_new_approval(db: Session, company: Company) -> None:
    action = _action(db, company)
    aid = approvals.open_approval(db, company.id, action.id, 1, urgency=Urgency.normal, now=NOW)
    assert approvals.decide(db, company.id, aid, ButtonChoice.edit, at=NOW).kind == "edit"
    new = approvals.apply_owner_edit(db, company.id, "Beste Sanne, morgen komt de loodgieter.", now=NOW)
    assert new is not None
    db.refresh(action)
    assert action.draft_version == 2
    assert action.payload["body_variants"] == ["Beste Sanne, morgen komt de loodgieter."]
    rev = db.scalar(select(ActionRevision).where(ActionRevision.action_id == action.id))
    assert rev is not None
    assert (rev.draft_version, rev.edited_by) == (2, "owner")
    live = db.scalar(select(Approval).where(Approval.id == new.approval_id))
    assert live is not None
    assert (live.draft_version, live.status) == (2, ApprovalStatus.pending)
    assert approvals.apply_owner_edit(db, company.id, "second text", now=NOW) is None  # nothing awaiting an edit


def test_ok_on_single_variant(db: Session, company: Company) -> None:
    action = _action(db, company)
    aid = approvals.open_approval(db, company.id, action.id, 1, urgency=Urgency.normal, now=NOW)
    assert approvals.decide(db, company.id, aid, ButtonChoice.ok, at=NOW).variant == 0
    assert db.scalar(select(func.count()).select_from(Approval).where(Approval.action_id == action.id)) == 1
