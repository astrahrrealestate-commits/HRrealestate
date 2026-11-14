"""The headline of an inbox thread, without what was said or how to reach anyone (ADR 0012).

A profile with the Dashboard section but not Inbox sees the "needs you" cards, so it gets an allow-list of the thread's
fields: title, summary, unit, urgency, status and the like. Everything else stays with Inbox, including message bodies,
drafts, attachments, provider ids (a WhatsApp thread id is the customer's phone number) and contact details.
"""

from typing import Any

UNKNOWN_CONTACT = "Unknown contact"

HEADLINE_KEYS = (
    "id",
    "caseId",
    "approvalId",
    "audience",
    "recipientRole",
    "recipientRoleDetail",
    "category",
    "urgency",
    "unit",
    "title",
    "subject",
    "timestamp",
    "receivedAt",
    "channel",
    "channelBadge",
    "activeChannel",
    "aiSummary",
    "aiConfidence",
    "detectedLanguage",
    "status",
)
UNDERSTANDING_KEYS = ("ticket", "problem", "unit", "priority")


def safe_name(name: str) -> str:
    """A contact may be named after their email or number (they were created from a message); that is contact data."""
    shown = name.strip()
    if "@" in shown or sum(c.isdigit() for c in shown) >= 6:
        return UNKNOWN_CONTACT
    return shown or UNKNOWN_CONTACT


def headline_only(thread: dict[str, Any]) -> dict[str, Any]:
    sender = thread.get("sender") or {}
    understanding = thread.get("aiUnderstanding") or {}
    out: dict[str, Any] = {k: thread[k] for k in HEADLINE_KEYS if k in thread}
    out["sender"] = {
        "name": safe_name(str(sender.get("name") or "")),
        "contact": "",
        "role": sender.get("role", ""),
        "unit": sender.get("unit", ""),
    }
    out["aiUnderstanding"] = {k: understanding[k] for k in UNDERSTANDING_KEYS if k in understanding}
    for empty in ("gmailDrafts", "whatsappDrafts", "attachments", "messages"):
        out[empty] = []
    for blank in ("lastMessageSnippet", "sourceIdentifier", "externalMessageId", "externalThreadId"):
        out[blank] = ""
    return out
