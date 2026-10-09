"""Owner approval cards: pure message builders (the recipient is filled in by the sender from the DB).

Drafts are shown in full in plain text messages (split at the 4096 limit); the choice follows as one interactive
message: a list menu for 2–3 drafts, reply buttons otherwise. Every choice id is a `ButtonId` for one approval.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any
from uuid import UUID

from app.channels.whatsapp import payloads
from app.contracts import ButtonChoice, ButtonId, DocType, Urgency
from app.owner.model import OwnerChoice, OwnerMessage
from app.owner.render_whatsapp import render_whatsapp

PayloadBuilder = Callable[[str], dict[str, Any]]
_PREFIX = {Urgency.emergency: "[EMERGENCY] ", Urgency.high: "[HIGH] "}
_DRAFT_CHOICES = (ButtonChoice.d1, ButtonChoice.d2, ButtonChoice.d3)


@dataclass(frozen=True)
class ApprovalCard:
    approval_id: UUID
    case_label: str
    urgency: Urgency
    intent: str
    kind_label: str  # "Reply", "Contractor request", "Escalation", ...
    drafts: tuple[str, ...]  # reply/contractor drafts, empty for other action types
    detail: str | None  # what a non-draft action does (notice text, escalation reason, reminder note)


def _header(card: ApprovalCard) -> str:
    return f"{_PREFIX.get(card.urgency, '')}{card.kind_label}: {card.case_label}\n{card.intent}"


def _id(card: ApprovalCard, choice: ButtonChoice) -> str:
    return ButtonId(approval_id=card.approval_id, choice=choice).render()


def _chunks(text: str, limit: int = payloads.TEXT_BODY_MAX) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)] or [text]


def _draft_texts(card: ApprovalCard) -> list[str]:
    parts = [_header(card), *(f"Draft {i}:\n{d}" for i, d in enumerate(card.drafts, start=1))]
    return _chunks("\n\n".join(parts))


def approval_messages(card: ApprovalCard) -> list[OwnerMessage]:
    """Channel-neutral approval card messages: text blocks for drafts followed by choice buttons or list menu."""
    if not card.drafts:
        body = f"{_header(card)}\n\n{card.detail or ''}".strip()
        no_draft_choices: tuple[OwnerChoice, ...] = (
            OwnerChoice(_id(card, ButtonChoice.ok), "Approve"),
            OwnerChoice(_id(card, ButtonChoice.rej), "Reject"),
        )
        return [OwnerMessage(text=body, choices=no_draft_choices)]

    texts = [OwnerMessage(text=t) for t in _draft_texts(card)]
    if len(card.drafts) == 1:
        single_choices: tuple[OwnerChoice, ...] = (
            OwnerChoice(_id(card, ButtonChoice.ok), "Approve"),
            OwnerChoice(_id(card, ButtonChoice.edit), "Edit"),
            OwnerChoice(_id(card, ButtonChoice.rej), "Reject"),
        )
        return [*texts, OwnerMessage(text="Approve, edit or reject this draft.", choices=single_choices)]

    menu_choices = (
        *(
            OwnerChoice(_id(card, c), f"Send draft {i}", " ".join(d.split())[: payloads.LIST_ROW_DESCRIPTION_MAX])
            for i, (c, d) in enumerate(zip(_DRAFT_CHOICES, card.drafts, strict=False), start=1)
        ),
        OwnerChoice(_id(card, ButtonChoice.edit), "Edit"),
        OwnerChoice(_id(card, ButtonChoice.rej), "Reject"),
    )
    menu_msg = OwnerMessage(
        text="Choose a draft, edit or reject.",
        choices=menu_choices,
        menu_title="Options",
        menu_button="Choose",
    )
    return [*texts, menu_msg]


def approval_payloads(card: ApprovalCard) -> list[PayloadBuilder]:
    """Backward-compatible WhatsApp payload builders."""
    return [partial(render_whatsapp, m) for m in approval_messages(card)]


def exception_message(case_label: str, reason: str) -> OwnerMessage:
    return OwnerMessage(text=f"Needs your eyes (not drafted): {case_label}\n{reason}"[: payloads.TEXT_BODY_MAX])


def exception_payload(case_label: str, reason: str) -> PayloadBuilder:
    return partial(render_whatsapp, exception_message(case_label, reason))


DOC_PREFIX = "doc:"
_DOC_TYPES = tuple(t.value for t in DocType)


def document_choice_id(attachment_id: UUID, choice: str) -> str:
    return f"{DOC_PREFIX}{attachment_id}:{choice}"


def document_review_message(attachment_id: UUID, file_label: str, suggested: str, title: str) -> OwnerMessage:
    body = f"Document to file: {file_label}\nBest guess: {suggested.replace('_', ' ')} - {title}"
    order = [suggested, *(t for t in _DOC_TYPES if t != suggested)]
    choices = (
        *(OwnerChoice(document_choice_id(attachment_id, t), f"File as {t.replace('_', ' ')}"[:24]) for t in order),
        OwnerChoice(document_choice_id(attachment_id, "skip"), "Do not file"),
    )
    return OwnerMessage(
        text=body,
        choices=choices[:10],
        menu_title="File as",
        menu_button="Choose",
    )


def document_review_payload(attachment_id: UUID, file_label: str, suggested: str, title: str) -> PayloadBuilder:
    """Low-confidence filing: Harjot picks the type (or skips). Suggested type first."""
    return partial(render_whatsapp, document_review_message(attachment_id, file_label, suggested, title))
