"""Test a real Gmail mailbox locally, before Pub/Sub and a public endpoint exist (dev only, never production).

    python -m app.dev.simulate gmail-pull --mailbox you@gmail.com   # register the mailbox, sync it once now
    python -m app.dev.simulate pending                              # pending approvals + the tap to approve each
    python -m app.dev.simulate approve --n 1 --choice d1            # tap it as Harjot (simulated WhatsApp)

`gmail-pull` is what the hourly `gmail.backfill` cron does for every mailbox: the same `ingest.gmail_sync` workflow
that a Pub/Sub push starts. The first sync of a mailbox reads its last day of mail; later ones read new history.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.channels import registry
from app.core.errors import UnsafeConfigurationError
from app.core.settings import Settings
from app.core.workflow_names import GMAIL_SYNC, GMAIL_SYNC_QUEUE
from app.db.enums import ApprovalStatus, SendStatus
from app.db.models import ActionRow, Approval, Case, Person, Send
from app.dev.seed import seed_dev_tenant
from app.ingestion.repository import Enqueuer


def pull_mailbox(engine: Engine, settings: Settings, client: Enqueuer, mailbox: str) -> str:
    """Register `mailbox` on the dev company (idempotent) and enqueue one sync up to its current history."""
    if settings.gmail_provider != "google":
        raise UnsafeConfigurationError("gmail-pull needs GMAIL_PROVIDER=google and GMAIL_CREDENTIALS_FILE")
    tenant = seed_dev_tenant(engine, mailbox=mailbox.strip().lower())
    history = registry.gmail_mailbox(settings, mailbox).current_history_id()  # also verifies the token's mailbox
    workflow_id = f"gpull:{tenant.gmail_account_id}:{history}"
    options = {"queue_name": GMAIL_SYNC_QUEUE, "workflow_name": GMAIL_SYNC, "workflow_id": workflow_id}
    with Session(engine) as session, session.begin():
        client.enqueue_in_transaction(session, options, str(tenant.gmail_account_id), history)
    return workflow_id


@dataclass(frozen=True)
class PendingApproval:
    n: int
    approval_id: UUID
    kind: str
    case_label: str
    draft_preview: str
    card_wamid: str | None  # the interactive message Harjot would tap (fake WhatsApp id)


def pending_approvals(engine: Engine, company_id: UUID, limit: int = 20) -> list[PendingApproval]:
    with Session(engine) as session:
        rows = session.execute(
            select(Approval, ActionRow, Case)
            .join(ActionRow, ActionRow.id == Approval.action_id)
            .join(Case, Case.id == ActionRow.case_id)
            .where(Approval.company_id == company_id, Approval.status == ApprovalStatus.pending)
            .order_by(Approval.created_at.desc())
            .limit(limit)
        ).all()
        found = []
        for n, (approval, action, case) in enumerate(rows, start=1):
            name = session.scalar(
                select(Person.display_name).where(Person.company_id == company_id, Person.id == case.primary_person_id)
            )
            wamid = session.scalar(
                select(Send.provider_ref)
                .where(Send.idempotency_key.like(f"approval:{approval.id}:%"), Send.status == SendStatus.sent)
                .order_by(Send.idempotency_key.desc())
                .limit(1)
            )
            drafts = action.payload.get("body_variants") or [action.payload.get("text") or action.payload.get("reason")]
            preview = " ".join(str(drafts[0] or "").split())[:100]
            label = f"{name or 'unknown'} · {case.category.value}"
            found.append(PendingApproval(n, approval.id, action.type.value, label, preview, wamid))
        return found
