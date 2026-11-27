"""Harjot's text commands on WhatsApp (#6 Task Manager, owner controls). Anything else is a question (owner Q&A).

pause | resume | tasks | done <#ref> | snooze <#ref> <30m|4h|2d|1w> | waiting | help
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, select
from sqlalchemy import case as sql_case
from sqlalchemy.orm import Session

from app.context.memory_items import record_owner_memory
from app.contracts import Urgency
from app.core.errors import AgentFailedError, BudgetExceededError, NotFoundError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import WaitStatus
from app.db.models import Case, Company, Person, TaskRow, WaitRow
from app.llm.agents.owner_qa import (
    FALLBACK_ANSWER,
    CaseBrief,
    accept_refs,
    answer_text,
    owner_qa_prompt,
    owner_qa_spec,
    page_case_ids,
)
from app.llm.budget import OWNER_QA_PURPOSE
from app.llm.calls import CallContext, run_agent
from app.llm.page_blocks import NO_PAGE, PagePrompt
from app.pipeline import case_repo, work_repo
from app.pipeline.concierge_sanitize import sanitize

log = get_logger(__name__)


class CommandKind(StrEnum):
    pause = "pause"
    resume = "resume"
    tasks = "tasks"
    done = "done"
    snooze = "snooze"
    waiting = "waiting"
    help = "help"
    question = "question"
    remember = "remember"


@dataclass(frozen=True)
class Command:
    kind: CommandKind
    index: int | None = None
    duration: timedelta | None = None
    text: str | None = None
    ref: str | None = None  # stable task reference shown by `tasks` (#xxxxxx); preferred over the position


HELP_TEXT = (
    "Commands:\n"
    "tasks - your open tasks\n"
    "done <#ref> - mark a task done (refs are shown by `tasks`)\n"
    "snooze <#ref> <30m|4h|2d|1w> - hide a task for a while\n"
    "waiting - who we are waiting on\n"
    "remember <rule> - save a standing rule or preference\n"
    "pause / resume - stop or restart all proposals\n"
    "Anything else is a question about your cases."
)
MAX_QUESTION_CHARS = 500
NOT_A_QUESTION = "Send a question about your cases, or `help` for the commands."
TOO_LONG = f"That is too long. Please keep questions under {MAX_QUESTION_CHARS} characters."
LIMIT_ANSWER = "The AI question limit is reached for now. `tasks`, `waiting` and `help` still work."
_UNITS = {"m": timedelta(minutes=1), "h": timedelta(hours=1), "d": timedelta(days=1), "w": timedelta(weeks=1)}
MAX_SNOOZE = timedelta(weeks=8)
_SIMPLE = {"pause", "resume", "tasks", "waiting", "help"}


def screen_question(text: str) -> str | None:
    """A reply when the text must not reach the model (empty, symbols only, too long); None when it may."""
    if not any(ch.isalnum() for ch in text):
        return NOT_A_QUESTION
    if len(text) > MAX_QUESTION_CHARS:
        return TOO_LONG
    return None


def parse_duration(raw: str) -> timedelta:
    match = re.fullmatch(r"(\d{1,3})([mhdw])", raw.strip().lower())
    if match is None:
        raise ValueError(f"bad duration {raw[:12]!r}: use 30m, 4h, 2d or 1w")
    value = int(match.group(1)) * _UNITS[match.group(2)]
    if not timedelta(0) < value <= MAX_SNOOZE:
        raise ValueError(f"duration {raw[:12]!r} must be between 1 minute and 8 weeks")
    return value


def parse_command(text: str) -> Command:
    clean = text.strip()
    lower = clean.lower()
    if lower.startswith("remember "):
        return Command(CommandKind.remember, text=clean[9:].strip())
    if lower.startswith("onthoud "):
        return Command(CommandKind.remember, text=clean[8:].strip())
    if lower.startswith("from now on "):
        return Command(CommandKind.remember, text=clean[12:].strip())
    words = clean.lower().split()
    if clean == "?" or (len(words) == 1 and words[0] in _SIMPLE):
        return Command(CommandKind.help if clean == "?" else CommandKind(words[0]))
    target = _target(words[1].lstrip("#")) if len(words) in (2, 3) else None
    if target is not None and len(words) == 2 and words[0] == "done":
        return Command(CommandKind.done, index=target[0], ref=target[1])
    if target is not None and len(words) == 3 and words[0] == "snooze":
        try:
            return Command(CommandKind.snooze, index=target[0], ref=target[1], duration=parse_duration(words[2]))
        except ValueError:
            pass
    return Command(CommandKind.question, text=clean)


def fallback_command(text: str) -> Command | None:
    """The exact command in `text`, for when the planner is down (outage or spent budget); None for anything else.
    Normally the planner decides the intent, so a command word is no longer a shortcut."""
    cmd = parse_command(text)
    return None if cmd.kind is CommandKind.question else cmd


def _target(token: str) -> tuple[int | None, str | None] | None:
    """A position (1–999) or a 6-character task reference."""
    if token.isdigit() and len(token) <= 3:
        return int(token), None
    if re.fullmatch(r"[0-9a-f]{6}", token):
        return None, token
    return None


def case_label(session: Session, case: Case) -> str:
    name = (
        session.scalar(
            select(Person.display_name).where(Person.company_id == case.company_id, Person.id == case.primary_person_id)
        )
        or "Unknown sender"
    )
    return f"{name} · {case.category.value}"


# ---- execution -----------------------------------------------------------------------------------------------------


def _due(at: datetime | None, tz: str) -> str:
    return f" (due {at.astimezone(ZoneInfo(tz)):%a %d %b %H:%M})" if at else ""


def _tasks(session: Session, company: Company, now: datetime) -> str:
    tasks = work_repo.open_tasks(session, company.id, now=now)
    if not tasks:
        return "No open tasks."
    lines = [
        f"{i}. [{t.priority.value}] {t.title}{_due(t.due_at, company.timezone)} #{work_repo.short_ref(t.id)}"
        for i, t in enumerate(tasks, 1)
    ]
    return "Open tasks:\n" + "\n".join(lines)


def _task_at(session: Session, company_id: UUID, ref: str) -> TaskRow | None:
    try:
        task_id = work_repo.resolve_task(session, company_id, ref)
    except NotFoundError:
        return None
    return session.get(TaskRow, task_id)


def _waiting(session: Session, company: Company) -> str:
    waits = session.scalars(
        select(WaitRow)
        .where(WaitRow.company_id == company.id, WaitRow.status == WaitStatus.waiting)
        .order_by(WaitRow.expected_by)
    ).all()
    if not waits:
        return "Not waiting on anyone."
    lines = [
        f"{i}. {w.about}{_due(w.expected_by, company.timezone)}, {w.chase_count} reminders sent"
        for i, w in enumerate(waits, 1)
    ]
    return "Waiting on:\n" + "\n".join(lines)


def _question(
    engine: Engine, settings: Settings, company_id: UUID, question: str, now: datetime, page: PagePrompt
) -> str:
    """owner_qa over the open cases and tasks; on a dashboard page also its facts and snapshot (prompt v3)."""
    with Session(engine) as session:
        urgency_order = sql_case(
            (Case.urgency == Urgency.emergency, 0),
            (Case.urgency == Urgency.high, 1),
            (Case.urgency == Urgency.normal, 2),
            else_=3,
        )
        cases = session.scalars(
            select(Case)
            .where(Case.company_id == company_id, Case.state.in_(case_repo.OPEN_STATES))
            .order_by(urgency_order.asc(), Case.opened_at.desc(), Case.id.desc())
            .limit(20)
        ).all()
        briefs = [CaseBrief(c.id, case_label(session, c), c.state.value, c.urgency.value, c.summary) for c in cases]
        tasks = [t.title for t in work_repo.open_tasks(session, company_id, now=now)]
    prompt = owner_qa_prompt(
        question, briefs, tasks, page_facts_text=page.facts, snapshot=page.snapshot, filters=page.filters
    )
    try:
        result = run_agent(engine, settings, owner_qa_spec(page), prompt, CallContext(company_id, OWNER_QA_PURPOSE))
    except BudgetExceededError:
        return LIMIT_ANSWER
    except AgentFailedError:
        return FALLBACK_ANSWER
    answer = accept_refs(result.output, briefs, page_case_ids(page.facts))
    if not answer.in_scope:
        log.info("owner_qa.refused")
    return answer_text(answer)


def _apply(session: Session, company: Company, cmd: Command, now: datetime) -> str:
    if cmd.kind is CommandKind.help:
        return HELP_TEXT
    if cmd.kind is CommandKind.tasks:
        return _tasks(session, company, now)
    if cmd.kind is CommandKind.waiting:
        return _waiting(session, company)
    if cmd.kind is CommandKind.remember:
        sanitized = sanitize(cmd.text or "")
        _, msg = record_owner_memory(session, company.id, sanitized)
        return msg
    if cmd.kind in (CommandKind.pause, CommandKind.resume):
        company.paused = cmd.kind is CommandKind.pause
        return "Paused: no new proposals until `resume`." if company.paused else "Resumed."
    if cmd.ref is None:  # positions shift as tasks arrive; a retried command must not hit a different task
        return "Use the task's #ref from `tasks`, e.g. `done #a1b2c3`."
    task = _task_at(session, company.id, cmd.ref)
    if task is None:
        return f"There is no open task #{cmd.ref}. Send `tasks` to see the list."
    if cmd.kind is CommandKind.done:
        work_repo.complete_task(session, company.id, task.id, at=now)
        return f"Done: {task.title}"
    until = now + (cmd.duration or timedelta(0))
    work_repo.snooze_task(session, company.id, task.id, until=until)
    return f"Snoozed: {task.title} until {until.astimezone(ZoneInfo(company.timezone)):%a %d %b %H:%M}"


def run_command(
    engine: Engine, settings: Settings, company_id: UUID, cmd: Command, *, now: datetime, page: PagePrompt = NO_PAGE
) -> str:
    """Execute one owner command and return the reply text (English). `page` (dashboard turns only: the stored page
    facts and snapshot) reaches the question prompt; screening applies to the owner's own text only."""
    if cmd.kind is CommandKind.question:
        rejected = screen_question(cmd.text or "")
        return rejected or _question(engine, settings, company_id, cmd.text or "", now, page)
    with Session(engine) as session, session.begin():
        company = session.get(Company, company_id)
        if company is None:
            return "Unknown company."
        return _apply(session, company, cmd, now)


def run_fallback(engine: Engine, settings: Settings, company_id: UUID, text: str, *, now: datetime) -> str | None:
    """The planner is down: run `text` when it is an exact command (no model needed), else None."""
    cmd = fallback_command(text)
    return None if cmd is None else run_command(engine, settings, company_id, cmd, now=now)
