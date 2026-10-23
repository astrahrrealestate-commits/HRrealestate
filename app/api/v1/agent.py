"""Super Agent chat: post a message (a workflow-backed turn), read a conversation, pre-warm the open page.

The turn row commits before the enqueue (invariant 1). Foreign or other owners' conversations answer the same 404 as
missing ones. Turn progress reaches the dashboard through `/events` (`event: turn`). `PUT /agent/page` resolves the
page facts for the session's owner ahead of the next message (`page_state`); it never creates a turn or calls a model.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import WorkflowClient, get_engine, get_workflow_client
from app.api.v1 import enqueue
from app.api.v1.auth import Principal, require_csrf, require_principal
from app.api.v1.ratelimit import agent_limit, page_limit
from app.api.v1.schemas import AgentMessageIn, AgentMessageOut, ConversationOut, TurnOut
from app.contracts import PageContext
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.pipeline import concierge_turns, page_state, read_turns

router = APIRouter(tags=["agent"])
log = get_logger(__name__)
NOT_FOUND = "not found"
START_FAILED = "could not start the assistant; try again"
WARM_FAILED = "page facts unavailable; try again"
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


@router.put("/agent/page", status_code=204, dependencies=[Depends(require_csrf), Depends(page_limit)])
def put_page(body: PageContext, who: Owner, engine: Engine_) -> None:
    """Pre-warm: resolve the open page's facts for this owner now, so the next message on the same page skips it.
    A resolver bug stores nothing (still 204: the turn resolves as usual); a transient error is 503."""
    try:
        warmed = page_state.warm(engine, who.company_id, who.owner_id, body)
    except Exception as exc:  # `warm` lets only transient errors out
        log.warning("dashboard.page_warm_unavailable", company_id=str(who.company_id), error=type(exc).__name__)
        raise HTTPException(status_code=503, detail=WARM_FAILED) from None
    log.info("dashboard.page_warmed", company_id=str(who.company_id), warmed=warmed)
