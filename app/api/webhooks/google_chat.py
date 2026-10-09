"""Google Chat webhook: token verification, mapping to owner/channel account, enqueuing process_event."""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.body import read_capped
from app.api.deps import WorkflowClient, get_engine, get_workflow_client
from app.channels.google_chat.inbound import ChatParseError, GoogleChatEvent, parse_chat_event
from app.channels.google_chat.verifier import ChatAuthError, ChatVerifier
from app.contracts import Channel
from app.core.logging import get_logger
from app.db.models import ChannelAccount, OwnerAccount
from app.ingestion.repository import record_event

router = APIRouter(prefix="/webhooks/googlechat", tags=["webhooks"])
log = get_logger(__name__)
MAX_CHAT_BYTES = 1_048_576


def get_chat_verifier(request: Request) -> ChatVerifier:
    verifier: ChatVerifier = request.app.state.google_chat_verifier
    return verifier


@router.post("", status_code=200)
async def receive(
    request: Request,
    verifier: Annotated[ChatVerifier, Depends(get_chat_verifier)],
    engine: Annotated[Engine, Depends(get_engine)],
    client: Annotated[WorkflowClient, Depends(get_workflow_client)],
) -> Response:
    body = await read_capped(request, MAX_CHAT_BYTES)
    try:
        verifier.verify_token(request.headers.get("authorization"))
    except ChatAuthError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc

    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ChatParseError("chat payload must be a JSON object")
        event = parse_chat_event(payload)
    except (ChatParseError, ValueError) as exc:
        log.error("google_chat.webhook.malformed_payload", error=str(exc))
        return Response(status_code=200, media_type="application/json", content="{}")

    await run_in_threadpool(_handle_chat_event, engine, client, event, payload)
    return Response(status_code=200, media_type="application/json", content="{}")


def _handle_chat_event(
    engine: Engine,
    client: WorkflowClient,
    event: GoogleChatEvent,
    payload: dict[str, Any],
) -> None:
    with Session(engine) as session, session.begin():
        account = session.scalar(
            select(ChannelAccount).where(
                ChannelAccount.channel == Channel.google_chat,
                ChannelAccount.address == event.space_name,
            )
        )
        if account is None:
            owner = session.scalar(select(OwnerAccount).where(OwnerAccount.chat_user == event.user_name))
            if owner is not None:
                account = session.scalar(
                    select(ChannelAccount).where(
                        ChannelAccount.channel == Channel.google_chat,
                        ChannelAccount.company_id == owner.company_id,
                    )
                )
                if account is None:
                    account = ChannelAccount(
                        company_id=owner.company_id,
                        channel=Channel.google_chat,
                        address=event.space_name,
                        is_owner_channel=True,
                    )
                    session.add(account)
                    session.flush()

        if account is None:
            log.warning("google_chat.webhook.unknown_sender", user=event.user_name, space=event.space_name)
            return

        record_event(session, client, account, event.message_name, payload)
