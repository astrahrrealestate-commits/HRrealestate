"""Propose stage (#4): proposer agent → rules engine → actions, approvals and owner tasks.

Replay-safe: actions carry `context_ref = [message_id]`, and a message that already has actions is not proposed
again. A failed proposer never drops the message: Harjot gets a "could not draft" notice to approve or dismiss.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.contracts import Action, ActionType, Category, NotifyOwnerPayload, ReplyDraftPayload, Understanding
from app.core.errors import AgentFailedError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import ActionStatus, ApprovalStatus, PersonKind, WaitStatus
from app.db.models import ActionRow, Approval, Case, Company, MessageRow, Person, UnderstandingRow, WaitRow
from app.llm.agents.doc_qa import Passage
from app.llm.agents.proposer import PROPOSER, Contractor, ProposerContext, proposer_prompt
from app.llm.calls import CallContext, run_agent
from app.pipeline import approvals, case_repo
from app.pipeline.concierge_sanitize import sanitize
from app.pipeline.document_qa import case_scope, strip_risky
from app.pipeline.document_search import DocFilter, top_passages
from app.pipeline.rules import RuleContext, Verdict, apply_rules

log = get_logger(__name__)
FALLBACK_RATIONALE = "Proposer failed"  # the "could not draft" notice; callers tell it apart from a real draft
_STATUS = {
    Verdict.pending_approval: ActionStatus.pending_approval,
    Verdict.exception: ActionStatus.exception,
    Verdict.paused: ActionStatus.paused,
}


@dataclass
class ProposeResult:
    approval_ids: list[UUID] = field(default_factory=list)
    exceptions: int = 0


@dataclass(frozen=True)
class _Loaded:
    ctx: ProposerContext
    company_id: UUID
    paused: bool


def _existing(session: Session, company_id: UUID, message_id: UUID) -> ProposeResult | None:
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


MAX_EXCERPTS = 3


def _case_documents(session: Session, msg: MessageRow, case: Case) -> tuple[Passage, ...]:
    """Passages of THIS case's own documents (its case, unit, lease and main person) that resemble the message.
    Nothing from any other tenant's documents, nothing flagged suspicious, and no link, address or IBAN."""
    scope = case_scope(session, msg.company_id, case.id)
    if not scope:
        return ()
    found = top_passages(session, msg.company_id, msg.text, DocFilter(any_link=scope, readable_only=True), MAX_EXCERPTS)
    return tuple(replace(p, text=strip_risky(p.text)) for p in found)


def _load(session: Session, msg: MessageRow, case: Case, und: Understanding) -> _Loaded:
    company = session.get(Company, msg.company_id)
    waiting = session.scalars(
        select(WaitRow.about).where(
            WaitRow.company_id == msg.company_id, WaitRow.case_id == case.id, WaitRow.status == WaitStatus.waiting
        )
    ).all()
    contractors = session.execute(
        select(Person.id, Person.display_name, Person.trade).where(
            Person.company_id == msg.company_id, Person.kind == PersonKind.contractor, Person.valid_to.is_(None)
        )
    ).all()
    ctx = ProposerContext(
        case_id=case.id,
        channel=msg.channel,
        subject=msg.meta.get("subject"),
        message_text=msg.text,
        understanding=und,
        case_state=case.state.value,
        case_summary=case.summary,
        waiting=tuple(waiting),
        contractors=tuple(Contractor(c[0], c[1], c[2]) for c in contractors),
        mode="reply",
        excerpts=_case_documents(session, msg, case),
    )
    return _Loaded(ctx, msg.company_id, bool(company and company.paused))


def _fallback(case_id: UUID) -> list[Action]:
    text = "EstateOS could not draft a reply for a new message on this case. Please look at it yourself."
    return [
        Action(
            type=ActionType.notify_owner,
            case_id=case_id,
            payload=NotifyOwnerPayload(kind="notify_owner", text=text),
            rationale=FALLBACK_RATIONALE,
            context_ref=[],
            draft_version=1,
        )
    ]


def _propose(engine: Engine, settings: Settings, loaded: _Loaded) -> list[Action]:
    try:
        result = run_agent(
            engine, settings, PROPOSER, proposer_prompt(loaded.ctx), CallContext(loaded.company_id, "proposer")
        )
    except AgentFailedError:
        log.warning("pipeline.proposer_failed", case_id=str(loaded.ctx.case_id))
        return _fallback(loaded.ctx.case_id)
    return list(result.output.actions)


def _with_sources(action: Action, excerpts: Sequence[Passage]) -> str:
    """A reply drafted with documents in view says which ones, so Harjot can check the clause on the card."""
    if action.type is not ActionType.reply_draft or not excerpts:
        return action.rationale
    titles = ", ".join(sanitize(p.title)[:60] for p in excerpts)
    return f"{action.rationale} (documents in view: {titles})"


def _persist(
    session: Session, loaded: _Loaded, message_id: UUID, actions: list[Action], contractors: frozenset[UUID]
) -> ProposeResult:
    und = loaded.ctx.understanding
    c = loaded.ctx
    source = "\n".join([c.subject or "", c.message_text, c.case_summary, *c.waiting])
    rule_ctx = RuleContext(
        paused=loaded.paused, suspicious=und.suspicious.flag, contractor_ids=contractors, source_text=source
    )
    result = ProposeResult()
    for decision in apply_rules(actions, rule_ctx):
        if decision.verdict is Verdict.drop:
            continue
        a = decision.action
        row = ActionRow(
            company_id=loaded.company_id,
            case_id=loaded.ctx.case_id,
            type=a.type,
            payload=a.payload.model_dump(mode="json"),
            rationale=_with_sources(a, loaded.ctx.excerpts),
            context_ref=[message_id],
            draft_version=1,
            status=_STATUS[decision.verdict],
        )
        session.add(row)
        session.flush()
        if decision.verdict is Verdict.pending_approval:
            now = datetime.now(UTC)
            result.approval_ids.append(
                approvals.open_approval(session, loaded.company_id, row.id, 1, urgency=und.urgency, now=now)
            )
        elif decision.verdict is Verdict.exception:
            result.exceptions += 1
            log.info("pipeline.rules.exception", reason=decision.reason, action_type=a.type.value)
    return result


def _trusted(action: Action, loaded: _Loaded) -> Action:
    """Code owns the case, the version and the reply channel; the model only proposes content."""
    update: dict[str, object] = {"case_id": loaded.ctx.case_id, "draft_version": 1}
    if isinstance(action.payload, ReplyDraftPayload):
        update["payload"] = action.payload.model_copy(update={"channel": loaded.ctx.channel})
    return action.model_copy(update=update)


def _with_reply_flag(body: dict[str, Any]) -> dict[str, Any]:
    """Understandings stored before `requires_reply` existed: spam never needed an answer, anything else did."""
    if "requires_reply" in body:
        return body
    return {**body, "requires_reply": body.get("category") != Category.spam.value}


def _prepare(engine: Engine, message_id: UUID) -> _Loaded | ProposeResult:
    with Session(engine) as session:
        msg = session.get(MessageRow, message_id)
        und = (
            session.scalar(
                select(UnderstandingRow).where(
                    UnderstandingRow.company_id == msg.company_id, UnderstandingRow.message_id == message_id
                )
            )
            if msg
            else None
        )
        if msg is None or und is None:
            return ProposeResult()
        done = _existing(session, msg.company_id, message_id)
        if done is not None:
            return done
        case_id = case_repo.case_of_message(session, msg.company_id, message_id)
        if case_id is None:
            return ProposeResult()
        case = case_repo.get_case(session, msg.company_id, case_id)
        understanding = Understanding.model_validate(_with_reply_flag(und.body))
        if not understanding.requires_reply and not understanding.suspicious.flag:
            return ProposeResult()  # nothing to answer: no proposal, no draft, no model call (suspicious mail stays)
        return _load(session, msg, case, understanding)


def propose_for_message(engine: Engine, settings: Settings, message_id: UUID) -> ProposeResult:
    loaded = _prepare(engine, message_id)
    if isinstance(loaded, ProposeResult):
        return loaded
    proposed = _propose(engine, settings, loaded)
    actions = [_trusted(a, loaded) for a in proposed]
    contractors = frozenset(c.person_id for c in loaded.ctx.contractors)
    with Session(engine) as session, session.begin():
        session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"propose:{message_id}"})
        done = _existing(session, loaded.company_id, message_id)  # a concurrent run (pipe:/requeue) finished first
        if done is not None:
            return done
        return _persist(session, loaded, message_id, actions, contractors)
