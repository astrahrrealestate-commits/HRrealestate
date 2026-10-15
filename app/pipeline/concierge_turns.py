"""Super Agent turns (spec §4): create a turn, then run it inside one DBOS step.

`run_turn` order: exact owner commands take the fast path (no model, works when the budget is spent); a question is
screened, planned by the concierge agent (one model call), executed by `run_plan`, and the answer is assembled from
the step summaries. The plan is stored before it executes and the results right after (status stays `running`), so
a retried step reuses the stored plan (no second model call) and never executes stored results again. The work clock
is the turn's `created_at`, so a retried step replays the same decisions; `updated_at` uses the database clock at
each write so every status change moves the SSE turn cursor.
Logs carry ids and status only, never the owner's text.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from app.contracts import ConciergePlan
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import TurnStatus
from app.db.models import AgentConversation, AgentTurn, Case
from app.llm.agents.concierge import CONCIERGE
from app.llm.agents.owner_qa import FALLBACK_ANSWER, CaseBrief
from app.llm.budget import CONCIERGE_PURPOSE
from app.llm.calls import CallContext, run_agent
from app.pipeline import case_repo, owner_commands, read_turns, work_repo
from app.pipeline.concierge import run_plan
from app.pipeline.concierge_outcome import (
    APOLOGY,
    MAX_BRIEF_CASES,
    MAX_BRIEF_TASKS,
    MAX_HISTORY_TURNS,
    PROMPT_REF,
    Fallback,
    Outcome,
    assemble_answer,
    build_prompt,
    failed_outcome,
    fallback_for,
    result_json,
    stored_answer,
)

log = get_logger(__name__)
FINAL = (TurnStatus.done, TurnStatus.failed)  # terminal: never re-run, never overwritten


@dataclass(frozen=True)
class TurnStart:
    turn_id: UUID
    company_id: UUID
    conversation_id: UUID
    text: str
    at: datetime  # the work clock
    results: list[dict[str, Any]] | None
    plan: dict[str, Any] | None


def create_turn(
    session: Session, company_id: UUID, owner_id: UUID, conversation_id: UUID | None, text: str
) -> tuple[UUID, UUID]:
    """A `pending` turn in the owner's conversation (created when None). A foreign or other owner's conversation
    raises NotFoundError. The caller commits, then enqueues `concierge:{turn_id}`."""
    if conversation_id is None:
        conversation = AgentConversation(company_id=company_id, owner_id=owner_id)
        session.add(conversation)
        session.flush()
        conversation_id = conversation.id
    elif not read_turns.owns_conversation(session, company_id, owner_id, conversation_id):
        raise NotFoundError("conversation not found")
    turn = AgentTurn(company_id=company_id, conversation_id=conversation_id, text=text, status=TurnStatus.pending)
    session.add(turn)
    session.flush()
    return conversation_id, turn.id


def _start(engine: Engine, turn_id: UUID) -> TurnStart | None:
    """Lock the turn and mark it running; None when it is missing, done or failed. Loaded by id alone (the
    workflow's only input); the company comes from the row and scopes everything after."""
    with Session(engine) as session, session.begin():
        turn = session.scalar(select(AgentTurn).where(AgentTurn.id == turn_id).with_for_update())
        if turn is None or turn.status in FINAL:
            return None
        session.execute(
            update(AgentTurn)
            .where(AgentTurn.company_id == turn.company_id, AgentTurn.id == turn_id)
            .values(status=TurnStatus.running, updated_at=func.clock_timestamp())
        )
        return TurnStart(
            turn.id, turn.company_id, turn.conversation_id, turn.text, turn.created_at, turn.results, turn.plan
        )


def _update(engine: Engine, company_id: UUID, turn_id: UUID, values: dict[str, Any]) -> None:
    """One short transaction on a turn that is not done or failed; `updated_at` from the DB clock so the SSE cursor
    moves."""
    with Session(engine) as session, session.begin():
        session.execute(
            update(AgentTurn)
            .where(AgentTurn.company_id == company_id, AgentTurn.id == turn_id, AgentTurn.status.not_in(FINAL))
            .values(**values, updated_at=func.clock_timestamp())
        )


def _finish(engine: Engine, company_id: UUID, turn_id: UUID, outcome: Outcome) -> None:
    """Answer and status in one transaction; plan/results only when the outcome carries them (a failure after the
    plan was stored keeps it). A done or failed turn is left as it is."""
    values: dict[str, Any] = {
        "answer": outcome.answer,
        "prompt_ref": outcome.prompt_ref,
        "status": outcome.status,
        "error": outcome.error,
    }
    if outcome.plan is not None:
        values["plan"] = outcome.plan
    if outcome.results is not None:
        values["results"] = outcome.results
    _update(engine, company_id, turn_id, values)
    log.info("concierge.turn_finished", company_id=str(company_id), turn_id=str(turn_id), status=outcome.status.value)


def _brief(engine: Engine, start: TurnStart) -> tuple[list[CaseBrief], list[str], list[str]]:
    cid = start.company_id
    with Session(engine) as session:
        cases = session.scalars(
            select(Case)
            .where(Case.company_id == cid, Case.state.in_(case_repo.OPEN_STATES))
            .order_by(Case.opened_at.desc(), Case.id.desc())
            .limit(MAX_BRIEF_CASES)
        ).all()
        briefs = [
            CaseBrief(c.id, owner_commands.case_label(session, c), c.state.value, c.urgency.value, c.summary)
            for c in cases
        ]
        tasks = [t.title for t in work_repo.open_tasks(session, cid, now=start.at)[:MAX_BRIEF_TASKS]]
        history = read_turns.earlier_texts(
            session, cid, start.conversation_id, (start.at, start.turn_id), MAX_HISTORY_TURNS
        )
    return briefs, tasks, history


def _owner_qa(engine: Engine, settings: Settings, start: TurnStart) -> str:
    """The planner failed: answer through the existing owner_qa path, then the fixed fallback."""
    cmd = owner_commands.Command(owner_commands.CommandKind.question, text=start.text)
    try:
        return owner_commands.run_command(engine, settings, start.company_id, cmd, now=start.at)
    except Exception as exc:
        if fallback_for(exc) is Fallback.retry:
            raise
        log.warning("concierge.owner_qa_failed", company_id=str(start.company_id), error=type(exc).__name__)
        return FALLBACK_ANSWER


def _plan(engine: Engine, settings: Settings, start: TurnStart) -> ConciergePlan | Outcome:
    briefs, tasks, history = _brief(engine, start)
    try:
        result = run_agent(
            engine,
            settings,
            CONCIERGE,
            build_prompt(start.text, history, briefs, tasks),
            CallContext(start.company_id, CONCIERGE_PURPOSE),
        )
    except Exception as exc:
        kind = fallback_for(exc)
        log.info("concierge.planner_fallback", company_id=str(start.company_id), fallback=kind.value)
        if kind is Fallback.limit:
            return Outcome(owner_commands.LIMIT_ANSWER)
        if kind is Fallback.owner_qa:
            return Outcome(_owner_qa(engine, settings, start))
        raise
    return result.output


def _planned(engine: Engine, settings: Settings, start: TurnStart) -> ConciergePlan | Outcome:
    """The stored plan of an earlier attempt, else a fresh one (stored before anything executes, so a retry runs
    the same plan and never asks the model twice)."""
    if start.plan is not None:
        return ConciergePlan.model_validate(start.plan)
    plan = _plan(engine, settings, start)
    if isinstance(plan, ConciergePlan):
        _update(engine, start.company_id, start.turn_id, {"plan": plan.model_dump(mode="json")})
    return plan


def _outcome(engine: Engine, settings: Settings, start: TurnStart) -> Outcome:
    if start.results is not None:  # executed by an earlier attempt: finish, never execute twice
        return Outcome(stored_answer(start.results), start.plan, start.results, PROMPT_REF)
    if start.plan is None:
        cmd = owner_commands.parse_command(start.text)
        if cmd.kind is not owner_commands.CommandKind.question:
            return Outcome(owner_commands.run_command(engine, settings, start.company_id, cmd, now=start.at))
        refused = owner_commands.screen_question(start.text)
        if refused is not None:
            return Outcome(refused)
    plan = _planned(engine, settings, start)
    if isinstance(plan, Outcome):
        return plan
    results = run_plan(engine, settings, start.company_id, plan, question=start.text, now=start.at)
    stored = [result_json(r) for r in results]
    _update(engine, start.company_id, start.turn_id, {"results": stored})
    return Outcome(assemble_answer(results), plan.model_dump(mode="json"), stored, PROMPT_REF)


def run_turn(engine: Engine, settings: Settings, turn_id: UUID) -> None:
    """All I/O of a turn (called from the DBOS step). Transient errors propagate so the step retries; any other
    error fails the turn with a fixed apology. Safe to re-run: a done or failed turn is skipped."""
    start = _start(engine, turn_id)
    if start is None:
        return
    try:
        outcome = _outcome(engine, settings, start)
    except Exception as exc:
        if fallback_for(exc) is Fallback.retry:
            raise
        log.warning(
            "concierge.turn_error", company_id=str(start.company_id), turn_id=str(turn_id), error=type(exc).__name__
        )
        outcome = failed_outcome(exc)
    _finish(engine, start.company_id, turn_id, outcome)


def fail_turn(engine: Engine, turn_id: UUID, error: str) -> None:
    """The step gave up after its retries: the turn must not stay `running`. A done turn is untouched."""
    with Session(engine) as session:
        company_id = session.scalar(select(AgentTurn.company_id).where(AgentTurn.id == turn_id))
    if company_id is not None:
        _finish(engine, company_id, turn_id, Outcome(APOLOGY, status=TurnStatus.failed, error=error))


def turn_state(engine: Engine, turn_id: UUID) -> dict[str, str | bool]:
    """Final status, company and whether the turn was the `resume` command (the workflow then re-runs approved
    actions, exactly as the WhatsApp path does)."""
    with Session(engine) as session:
        turn = session.scalar(select(AgentTurn).where(AgentTurn.id == turn_id))
    if turn is None:
        return {"status": "missing", "company_id": "", "resume": False}
    resumed = turn.status is TurnStatus.done and turn.plan is None and turn.results is None
    resumed = resumed and owner_commands.parse_command(turn.text).kind is owner_commands.CommandKind.resume
    return {"status": turn.status.value, "company_id": str(turn.company_id), "resume": resumed}
