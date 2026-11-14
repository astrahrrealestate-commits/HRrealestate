"""Harjot's WhatsApp messages: button taps decide approvals, the text after `edit` becomes a new draft revision.

Any other text is a command (tasks, done, snooze, waiting, pause, resume, help) or a question for owner Q&A.
"""

import re
from datetime import UTC, datetime
from functools import partial
from typing import Any
from uuid import UUID

from dbos import DBOS, SetWorkflowID
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.whatsapp import payloads
from app.contracts import ButtonId, DocType
from app.core.errors import InvalidButtonIdError, NotFoundError
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.core.workflow_names import OWNER_REPLY
from app.db.models import ActionRow, MessageRow
from app.pipeline import approvals, owner_commands
from app.pipeline.local_actions import LOCAL_TYPES
from app.sender.execute import send_to_owner
from app.workflows import queues
from app.workflows.actions import execute_action_wf
from app.workflows.deps import get_engine, get_sender_deps
from app.workflows.documents import SKIP, enqueue_filing
from app.workflows.owner_notify import flush_outbox_step, send_card_step
from app.workflows.retry import STEP_RETRY

log = get_logger(__name__)
EDIT_PROMPT = "Send the new text as your next message. It replaces the draft."
UNKNOWN_PROMPT = "That request is no longer open."


def _button(meta: dict[str, Any]) -> ButtonId | None:
    try:
        return ButtonId.parse(meta.get("interactive_id"))
    except InvalidButtonIdError:
        return None


_DOC_TAP = re.compile(r"doc:([0-9a-f-]{36}):([a-z_]{1,32})")
_DOC_CHOICES = {t.value for t in DocType} | {SKIP}


def _document_tap(meta: dict[str, Any]) -> tuple[str, str] | None:
    match = _DOC_TAP.fullmatch(str(meta.get("interactive_id") or ""))
    if match is None or match.group(2) not in _DOC_CHOICES:
        return None
    return match.group(1), match.group(2)


def handle_owner_message(message_id: UUID) -> dict[str, Any]:
    now = datetime.now(UTC)
    with Session(get_engine()) as session, session.begin():
        msg = session.scalar(select(MessageRow).where(MessageRow.id == message_id))
        if msg is None:
            return {"kind": "missing"}
        company_id, button = msg.company_id, _button(msg.meta)
        doc_tap = _document_tap(msg.meta)
        if doc_tap is not None:
            return {
                "kind": "document",
                "company_id": str(company_id),
                "attachment_id": doc_tap[0],
                "choice": doc_tap[1],
            }
        if button is not None:
            try:
                d = approvals.decide(session, company_id, button.approval_id, button.choice, at=now)
            except NotFoundError:  # an old, foreign or forged button id: answer, never fail the workflow
                return {"kind": "unknown", "company_id": str(company_id)}
            action_type = session.scalar(
                select(ActionRow.type).where(ActionRow.company_id == company_id, ActionRow.id == d.action_id)
            )
            local = action_type in LOCAL_TYPES
            return {
                "kind": d.kind,
                "company_id": str(company_id),
                "action_id": str(d.action_id),
                "version": d.draft_version,
                "local": local,
                "approval_id": str(button.approval_id),
            }
        is_command = owner_commands.parse_command(msg.text).kind is not owner_commands.CommandKind.question
        revision = (
            None
            if is_command
            else approvals.apply_owner_edit(session, company_id, msg.text, now=now, message_id=msg.id)
        )
        if revision is not None:
            return {
                "kind": "revision",
                "company_id": str(company_id),
                "approval_id": str(revision.approval_id),
                "text": msg.text,
            }
        return {"kind": "command", "company_id": str(company_id), "text": msg.text}


@DBOS.step(name="owner.handle", **STEP_RETRY)
def handle_step(message_id: str) -> dict[str, Any]:
    return handle_owner_message(UUID(message_id))


def _text(body: str, to: str) -> dict[str, Any]:
    return payloads.text(to, body)


@DBOS.step(name="owner.reply", **STEP_RETRY)
def reply_step(company_id: str, key: str, text: str) -> None:
    chunks = [text[i : i + payloads.TEXT_BODY_MAX] for i in range(0, len(text), payloads.TEXT_BODY_MAX)] or ["-"]
    for n, chunk in enumerate(chunks):
        send_to_owner(get_sender_deps(), UUID(company_id), f"{key}:{n}", partial(_text, chunk))


@DBOS.step(name="owner.command", **STEP_RETRY)
def command_step(company_id: str, text: str) -> str:
    cmd = owner_commands.parse_command(text)
    return owner_commands.run_command(get_engine(), get_settings(), UUID(company_id), cmd, now=datetime.now(UTC))


@DBOS.step(name="owner.approved_unexecuted", **STEP_RETRY)
def approved_unexecuted_step(company_id: str) -> list[tuple[str, int, bool]]:
    with Session(get_engine()) as session:
        rows = approvals.approved_unexecuted(session, UUID(company_id))
    return [(str(a), v, t in LOCAL_TYPES) for a, v, t in rows]


@DBOS.workflow(name=OWNER_REPLY)
def owner_reply(message_id: str) -> str:
    r = handle_step(message_id)
    kind = str(r["kind"])
    if kind == "execute":
        with SetWorkflowID(f"exec:{r['action_id']}:{r['version']}"):
            queues.pipeline_queue().enqueue(execute_action_wf, r["action_id"], r["version"], r["local"])
    elif kind in ("unknown", "stale"):
        reply_step(r["company_id"], f"owner:{message_id}:{kind}", UNKNOWN_PROMPT)
    elif kind == "edit":
        reply_step(r["company_id"], f"owner:{message_id}:edit", EDIT_PROMPT)
    elif kind == "document":
        enqueue_filing(r["company_id"], r["attachment_id"], r["choice"])
    elif kind == "command":
        reply = command_step(r["company_id"], r["text"])
        reply_step(r["company_id"], f"owner:{message_id}:command", reply)
        if owner_commands.parse_command(r["text"]).kind is owner_commands.CommandKind.resume:
            for action_id, version, local in approved_unexecuted_step(r["company_id"]):
                with SetWorkflowID(f"exec:{action_id}:{version}:resume:{message_id}"):
                    queues.pipeline_queue().enqueue(execute_action_wf, action_id, version, local)
    elif kind == "revision":
        send_card_step(r["company_id"], r["approval_id"])
    if "company_id" in r:  # after acting on the message: a stuck outbox item can never block a decision
        try:
            flush_outbox_step(r["company_id"])
        except Exception as exc:
            log.error("owner.flush_failed", company_id=r["company_id"], error=type(exc).__name__)
    return kind
