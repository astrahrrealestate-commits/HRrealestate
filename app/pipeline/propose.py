"""Propose stage (#4): proposer agent → rules engine → actions, approvals and owner tasks.

Replay-safe: actions carry `context_ref = [message_id]`, and a message that already has actions is not proposed
again. A failed proposer never drops the message: Harjot gets a "could not draft" notice to approve or dismiss.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import Action, ActionType, NotifyOwnerPayload, Understanding
from app.core.errors import AgentFailedError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import ActionStatus, ApprovalStatus, PersonKind, WaitStatus
from app.db.models import ActionRow, Approval, Case, Company, MessageRow, Person, UnderstandingRow, WaitRow
from app.llm.agents.proposer import PROPOSER, Contractor, ProposerContext, proposer_prompt
from app.llm.calls import CallContext, run_agent
from app.pipeline import approvals, case_repo
from app.pipeline.rules import RuleContext, Verdict, apply_rules

log = get_logger(__name__)
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
            Approval.action_id.in_([r.id for r in rows]), Approval.status == ApprovalStatus.pending
        )
    ).all()
    return ProposeResult(list(live), sum(r.status is ActionStatus.exception for r in rows))


def _load(session: Session, msg: MessageRow, case: Case, und: Understanding) -> _Loaded:
    company = session.get(Company, msg.company_id)
    waiting = session.scalars(
        select(WaitRow.about).where(WaitRow.case_id == case.id, WaitRow.status == WaitStatus.waiting)
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
    )
    return _Loaded(ctx, msg.company_id, bool(company and company.paused))


def _fallback(case_id: UUID) -> list[Action]:
    text = "EstateOS could not draft a reply for a new message on this case. Please look at it yourself."
    return [
        Action(
            type=ActionType.notify_owner,
            case_id=case_id,
            payload=NotifyOwnerPayload(kind="notify_owner", text=text),
            rationale="Proposer failed",
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


def _persist(
    session: Session, loaded: _Loaded, message_id: UUID, actions: list[Action], contractors: frozenset[UUID]
) -> ProposeResult:
    und = loaded.ctx.understanding
    rule_ctx = RuleContext(paused=loaded.paused, suspicious=und.suspicious.flag, contractor_ids=contractors)
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
            rationale=a.rationale,
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
    return result


def _prepare(engine: Engine, message_id: UUID) -> _Loaded | ProposeResult:
    with Session(engine) as session:
        msg = session.get(MessageRow, message_id)
        und = session.scalar(select(UnderstandingRow).where(UnderstandingRow.message_id == message_id))
        if msg is None or und is None:
            return ProposeResult()
        done = _existing(session, msg.company_id, message_id)
        if done is not None:
            return done
        case_id = case_repo.case_of_message(session, msg.company_id, message_id)
        if case_id is None:
            return ProposeResult()
        case = case_repo.get_case(session, msg.company_id, case_id)
        return _load(session, msg, case, Understanding.model_validate(und.body))


def propose_for_message(engine: Engine, settings: Settings, message_id: UUID) -> ProposeResult:
    loaded = _prepare(engine, message_id)
    if isinstance(loaded, ProposeResult):
        return loaded
    proposed = _propose(engine, settings, loaded)
    actions = [a.model_copy(update={"case_id": loaded.ctx.case_id, "draft_version": 1}) for a in proposed]
    contractors = frozenset(c.person_id for c in loaded.ctx.contractors)
    with Session(engine) as session, session.begin():
        done = _existing(session, loaded.company_id, message_id)  # a concurrent replay finished first
        if done is not None:
            return done
        return _persist(session, loaded, message_id, actions, contractors)
