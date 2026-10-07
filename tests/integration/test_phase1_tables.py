"""Constraints of the Phase 1 agent tables (tasks, waits, documents, metric snapshots) and company defaults."""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts import Category, Channel, Direction, Urgency
from app.core.ids import new_id
from app.db.enums import PersonKind, PipelineStatus, TaskPriority, TaskStatus, WaitStatus
from app.db.models import (
    AttachmentRow,
    Case,
    Company,
    DocumentRow,
    MessageRow,
    MetricSnapshot,
    Person,
    RawEvent,
    TaskRow,
    WaitRow,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


def _case(db: Session, company: Company) -> Case:
    case = Case(company_id=company.id, category=Category.maintenance, urgency=Urgency.normal)
    db.add(case)
    db.flush()
    return case


def _person(db: Session, company: Company) -> Person:
    p = Person(company_id=company.id, kind=PersonKind.other, display_name="Mieter", valid_from=date(2026, 1, 1))
    db.add(p)
    db.flush()
    return p


def _message(db: Session, company: Company) -> MessageRow:
    raw = RawEvent(company_id=company.id, provider=Channel.whatsapp, provider_msg_id=str(new_id()), payload={})
    db.add(raw)
    db.flush()
    msg = MessageRow(
        company_id=company.id,
        raw_event_id=raw.id,
        channel=Channel.whatsapp,
        provider_msg_id=raw.provider_msg_id,
        sender_identity="+4915550000001",
        direction=Direction.inbound,
        sent_at=NOW,
        text="hallo",
    )
    db.add(msg)
    db.flush()
    return msg


def _assert_rejected(db: Session, row: object) -> None:
    """The insert violates a unique constraint; the savepoint keeps the test transaction usable."""
    nested = db.begin_nested()
    db.add(row)
    with pytest.raises(IntegrityError):
        db.flush()
    nested.rollback()


def test_company_defaults_are_dutch_and_chase_ladder(db: Session, company: Company) -> None:
    db.refresh(company)
    assert company.timezone == "Europe/Amsterdam"
    assert (company.chase_after_days, company.escalate_after_chases) == (3, 2)
    assert (company.briefing_time, company.weekly_weekday, company.weekly_time) == (time(7, 30), 4, time(16, 0))
    assert company.drift_thresholds == {}


def test_message_pipeline_status_defaults_pending(db: Session, company: Company) -> None:
    msg = _message(db, company)
    db.refresh(msg)
    assert (msg.pipeline_status, msg.pipeline_attempts, msg.pipeline_error) == (PipelineStatus.pending, 0, None)


def test_one_open_wait_per_case_and_party(db: Session, company: Company) -> None:
    case, party = _case(db, company), _person(db, company)
    first = WaitRow(company_id=company.id, case_id=case.id, party_person_id=party.id, about="quote", expected_by=NOW)
    db.add(first)
    db.flush()
    first.status = WaitStatus.received
    db.flush()
    db.add(WaitRow(company_id=company.id, case_id=case.id, party_person_id=party.id, about="again", expected_by=NOW))
    db.flush()  # the earlier wait is closed, so a new open one is allowed
    _assert_rejected(
        db, WaitRow(company_id=company.id, case_id=case.id, party_person_id=party.id, about="dup", expected_by=NOW)
    )


def test_task_defaults_and_one_task_per_action_source(db: Session, company: Company) -> None:
    case = _case(db, company)
    action_id = new_id()
    task = TaskRow(company_id=company.id, case_id=case.id, title="Decide", assignee="owner", source="approval")
    db.add(task)
    db.flush()
    db.refresh(task)
    assert (task.status, task.priority) == (TaskStatus.open, TaskPriority.p2)
    from app.contracts import ActionType
    from app.db.models import ActionRow

    action = ActionRow(
        id=action_id,
        company_id=company.id,
        case_id=case.id,
        type=ActionType.notify_owner,
        payload={},
        rationale="r",
        context_ref=[],
    )
    db.add(action)
    db.flush()
    db.add(
        TaskRow(
            company_id=company.id, case_id=case.id, action_id=action_id, title="a", assignee="owner", source="approval"
        )
    )
    db.flush()
    _assert_rejected(
        db,
        TaskRow(
            company_id=company.id,
            case_id=case.id,
            action_id=action_id,
            title="b",
            assignee="owner",
            source="approval",
        ),
    )


def test_one_document_per_attachment(db: Session, company: Company) -> None:
    msg = _message(db, company)
    att = AttachmentRow(
        company_id=company.id,
        message_id=msg.id,
        s3_key="k",
        mime_type="application/pdf",
        filename="f.pdf",
        size_bytes=1,
        sha256="0" * 64,
    )
    db.add(att)
    db.flush()
    db.add(
        DocumentRow(
            company_id=company.id,
            attachment_id=att.id,
            doc_type="invoice",
            title="t",
            file_name="f.pdf",
            confidence=0.9,
        )
    )
    db.flush()
    _assert_rejected(
        db,
        DocumentRow(
            company_id=company.id, attachment_id=att.id, doc_type="other", title="t", file_name="g", confidence=0.1
        ),
    )


def test_one_metric_snapshot_per_company_day_metric(db: Session, company: Company) -> None:
    day = (NOW - timedelta(days=1)).date()
    db.add(MetricSnapshot(company_id=company.id, day=day, metric="llm_cost_usd", value=1.5))
    db.flush()
    _assert_rejected(db, MetricSnapshot(company_id=company.id, day=day, metric="llm_cost_usd", value=2.0))
