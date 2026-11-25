"""Who wrote a thread, for the inbox labels. Decided from the directory (the DB), never from message text.

The label comes after the intent: it is only a display hint and never picks a recipient, a person kind or a lease.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Category, SenderRole
from app.db.enums import PersonKind
from app.db.models import LeaseParty, Person

UNASSIGNED_UNIT = "Unassigned Unit"
_FREE_MAIL = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "hotmail.com",
        "hotmail.nl",
        "outlook.com",
        "live.nl",
        "yahoo.com",
        "icloud.com",
        "ziggo.nl",
        "kpnmail.nl",
        "planet.nl",
        "proton.me",
        "protonmail.com",
    }
)


class SenderKind(StrEnum):
    tenant = "tenant"
    contractor = "contractor"
    legal = "legal"
    vve = "vve"
    business = "business"
    prospect = "prospect"
    contact = "contact"  # anyone the directory and the model cannot place


@dataclass(frozen=True)
class SenderLabel:
    kind: SenderKind
    role_detail: str  # e.g. "Tenant", "Contractor · Electrician", "Legal", "Contact"
    audience: str  # the inbox filter value: tenants, contractors, inquiries or others
    recipient_role: str  # the frontend's RecipientRole: tenant, contractor, inquiry or contact

    @property
    def may_be_tenant(self) -> bool:
        """Only a tenant or an unplaced contact can be a leaseholder writing from an unregistered address."""
        return self.kind in (SenderKind.tenant, SenderKind.contact)


_TENANT = SenderLabel(SenderKind.tenant, "Tenant", "tenants", "tenant")
_CONTACT = SenderLabel(SenderKind.contact, "Contact", "others", "contact")
_TRADE_LABELS = {
    "legal": SenderLabel(SenderKind.legal, "Legal", "others", "contact"),
    "vve": SenderLabel(SenderKind.vve, "VvE", "others", "contact"),
    "business": SenderLabel(SenderKind.business, "Business", "others", "contact"),
    "utility": SenderLabel(SenderKind.business, "Utility", "others", "contact"),
    "municipal": SenderLabel(SenderKind.business, "Municipality", "others", "contact"),
}
_FROM_MODEL = {
    SenderRole.legal: SenderLabel(SenderKind.legal, "Legal", "others", "contact"),
    SenderRole.vve: SenderLabel(SenderKind.vve, "VvE", "others", "contact"),
    SenderRole.business: SenderLabel(SenderKind.business, "Business", "others", "contact"),
    SenderRole.prospect: SenderLabel(SenderKind.prospect, "Prospect", "inquiries", "inquiry"),
}


def resolve_sender_label(
    *,
    person_kind: PersonKind | None,
    trade: str | None,
    is_lease_party: bool,
    contractor_hint: bool,
    role_hint: SenderRole | None = None,
) -> SenderLabel:
    """The directory decides; the address hint and then the model's role only place a sender it does not know.

    A model `tenant` hint is ignored on purpose: an unknown "tenant" stays a contact so the unregistered-sender
    banner can offer to link them to the lease.
    """
    if person_kind is PersonKind.contractor:
        return _contractor(trade)
    if person_kind is PersonKind.tenant or is_lease_party:
        return _TENANT
    if person_kind is PersonKind.other and trade:
        fixed = _TRADE_LABELS.get(trade.strip().lower())
        if fixed is not None:
            return fixed
    if contractor_hint or role_hint is SenderRole.contractor:
        return _contractor(trade)
    return _FROM_MODEL.get(role_hint, _CONTACT) if role_hint else _CONTACT


def sender_label_for(
    session: Session, company_id: UUID, person: Person | None, *, role_hint: SenderRole | None, contractor_hint: bool
) -> SenderLabel:
    """The label of a thread's sender: the directory's facts about `person` (their kind, any lease they sign) first."""
    is_lease_party = (
        person is not None
        and session.scalar(
            select(LeaseParty.id).where(LeaseParty.company_id == company_id, LeaseParty.person_id == person.id)
        )
        is not None
    )
    return resolve_sender_label(
        person_kind=person.kind if person else None,
        trade=person.trade if person else None,
        is_lease_party=is_lease_party,
        contractor_hint=contractor_hint,
        role_hint=role_hint,
    )


def _contractor(trade: str | None) -> SenderLabel:
    detail = f"Contractor · {trade.title()}" if trade and trade.strip() else "Contractor"
    return SenderLabel(SenderKind.contractor, detail, "contractors", "contractor")


def _readable(raw: object) -> SenderRole | None:
    try:
        return SenderRole(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


def role_hint_of(understanding_body: dict[str, Any], message_meta: dict[str, Any] | None = None) -> SenderRole | None:
    """The role the model stored for a message. Anything unreadable (an old row, a value since removed) is None, and so
    is a role on mail flagged suspicious or spam: the scanner can flag a mail after the model answered. The one-time
    label pass (`meta.sender_role_pass`, ADR 0016) saw the repaired sender, so its answer replaces the stored one."""
    suspicious = understanding_body.get("suspicious")
    if isinstance(suspicious, dict) and suspicious.get("flag"):
        return None
    if understanding_body.get("category") == Category.spam.value:
        return None
    if message_meta is not None and "sender_role_pass" in message_meta:
        return _readable(message_meta["sender_role_pass"])
    return _readable(understanding_body.get("sender_role"))


def organisation_of(sender: str) -> str | None:
    """The email domain of a sender when it names an organisation; None for a phone number or a free-mail address."""
    _, at, domain = sender.strip().lower().rpartition("@")
    if not at or not domain or domain in _FREE_MAIL:
        return None
    return domain


def unit_display(kind: SenderKind, unit: str | None, sender: str) -> str:
    """What the thread shows where a tenant's unit would be. Only a tenant can be missing a unit; anyone else shows
    their organisation, or nothing."""
    if unit:
        return unit
    if kind is SenderKind.tenant:
        return UNASSIGNED_UNIT
    return organisation_of(sender) or ""
