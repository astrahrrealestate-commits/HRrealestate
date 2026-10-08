"""Owner approval cards: pure WhatsApp payload builders (the recipient is filled in by the sender from the DB).

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


def _menu(card: ApprovalCard, to: str) -> dict[str, Any]:
    rows = [
        payloads.ListRow(_id(card, c), f"Send draft {i}", " ".join(d.split())[: payloads.LIST_ROW_DESCRIPTION_MAX])
        for i, (c, d) in enumerate(zip(_DRAFT_CHOICES, card.drafts, strict=False), start=1)
    ]
    rows += [
        payloads.ListRow(_id(card, ButtonChoice.edit), "Edit"),
        payloads.ListRow(_id(card, ButtonChoice.rej), "Reject"),
    ]
    return payloads.list_menu(to, "Choose a draft, edit or reject.", "Choose", [payloads.ListSection("Options", rows)])


def _buttons(card: ApprovalCard, body: str, choices: tuple[tuple[ButtonChoice, str], ...], to: str) -> dict[str, Any]:
    items = [payloads.Button(_id(card, c), title) for c, title in choices]
    return payloads.buttons(to, body[: payloads.BODY_MAX], items)


def approval_payloads(card: ApprovalCard) -> list[PayloadBuilder]:
    if not card.drafts:
        body = f"{_header(card)}\n\n{card.detail or ''}".strip()
        return [partial(_buttons, card, body, ((ButtonChoice.ok, "Approve"), (ButtonChoice.rej, "Reject")))]
    texts: list[PayloadBuilder] = [partial(_text, t) for t in _draft_texts(card)]
    if len(card.drafts) == 1:
        choices = ((ButtonChoice.ok, "Approve"), (ButtonChoice.edit, "Edit"), (ButtonChoice.rej, "Reject"))
        return [*texts, partial(_buttons, card, "Approve, edit or reject this draft.", choices)]
    return [*texts, partial(_menu, card)]


def _text(body: str, to: str) -> dict[str, Any]:
    return payloads.text(to, body)


def exception_payload(case_label: str, reason: str) -> PayloadBuilder:
    return partial(_text, f"Needs your eyes (not drafted): {case_label}\n{reason}"[: payloads.TEXT_BODY_MAX])


DOC_PREFIX = "doc:"
_DOC_TYPES = tuple(t.value for t in DocType)


def document_choice_id(attachment_id: UUID, choice: str) -> str:
    return f"{DOC_PREFIX}{attachment_id}:{choice}"


def _document_menu(attachment_id: UUID, body: str, suggested: str, to: str) -> dict[str, Any]:
    order = [suggested, *(t for t in _DOC_TYPES if t != suggested)]
    rows = [
        payloads.ListRow(document_choice_id(attachment_id, t), f"File as {t.replace('_', ' ')}"[:24]) for t in order
    ]
    rows.append(payloads.ListRow(document_choice_id(attachment_id, "skip"), "Do not file"))
    return payloads.list_menu(to, body[: payloads.BODY_MAX], "Choose", [payloads.ListSection("File as", rows[:10])])


def document_review_payload(attachment_id: UUID, file_label: str, suggested: str, title: str) -> PayloadBuilder:
    """Low-confidence filing: Harjot picks the type (or skips). Suggested type first."""
    body = f"Document to file: {file_label}\nBest guess: {suggested.replace('_', ' ')} - {title}"
    return partial(_document_menu, attachment_id, body, suggested)
