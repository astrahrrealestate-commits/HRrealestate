"""Where an approved action goes. Recipients come from the DB only (invariant 6), never from model output.

Allowlist: a Gmail *draft* in the tenant's thread, or a message to one of the company's owner addresses (or the
owner's own dashboard feed). In `outbound_mode=send` an approved reply also reaches the tenant (`tenant_plans`),
re-checked by `assert_tenant`. In draft mode a tenant-facing WhatsApp reply is delivered to the owner as copy-ready
text. Owner-directed text goes where the owner reads: the dashboard feed when his `interactive_channel` is
`dashboard`, otherwise WhatsApp (unchanged for WhatsApp and Google Chat owners).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.whatsapp import payloads
from app.contracts import ActionType, Channel, Direction, InteractiveChannel, OwnerMessage
from app.db.models import ActionRow, ChannelAccount, ChannelIdentity, MessageRow, OwnerAccount, Person
from app.sender.errors import SendBlockedError as SendBlockedError
from app.sender.gmail_reply import gmail_draft as _gmail_draft
from app.sender.plan import Plan as Plan
from app.sender.recipient import latest_inbound
from app.sender.tenant_plans import assert_tenant, tenant_plan

__all__ = ["Plan", "SendBlockedError", "_gmail_draft", "assert_allowed", "owner_feed_target", "plan_for"]


def owner_feed_target(owner_id: UUID) -> str:
    """The `sends.target` of a delivery to an owner's dashboard feed."""
    return f"owner:{owner_id}"


def owner_number(session: Session, company_id: UUID) -> str:
    number = session.scalar(
        select(OwnerAccount.whatsapp_e164)
        .where(OwnerAccount.company_id == company_id)
        .order_by(OwnerAccount.created_at)
    )
    if number is None:
        raise SendBlockedError("company has no owner WhatsApp number")
    return number


def owner_chat_space(session: Session, company_id: UUID) -> str:
    space = session.scalar(
        select(ChannelAccount.address)
        .where(ChannelAccount.company_id == company_id, ChannelAccount.channel == Channel.google_chat)
        .order_by(ChannelAccount.created_at)
    )
    if space:
        return space
    latest = session.scalar(
        select(MessageRow.thread_ref)
        .where(
            MessageRow.company_id == company_id,
            MessageRow.channel == Channel.google_chat,
            MessageRow.direction == Direction.inbound,
        )
        .order_by(MessageRow.sent_at.desc())
        .limit(1)
    )
    if latest:
        return latest
    raise SendBlockedError("company has no Google Chat space configured")


def _owner_text(session: Session, company_id: UUID, body: str) -> Plan:
    owner = session.scalar(
        select(OwnerAccount).where(OwnerAccount.company_id == company_id).order_by(OwnerAccount.created_at)
    )  # the same owner `send_to_owner` addresses
    if owner is not None and owner.interactive_channel is InteractiveChannel.dashboard:
        target = owner_feed_target(owner.id)
        return Plan(Channel.dashboard, target, owner_message=OwnerMessage(text=body), company_id=company_id)
    to = owner_number(session, company_id)
    return Plan(Channel.whatsapp, to, whatsapp=payloads.text(to, body[: payloads.TEXT_BODY_MAX]))


def _contact(session: Session, company_id: UUID, person_id: UUID) -> str:
    name = session.scalar(select(Person.display_name).where(Person.id == person_id, Person.company_id == company_id))
    idents = session.scalars(
        select(ChannelIdentity.identity).where(
            ChannelIdentity.company_id == company_id,
            ChannelIdentity.person_id == person_id,
            ChannelIdentity.valid_to.is_(None),
        )
    ).all()
    if name is None:
        raise SendBlockedError("contractor is not a person of this company")
    return f"{name} ({', '.join(idents) or 'no contact on file'})"


def _counterpart(session: Session, action: ActionRow) -> str:
    msg = latest_inbound(session, action.company_id, action.case_id, Channel.whatsapp)
    return msg.sender_identity if msg else "the tenant"


def _reply_plan(session: Session, action: ActionRow, body: str, key: str, send_mode: bool, now: datetime) -> Plan:
    if send_mode:
        return tenant_plan(session, action, body, key, now)
    if action.payload.get("channel") == Channel.gmail.value:
        return _gmail_draft(session, action, body, key)
    who = _counterpart(session, action)
    return _owner_text(session, action.company_id, f"Approved reply for {who}. Copy and send:\n\n{body}")


def plan_for(session: Session, action: ActionRow, variant: int, key: str, *, send_mode: bool, now: datetime) -> Plan:
    """The delivery for an approved action. The sent text is the approved variant's body only.

    `send_mode` (the company's `outbound_mode` is `send`) only changes `reply_draft`: it reaches the tenant (Gmail
    reply in the thread with the thread's own subject, or WhatsApp text inside the window, never trimmed); any
    other payload channel is blocked. Contractor requests, escalations and owner notes stay
    copy-ready text to the owner in every mode (his dashboard feed when that is his channel, else WhatsApp):
    sending to contractors is out of scope for v1.
    """
    payload = action.payload
    variants: list[str] = payload.get("body_variants") or []
    body = variants[min(variant, len(variants) - 1)] if variants else ""
    if action.type is ActionType.reply_draft:
        return _reply_plan(session, action, body, key, send_mode, now)
    if action.type is ActionType.request_contractor:
        who = _contact(session, action.company_id, UUID(payload["contractor_person_id"]))
        return _owner_text(session, action.company_id, f"Approved request for {who}. Copy and send:\n\n{body}")
    if action.type is ActionType.notify_owner:
        return _owner_text(session, action.company_id, str(payload["text"]))
    if action.type is ActionType.escalate:
        return _owner_text(session, action.company_id, f"Escalation: {payload['reason']}")
    raise SendBlockedError(f"{action.type.value} actions are not delivered by the sender")


def assert_allowed(session: Session, company_id: UUID, plan: Plan) -> None:
    """Re-checked right before every claim. A tenant plan passes only through `assert_tenant` (send mode re-read and
    recipient re-derived now); everything else must be a Gmail draft or go to the owner."""
    if plan.tenant_send:
        assert_tenant(session, company_id, plan)
        return
    if plan.channel is Channel.dashboard:
        _assert_own_feed(session, company_id, plan)
        return
    if plan.channel is Channel.gmail and plan.draft is not None and plan.whatsapp is None and plan.email is None:
        return  # a draft: Harjot sends it himself from Gmail
    owner_emails = set(
        session.scalars(
            select(OwnerAccount.email).where(
                OwnerAccount.company_id == company_id,
                OwnerAccount.email.is_not(None),
            )
        )
    )
    if plan.channel is Channel.gmail and plan.email is not None and plan.target in owner_emails:
        return  # sending email is allowed strictly to the owner's email address (morning digest)
    owners = set(session.scalars(select(OwnerAccount.whatsapp_e164).where(OwnerAccount.company_id == company_id)))
    payload_to = "+" + str((plan.whatsapp or {}).get("to", "")).removeprefix("+")
    if plan.channel is Channel.whatsapp and plan.target in owners and payload_to == plan.target and plan.draft is None:
        return  # the recipient actually in the payload is checked too, not only the planned target
    if plan.channel is Channel.google_chat and plan.google_chat is not None:
        owner_spaces = set(
            session.scalars(
                select(ChannelAccount.address).where(
                    ChannelAccount.company_id == company_id,
                    ChannelAccount.channel == Channel.google_chat,
                )
            )
        )
        if plan.target in owner_spaces or plan.target.startswith("spaces/") or plan.target.startswith("https://"):
            return
    raise SendBlockedError("Phase 1 allowlist: only Gmail drafts and messages to the owner")


def _assert_own_feed(session: Session, company_id: UUID, plan: Plan) -> None:
    """A dashboard plan carries only a feed message, for this company, to one of its dashboard owners."""
    owners = session.scalars(
        select(OwnerAccount.id).where(
            OwnerAccount.company_id == company_id,
            OwnerAccount.interactive_channel == InteractiveChannel.dashboard,
        )
    )
    only_feed = plan.owner_message is not None and plan.whatsapp is None and plan.draft is None
    only_feed = only_feed and plan.email is None and plan.google_chat is None
    if only_feed and plan.company_id == company_id and plan.target in {owner_feed_target(o) for o in owners}:
        return
    raise SendBlockedError("Phase 1 allowlist: a dashboard delivery goes only to this company's owner feed")
