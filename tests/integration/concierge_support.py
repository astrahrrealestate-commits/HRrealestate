"""Shared seed helpers for the concierge executor integration tests."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.contracts import (
    Category,
    Channel,
    ConciergePlan,
    Direction,
    Entities,
    Intent,
    PlanStep,
    Suspicious,
    Understanding,
    Urgency,
)
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.enums import LinkMethod, PersonKind
from app.db.models import MessageRow, Person, RawEvent, UnderstandingRow
from app.pipeline import case_repo, work_repo
from app.pipeline.concierge import run_plan
from app.pipeline.concierge_base import StepResult

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)  # a Wednesday
EVIL = "evil@attacker.test"


def step(intent: Intent, **kw: Any) -> PlanStep:
    return PlanStep(
        intent=intent, case_id=kw.get("case_id"), task_ref=kw.get("task_ref"), text=kw.get("text"), view=kw.get("view")
    )


def plan(*steps: PlanStep) -> ConciergePlan:
    return ConciergePlan(in_scope=True, steps=list(steps))


def understanding(requires_reply: bool = True) -> Understanding:
    return Understanding(
        category=Category.maintenance,
        intent="Leak",
        urgency=Urgency.normal,
        requires_reply=requires_reply,
        entities=Entities.none(),
        suspicious=Suspicious(flag=False, reason=None),
        confidence=0.9,
        prompt_version="understanding/v2",
    )


def seed_case(
    engine: Engine, cid: UUID, text: str = "Er lekt water in de badkamer", *, requires_reply: bool = True
) -> tuple[UUID, UUID]:
    """A tenant case with one inbound Gmail message and its understanding; returns (case_id, tenant_id)."""
    und = understanding(requires_reply)
    with Session(engine) as s, s.begin():
        tenant = Person(company_id=cid, kind=PersonKind.tenant, display_name="Sanne", valid_from=date(2026, 1, 1))
        raw = RawEvent(company_id=cid, provider=Channel.gmail, provider_msg_id=str(new_id()), payload={})
        s.add_all([tenant, raw])
        s.flush()
        msg = MessageRow(
            company_id=cid,
            raw_event_id=raw.id,
            channel=Channel.gmail,
            provider_msg_id=raw.provider_msg_id,
            thread_ref=f"t-{raw.id}",
            sender_identity="sanne@example.test",
            direction=Direction.inbound,
            sent_at=NOW - timedelta(hours=1),
            text=text,
            person_id=tenant.id,
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
        case_id = case_repo.create_case(s, cid, tenant.id, Category.maintenance, Urgency.normal)
        case_repo.link_message(s, cid, case_id, msg.id, LinkMethod.new_case, None)
        return case_id, tenant.id


def seed_task(engine: Engine, cid: UUID, title: str = "Call plumber") -> tuple[UUID, str]:
    with Session(engine) as s, s.begin():
        task_id = work_repo.create_task(s, cid, title=title, assignee="owner", source="owner")
    return task_id, work_repo.short_ref(task_id)


def count(engine: Engine, model: Any, cid: UUID) -> int:
    with Session(engine) as s:
        return int(s.scalar(select(func.count()).select_from(model).where(model.company_id == cid)) or 0)


def run(
    engine: Engine, settings: Settings, cid: UUID, p: ConciergePlan, *, question: str = "q", now: datetime = NOW
) -> list[StepResult]:
    return run_plan(engine, settings, cid, p, question=question, now=now)
