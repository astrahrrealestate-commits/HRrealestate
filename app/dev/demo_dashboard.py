"""Dashboard scenario for `make sim-demo`: the owner works through the v1 API instead of WhatsApp.

Needs the stack's fake providers, DASHBOARD_AUTH_PROVIDER=fake and DASHBOARD_SESSION_SECRET set. The dev company is
switched to outbound_mode=send and its owner to the dashboard channel (fake providers only, the simulator refuses
prod). Flow: tenant writes over WhatsApp and Gmail -> inbox -> approval list -> decide `ok` -> post "tasks" to the
agent and poll the conversation. Rows asserted: an owner_feed approval card, one `sends` row to the tenant, one
agent turn `done`, no model call for the fast path.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

import httpx
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, CSRF_HEADER, CSRF_VALUE, FAKE_DEFAULT_TOKENS
from app.contracts import Channel, InteractiveChannel, OutboundMode
from app.core.logging import get_logger
from app.db.enums import FeedKind, SendStatus, TurnStatus
from app.db.models import ActionRow, AgentTurn, Company, MessageRow, ModelCall, OwnerAccount, OwnerFeed, Send
from app.dev.simulate import Simulator

log = get_logger(__name__)

TENANT_E164 = "+4915550000002"
TENANT_EMAIL = "tenant-003@example.test"
OWNER_TOKEN, OWNER_EMAIL = next(iter(FAKE_DEFAULT_TOKENS.items()))
WRITE = {CSRF_HEADER: CSRF_VALUE}


@dataclass(frozen=True)
class Facts:
    feed_cards: int
    sends: tuple[tuple[str, SendStatus], ...]  # (target, status) of the decided action
    turn_statuses: tuple[TurnStatus, ...]
    model_calls_after_turn: int


def dashboard_problems(facts: Facts, tenant_targets: frozenset[str]) -> list[str]:
    found: list[str] = []
    if facts.feed_cards < 1:
        found.append("no approval card in owner_feed")
    if len(facts.sends) != 1:
        found.append(f"sends: {len(facts.sends)}/1 for the decided action")
    else:
        target, status = facts.sends[0]
        if target not in tenant_targets or status is not SendStatus.sent:
            found.append(f"send went to {target!r} with status {status.value}")
    if facts.turn_statuses != (TurnStatus.done,):
        found.append(f"agent turns: {[s.value for s in facts.turn_statuses]}, expected one done")
    if facts.model_calls_after_turn:
        found.append(f"{facts.model_calls_after_turn} model calls on the fast path, expected 0")
    return found


def prepare(engine: Engine, company_id: UUID) -> None:
    """Send mode and the dashboard channel for the dev company (fake providers only)."""
    with Session(engine) as session, session.begin():
        session.execute(update(Company).where(Company.id == company_id).values(outbound_mode=OutboundMode.send))
        session.execute(
            update(OwnerAccount)
            .where(OwnerAccount.company_id == company_id)
            .values(interactive_channel=InteractiveChannel.dashboard, email=OWNER_EMAIL)
        )


def login(api: httpx.Client) -> None:
    r = api.post("/api/v1/auth/session", json={"id_token": OWNER_TOKEN}, headers=WRITE)
    r.raise_for_status()
    if COOKIE not in api.cookies:
        raise RuntimeError("login set no session cookie")


def _poll[T](fetch: Callable[[], T | None], timeout: float, what: str) -> T:
    deadline = time.monotonic() + timeout
    while True:
        value = fetch()
        if value is not None:
            return value
        if time.monotonic() >= deadline:
            raise TimeoutError(f"dashboard demo: timed out waiting for {what}")
        time.sleep(0.5)


def _tenant_whatsapp_actions(engine: Engine, company_id: UUID) -> set[UUID]:
    """Reply drafts on WhatsApp that answer this scenario's tenant messages."""
    with Session(engine) as session:
        ids = list(
            session.scalars(
                select(MessageRow.id).where(
                    MessageRow.company_id == company_id, MessageRow.sender_identity == TENANT_E164
                )
            )
        )
        if not ids:
            return set()
        return set(
            session.scalars(
                select(ActionRow.id).where(
                    ActionRow.company_id == company_id,
                    ActionRow.context_ref.overlap(ids),
                    ActionRow.payload["channel"].astext == Channel.whatsapp.value,
                )
            )
        )


def _find_approval(api: httpx.Client, engine: Engine, company_id: UUID) -> dict[str, object] | None:
    mine = _tenant_whatsapp_actions(engine, company_id)
    r = api.get("/api/v1/approvals", params={"limit": 100})
    r.raise_for_status()
    return next((a for a in r.json() if UUID(a["action_id"]) in mine), None)


def _inbox_has_tenant(api: httpx.Client) -> bool | None:
    r = api.get("/api/v1/inbox", params={"limit": 100})
    r.raise_for_status()
    return True if any(i["sender"] in (TENANT_E164, TENANT_EMAIL) for i in r.json()) else None


def _post_tasks(api: httpx.Client, timeout: float) -> UUID:
    r = api.post("/api/v1/agent/messages", json={"text": "tasks"}, headers=WRITE)
    r.raise_for_status()
    conversation, turn = r.json()["conversation_id"], UUID(r.json()["turn_id"])

    def done() -> UUID | None:
        got = api.get(f"/api/v1/agent/conversations/{conversation}")
        got.raise_for_status()
        turns = [t for t in got.json()["turns"] if UUID(t["id"]) == turn]
        return turn if turns and turns[0]["status"] in ("done", "failed") else None

    return _poll(done, timeout, "the agent turn")


def collect_facts(engine: Engine, company_id: UUID, action_id: UUID, turn_id: UUID) -> Facts:
    with Session(engine) as session:
        turn = session.get(AgentTurn, turn_id)
        if turn is None or turn.company_id != company_id:
            raise RuntimeError("turn row missing")
        cards = session.scalar(
            select(func.count())
            .select_from(OwnerFeed)
            .where(OwnerFeed.company_id == company_id, OwnerFeed.kind == FeedKind.approval)
        )
        sends = session.execute(
            select(Send.target, Send.status).where(Send.company_id == company_id, Send.action_id == action_id)
        ).all()
        calls = session.scalar(
            select(func.count())
            .select_from(ModelCall)
            .where(ModelCall.company_id == company_id, ModelCall.created_at >= turn.created_at)
        )
    return Facts(cards or 0, tuple((t, st) for t, st in sends), (turn.status,), calls or 0)


def _wait_for_send(engine: Engine, company_id: UUID, action_id: UUID, timeout: float) -> None:
    def sent() -> bool | None:
        with Session(engine) as session:
            status = session.scalar(
                select(Send.status).where(Send.company_id == company_id, Send.action_id == action_id)
            )
        return True if status in (SendStatus.sent, SendStatus.failed) else None

    _poll(sent, timeout, "the tenant send")


def targets() -> frozenset[str]:
    return frozenset({TENANT_E164, TENANT_E164.lstrip("+"), TENANT_EMAIL})


def run_dashboard(sim: Simulator, engine: Engine, company_id: UUID, *, timeout: float) -> list[str]:
    """Returns the problems found (empty = `dashboard=ok`). Raises on API errors or timeouts."""
    prepare(engine, company_id)
    sim.whatsapp(TENANT_E164, "Die Heizung im Flur ist kaputt, bitte schnell reparieren.")
    sim.gmail(f"Mieter 003 <{TENANT_EMAIL}>", "Heizung Flur", "Die Heizung im Flur ist kaputt.")
    api = sim.api
    login(api)
    _poll(lambda: _inbox_has_tenant(api), timeout, "the tenant in the inbox")
    approval = _poll(lambda: _find_approval(api, engine, company_id), timeout, "the reply approval")
    decided = api.post(f"/api/v1/approvals/{approval['id']}/decide", json={"choice": "ok"}, headers=WRITE)
    decided.raise_for_status()
    action_id = UUID(decided.json()["action_id"])
    _wait_for_send(engine, company_id, action_id, timeout)
    turn_id = _post_tasks(api, timeout)
    return dashboard_problems(collect_facts(engine, company_id, action_id, turn_id), targets())
