"""Briefing wiring (#7): hourly cron keeps the next runs scheduled; timer handlers compose and send to Harjot."""

from datetime import UTC, datetime
from functools import partial
from typing import Any
from uuid import UUID

from dbos import DBOS
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.whatsapp import payloads
from app.contracts import Channel, EmailRequest
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.db.models import ActionRow, ChannelAccount, OwnerAccount
from app.llm.agents.briefing import Kind
from app.owner.digest import DigestCaseReply, collect_digest_data, render_digest_email
from app.pipeline import briefing
from app.pipeline.timers import ClaimedTimer
from app.sender.execute import SenderDeps, send_owner_email, send_to_owner
from app.sender.targets import _gmail_draft
from app.workflows import timer_dispatch
from app.workflows.deps import get_engine, get_sender_deps

log = get_logger(__name__)


def _text(body: str, to: str) -> dict[str, Any]:
    return payloads.text(to, body)


def send_digest_email(deps: SenderDeps, company_id: UUID, key: str, kind: Kind, now: datetime) -> str | None:
    """Delivers the morning digest email to owner_accounts.email if items need the owner.

    If the owner has no interactive channel configured, creates the first draft of each reply in the
    Gmail thread so he can edit and send from Gmail.
    """
    with Session(deps.engine) as session:
        owner = session.scalar(
            select(OwnerAccount).where(OwnerAccount.company_id == company_id).order_by(OwnerAccount.created_at)
        )
        if owner is None or not owner.email:
            log.info("digest.no_owner_email", company_id=str(company_id))
            return None

        data = collect_digest_data(session, company_id, kind, now)
        if not data.has_items:
            log.info("digest.empty_skipped", company_id=str(company_id))
            return None

        no_interactive = not bool(owner.interactive_channel)
        if no_interactive:
            _create_gmail_thread_drafts(session, deps, company_id, data.replies)

    subject, body_text, body_html = render_digest_email(data)
    req = EmailRequest(
        idempotency_key=key,
        to=owner.email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )
    return send_owner_email(deps, company_id, key, req)


def _create_gmail_thread_drafts(
    session: Session, deps: SenderDeps, company_id: UUID, replies: tuple[DigestCaseReply, ...]
) -> None:
    """When no interactive channel exists, the first reply draft is placed in Gmail so Harjot can edit & send."""
    mailbox = session.scalar(
        select(ChannelAccount.address).where(
            ChannelAccount.company_id == company_id, ChannelAccount.channel == Channel.gmail
        )
    )
    if not mailbox:
        return
    for reply in replies:
        if not reply.drafts or not reply.thread_id:
            continue
        action = session.get(ActionRow, reply.action_id)
        if action is None:
            continue
        try:
            plan = _gmail_draft(session, action, reply.drafts[0], f"digest_draft:{reply.approval_id}:0")
            if plan.draft is not None:
                deps.gmail_drafts(mailbox).create_draft(plan.draft)
        except Exception as exc:
            log.warning("digest.draft_creation_failed", approval_id=str(reply.approval_id), error=str(exc))


def on_briefing(timer: ClaimedTimer) -> None:
    """Runs inside the `timers.run_handler` step. One send key per timer, so a re-fired timer sends nothing twice;
    outside the WhatsApp window the briefing waits behind the template nudge until Harjot replies."""
    kind: Kind = "weekly" if timer.kind == briefing.WEEKLY else "daily"
    now = datetime.now(UTC)
    with Session(get_engine()) as session, session.begin():  # book the next runs first: a failed send never stops them
        briefing.ensure_timers(session, now)
    text = briefing.compose(get_engine(), get_settings(), timer.company_id, kind, now)
    send_to_owner(get_sender_deps(), timer.company_id, f"briefing:{timer.id}", partial(_text, text))
    send_digest_email(get_sender_deps(), timer.company_id, f"digest:{timer.id}", kind, now)


@DBOS.step(name="briefing.ensure_timers")
def ensure_step(now_iso: str) -> int:
    with Session(get_engine()) as session, session.begin():
        return briefing.ensure_timers(session, datetime.fromisoformat(now_iso))


@DBOS.workflow(name="briefing.ensure")
def ensure_briefings(scheduled_time: datetime, context: Any) -> None:
    ensure_step(scheduled_time.isoformat())


timer_dispatch.register(briefing.DAILY, on_briefing)
timer_dispatch.register(briefing.WEEKLY, on_briefing)
