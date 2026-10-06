"""WhatsApp Cloud API / 360dialog webhook: handshake, signature check, one transaction per delivery."""

import hashlib
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import Engine
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.body import read_capped
from app.api.deps import WorkflowClient, get_engine, get_settings_dep, get_workflow_client
from app.channels.whatsapp.inbound import (
    WaEvent,
    WaStatus,
    count_items,
    event_to_payload,
    parse_webhook,
    phone_number_ids,
)
from app.channels.whatsapp.webhook_auth import (
    DEV_APP_SECRET,
    DEV_VERIFY_TOKEN,
    MAX_WEBHOOK_BYTES,
    verify_handshake,
    verify_signature,
)
from app.contracts import Channel
from app.core.errors import NotFoundError, WebhookRejectedError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import DeliveryStatus, RawEventStatus
from app.db.models import ChannelAccount
from app.ingestion.repository import record_event, record_status, resolve_channel_account

router = APIRouter(prefix="/webhooks/whatsapp", tags=["webhooks"])
log = get_logger(__name__)
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def _secret(value: object, fallback: str, settings: Settings) -> str:
    raw = value.get_secret_value() if value is not None and hasattr(value, "get_secret_value") else ""
    return raw or (fallback if settings.whatsapp_provider == "fake" else "")


@router.get("", response_class=PlainTextResponse)
def handshake(request: Request, settings: SettingsDep) -> str:
    params = request.query_params
    expected = _secret(settings.whatsapp_verify_token, DEV_VERIFY_TOKEN, settings)
    try:
        return verify_handshake(
            params.get("hub.mode"), params.get("hub.verify_token"), params.get("hub.challenge"), expected_token=expected
        )
    except WebhookRejectedError as exc:
        raise HTTPException(status_code=403, detail="verification failed") from exc


@router.post("")
async def receive(
    request: Request,
    settings: SettingsDep,
    engine: Annotated[Engine, Depends(get_engine)],
    client: Annotated[WorkflowClient, Depends(get_workflow_client)],
) -> Response:
    body = await read_capped(request, MAX_WEBHOOK_BYTES)
    secret = _secret(settings.whatsapp_app_secret, DEV_APP_SECRET, settings)
    try:
        verify_signature(body, request.headers.get("x-hub-signature-256"), secret)
    except WebhookRejectedError as exc:
        raise HTTPException(status_code=401, detail="invalid signature") from exc
    await run_in_threadpool(_handle, engine, client, body)
    return Response(status_code=200)


def _handle(engine: Engine, client: WorkflowClient, body: bytes) -> None:
    """Parse and persist off the event loop. DB outages raise (→ 5xx, provider retries); bad items never do."""
    events = sorted(parse_webhook(body), key=lambda e: (e.phone_number_id, e.wamid))  # stable lock order
    dropped = count_items(body) - len(events)
    with Session(engine) as session, session.begin():
        accounts = _accounts(session, {e.phone_number_id for e in events} | set(phone_number_ids(body)))
        for event in events:
            account = accounts.get(event.phone_number_id)
            if account is not None:
                _record_one(session, client, account, event)
        if dropped > 0:
            _keep_unparsed(session, accounts, body, dropped)


def _accounts(session: Session, pnids: set[str]) -> dict[str, ChannelAccount]:
    found: dict[str, ChannelAccount] = {}
    for pnid in sorted(pnids):
        try:
            found[pnid] = resolve_channel_account(session, Channel.whatsapp, pnid)
        except NotFoundError:
            log.warning("whatsapp.webhook.unknown_number", phone_number_id=pnid)
    return found


def _record_one(session: Session, client: WorkflowClient, account: ChannelAccount, event: WaEvent) -> None:
    try:
        with session.begin_nested():  # one bad event must not poison the batch (the provider would redeliver forever)
            if isinstance(event, WaStatus):
                record_status(session, account, event.wamid, DeliveryStatus(event.status), event.raw)
            else:
                record_event(session, client, account, event.wamid, event_to_payload(event))
    except (DataError, IntegrityError) as exc:
        log.error("whatsapp.webhook.event_rejected_by_db", wamid=event.wamid[:80], error_type=type(exc).__name__)


def _keep_unparsed(session: Session, accounts: dict[str, ChannelAccount], body: bytes, dropped: int) -> None:
    """Items the parser could not read are stored (failed) and alerted on, never silently acked away."""
    digest = hashlib.sha256(body).hexdigest()
    log.error("whatsapp.webhook.items_dropped", dropped=dropped, body_sha256=digest)
    account = next(iter(accounts.values()), None)
    if account is None:
        return
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        payload = {"undecodable": True}
    with session.begin_nested():
        record_event(
            session,
            client=_UNUSED,
            account=account,
            provider_msg_id=f"unparsed:{digest[:48]}",
            payload=payload if isinstance(payload, dict) else {"body": payload},
            status=RawEventStatus.failed,
            workflow=None,
        )


class _NoEnqueue:
    def enqueue_in_transaction(self, conn_or_session: object, options: object, *args: object) -> None:
        raise AssertionError("unparsed bodies never enqueue work")


_UNUSED = _NoEnqueue()
