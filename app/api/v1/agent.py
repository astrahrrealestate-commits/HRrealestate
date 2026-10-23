"""Super Agent chat: post a message (a workflow-backed turn) and read a conversation.

The turn row commits before the enqueue (invariant 1). Foreign or other owners' conversations answer the same 404 as
missing ones. Turn progress reaches the dashboard through `/events` (`event: turn`).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import WorkflowClient, get_engine, get_workflow_client
from app.api.v1 import enqueue
from app.api.v1.auth import Principal, require_csrf, require_principal
from app.api.v1.ratelimit import agent_limit
from app.api.v1.schemas import AgentMessageIn, AgentMessageOut, ConversationOut, TurnOut
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.pipeline import concierge_turns, read_turns

router = APIRouter(tags=["agent"])
log = get_logger(__name__)
NOT_FOUND = "not found"
START_FAILED = "could not start the assistant; try again"
Owner = Annotated[Principal, Depends(require_principal)]
Engine_ = Annotated[Engine, Depends(get_engine)]
Client = Annotated[WorkflowClient, Depends(get_workflow_client)]


def _start_turn(engine: Engine, client: WorkflowClient, company_id: UUID, turn_id: UUID) -> None:
    """Enqueue after commit. If that fails the turn is marked failed (never left pending with no workflow) and the
    client gets 503 to retry with a new message."""
    try:
        enqueue.enqueue_turn(client, turn_id)
    except Exception as exc:
        log.error(
            "dashboard.agent_enqueue_failed", company_id=str(company_id), turn_id=str(turn_id), error=type(exc).__name__
        )
        concierge_turns.fail_turn(engine, turn_id, type(exc).__name__)
        raise HTTPException(status_code=503, detail=START_FAILED) from None


@router.post("/agent/messages", status_code=202, dependencies=[Depends(require_csrf), Depends(agent_limit)])
def post_message(body: AgentMessageIn, who: Owner, engine: Engine_, client: Client) -> AgentMessageOut:
    try:
        with Session(engine) as session, session.begin():
            conversation_id, turn_id = concierge_turns.create_turn(
                session, who.company_id, who.owner_id, body.conversation_id, body.text, page=body.page
            )
    except NotFoundError:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None
    _start_turn(engine, client, who.company_id, turn_id)
    log.info("dashboard.agent_turn_created", company_id=str(who.company_id), turn_id=str(turn_id))
    return AgentMessageOut(conversation_id=conversation_id, turn_id=turn_id)


@router.get("/agent/conversations/{conversation_id}")
def get_conversation(conversation_id: UUID, who: Owner, engine: Engine_) -> ConversationOut:
    with Session(engine) as session:
        turns = read_turns.conversation_turns(session, who.company_id, who.owner_id, conversation_id)
        if turns is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return ConversationOut(id=conversation_id, turns=[TurnOut.model_validate(t) for t in turns])
