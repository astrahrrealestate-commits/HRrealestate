"""The headline of an inbox thread, without what was said or how to reach anyone (ADR 0012).

A profile with the Dashboard section but not Inbox sees the "needs you" cards, so it gets an allow-list of the thread's
fields: title, summary, unit, urgency, status and the like. Everything else stays with Inbox, including message bodies,
drafts, attachments, provider ids (a WhatsApp thread id is the customer's phone number) and contact details.
"""

from typing import Any

from app.context.sender_label import UNKNOWN_CONTACT as UNKNOWN_CONTACT
from app.context.sender_label import safe_name as safe_name

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
