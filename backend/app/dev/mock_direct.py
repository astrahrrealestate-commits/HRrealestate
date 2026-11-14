"""Agents the scripted traffic cannot reach through the pipeline, called directly.

`link_check` runs only when one person has several open cases and the message is not in their recent thread (the
pipeline links to a person's only open case first), and the briefings are timer-driven. Both calls are read-only:
they return an answer and write nothing but the `model_calls` row, so the dashboard shows them like any other call.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import Category
from app.core.errors import AgentFailedError
from app.core.settings import Settings
from app.db.models import Case
from app.llm.agents.link_check import LINK_CHECK, CandidateCase, accept_link, link_check_prompt
from app.llm.calls import CallContext, run_agent
from app.pipeline import briefing
from app.pipeline.case_repo import OPEN_STATES

VAGUE_FOLLOWUP = "Het is nog steeds koud hier, wanneer komt er nu iemand langs?"


def link_check(engine: Engine, settings: Settings, company_id: UUID) -> str:
    """The company's two newest open cases are the candidates for one vague follow-up."""
    with Session(engine) as session:
        cases = session.scalars(
            select(Case)
            .where(Case.company_id == company_id, Case.state.in_(OPEN_STATES))
            .order_by(Case.opened_at.desc())
            .limit(2)
        ).all()
        cands = [CandidateCase(c.id, c.category, c.summary, c.opened_at) for c in cases]
    if len(cands) < 2:
        return f"skipped ({len(cands)} open cases)"
    prompt = link_check_prompt(VAGUE_FOLLOWUP, Category.maintenance, cands, None)
    try:
        result = run_agent(engine, settings, LINK_CHECK, prompt, CallContext(company_id, "link_check"))
    except AgentFailedError:
        return "failed"
    return "matched one of 2 cases" if accept_link(result.output, cands) else "no case matched"


def briefings(engine: Engine, settings: Settings, company_id: UUID) -> str:
    now = datetime.now(UTC)
    written = [briefing.compose(engine, settings, company_id, kind, now) for kind in ("daily", "weekly")]
    return f"daily {len(written[0])} chars, weekly {len(written[1])} chars"
