"""Writing a proposal (#4): actions through the rules, approvals, the card's rationale and draft provenance."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.context.persona import stamp_persona
from app.context.sender_label import SenderKind
from app.contracts import Action, ActionType
from app.core.logging import get_logger
from app.db.enums import ActionStatus, ApprovalStatus
from app.db.models import ActionRevision, ActionRow, Approval
from app.llm.agents.proposer import proposer_spec
from app.pipeline import approvals
from app.pipeline.concierge_sanitize import sanitize
from app.pipeline.propose_load import Loaded
from app.pipeline.rules import RuleContext, Verdict, apply_rules

log = get_logger(__name__)
_STATUS = {
    Verdict.pending_approval: ActionStatus.pending_approval,
    Verdict.exception: ActionStatus.exception,
    Verdict.paused: ActionStatus.paused,
}
LEGAL_REVIEW_NOTE = "Legal sender: read the original before approving this reply."


@dataclass
class ProposeResult:
    approval_ids: list[UUID] = field(default_factory=list)
    exceptions: int = 0


def existing(session: Session, company_id: UUID, message_id: UUID) -> ProposeResult | None:
    rows = session.scalars(
        select(ActionRow).where(ActionRow.company_id == company_id, ActionRow.context_ref.contains([message_id]))
    ).all()
    if not rows:
        return None
    live = session.scalars(
        select(Approval.id).where(
            Approval.company_id == company_id,
            Approval.action_id.in_([r.id for r in rows]),
            Approval.status == ApprovalStatus.pending,
        )
    ).all()
    return ProposeResult(list(live), sum(r.status is ActionStatus.exception for r in rows))


def lock_message(session: Session, message_id: UUID) -> None:
    """Serialises proposals for one message (the pipeline, a requeue and owner-requested drafts)."""
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"propose:{message_id}"})


def record_draft(session: Session, company_id: UUID, row: ActionRow, key: str) -> None:
    """The provenance of an owner-requested draft: an ActionRevision of its first version under the turn's key."""
    session.add(
        ActionRevision(
            company_id=company_id, action_id=row.id, draft_version=row.draft_version, payload=row.payload, edited_by=key
        )
    )


def _with_sources(action: Action, sources: Sequence[str]) -> str:
    """A reply drafted with documents or research in view says which, so Harjot can check them on the card."""
    if action.type is not ActionType.reply_draft or not sources:
        return action.rationale
    return f"{action.rationale} (sources in view: {', '.join(sanitize(s)[:80] for s in sources)})"


def rationale(action: Action, loaded: Loaded) -> str:
    """What the card says about a draft: its sources, and a nudge to read a lawyer's letter first. Decided by code from
    the resolved sender, never by the model."""
    text_ = _with_sources(action, loaded.sources)
    if action.type is ActionType.reply_draft and loaded.ctx.sender_kind == SenderKind.legal.value:
        return f"{text_} {LEGAL_REVIEW_NOTE}"
    return text_


def persist(
    session: Session, loaded: Loaded, message_id: UUID, actions: list[Action], key: str | None, rules: RuleContext
) -> ProposeResult:
    result = ProposeResult()
    for decision in apply_rules(actions, rules):
        if decision.verdict is Verdict.drop:
            continue
        a = decision.action
        row = ActionRow(
            company_id=loaded.company_id, case_id=loaded.ctx.case_id, type=a.type,
            payload=a.payload.model_dump(mode="json"), rationale=rationale(a, loaded), context_ref=[message_id],
            draft_version=1, status=_STATUS[decision.verdict], prompt_version=proposer_spec(loaded.ctx).prompt.version,
        )  # fmt: skip
        stamp_persona(row, a.payload, loaded.ctx.persona)
        session.add(row)
        session.flush()
        if key is not None and a.type is ActionType.reply_draft:
            record_draft(session, loaded.company_id, row, key)
            key = None  # one keyed reply per call
        if decision.verdict is Verdict.pending_approval:
            urgency, now = loaded.ctx.understanding.urgency, datetime.now(UTC)
            result.approval_ids.append(approvals.open_approval(session, loaded.company_id, row.id, 1, urgency=urgency,
                                                               now=now))  # fmt: skip
        elif decision.verdict is Verdict.exception:
            result.exceptions += 1
            log.info("pipeline.rules.exception", reason=decision.reason, action_type=a.type.value)
    return result
