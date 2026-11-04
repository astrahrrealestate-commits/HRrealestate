"""Agent tour (`make sim-agents`): one scripted day of mock traffic so every agent runs at least once and the dashboard
has something to show. Fake WhatsApp only, `outbound_mode` untouched (drafts), nothing leaves the machine.

Stages: tenant problems and a vague follow-up (triage, link_check, case_summary, proposer) -> contractor quote and
documents (quote reader, document classifier and reader) -> due-diligence screening of the lease, energy label and
VvE minutes -> the owner asks the Super Agent four questions and opens the briefing -> report per agent.

The owner is switched to the dashboard channel for the run (so no approval card goes to Google Chat) and put back.
"""

import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import Engine, Select, func, select, update
from sqlalchemy.orm import Session

from app.contracts import ActionType, InteractiveChannel
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import ApprovalStatus, DocumentStatus, PipelineStatus
from app.db.models import ActionRow, Approval, AttachmentRow, DocumentRow, MessageRow, ModelCall, OwnerAccount
from app.dev import mock_content as mc
from app.dev import mock_direct, mock_report
from app.dev.demo_dashboard import OWNER_EMAIL, WRITE, login, skip_reason
from app.dev.mock_portfolio import seed_portfolio
from app.dev.seed import seed_dev_tenant
from app.dev.simulate import Simulator

log = get_logger(__name__)
SETTLED_DOCS = (DocumentStatus.filed, DocumentStatus.review, DocumentStatus.skipped, DocumentStatus.failed)
Owners = list[tuple[UUID, InteractiveChannel | None, str | None]]


def _wait(done: Callable[[], bool], timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while not done():
        if time.monotonic() >= deadline:
            log.warning("sim.tour.timeout", waiting_for=what)
            return
        time.sleep(1.0)


def _count(engine: Engine, query: Select[Any]) -> int:
    with Session(engine) as session:
        return session.scalar(query) or 0


def pipeline_idle(engine: Engine, company_id: UUID, since: datetime, *, messages: int, files: int) -> bool:
    """All `messages` sent so far are stored and processed and all `files` have a settled document row."""
    scoped = (MessageRow.company_id == company_id, MessageRow.created_at >= since)
    stored = _count(engine, select(func.count()).select_from(MessageRow).where(*scoped))
    pending = _count(
        engine,
        select(func.count())
        .select_from(MessageRow)
        .where(*scoped, MessageRow.pipeline_status == PipelineStatus.pending),
    )
    settled = _count(
        engine,
        select(func.count())
        .select_from(DocumentRow)
        .where(
            DocumentRow.company_id == company_id, DocumentRow.created_at >= since, DocumentRow.status.in_(SETTLED_DOCS)
        ),
    )
    return stored >= messages and not pending and settled >= files


def _calls(engine: Engine, company_id: UUID, since: datetime) -> int:
    where = (ModelCall.company_id == company_id, ModelCall.created_at >= since)
    return _count(engine, select(func.count()).select_from(ModelCall).where(*where))


def settle(engine: Engine, company_id: UUID, since: datetime, *, messages: int, files: int, timeout: float) -> None:
    """Wait for the messages to be processed, then until no new model call has started for a few seconds (case
    summaries, proposals and quote reviews run in workflows after the message is marked done)."""
    _wait(lambda: pipeline_idle(engine, company_id, since, messages=messages, files=files), timeout, "pipeline")
    deadline, last = time.monotonic() + timeout, -1
    while time.monotonic() < deadline:
        now = _calls(engine, company_id, since)
        if now == last:
            return
        last = now
        time.sleep(8.0)


def tenant_stage(sim: Simulator) -> int:
    sanne, mohammed, lotte = mc.PHONE["Sanne"], mc.PHONE["Mohammed"], mc.PHONE["Lotte"]
    sim.whatsapp(sanne, "Goedemorgen, de verwarming in de woonkamer doet het niet meer. Het is hier 14 graden.")
    sim.whatsapp(sanne, "Ook druppelt er water uit het plafond in de badkamer, het wordt steeds erger!")
    sim.whatsapp(mohammed, "Hallo, de voordeur sluit niet goed meer en de buren boven maken elke nacht lawaai.")
    sim.whatsapp(lotte, "Kan ik mijn huurcontract en de energiekosten van vorig jaar ontvangen? Dank u wel.")
    return 4


def email_stage(sim: Simulator, settings: Settings) -> int:
    """Sanne also writes by email: a second channel with its own thread, the same person and case."""
    if settings.gmail_provider != "fake":
        log.warning("sim.tour.email_skipped", reason="GMAIL_PROVIDER is not fake")
        return 0
    sender = f"Sanne de Vries <{mc.EMAIL['Sanne']}>"
    sim.gmail(sender, "Verwarming doet het niet", "De cv-ketel geeft foutcode E5 en de radiatoren blijven koud.")
    sim.gmail(sender, "Lekkage badkamer", "Er komt water door het plafond van de badkamer, zie ook mijn WhatsApp.")
    return 2


def document_stage(sim: Simulator) -> int:
    pieter, visser = mc.PHONE["Pieter"], mc.PHONE["Elektro"]
    sim.whatsapp(pieter, "Offerte lekkage Keizersgracht 42-A: totaal 480 euro excl. btw, zie bijlage.",
                 document=mc.pdf("offerte_2026-117.pdf"))  # fmt: skip
    sim.whatsapp(visser, "Factuur groepenkast Prinsengracht 118-B, graag betalen voor 11 november.",
                 document=mc.pdf("factuur_2026-0931.pdf"))  # fmt: skip
    sim.whatsapp(mc.PHONE["Mohammed"], "Hierbij mijn huurovereenkomst.",
                 document=mc.pdf("huurovereenkomst_prinsengracht-118-B.pdf"))  # fmt: skip
    sim.whatsapp(
        mc.PHONE["Sanne"], "Het energielabel van mijn woning.", document=mc.pdf("energielabel_keizersgracht-42-A.pdf")
    )
    sim.whatsapp(mc.PHONE["Lotte"], "De notulen van de VvE vergadering.", document=mc.pdf("notulen_vve_2026.pdf"))
    return 5


def screening_documents(engine: Engine, company_id: UUID, since: datetime) -> list[UUID]:
    wanted = ("huurovereenkomst", "energielabel", "notulen")
    with Session(engine) as session:
        rows = session.execute(
            select(DocumentRow.id, AttachmentRow.filename)
            .join(AttachmentRow, AttachmentRow.id == DocumentRow.attachment_id)
            .where(DocumentRow.company_id == company_id, DocumentRow.created_at >= since)
        ).all()
    return [doc_id for doc_id, name in rows if name and name.startswith(wanted)]


def screening(api: httpx.Client, document_ids: list[UUID]) -> UUID | None:
    if not document_ids:
        return None
    body = {"title": "Aankoop Keizersgracht 42-A", "property_kind": "tenanted_investment",
            "document_ids": [str(d) for d in document_ids]}  # fmt: skip
    created = api.post("/api/v1/diligence/reviews", json=body, headers=WRITE)
    created.raise_for_status()
    return UUID(created.json()["id"])


def ask_agent(api: httpx.Client, question: str, timeout: float) -> str:
    posted = api.post("/api/v1/agent/messages", json={"text": question}, headers=WRITE)
    posted.raise_for_status()
    conversation, turn = posted.json()["conversation_id"], posted.json()["turn_id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        got = api.get(f"/api/v1/agent/conversations/{conversation}")
        got.raise_for_status()
        status = next((t["status"] for t in got.json()["turns"] if t["id"] == turn), "pending")
        if status in ("done", "failed"):
            return status
        time.sleep(1.0)
    return "timeout"


def switch_to_dashboard(engine: Engine, company_id: UUID) -> Owners:
    """Owners answer on the dashboard for the run. Returns what they had, for `restore_owners`."""
    with Session(engine) as session, session.begin():
        owners = session.execute(
            select(OwnerAccount.id, OwnerAccount.interactive_channel, OwnerAccount.email).where(
                OwnerAccount.company_id == company_id
            )
        ).all()
        session.execute(
            update(OwnerAccount)
            .where(OwnerAccount.company_id == company_id)
            .values(interactive_channel=InteractiveChannel.dashboard, email=OWNER_EMAIL)
        )
    return [(o.id, o.interactive_channel, o.email) for o in owners]


def restore_owners(engine: Engine, company_id: UUID, previous: Owners) -> None:
    with Session(engine) as session, session.begin():
        for owner_id, channel, email in previous:
            session.execute(
                update(OwnerAccount)
                .where(OwnerAccount.company_id == company_id, OwnerAccount.id == owner_id)
                .values(interactive_channel=channel, email=email)
            )


def approve_contractor_request(api: httpx.Client, engine: Engine, company_id: UUID, since: datetime) -> str:
    """Approving a request_contractor action fixes the decision-day snapshot (job items and price agents)."""
    with Session(engine) as session:
        approval_id = session.scalar(
            select(Approval.id)
            .join(ActionRow, ActionRow.id == Approval.action_id)
            .where(
                Approval.company_id == company_id,
                Approval.status == ApprovalStatus.pending,
                ActionRow.type == ActionType.request_contractor,
                ActionRow.created_at >= since,
            )
            .limit(1)
        )
    if approval_id is None:
        return "no contractor request proposed"
    decided = api.post(f"/api/v1/approvals/{approval_id}/decide", json={"choice": "ok"}, headers=WRITE)
    return f"http {decided.status_code}"


def propose_visit(api: httpx.Client) -> str:
    body = {"messageText": "Morgen tussen 10:00 en 12:00 kan ik langskomen voor de lekkage.",
            "propertyAddress": "Keizersgracht 42-A, Amsterdam"}  # fmt: skip
    return f"http {api.post('/api/calendar/propose', json=body, headers=WRITE).status_code}"


def run_tour(sim: Simulator, engine: Engine, settings: Settings, *, timeout: float) -> int:
    reason = skip_reason(settings)
    if reason:
        log.error("sim.tour.cannot_run", reason=reason)
        return 1
    company_id = seed_dev_tenant(engine).company_id
    added = seed_portfolio(engine, company_id)
    since = datetime.now(UTC)
    previous = switch_to_dashboard(engine, company_id)
    try:
        status = _tour(sim, engine, settings, company_id, since, timeout)
    finally:
        restore_owners(engine, company_id, previous)
    log.info("sim.tour.done", people_added=added, **status)
    calls = mock_report.model_calls(engine, company_id, since)
    counts = mock_report.row_counts(engine, company_id, since)
    print_report(mock_report.render(calls, counts))
    return 0


def wait_review(api: httpx.Client, review_id: UUID | None, timeout: float) -> str:
    if review_id is None:
        return "not started (no documents read yet)"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        got = api.get(f"/api/v1/diligence/reviews/{review_id}")
        got.raise_for_status()
        if got.json()["status"] in ("done", "failed"):
            return f"{got.json()['status']} verdict={got.json()['verdict']}"
        time.sleep(2.0)
    return "timeout"


def _tour(
    sim: Simulator, engine: Engine, settings: Settings, company_id: UUID, since: datetime, timeout: float
) -> dict[str, str]:
    login(sim.api)
    sent = tenant_stage(sim) + email_stage(sim, settings)
    settle(engine, company_id, since, messages=sent, files=0, timeout=timeout)
    files = document_stage(sim)
    settle(engine, company_id, since, messages=sent + files, files=files, timeout=timeout)
    review = screening(sim.api, screening_documents(engine, company_id, since))
    answers = {f"q{n}": ask_agent(sim.api, q, timeout) for n, q in enumerate(mc.AGENT_QUESTIONS, start=1)}
    contractor = approve_contractor_request(sim.api, engine, company_id, since)
    briefing = sim.api.get("/api/v1/briefing").status_code
    visit = propose_visit(sim.api)
    outcome = wait_review(sim.api, review, timeout)
    direct = {
        "link_check_direct": mock_direct.link_check(engine, settings, company_id),
        "briefings_direct": mock_direct.briefings(engine, settings, company_id),
    }
    settle(engine, company_id, since, messages=sent + files, files=files, timeout=timeout)
    return {**answers, "briefing_http": str(briefing), "contractor_request": contractor, "calendar": visit,
            "review": outcome, **direct}  # fmt: skip


def print_report(text: str) -> None:
    sys.stdout.write(text)
