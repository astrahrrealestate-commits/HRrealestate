"""Parity scenario: one tenant reports the same problem over WhatsApp and over Gmail, then the owner taps a button.

Both channels must yield equivalent normalised rows (direction, sender, text, one photo, one thread per channel,
routed to the pipeline); the owner's tap must route to the owner handler. `make sim-demo` runs this against the
compose stack; tests/integration/test_parity.py runs it in-process.
"""

import hashlib
import time
from dataclasses import dataclass, field
from uuid import UUID

from dbos import DBOSClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import PipelineStatus
from app.db.models import ActionRow, Approval, AttachmentRow, CaseLink, MessageRow, UnderstandingRow
from app.dev import fixtures as fx
from app.dev.seed import seed_dev_tenant
from app.dev.simulate import Simulator

log = get_logger(__name__)

TENANT_E164 = "+4915550000001"
TENANT_EMAIL = "tenant-001@example.test"
TEXTS = ("Die Heizung im Bad bleibt kalt.", "Hier ein Foto vom Heizkörper.")
PHOTO = fx.Attachment("heizkoerper.jpg", "image/jpeg", b"\xff\xd8\xff\xe0 EstateOS demo photo")


@dataclass(frozen=True)
class Sent:
    company_id: UUID
    whatsapp: tuple[str, ...]  # wamids
    gmail: tuple[str, ...]  # RFC 822 Message-IDs (Gmail assigns its own provider ids)
    button: str


@dataclass(frozen=True)
class Row:
    id: UUID
    direction: Direction
    sender: str
    text: str
    thread: str | None
    photos: tuple[str, ...] = field(default=())  # attachment sha256s


def send_scenario(sim: Simulator, company_id: UUID) -> Sent:
    wa = (sim.whatsapp(TENANT_E164, TEXTS[0]), sim.whatsapp(TENANT_E164, TEXTS[1], image=PHOTO))
    sender = f"Mieter 001 <{TENANT_EMAIL}>"
    first = sim.gmail(sender, "Heizung kalt", TEXTS[0])
    second = sim.gmail(sender, "Re: Heizung kalt", TEXTS[1], in_reply_to=first, attachment=PHOTO)
    button = sim.button(f"apr:{new_id()}:ok", "Freigeben", reply_to=wa[0])
    return Sent(company_id, wa, (first, second), button)


def load_rows(engine: Engine, sent: Sent) -> tuple[list[Row], list[Row], list[Row]]:
    """(whatsapp rows, gmail rows, button rows) in send order; rows not stored yet are simply absent."""
    with Session(engine) as session:
        scoped = select(MessageRow).where(MessageRow.company_id == sent.company_id)
        wa_ids = (*sent.whatsapp, sent.button)
        wa = {m.provider_msg_id: m for m in session.scalars(scoped.where(MessageRow.provider_msg_id.in_(wa_ids)))}
        by_rfc_id = scoped.where(
            MessageRow.channel == Channel.gmail, MessageRow.meta["message_id"].astext.in_(sent.gmail)
        )
        gm = {str(m.meta["message_id"]): m for m in session.scalars(by_rfc_id)}
        photos = _photos(session, sent.company_id, [m.id for m in (*wa.values(), *gm.values())])

    def rows(found: dict[str, MessageRow], keys: tuple[str, ...]) -> list[Row]:
        return [_row(found[k], photos) for k in keys if k in found]

    return rows(wa, sent.whatsapp), rows(gm, sent.gmail), rows(wa, (sent.button,))


def _photos(session: Session, company_id: UUID, message_ids: list[UUID]) -> dict[UUID, list[str]]:
    found: dict[UUID, list[str]] = {}
    query = select(AttachmentRow).where(
        AttachmentRow.company_id == company_id, AttachmentRow.message_id.in_(message_ids)
    )
    for att in session.scalars(query):
        found.setdefault(att.message_id, []).append(att.sha256)
    return found


def _row(m: MessageRow, photos: dict[UUID, list[str]]) -> Row:
    return Row(m.id, m.direction, m.sender_identity, m.text.strip(), m.thread_ref, tuple(photos.get(m.id, ())))


def problems(rows: tuple[list[Row], list[Row], list[Row]], routes: dict[UUID, str]) -> list[str]:
    wa, gm, button = rows
    found: list[str] = []
    photo = hashlib.sha256(PHOTO.data).hexdigest()
    for name, channel_rows, sender in (("whatsapp", wa, TENANT_E164), ("gmail", gm, TENANT_EMAIL)):
        if len(channel_rows) != 2:
            found.append(f"{name}: {len(channel_rows)}/2 messages stored")
            continue
        shape = [(r.direction, r.sender, r.text, r.photos, routes.get(r.id)) for r in channel_rows]
        expected = [
            (Direction.inbound, sender, TEXTS[0], (), "pipe"),
            (Direction.inbound, sender, TEXTS[1], (photo,), "pipe"),
        ]
        if shape != expected:
            found.append(f"{name}: got {shape}, expected {expected}")
        if any(r.thread is None for r in channel_rows) or len({r.thread for r in channel_rows}) != 1:
            found.append(f"{name}: messages split across threads {[r.thread for r in channel_rows]}")
    if [(r.sender, routes.get(r.id)) for r in button] != [(fx.DEV_OWNER_E164, "owner")]:
        found.append(f"owner button: got {[(r.sender, routes.get(r.id)) for r in button]}")
    return found


def routes_of(client: DBOSClient, rows: tuple[list[Row], list[Row], list[Row]]) -> dict[UUID, str]:
    """Which handler each message was routed to: `pipe:<id>` or `owner:<id>` child workflows."""
    wanted = {f"{prefix}:{r.id}": (r.id, prefix) for group in rows for r in group for prefix in ("pipe", "owner")}
    if not wanted:
        return {}  # an empty id filter would list every workflow
    return {
        wanted[w.workflow_id][0]: wanted[w.workflow_id][1] for w in client.list_workflows(workflow_ids=list(wanted))
    }


def wait_for_parity(engine: Engine, client: DBOSClient, sent: Sent, timeout: float) -> list[str]:
    deadline = time.monotonic() + timeout
    while True:
        rows = load_rows(engine, sent)
        found = problems(rows, routes_of(client, rows))
        if not found or time.monotonic() >= deadline:
            return found
        time.sleep(0.5)


def pipeline_problems(engine: Engine, company_id: UUID, message_ids: list[UUID]) -> list[str]:
    """Agents ran on every tenant message: understood, linked to a case, and an approval is waiting for Harjot."""
    with Session(engine) as session:
        statuses = session.scalars(select(MessageRow.pipeline_status).where(MessageRow.id.in_(message_ids))).all()
        understood = session.scalar(
            select(func.count()).select_from(UnderstandingRow).where(UnderstandingRow.message_id.in_(message_ids))
        )
        cases = set(session.scalars(select(CaseLink.case_id).where(CaseLink.message_id.in_(message_ids))))
        approvals = session.scalar(
            select(func.count())
            .select_from(Approval)
            .join(ActionRow, ActionRow.id == Approval.action_id)
            .where(ActionRow.company_id == company_id, ActionRow.context_ref.overlap(message_ids))
        )
    found = []
    if statuses.count(PipelineStatus.done) != len(message_ids):
        found.append(f"pipeline: {statuses.count(PipelineStatus.done)}/{len(message_ids)} messages done")
    if understood != len(message_ids):
        found.append(f"understanding: {understood}/{len(message_ids)}")
    if len(cases) != 2:  # one case per channel thread (the phone and the email address are two senders)
        found.append(f"cases: {len(cases)}/2")
    if not approvals:
        found.append("no approval waiting for the owner")
    return found


def wait_for_pipeline(engine: Engine, sent: Sent, timeout: float) -> list[str]:
    wa, gm, _ = load_rows(engine, sent)
    ids = [r.id for r in (*wa, *gm)]
    deadline = time.monotonic() + timeout
    while True:
        found = pipeline_problems(engine, sent.company_id, ids)
        if not found or time.monotonic() >= deadline:
            return found
        time.sleep(0.5)


def run_demo(sim: Simulator, engine: Engine, settings: Settings, *, timeout: float) -> int:
    tenant = seed_dev_tenant(engine)
    sent = send_scenario(sim, tenant.company_id)
    client = DBOSClient(system_database_url=settings.dbos_database_url)
    try:
        found = wait_for_parity(engine, client, sent, timeout) or wait_for_pipeline(engine, sent, timeout)
        if found:
            log.error("sim.demo.failed", problems=found)
            return 1
        rows = load_rows(engine, sent)
        routes = routes_of(client, rows)
    finally:
        client.destroy()
    for channel, group in zip(("whatsapp", "gmail", "owner"), rows, strict=True):
        for r in group:  # message text stays out of logs
            log.info(
                "sim.demo.row",
                channel=channel,
                direction=r.direction.value,
                sender=r.sender,
                thread=r.thread,
                photos=len(r.photos),
                route=routes.get(r.id),
            )
    log.info("sim.demo.ok", whatsapp=len(sent.whatsapp), gmail=len(sent.gmail), owner_buttons=1, agents="ok")
    return 0
