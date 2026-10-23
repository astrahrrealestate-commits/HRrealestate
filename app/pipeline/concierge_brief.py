"""The planner's brief for a Super Agent turn: the newest open cases, the open tasks and the conversation's earlier
exchanges, every query company-scoped (invariant 4). The case ids alone are what a retried turn's stored plan is
checked against (with the page's case ids, the only ones a plan may name)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, Select, select
from sqlalchemy.orm import Session

from app.db.models import Case
from app.llm.agents.owner_qa import CaseBrief
from app.pipeline import case_repo, owner_commands, read_turns, work_repo
from app.pipeline.concierge_outcome import (
    MAX_BRIEF_CASES,
    MAX_BRIEF_TASKS,
    MAX_HISTORY_TURNS,
    history_lines,
    task_brief,
)

Brief = tuple[list[CaseBrief], list[str], list[str]]  # (open cases, open tasks, history lines)


def brief_cases(company_id: UUID) -> Select[Case]:
    return (
        select(Case)
        .where(Case.company_id == company_id, Case.state.in_(case_repo.OPEN_STATES))
        .order_by(Case.opened_at.desc(), Case.id.desc())
        .limit(MAX_BRIEF_CASES)
    )


def brief_case_ids(engine: Engine, company_id: UUID) -> list[UUID]:
    """The brief's case ids alone (same query): what a retried turn's stored plan is checked against."""
    with Session(engine) as session:
        return list(session.scalars(brief_cases(company_id).with_only_columns(Case.id)))


def load_brief(engine: Engine, company_id: UUID, conversation_id: UUID, at: datetime, turn_id: UUID) -> Brief:
    """The brief as of the turn's work clock `at`; history is the conversation's exchanges before this turn."""
    with Session(engine) as session:
        cases = session.scalars(brief_cases(company_id)).all()
        briefs = [
            CaseBrief(c.id, owner_commands.case_label(session, c), c.state.value, c.urgency.value, c.summary)
            for c in cases
        ]
        open_tasks = work_repo.open_tasks(session, company_id, now=at)[:MAX_BRIEF_TASKS]
        tasks = [task_brief(t.id, t.title) for t in open_tasks]
        exchanges = read_turns.earlier_exchanges(session, company_id, conversation_id, (at, turn_id), MAX_HISTORY_TURNS)
    return briefs, tasks, history_lines(exchanges)
