"""Reads around a Super Agent turn: its final state for the workflow, and the owner_qa answer when the planner fails."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import TurnStatus
from app.db.models import AgentTurn
from app.llm.agents.owner_qa import FALLBACK_ANSWER
from app.pipeline import concierge_page, owner_commands
from app.pipeline.concierge_outcome import Fallback, fallback_for, resumes

if TYPE_CHECKING:
    from app.pipeline.concierge_turns import TurnStart

log = get_logger("app.pipeline.concierge_turns")


def owner_qa(engine: Engine, settings: Settings, start: "TurnStart") -> str:
    """The planner failed: answer through the existing owner_qa path, then the fixed fallback."""
    cmd = owner_commands.Command(owner_commands.CommandKind.question, text=start.text)
    page = concierge_page.stored_prompt(start.page)
    try:
        return owner_commands.run_command(engine, settings, start.company_id, cmd, now=start.at, page=page)
    except Exception as exc:
        if fallback_for(exc) is Fallback.retry:
            raise
        log.warning("concierge.owner_qa_failed", company_id=str(start.company_id), error=type(exc).__name__)
        return FALLBACK_ANSWER


def turn_state(engine: Engine, turn_id: UUID) -> dict[str, str | bool]:
    """Final status, company and whether the owner's own exact `resume` command ran (outage fallback only, never a
    planned step); the workflow then re-runs approved actions, exactly as the WhatsApp path does."""
    with Session(engine) as session:
        turn = session.scalar(select(AgentTurn).where(AgentTurn.id == turn_id))
    if turn is None:
        return {"status": "missing", "company_id": "", "resume": False}
    resumed = turn.status is TurnStatus.done and resumes(turn.text, turn.plan, turn.results)
    return {"status": turn.status.value, "company_id": str(turn.company_id), "resume": resumed}
