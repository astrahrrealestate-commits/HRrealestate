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
from app.api.v1.schemas import AgentMessageIn, AgentMessageOut, ConversationOut, TurnOut
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.pipeline import concierge_turns, read_turns

router = APIRouter(tags=["agent"])
log = get_logger(__name__)
NOT_FOUND = "not found"
Owner = Annotated[Principal, Depends(require_principal)]
Engine_ = Annotated[Engine, Depends(get_engine)]
Client = Annotated[WorkflowClient, Depends(get_workflow_client)]


@router.post("/agent/messages", status_code=202, dependencies=[Depends(require_csrf)])
def post_message(body: AgentMessageIn, who: Owner, engine: Engine_, client: Client) -> AgentMessageOut:
    try:
        with Session(engine) as session, session.begin():
            conversation_id, turn_id = concierge_turns.create_turn(
                session, who.company_id, who.owner_id, body.conversation_id, body.text
            )
    except NotFoundError:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None
    enqueue.enqueue_turn(client, turn_id)  # after commit
    log.info("dashboard.agent_turn_created", company_id=str(who.company_id), turn_id=str(turn_id))
    return AgentMessageOut(conversation_id=conversation_id, turn_id=turn_id)


@router.get("/agent/conversations/{conversation_id}")
def get_conversation(conversation_id: UUID, who: Owner, engine: Engine_) -> ConversationOut:
    with Session(engine) as session:
        turns = read_turns.conversation_turns(session, who.company_id, who.owner_id, conversation_id)
        if turns is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return ConversationOut(id=conversation_id, turns=[TurnOut.model_validate(t) for t in turns])
