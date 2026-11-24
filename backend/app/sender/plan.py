"""What the sender is about to deliver, and to whom. Built from the DB only (invariant 6)."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.contracts import Channel, DraftRequest, EmailRequest, OwnerMessage


@dataclass(frozen=True)
class Plan:
    channel: Channel
    target: str  # owner E.164 for WhatsApp, tenant address for a Gmail draft/reply, owner email for digest,
    # `owner:{owner_id}` for the owner's dashboard feed
    whatsapp: dict[str, Any] | None = None
    draft: DraftRequest | None = None
    email: EmailRequest | None = None
    google_chat: dict[str, Any] | None = None
    mailbox: str | None = None
    tenant_send: bool = False  # a message that reaches the tenant (send mode); `assert_allowed` re-derives the target
    case_id: UUID | None = None  # the case whose contact a tenant plan goes to
    owner_message: OwnerMessage | None = None  # dashboard plans: the feed row's message
    company_id: UUID | None = None  # dashboard plans: whose owner feed (re-checked by `assert_allowed`)
    chat_message_id: UUID | None = None  # owner-typed chat send: the stored outbound row (`assert_chat` re-derives all)
