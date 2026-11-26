"""Propose stage (#4): proposer agent → draft quality → rules engine → actions, approvals and owner tasks.

Replay-safe: actions carry `context_ref = [message_id]`, and a message that already has actions is not proposed
again. A failed proposer never drops the message: Harjot gets a "could not draft" notice to approve or dismiss.
Since M13 every proposal and owner redraft reads the message's dossier (`proposer/v7`). A reply that only
acknowledges or promises to come back is redrafted once with feedback; if it still is, no reply is offered and the
card says to draft with Astra. An owner-requested draft passes the owner's sanitised guidance and a key; its reply
then also gets an ActionRevision under that key, so the turn's retry finds it. The redraft module reuses
`load_message`, `guided_reply` and `rule_context` for messages that already had a proposal.
"""

from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.context.message_origin import is_owner_authored
from app.contracts import Action, ActionType, NotifyOwnerPayload, ReplyDraftPayload, Understanding
from app.core.errors import AgentFailedError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models import MessageRow, UnderstandingRow
from app.llm.agents.proposer import proposer_prompt, proposer_spec
from app.llm.calls import CallContext, run_agent
from app.llm.embeddings import TextEmbedder, build_embedder
from app.pipeline import case_repo
from app.pipeline.draft_quality import usable_variants
from app.pipeline.propose_load import Loaded, load, with_defaults
from app.pipeline.propose_persist import ProposeResult, existing, lock_message, persist, record_draft
from app.pipeline.rules import RuleContext, RuleDecision, apply_rules

__all__ = [
    "FALLBACK_RATIONALE", "NO_USABLE_DRAFT", "Loaded", "ProposeResult", "guided_reply", "load_message",
    "lock_message", "propose_for_message", "record_draft", "rule_context", "with_defaults",
]  # fmt: skip

log = get_logger(__name__)
FALLBACK_RATIONALE = "Proposer failed"  # the "could not draft" notice; callers tell it apart from a real draft
NO_USABLE_DRAFT = "No usable draft: the drafts for this message only acknowledged it. Draft the reply with Astra."
QUALITY_FEEDBACK = (
    "Every variant only thanked the sender, confirmed receipt or promised to come back. Answer the message on "
    "substance from the data, or ask the specific questions whose answers you need."
)


def _notice(case_id: UUID, text: str, why: str) -> Action:
    return Action(
        type=ActionType.notify_owner, case_id=case_id, payload=NotifyOwnerPayload(kind="notify_owner", text=text),
        rationale=why, context_ref=[], draft_version=1,
    )  # fmt: skip


def _fallback(case_id: UUID) -> list[Action]:
    text = "EstateOS could not draft a reply for a new message on this case. Please look at it yourself."
    return [_notice(case_id, text, FALLBACK_RATIONALE)]


def _run_proposer(engine: Engine, settings: Settings, loaded: Loaded) -> list[Action]:
    spec = proposer_spec(loaded.ctx)
    ctx = CallContext(loaded.company_id, "proposer", message_ids=loaded.message_ids)
    result = run_agent(engine, settings, spec, proposer_prompt(loaded.ctx), ctx)
    return [_trusted(a, loaded) for a in result.output.actions]


def _keep_usable(actions: list[Action]) -> list[Action] | None:
    """Generic variants dropped; None when a reply is left with fewer than two (it must be redrafted)."""
    out: list[Action] = []
    for a in actions:
        if isinstance(a.payload, ReplyDraftPayload):
            good = usable_variants(a.payload.body_variants)
            if len(good) < 2:
                return None
            a = a.model_copy(update={"payload": a.payload.model_copy(update={"body_variants": good})})
        out.append(a)
    return out


def _drafted(engine: Engine, settings: Settings, loaded: Loaded) -> list[Action]:
    """The proposal, held to the drafting standard: one retry with feedback, then no reply at all."""
    actions = _run_proposer(engine, settings, loaded)
    if loaded.ctx.mode != "reply":
        return actions
    if (kept := _keep_usable(actions)) is not None:
        return kept
    retry = _run_proposer(engine, settings, loaded.retry(QUALITY_FEEDBACK))
    if (kept := _keep_usable(retry)) is not None:
        return kept
    log.info("pipeline.proposer_generic", case_id=str(loaded.ctx.case_id))
    others = [a for a in retry if a.type is not ActionType.reply_draft]
    if not any(a.type is ActionType.escalate for a in others):  # an emergency never loses its escalation
        others += [a for a in actions if a.type is ActionType.escalate][:1]
    return [*others, _notice(loaded.ctx.case_id, NO_USABLE_DRAFT, "Draft rejected as generic")][:4]


def _propose(engine: Engine, settings: Settings, loaded: Loaded) -> list[Action]:
    try:
        return _drafted(engine, settings, loaded)
    except AgentFailedError:
        log.warning("pipeline.proposer_failed", case_id=str(loaded.ctx.case_id))
        return _fallback(loaded.ctx.case_id)


def rule_context(loaded: Loaded) -> RuleContext:
    contractors = frozenset(c.person_id for c in loaded.ctx.contractors)
    suspicious = loaded.ctx.understanding.suspicious.flag
    return RuleContext(
        paused=loaded.paused, suspicious=suspicious, contractor_ids=contractors, source_text=loaded.source
    )


def guided_reply(engine: Engine, settings: Settings, loaded: Loaded) -> RuleDecision | None:
    """The proposer's first reply draft for an owner-requested redraft, with the rules' verdict (paused, suspicious,
    unverified link/account/phone); None when it proposed no usable reply. AgentFailedError propagates (no notice)."""
    replies = [a for a in _drafted(engine, settings, loaded) if isinstance(a.payload, ReplyDraftPayload)]
    return apply_rules(replies[:1], rule_context(loaded))[0] if replies else None


def _trusted(action: Action, loaded: Loaded) -> Action:
    """Code owns the case, the version and the reply channel; the model only proposes content."""
    update: dict[str, object] = {"case_id": loaded.ctx.case_id, "draft_version": 1}
    if isinstance(action.payload, ReplyDraftPayload):
        update["payload"] = action.payload.model_copy(update={"channel": loaded.ctx.channel})
    return action.model_copy(update=update)


def _prepare(
    engine: Engine, message_id: UUID, *, replay: bool = True, embedder: TextEmbedder | None = None
) -> Loaded | ProposeResult:
    """The proposer context of a message; with `replay`, a message that already has actions returns those instead."""
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
        if msg is None or und is None or is_owner_authored(msg):
            return ProposeResult()  # nothing understood, or Harjot's own mail: there is nobody to write to
        done = existing(session, msg.company_id, message_id) if replay else None
        if done is not None:
            return done
        case_id = case_repo.case_of_message(session, msg.company_id, message_id)
        if case_id is None:
            return ProposeResult()
        case = case_repo.get_case(session, msg.company_id, case_id)
        understanding = Understanding.model_validate(with_defaults(und.body))
        if not understanding.requires_reply and not understanding.suspicious.flag:
            return ProposeResult()  # nothing to answer: no proposal, no draft, no model call (suspicious mail stays)
        return load(session, msg, case, understanding, embedder)


def load_message(engine: Engine, message_id: UUID, embedder: TextEmbedder | None = None) -> Loaded | None:
    """The proposer context even when the message was proposed before (owner-requested redraft); None when there is
    nothing to answer (no understanding, no case, no reply needed, or Harjot's own mail)."""
    loaded = _prepare(engine, message_id, replay=False, embedder=embedder)
    return loaded if isinstance(loaded, Loaded) else None


def propose_for_message(
    engine: Engine, settings: Settings, message_id: UUID, *, guidance: str | None = None, key: str | None = None
) -> ProposeResult:
    """`guidance`/`key` only for an owner-requested first draft (see the module docstring)."""
    loaded = _prepare(engine, message_id, embedder=build_embedder(settings))
    if isinstance(loaded, ProposeResult):
        return loaded
    loaded = loaded.guided(guidance) if guidance else loaded
    actions = _propose(engine, settings, loaded)
    with Session(engine) as session, session.begin():
        lock_message(session, message_id)
        done = existing(session, loaded.company_id, message_id)  # a concurrent run (pipe:/requeue) finished first
        if done is not None:
            return done
        return persist(session, loaded, message_id, actions, key, rule_context(loaded))
