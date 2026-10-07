"""Harjot's WhatsApp messages: button taps decide approvals, the text after `edit` becomes a new draft revision.

Text commands and questions (owner Q&A) are added on top of `handle_owner_message` by the owner-channel module.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from dbos import DBOS, SetWorkflowID
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.whatsapp import payloads
from app.contracts import ButtonChoice, ButtonId
from app.core.errors import InvalidButtonIdError, NotFoundError
from app.core.workflow_names import OWNER_REPLY
from app.db.models import ActionRow, MessageRow
from app.pipeline import approvals
from app.pipeline.local_actions import LOCAL_TYPES
from app.sender.execute import send_to_owner
from app.workflows import queues
from app.workflows.actions import execute_action_wf
from app.workflows.deps import get_engine, get_sender_deps

EDIT_PROMPT = "Send the new text as your next message. It replaces the draft."
UNKNOWN_PROMPT = "That request is no longer open."


def _button(meta: dict[str, Any]) -> ButtonId | None:
    try:
        return ButtonId.parse(meta.get("interactive_id"))
    except InvalidButtonIdError:
        return None


def handle_owner_message(message_id: UUID) -> dict[str, Any]:
    now = datetime.now(UTC)
    with Session(get_engine()) as session, session.begin():
        msg = session.scalar(select(MessageRow).where(MessageRow.id == message_id))
        if msg is None:
            return {"kind": "missing"}
        company_id, button = msg.company_id, _button(msg.meta)
        if button is not None:
            try:
                d = approvals.decide(session, company_id, button.approval_id, button.choice, at=now)
            except NotFoundError:  # an old, foreign or forged button id: answer, never fail the workflow
                return {"kind": "unknown", "company_id": str(company_id)}
            local = session.scalar(select(ActionRow.type).where(ActionRow.id == d.action_id)) in LOCAL_TYPES
            return {
                "kind": d.kind,
                "company_id": str(company_id),
                "action_id": str(d.action_id),
                "version": d.draft_version,
                "local": local,
                "approval_id": str(button.approval_id),
            }
        revision = approvals.apply_owner_edit(session, company_id, msg.text, now=now)
        if revision is not None:
            return {
                "kind": "revision",
                "company_id": str(company_id),
                "approval_id": str(revision.approval_id),
                "text": msg.text,
            }
        return {"kind": "command", "company_id": str(company_id), "text": msg.text}


def approval_prompt(to: str, approval_id: UUID, body: str) -> dict[str, Any]:
    items = [
        payloads.Button(ButtonId(approval_id=approval_id, choice=c).render(), t)
        for c, t in ((ButtonChoice.ok, "Approve"), (ButtonChoice.edit, "Edit"), (ButtonChoice.rej, "Reject"))
    ]
    return payloads.buttons(to, body[: payloads.BODY_MAX], items)


@DBOS.step(name="owner.handle")
def handle_step(message_id: str) -> dict[str, Any]:
    return handle_owner_message(UUID(message_id))


@DBOS.step(name="owner.reply")
def reply_step(company_id: str, key: str, kind: str, approval_id: str | None, text: str) -> None:
    def build(to: str) -> dict[str, Any]:
        if kind == "prompt" and approval_id:
            return approval_prompt(to, UUID(approval_id), text)
        return payloads.text(to, text)

    send_to_owner(get_sender_deps(), UUID(company_id), key, build)


@DBOS.workflow(name=OWNER_REPLY)
def owner_reply(message_id: str) -> str:
    r = handle_step(message_id)
    kind = str(r["kind"])
    if kind == "execute":
        with SetWorkflowID(f"exec:{r['action_id']}:{r['version']}"):
            queues.pipeline_queue().enqueue(execute_action_wf, r["action_id"], r["version"], r["local"])
    elif kind in ("unknown", "stale"):
        reply_step(r["company_id"], f"owner:{message_id}:{kind}", "text", None, UNKNOWN_PROMPT)
    elif kind == "edit":
        reply_step(r["company_id"], f"owner:{message_id}:edit", "text", None, EDIT_PROMPT)
    elif kind == "revision":
        body = f"Your edited draft:\n\n{r['text']}"
        reply_step(r["company_id"], f"owner:{message_id}:revision", "prompt", r["approval_id"], body)
    return kind
