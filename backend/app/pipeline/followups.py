"""Follow-up and chasing (#5): waits opened after approved requests, chasers when they fall due, then escalation.

Timer-driven and replay-safe: a `wait.due` timer carries the chase step it was scheduled for, and acts only while the
wait is still on that step, so a reclaimed (re-fired) timer never chases twice.
"""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.context.persona import load_persona, stamp_persona
from app.contracts import (
    Action,
    ActionType,
    CaseState,
    Channel,
    Direction,
    Entities,
    EscalatePayload,
    RequestContractorPayload,
    Suspicious,
    Understanding,
)
from app.core.errors import AgentFailedError, NotFoundError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import ActionStatus, ApprovalStatus, PersonKind, WaitStatus
from app.db.models import ActionRow, Approval, Case, CaseLink, Company, MessageRow, Person, WaitRow
from app.llm.agents.proposer import Persona, ProposerContext, proposer_prompt, proposer_spec
from app.llm.calls import CallContext, run_agent
from app.pipeline import approvals, case_repo, work_repo
from app.pipeline.chasing import ChasePolicy, ChaseStep, add_business_days, next_step

log = get_logger(__name__)
CONTRACTOR_CHASE = (
    "Beste {name},\n\nMag ik u herinneren aan ons verzoek? Kunt u laten weten wanneer u langs kunt komen?\n\n"
    "Met vriendelijke groet,\nHarjot",
    "Beste {name},\n\nWij hebben nog geen reactie ontvangen op ons verzoek. Graag hoor ik vandaag van u.\n\n"
    "Met vriendelijke groet,\nHarjot",
)
TENANT_CHASE = (
    "Geachte heer/mevrouw,\n\nGraag herinneren wij u aan ons eerdere bericht: {about}. Kunt u reageren?\n\n"
    "Met vriendelijke groet,\nHarjot",
    "Beste,\n\nWij wachten nog op uw reactie ({about}). Laat u het ons weten?\n\nMet vriendelijke groet,\nHarjot",
)


def _company(session: Session, company_id: UUID) -> Company:
    company = session.get(Company, company_id)
    if company is None:
        raise NotFoundError(f"company {company_id} not found")
    return company


def _policy(company: Company) -> ChasePolicy:
    return ChasePolicy(company.chase_after_days, company.escalate_after_chases)


def open_waits_after_execute(engine: Engine, action_id: UUID, *, now: datetime) -> UUID | None:
    """A contractor request always waits for the contractor; a reply waits for the tenant only when the case is
    waiting on a third party. `expected_by` = `chase_after_days` business days later (company timezone)."""
    with Session(engine) as session, session.begin():
        action = session.get(ActionRow, action_id)
        if action is None or action.status is not ActionStatus.executed:
            return None
        case = case_repo.get_case(session, action.company_id, action.case_id)
        company = _company(session, action.company_id)
        party: UUID | None
        if action.type is ActionType.request_contractor:
            party, about = UUID(action.payload["contractor_person_id"]), "Contractor to respond to our request"
        elif action.type is ActionType.reply_draft and case.state is CaseState.waiting_on_third_party:
            party, about = case.primary_person_id, "Tenant to answer our reply"
        else:
            return None
        due = add_business_days(now, company.chase_after_days, company.timezone)
        return work_repo.open_wait(
            session, action.company_id, case.id, party, about=about, expected_by=due, source_action_id=action.id
        )


def _latest_inbound(session: Session, case: Case) -> MessageRow | None:
    return session.scalar(
        select(MessageRow)
        .join(CaseLink, CaseLink.message_id == MessageRow.id)
        .where(
            CaseLink.company_id == case.company_id,
            CaseLink.case_id == case.id,
            MessageRow.direction == Direction.inbound,
        )
        .order_by(MessageRow.sent_at.desc())
        .limit(1)
    )


def _tenant_chaser(
    engine: Engine, settings: Settings, case: Case, wait: WaitRow, msg: MessageRow | None
) -> tuple[Action, Persona | None]:
    """The chaser and the persona it was written in (None for the template fallback, which uses no persona)."""
    channel = msg.channel if msg else Channel.whatsapp
    und = Understanding(
        category=case.category,
        intent=wait.about[:200],
        urgency=case.urgency,
        requires_reply=True,
        entities=Entities.none(),
        suspicious=Suspicious(flag=False, reason=None),
        confidence=1.0,
        sender_role=None,
        needs_research=False,
        research_questions=[],
        prompt_version="understanding/v2",
    )
    persona = load_persona(engine, case.company_id)
    ctx = ProposerContext(
        case_id=case.id,
        channel=channel,
        subject=msg.meta.get("subject") if msg else None,
        message_text=msg.text if msg else "",
        understanding=und,
        case_state=case.state.value,
        case_summary=case.summary,
        waiting=(wait.about,),
        contractors=(),
        mode="chase",
        persona=persona,
    )
    try:
        call = CallContext(case.company_id, "chaser")
        out = run_agent(engine, settings, proposer_spec(ctx), proposer_prompt(ctx), call)
        reply = next(a for a in out.output.actions if a.type is ActionType.reply_draft)
        payload = reply.payload.model_copy(
            update={"channel": channel}
        )  # the channel comes from the case, not the model
        return reply.model_copy(update={"case_id": case.id, "draft_version": 1, "payload": payload}), persona
    except (AgentFailedError, StopIteration):
        log.warning("followups.chaser_fallback", wait_id=str(wait.id))
        variants = [v.format(about=wait.about) for v in TENANT_CHASE]
        subject = (
            f"Re: {msg.meta.get('subject')}" if msg and channel is Channel.gmail and msg.meta.get("subject") else None
        )
        fallback = Action.model_validate(
            {
                "type": "reply_draft",
                "case_id": case.id,
                "rationale": "Chaser (template)",
                "payload": {
                    "kind": "reply_draft",
                    "channel": channel.value,
                    "subject": subject,
                    "body_variants": variants,
                },
                "context_ref": [],
                "draft_version": 1,
            }
        )
        return fallback, None


def _contractor_chaser(session: Session, case: Case, wait: WaitRow) -> Action:
    name = (
        session.scalar(
            select(Person.display_name).where(Person.company_id == case.company_id, Person.id == wait.party_person_id)
        )
        or "vakman"
    )
    payload = RequestContractorPayload(
        kind="request_contractor",
        contractor_person_id=wait.party_person_id,  # type: ignore[arg-type]
        body_variants=[v.format(name=name) for v in CONTRACTOR_CHASE],
    )
    return Action(
        type=ActionType.request_contractor,
        case_id=case.id,
        payload=payload,
        rationale="Contractor chaser (template)",
        context_ref=[],
        draft_version=1,
    )


def _escalation(case: Case, wait: WaitRow, who: str) -> Action:
    reason = f"No answer from {who} after {wait.chase_count} reminders: {wait.about}"
    return Action(
        type=ActionType.escalate,
        case_id=case.id,
        payload=EscalatePayload(kind="escalate", reason=reason),
        rationale="Chase ladder exhausted",
        context_ref=[],
        draft_version=1,
    )


def _store(
    session: Session, company: Company, case: Case, action: Action, now: datetime, persona: Persona | None = None
) -> UUID | None:
    status = ActionStatus.paused if company.paused else ActionStatus.pending_approval
    row = ActionRow(
        company_id=company.id,
        case_id=case.id,
        type=action.type,
        payload=action.payload.model_dump(mode="json"),
        rationale=action.rationale,
        context_ref=[],
        draft_version=1,
        status=status,
    )
    stamp_persona(row, action.payload, persona)
    session.add(row)
    session.flush()
    if company.paused:
        return None
    return approvals.open_approval(session, company.id, row.id, 1, urgency=case.urgency, now=now)


def _load(session: Session, company_id: UUID, wait_id: UUID) -> tuple[WaitRow, Case, Company, str] | None:
    wait = session.scalar(
        select(WaitRow).where(WaitRow.company_id == company_id, WaitRow.id == wait_id).with_for_update()
    )
    if wait is None:
        return None
    case = case_repo.get_case(session, wait.company_id, wait.case_id)
    company = _company(session, wait.company_id)
    party = session.execute(
        select(Person.display_name, Person.kind).where(
            Person.company_id == wait.company_id, Person.id == wait.party_person_id
        )
    ).first()
    who = f"{party[0]} ({party[1].value})" if party else "the other party"
    return wait, case, company, who


def _already_handled(wait: WaitRow, step: int) -> bool:
    chased = wait.chase_count == step + 1
    escalated = wait.status is WaitStatus.escalated and wait.chase_count == step
    return chased or escalated


def pending_step_approval(session: Session, wait: WaitRow) -> UUID | None:
    since = wait.last_chased_at or wait.created_at
    return session.scalar(
        select(Approval.id)
        .join(ActionRow, ActionRow.id == Approval.action_id)
        .where(
            ActionRow.company_id == wait.company_id,
            ActionRow.case_id == wait.case_id,
            ActionRow.type.in_([ActionType.reply_draft, ActionType.request_contractor, ActionType.escalate]),
            ActionRow.created_at >= since - timedelta(seconds=5),
            Approval.status == ApprovalStatus.pending,
        )
        .order_by(Approval.created_at.desc())
        .limit(1)
    )


def handle_wait_due(
    engine: Engine,
    settings: Settings,
    company_id: UUID,
    wait_id: UUID,
    *,
    step: int,
    now: datetime,
    force: bool = False,
) -> UUID | None:
    """Returns the approval to show Harjot (chaser or escalation), or None when nothing is due.

    `force` (the owner asked to chase now) treats a wait that is not yet due as due; the ladder is unchanged."""
    with Session(engine) as session:
        loaded = _load(session, company_id, wait_id)
        if loaded is None:
            return None
        if _already_handled(loaded[0], step):  # a re-fired timer: hand back the card it created, if still open
            return pending_step_approval(session, loaded[0])
        if loaded[0].chase_count != step:
            return None
        wait, case, company, who = loaded
        decide_at = max(now, wait.expected_by) if force else now
        decision = next_step(wait.status, wait.chase_count, wait.expected_by, _policy(company), decide_at)
        contractor = (
            session.scalar(
                select(Person.kind).where(Person.company_id == wait.company_id, Person.id == wait.party_person_id)
            )
            is PersonKind.contractor
        )
        msg = _latest_inbound(session, case)
    if decision is ChaseStep.none:
        return None
    if decision is ChaseStep.chase:
        with Session(engine) as session:
            action, persona = (
                (_contractor_chaser(session, case, wait), None)
                if contractor
                else _tenant_chaser(engine, settings, case, wait, msg)
            )
    else:
        action, persona = _escalation(case, wait, who), None
    with Session(engine) as session, session.begin():
        current = session.scalar(
            select(WaitRow).where(WaitRow.company_id == company_id, WaitRow.id == wait_id).with_for_update()
        )
        if current is None or current.chase_count != step or current.status is not wait.status:
            return None  # a concurrent run already handled this step
        approval_id = _store(session, company, case, action, now, persona)
        if decision is ChaseStep.chase:
            next_due = add_business_days(now, company.chase_after_days, company.timezone)
            work_repo.record_chase(session, company.id, wait_id, at=now, next_due=next_due)
        else:
            work_repo.escalate_wait(session, company.id, wait_id)
        return approval_id
