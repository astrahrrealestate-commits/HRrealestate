"""Gmail Pub/Sub push endpoint: verify the OIDC token, map the mailbox to its account, enqueue a history sync."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.body import read_capped
from app.api.deps import WorkflowClient, get_engine, get_workflow_client
from app.channels.gmail.ports import PushNotice
from app.channels.gmail.push import MAX_PUSH_BYTES, PushVerifier, parse_push_body
from app.contracts import Channel
from app.core.errors import NotFoundError, PushRejectedError
from app.core.logging import get_logger
from app.core.workflow_names import GMAIL_SYNC, GMAIL_SYNC_QUEUE
from app.ingestion.repository import resolve_channel_account

router = APIRouter(prefix="/webhooks/gmail", tags=["webhooks"])
log = get_logger(__name__)


def get_push_verifier(request: Request) -> PushVerifier:
    verifier: PushVerifier = request.app.state.gmail_push_verifier
    return verifier


def gmail_sync_workflow_id(account_id: UUID, history_id: int) -> str:
    return f"gsync:{account_id}:{history_id}"


@router.post("/push", status_code=204)
async def push(
    request: Request,
    verifier: Annotated[PushVerifier, Depends(get_push_verifier)],
    engine: Annotated[Engine, Depends(get_engine)],
    client: Annotated[WorkflowClient, Depends(get_workflow_client)],
) -> Response:
    body = await read_capped(request, MAX_PUSH_BYTES)
    try:
        await run_in_threadpool(verifier.verify_token, request.headers.get("authorization"))
    except PushRejectedError as exc:
        raise HTTPException(status_code=401, detail="push rejected") from exc
    try:
        notice = parse_push_body(body)
    except PushRejectedError:
        # Authenticated but malformed: redelivery can never succeed, so acknowledge and alert instead.
        log.error("gmail.push.malformed_envelope", size=len(body))
        return Response(status_code=204)
    await run_in_threadpool(_enqueue_sync, engine, client, notice)
    return Response(status_code=204)  # 2xx acks the Pub/Sub message; duplicates are harmless (idempotent id)


def _enqueue_sync(engine: Engine, client: WorkflowClient, notice: PushNotice) -> None:
    with Session(engine) as session:
        try:
            account = resolve_channel_account(session, Channel.gmail, notice.email)
        except NotFoundError:
            log.warning("gmail.push.unknown_mailbox", history_id=notice.history_id)
            return  # ack anyway: retrying would not make the mailbox known
        options = {
            "queue_name": GMAIL_SYNC_QUEUE,
            "workflow_name": GMAIL_SYNC,
            "workflow_id": gmail_sync_workflow_id(account.id, notice.history_id),
        }
        client.enqueue(options, str(account.id), notice.history_id)
