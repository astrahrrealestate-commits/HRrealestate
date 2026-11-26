"""The chunk lines of one message (M13 T14c). An email adds its new part, not the history it quotes, which the thread
already holds. A reply of Harjot's quoted in it is added once, marked: his replies are often only in the mailbox as a
quote in a later mail (he answers from his own mailbox). The quote is sender-controlled text, so it is never shown as
his own outbound line. WhatsApp and other channels are indexed as they are."""

from collections.abc import Iterable, Sequence

from sqlalchemy.orm import Session

from app.channels.gmail.quoted import quoted_messages, split_quoted
from app.context.message_origin import full_text, owner_emails
from app.contracts import Channel
from app.db.models import MessageRow
from app.tools.message_rag.chunker import AMSTERDAM_TZ, LINE_HEAD, format_message_line, plain_body

QUOTED_OWNER = "Harjot (quoted in a later mail, not verified)"


def _quoted_line(msg: MessageRow, text: str) -> str:
    stamp = msg.sent_at.astimezone(AMSTERDAM_TZ).strftime("%Y-%m-%d %H:%M")
    return f"[before {stamp} | {QUOTED_OWNER} | quoted] {plain_body(' '.join(text.split()))}"


def message_lines(session: Session, msg: MessageRow, person_name: str | None) -> list[str]:
    if msg.channel is not Channel.gmail:
        return [format_message_line(msg, person_name)]
    new, _ = split_quoted(msg.text or "")
    lines = [format_message_line(msg, person_name, text=new if new.strip() else msg.text)]
    owners = owner_emails(session, msg.company_id)
    lines += [_quoted_line(msg, q.text) for q in quoted_messages(full_text(msg)) if q.author in owners]
    return lines


def _body(line: str) -> str:
    found = LINE_HEAD.match(line)
    return line[found.end() :] if found else line


def merge_lines(existing: Sequence[str], added: Iterable[str]) -> list[str]:
    """`added` after `existing`, without a quoted line whose text the chunk already holds."""
    seen = {_body(line) for line in existing if QUOTED_OWNER in line}
    out: list[str] = []
    for line in added:
        if QUOTED_OWNER in line:
            if _body(line) in seen:
                continue
            seen.add(_body(line))
        out.append(line)
    return out
