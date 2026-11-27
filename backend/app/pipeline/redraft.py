"""Owner-requested redrafts (Super Agent `draft_reply`, amendment 2026-10-22) for a message that already had a proposal.

- A live pending reply approval (or an edit tap older than the 24 h edit window) is superseded exactly once
  (`supersede.supersede_draft`): new `draft_version`, new pending approval, the old one expired and its feed card
  resolved.
- A message whose reply was decided (or that has only other actions) gets a fresh reply action
  (`context_ref = [message_id]`, so the decide gate's suspicious check covers it) with a pending approval; under the
  message lock the state is read again, so a reply another turn just proposed is superseded, never doubled.
- A reply awaiting approval without a live pending approval (an edit tap's window) and held messages (paused,
  exception: suspicious or an unverified link) are never redrafted. Locks follow `decide`: approval, then action.
Every write carries an ActionRevision keyed `agent:{turn_id}:{step}`; `turn_replay` finds any of the turn's revisions
on the message first, so a retried step (or a second draft_reply step of the same turn) returns the same revision and
never calls the model again. The proposer output passes the same rules as the propose stage; recipients are never
part of a payload (the sender derives them from the DB). Nothing here sends or approves.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.context.persona import stamp_persona
from app.contracts import ActionType
from app.core.errors import AgentFailedError
from app.core.settings import Settings
from app.db.enums import ActionStatus
from app.db.models import ActionRevision, ActionRow, Approval
from app.llm.embeddings import build_embedder
from app.pipeline import approvals, dashboard_decisions, propose
from app.pipeline.approvals import NewRevision
from app.pipeline.rules import RuleDecision, Verdict
from app.pipeline.supersede import supersedable, supersede_draft

NO_DRAFT = "the drafting model did not return a reply"
NOT_LIVE = "the draft waiting for approval changed meanwhile"
NOTHING = "the message does not need a reply"
_HELD = (ActionStatus.paused, ActionStatus.exception)


Kind = Literal["new", "pending", "busy", "held", "decided", "no_reply"]
BUSY = "the reply draft is being edited or is not ready for approval yet; finish it in Approvals first"
HELD = "the message is held for your review (paused or flagged)"


@dataclass(frozen=True)
class MessageState:
    kind: Kind
    pending: UUID | None  # the live pending reply approval
    current: tuple[str, ...]  # the variants of the message's latest reply draft


@dataclass(frozen=True)
class Request:
    company_id: UUID
    message_id: UUID
    guidance: str | None
    prefix: str  # `agent:{turn_id}:`: any revision of this turn on the message counts as done
    key: str  # `agent:{turn_id}:{step}`
    now: datetime


@dataclass(frozen=True)
class Redraft:
    revision: NewRevision | None  # None: nothing was written
    variants: tuple[str, ...]
    source: str  # the conversation the drafts are checked against
    problem: str | None = None  # why nothing was written (a rules reason or a fixed text)
    superseded: UUID | None = None  # the pending approval this draft replaced


def _variants(payload: dict[str, Any] | None) -> tuple[str, ...]:
    return tuple(str(v) for v in (payload or {}).get("body_variants") or ())


def _live_reply(session: Session, company_id: UUID, replies: list[ActionRow], now: datetime) -> UUID | None:
    """A reply approval that may be superseded: pending, or an edit tap older than the edit window (stale)."""
    if not replies:
        return None
    return session.scalar(
        select(Approval.id)
        .join(ActionRow, ActionRow.id == Approval.action_id)
        .where(
            Approval.company_id == company_id,
            ActionRow.company_id == company_id,
            Approval.action_id.in_([a.id for a in replies]),
            supersedable(now),
            Approval.draft_version == ActionRow.draft_version,
            ActionRow.status == ActionStatus.pending_approval,
        )
        .order_by(Approval.created_at.desc(), Approval.id.desc())
        .limit(1)
    )


def classify(actions: Sequence[tuple[ActionType, ActionStatus]], live_pending: bool) -> Kind:
    """Pure. `new`: no proposal. `pending`: a reply draft has a supersedable approval (pending, or a stale edit tap).
    `busy`: a reply draft awaits approval without one (an edit tap inside its 24 h window, or not opened yet). `held`:
    something was paused or flagged. `decided`: every reply draft was decided (a fresh one is drafted). `no_reply`:
    only other actions (an escalation, the could-not-draft notice; pending or not): a first reply is drafted."""
    if not actions:
        return "new"
    if live_pending:
        return "pending"
    replies = [status for kind, status in actions if kind is ActionType.reply_draft]
    if ActionStatus.pending_approval in replies:
        return "busy"
    if any(status in _HELD for _, status in actions):
        return "held"
    return "decided" if replies else "no_reply"


def message_state(session: Session, company_id: UUID, message_id: UUID, now: datetime) -> MessageState:
    actions = list(
        session.scalars(
            select(ActionRow)
            .where(ActionRow.company_id == company_id, ActionRow.context_ref.contains([message_id]))
            .order_by(ActionRow.created_at.desc(), ActionRow.id.desc())
        )
    )
    replies = [a for a in actions if a.type is ActionType.reply_draft]
    current = _variants(replies[0].payload) if replies else ()
    pending = _live_reply(session, company_id, replies, now)
    kind = classify([(a.type, a.status) for a in actions], pending is not None)
    return MessageState(kind, pending, current)


def turn_replay(
    session: Session, company_id: UUID, prefix: str, message_id: UUID
) -> tuple[NewRevision, tuple[str, ...]] | None:
    """The revision (and its variants) this turn already wrote for the message, if any."""
    row = session.execute(
        select(ActionRevision.action_id, ActionRevision.draft_version, Approval.id, ActionRevision.payload)
        .join(ActionRow, (ActionRow.id == ActionRevision.action_id) & (ActionRow.company_id == company_id))
        .join(
            Approval,
            (Approval.action_id == ActionRevision.action_id)
            & (Approval.draft_version == ActionRevision.draft_version)
            & (Approval.company_id == company_id),
        )
        .where(
            ActionRevision.company_id == company_id,
            ActionRevision.edited_by.startswith(prefix, autoescape=True),
            ActionRow.context_ref.contains([message_id]),
        )
        .order_by(ActionRevision.draft_version.desc(), Approval.created_at.desc())
        .limit(1)
    ).first()
    return (NewRevision(row[0], row[1], row[2]), _variants(row[3])) if row else None


def _decide(
    engine: Engine, settings: Settings, req: Request, current: tuple[str, ...]
) -> tuple[propose.Loaded, RuleDecision] | Redraft:
    loaded = propose.load_message(engine, req.message_id, embedder=build_embedder(settings))
    if loaded is None:
        return Redraft(None, (), "", NOTHING)
    try:
        decision = propose.guided_reply(engine, settings, loaded.guided(req.guidance, current))
    except AgentFailedError:
        return Redraft(None, (), loaded.source, NO_DRAFT)
    if decision is None:
        return Redraft(None, (), loaded.source, NO_DRAFT)
    variants = _variants(decision.action.payload.model_dump(mode="json"))
    if decision.verdict is not Verdict.pending_approval:
        return Redraft(None, variants, loaded.source, decision.reason or "held for review")
    return loaded, decision


def _commitments(payload: dict[str, Any] | None) -> list[str]:
    return [str(c) for c in (payload or {}).get("commitments") or () if str(c).strip()]


def supersede(engine: Engine, settings: Settings, req: Request, approval_id: UUID, current: tuple[str, ...]) -> Redraft:
    decided = _decide(engine, settings, req, current)
    if isinstance(decided, Redraft):
        return decided
    loaded, decision = decided
    payload_dict = decision.action.payload.model_dump(mode="json")
    variants = _variants(payload_dict)
    commitments = _commitments(payload_dict)
    with Session(engine) as session, session.begin():
        return _supersede_in(session, req, loaded, approval_id, variants, commitments=commitments)


def _insert_reply(session: Session, req: Request, loaded: propose.Loaded, decision: RuleDecision) -> NewRevision:
    payload = decision.action.payload  # guided_reply only returns reply drafts
    row = ActionRow(
        company_id=req.company_id, case_id=loaded.ctx.case_id, type=ActionType.reply_draft,
        payload=payload.model_dump(mode="json"), rationale=decision.action.rationale, context_ref=[req.message_id],
        draft_version=1, status=ActionStatus.pending_approval,
    )  # fmt: skip
    stamp_persona(row, payload, loaded.ctx.persona)
    session.add(row)
    session.flush()
    propose.record_draft(session, req.company_id, row, req.key)
    urgency = loaded.ctx.understanding.urgency
    approval_id = approvals.open_approval(session, req.company_id, row.id, 1, urgency=urgency, now=req.now)
    return NewRevision(row.id, 1, approval_id)


def persist_decision(engine: Engine, req: Request, loaded: propose.Loaded, decision: RuleDecision) -> Redraft:
    """Persist an already-evaluated guided reply (supersede live pending approval, else insert a fresh reply)."""
    payload_dict = decision.action.payload.model_dump(mode="json")
    variants = _variants(payload_dict)
    commitments = _commitments(payload_dict)
    if decision.verdict is not Verdict.pending_approval:
        return Redraft(None, variants, loaded.source, decision.reason or "held for review")
    with Session(engine) as session, session.begin():
        propose.lock_message(session, req.message_id)
        if (done := turn_replay(session, req.company_id, req.prefix, req.message_id)) is not None:
            return Redraft(done[0], done[1], loaded.source)
        state = message_state(session, req.company_id, req.message_id, req.now)
        if state.kind == "pending" and state.pending is not None:
            return _supersede_in(session, req, loaded, state.pending, variants, commitments=commitments)
        if state.kind in ("busy", "held"):
            return Redraft(None, (), loaded.source, BUSY if state.kind == "busy" else HELD)
        revision = _insert_reply(session, req, loaded, decision)
    return Redraft(revision, variants, loaded.source)


def fresh(engine: Engine, settings: Settings, req: Request, current: tuple[str, ...]) -> Redraft:
    """A new reply for a message whose earlier reply was decided (or that has none), once per turn. Under the message
    lock the state is read again: a reply another turn just proposed is superseded by this draft, never doubled."""
    decided = _decide(engine, settings, req, current)
    if isinstance(decided, Redraft):
        return decided
    loaded, decision = decided
    return persist_decision(engine, req, loaded, decision)


def _supersede_in(
    session: Session,
    req: Request,
    loaded: propose.Loaded,
    approval_id: UUID,
    variants: tuple[str, ...],
    *,
    commitments: list[str] | None = None,
) -> Redraft:
    urgency = loaded.ctx.understanding.urgency
    revision = supersede_draft(
        session,
        req.company_id,
        approval_id,
        list(variants),
        editor=req.key,
        urgency=urgency,
        now=req.now,
        persona=loaded.ctx.persona,
        commitments=commitments,
    )
    if revision is None:
        return Redraft(None, (), loaded.source, NOT_LIVE)
    dashboard_decisions.resolve_feed(session, req.company_id, approval_id, at=req.now)
    return Redraft(revision, variants, loaded.source, superseded=approval_id)
