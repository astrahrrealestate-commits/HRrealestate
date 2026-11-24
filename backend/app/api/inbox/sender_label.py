"""Who wrote a thread, for the inbox labels. Decided from the directory (the DB), never from message text.

The label comes after the intent: it is only a display hint and never picks a recipient, a person kind or a lease.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.db.enums import PersonKind

UNASSIGNED_UNIT = "Unassigned Unit"
UNLISTED_CONTACT = "Unlisted contact"
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
    contact = "contact"  # anyone the directory cannot place: lawyer, VvE, bank, vendor, prospect, a stranger


@dataclass(frozen=True)
class SenderLabel:
    kind: SenderKind
    role_detail: str  # e.g. "Tenant", "Contractor · Electrician", "Contact"
    audience: str  # the inbox filter value: tenants, contractors or others


def resolve_sender_label(
    *, person_kind: PersonKind | None, trade: str | None, is_lease_party: bool, contractor_hint: bool
) -> SenderLabel:
    """The directory decides; the address hint only counts when the directory knows nothing better."""
    if person_kind is PersonKind.contractor:
        return _contractor(trade)
    if person_kind is PersonKind.tenant or is_lease_party:
        return SenderLabel(SenderKind.tenant, "Tenant", "tenants")
    if contractor_hint:
        return _contractor(trade)
    return SenderLabel(SenderKind.contact, "Contact", "others")


def _contractor(trade: str | None) -> SenderLabel:
    detail = f"Contractor · {trade.title()}" if trade and trade.strip() else "Contractor"
    return SenderLabel(SenderKind.contractor, detail, "contractors")


def organisation_of(sender: str) -> str | None:
    """The email domain of a sender when it names an organisation; None for a phone number or a free-mail address."""
    _, at, domain = sender.strip().lower().rpartition("@")
    if not at or not domain or domain in _FREE_MAIL:
        return None
    return domain


def unit_display(kind: SenderKind, unit: str | None, sender: str) -> str:
    """What the thread shows where a tenant's unit would be. Only a tenant can be missing a unit."""
    if unit:
        return unit
    if kind is SenderKind.tenant:
        return UNASSIGNED_UNIT
    return organisation_of(sender) or UNLISTED_CONTACT
