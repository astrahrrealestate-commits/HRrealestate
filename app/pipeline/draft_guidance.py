"""Pure parts of an owner-requested draft (`draft_reply`, amendment 2026-10-22): the owner's guidance, the retry key,
and what the chat shows of the drafts. No I/O.

The guidance is the OWNER's own message, never model output: the planner reads tenant text (the memory pack), so its
`text` could carry a tenant's instruction, and no word-overlap check on it is safe (negations, spelled-out or
look-alike words). The owner's message, sanitised (links, emails, phone numbers, IBANs and amounts become
`[redacted]`) and capped, is what the proposer sees in its `<owner_guidance>` block; the planner's `text` is ignored.
The drafts shown in the chat are capped, quoted, and checked by the draft output guard against the source
conversation: a variant with an unverified link, account or phone number is flagged and shown redacted.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.pipeline.concierge_sanitize import normalise_query, redact, sanitize
from app.pipeline.output_guard import unverified_kinds

MAX_SHOWN = 600  # characters of each draft variant in the chat
MAX_VARIANTS = 3
READY = "Nothing is sent until you approve it in Approvals."
DETAILS_REMOVED = "Contact, bank or payment details and links in your request were removed before drafting."
KEY_PREFIX = "agent:"  # ActionRevision.edited_by of a draft the agent wrote on the owner's request


@dataclass(frozen=True)
class Guidance:
    text: str | None  # sanitised; None when there is nothing to pass on
    redacted: bool  # the sanitiser changed the owner's message: the result says "details removed"


def guidance_for(owner_message: str) -> Guidance:
    plain = normalise_query(owner_message)
    if not plain:
        return Guidance(None, False)
    return Guidance(sanitize(owner_message) or None, redact(plain) != plain)


def turn_prefix(turn_id: UUID) -> str:
    return f"{KEY_PREFIX}{turn_id}:"


def redraft_key(turn_id: UUID, step_index: int) -> str:
    """Deterministic per turn and step: a retried step finds the revision it already wrote (36 + 9 chars < 64)."""
    return f"{turn_prefix(turn_id)}{step_index}"


def _shown(text: str) -> str:
    kept = "".join(ch if ch == "\n" or ch.isprintable() else " " for ch in text[:MAX_SHOWN])
    return "\n".join(" ".join(line.split()) for line in kept.splitlines() if line.strip())


def draft_views(variants: Sequence[str], source: str) -> list[dict[str, Any]]:
    """Each variant capped at MAX_SHOWN, with the output guard's flags; a flagged variant is shown redacted."""
    views = []
    for variant in variants[:MAX_VARIANTS]:
        flags = unverified_kinds(variant, source)
        text = _shown(variant)
        views.append({"text": redact(text) if flags else text, "flags": flags})
    return views


def _quoted(view: dict[str, Any], number: int) -> str:
    flags = view["flags"]
    note = f" (held back: unverified {', '.join(flags)})" if flags else ""
    body = "\n".join(f"> {line}" for line in str(view["text"]).splitlines() if line.strip())
    return f"Draft {number}{note}:\n{body}"


def drafted_summary(headline: str, views: Sequence[dict[str, Any]], *, details_removed: bool) -> str:
    """The owner-facing text, assembled from fixed phrases and the quoted drafts (no model phrases it)."""
    parts = [headline]
    if details_removed:
        parts.append(DETAILS_REMOVED)
    parts.extend(_quoted(v, n) for n, v in enumerate(views, start=1))
    return "\n".join(parts)
