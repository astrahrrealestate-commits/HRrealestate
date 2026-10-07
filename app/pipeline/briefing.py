"""Executive briefing (#7): collect the facts, let the agent write them up (template fallback), schedule the runs.

Daily at `companies.briefing_time` and weekly on `weekly_weekday` at `weekly_time`, both in the company timezone.
Each run is a `timers` row keyed by its local date, so a re-run of the scheduler never doubles a briefing.
"""

from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Engine, func, select
from sqlalchemy.orm import Session

from app.contracts import Urgency
from app.core.errors import AgentFailedError, NotFoundError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import ActionStatus, ApprovalStatus
from app.db.models import ActionRow, Approval, Case, Company, Person, Timer
from app.llm.agents.briefing import BRIEFING, BriefingFacts, Kind, briefing_prompt, fallback_briefing, render_text
from app.llm.calls import CallContext, run_agent
from app.pipeline import case_repo, timers, work_repo

log = get_logger(__name__)
DAILY, WEEKLY = "briefing.daily", "briefing.weekly"


def _label(session: Session, case: Case) -> str:
    name = session.scalar(select(Person.display_name).where(Person.id == case.primary_person_id)) or "Unknown sender"
    return f"{name} · {case.category.value}"


def _first_line(text: str) -> str:
    return text.splitlines()[0][:120] if text else "no summary yet"


def _urgent(session: Session, company_id: UUID) -> list[str]:
    cases = session.scalars(
        select(Case).where(
            Case.company_id == company_id,
            Case.state.in_(case_repo.OPEN_STATES),
            Case.urgency.in_([Urgency.emergency, Urgency.high]),
        )
    ).all()
    return [f"[{c.urgency.value}] {_label(session, c)}: {_first_line(c.summary)}" for c in cases]


def _approvals(session: Session, company_id: UUID) -> list[str]:
    rows = session.execute(
        select(ActionRow, Case)
        .join(Approval, Approval.action_id == ActionRow.id)
        .join(Case, Case.id == ActionRow.case_id)
        .where(Approval.company_id == company_id, Approval.status == ApprovalStatus.pending)
        .order_by(Approval.created_at)
    ).all()
    return [f"{a.type.value.replace('_', ' ')}: {_label(session, c)}" for a, c in rows]


def _stats(session: Session, company_id: UUID, since: datetime) -> dict[str, int]:
    def count(where: ColumnElement[bool]) -> int:
        return int(
            session.scalar(select(func.count()).select_from(Case).where(Case.company_id == company_id, where)) or 0
        )

    decided = session.scalar(
        select(func.count())
        .select_from(Approval)
        .where(Approval.company_id == company_id, Approval.decided_at >= since)
    )
    return {
        "cases opened": count(Case.opened_at >= since),
        "cases resolved": count(Case.resolved_at >= since),
        "decisions taken": int(decided or 0),
    }


def collect(engine: Engine, company_id: UUID, kind: Kind, now: datetime) -> BriefingFacts:
    with Session(engine) as session:
        company = session.get(Company, company_id)
        if company is None:
            raise NotFoundError(f"company {company_id} not found")
        tz = ZoneInfo(company.timezone)
        tasks = [t for t in work_repo.open_tasks(session, company_id, now=now) if t.due_at and t.due_at < now]
        waits = work_repo.overdue_waits(session, company_id, now)
        exceptions = session.scalars(
            select(ActionRow.rationale).where(
                ActionRow.company_id == company_id,
                ActionRow.status == ActionStatus.exception,
                ActionRow.created_at >= now - timedelta(days=7 if kind == "weekly" else 1),
            )
        ).all()
        return BriefingFacts(
            kind=kind,
            day_label=f"{now.astimezone(tz):%a %d %b}",
            urgent=_urgent(session, company_id),
            approvals=_approvals(session, company_id),
            overdue_tasks=[f"{t.title} (due {t.due_at.astimezone(tz):%a %H:%M})" for t in tasks if t.due_at],
            overdue_waits=[f"{w.about} ({w.chase_count} reminders)" for w in waits],
            exceptions=[str(e) for e in exceptions],
            stats=_stats(session, company_id, now - timedelta(days=7)) if kind == "weekly" else {},
        )


def compose(engine: Engine, settings: Settings, company_id: UUID, kind: Kind, now: datetime) -> str:
    facts = collect(engine, company_id, kind, now)
    try:
        written = run_agent(
            engine, settings, BRIEFING, briefing_prompt(facts), CallContext(company_id, f"briefing_{kind}")
        ).output
    except AgentFailedError:
        log.warning("briefing.fallback", company_id=str(company_id), kind=kind)
        written = fallback_briefing(facts)
    return render_text(facts, written)


def _next_local(now: datetime, tz: str, at: time, weekday: int | None) -> datetime:
    local = now.astimezone(ZoneInfo(tz))
    day: date = local.date()
    for _ in range(8):
        candidate = datetime.combine(day, at, tzinfo=ZoneInfo(tz))
        if candidate > local and (weekday is None or day.weekday() == weekday):
            return candidate
        day += timedelta(days=1)
    raise AssertionError("unreachable: a matching day exists within a week")


def _ensure(session: Session, company: Company, kind: str, due: datetime) -> bool:
    key = f"{kind}:{due.date().isoformat()}"
    if session.scalar(select(Timer.id).where(Timer.company_id == company.id, Timer.dedupe_key == key)):
        return False
    timers.schedule(session, company.id, kind, due, {"kind": kind.split(".")[1]}, dedupe_key=key)
    return True


def ensure_timers(session: Session, now: datetime) -> int:
    """Every company has its next daily and weekly briefing scheduled (hourly cron; idempotent)."""
    created = 0
    for company in session.scalars(select(Company)).all():
        daily = _next_local(now, company.timezone, company.briefing_time, None)
        weekly = _next_local(now, company.timezone, company.weekly_time, company.weekly_weekday)
        created += _ensure(session, company, DAILY, daily) + _ensure(session, company, WEEKLY, weekly)
    return created
