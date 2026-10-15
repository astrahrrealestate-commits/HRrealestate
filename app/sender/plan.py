"""What the sender is about to deliver, and to whom. Built from the DB only (invariant 6)."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.contracts import Channel, DraftRequest, EmailRequest


@dataclass(frozen=True)
class Plan:
    channel: Channel
    target: str  # owner E.164 for WhatsApp, tenant address for a Gmail draft/reply, owner email for digest
    whatsapp: dict[str, Any] | None = None
    draft: DraftRequest | None = None
    email: EmailRequest | None = None
    google_chat: dict[str, Any] | None = None
    mailbox: str | None = None
    tenant_send: bool = False  # a message that reaches the tenant (send mode); `assert_allowed` re-derives the target
    case_id: UUID | None = None  # the case whose contact a tenant plan goes to
