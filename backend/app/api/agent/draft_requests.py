"""Draft requests the Super Agent must not answer silently.

It cannot rewrite or translate a draft (it only proposes; the owner edits and approves), and a draft is written
for the channel the contact can actually be reached on, which may not be the one the owner named.
"""

import re

from app.pipeline.concierge_reads import REWRITE_UNSUPPORTED_ANSWER as REWRITE_UNSUPPORTED_ANSWER  # rewrite_draft's

_REWRITE = re.compile(
    r"\b(shorter|shorten|longer|rewrite|rephrase|reword|translate|firmer|softer|friendlier|"
    r"more\s+formal|less\s+formal|in\s+(?:english|dutch|nederlands))\b",
    re.IGNORECASE,
)
_ABOUT_A_DRAFT = re.compile(r"\b(it|that|this|draft|reply|message|mail|email|text|him|her|them)\b", re.IGNORECASE)
_WHATSAPP = re.compile(r"\bwhats\s?app\b", re.IGNORECASE)
_EMAIL = re.compile(r"\b(e-?mail|gmail|mail)\b", re.IGNORECASE)


def rewrite_answer(query: str) -> str | None:
    """The honest answer to "make it shorter" / "translate that", None for anything else."""
    if _REWRITE.search(query) and _ABOUT_A_DRAFT.search(query) and not re.search(r"\bword\b", query, re.IGNORECASE):
        return REWRITE_UNSUPPORTED_ANSWER
    return None


def channel_note(query: str, draft_channel: str | None, recipient: str | None) -> str:
    """A sentence to put before the draft when it is for another channel than the one the owner asked for."""
    to = f" to {recipient}" if recipient else ""
    if _WHATSAPP.search(query) and draft_channel == "gmail":
        return f"I don't have a WhatsApp number for this contact, so this draft is an email{to} instead."
    if _EMAIL.search(query) and not _WHATSAPP.search(query) and draft_channel == "whatsapp":
        return f"I don't have an email address for this contact, so this draft is a WhatsApp message{to} instead."
    return ""
