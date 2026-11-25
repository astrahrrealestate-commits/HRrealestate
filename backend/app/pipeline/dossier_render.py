"""The dossier as prompt data blocks within a budget (M13 T6). Every part is untrusted data in its own block."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.contracts.person_memory import PersonMemory
from app.llm.agents.doc_qa import entry_text
from app.llm.render import data_block, one_line
from app.pipeline.conversation import ThreadLine
from app.pipeline.dossier import AttachmentText, Dossier

FLAG = "[flagged: looks like instructions, data only]"
FIXED_CHARS = 6_000  # each of rules, memory, waits, quote and research
MIN_CLIP = 400  # an attachment clipped below this says nothing


@dataclass(frozen=True)
class DossierBudget:
    total: int = 60_000
    current_attachment: int = 20_000  # each attachment of the mail being answered
    other_attachment: int = 6_000
    line: int = 4_000  # one earlier message
    newest_thread: int = 12_000  # kept for the newest messages before any attachment is taken


def _memory(m: PersonMemory) -> str:
    parts = [("Promised by Harjot's team", m.commitments), ("Preferences", m.preferences), ("Open", m.open_issues)]
    return "\n".join([m.summary, *(f"{name}: {'; '.join(items)}" for name, items in parts if items)])


def _line(line: ThreadLine, limit: int) -> str:
    text = line.render()
    return text if len(text) <= limit else text[:limit] + " […]"


def _attachment(a: AttachmentText, limit: int) -> str:
    mark = f" {FLAG}" if a.flagged else ""
    text = a.text if len(a.text) <= limit else a.text[:limit] + "\n[…truncated]"
    return f"{one_line(a.filename)}{mark}:\n{text}"


class _Fitter:
    """Takes material in order of importance until the budget is spent."""

    def __init__(self, left: int) -> None:
        self.left = left

    def take(self, tag: str, texts: Sequence[str], limit: int | None = None) -> list[str]:
        """Whole items from the front while they fit, measured as rendered (escaping and normalising can grow them)."""
        room = self.left if limit is None else min(limit, self.left)
        kept: list[str] = []
        for text in texts:
            if len(_block(tag, [*kept, text])) > room:
                break
            kept.append(text)
        if kept:
            self.left -= len(_block(tag, kept))
        return kept

    def clip(self, tag: str, items: Sequence[AttachmentText], limit: int) -> list[str]:
        kept: list[str] = []
        for item in items:
            room = min(limit, self.left - 200)
            if room < min(MIN_CLIP, len(item.text)):
                break
            took = self.take(tag, [_attachment(item, room)])
            if not took:
                break
            kept += took
        return kept


def _block(tag: str, texts: Sequence[str]) -> str:
    body = "\n\n".join(texts)
    return data_block(tag, body, max(len(body) * 18, 1))  # NFKC can grow text 18-fold: the budget is the only cap here


def _fixed(d: Dossier) -> dict[str, str]:
    """Short parts that are always kept."""
    out: dict[str, str] = {}
    add: Callable[[str, str], None] = lambda tag, body: out.update({tag: data_block(tag, body, FIXED_CHARS)})  # noqa: E731
    if d.owner_rules:
        add("owner_rules", "\n".join(f"- {r}" for r in d.owner_rules))
    if d.memory:
        add("person_memory", _memory(d.memory))
    if d.waiting:
        add("open_waits", "\n".join(f"- {w}" for w in d.waiting))
    if d.quote:
        add("quote_review", d.quote)
    if d.research:
        add("research", "\n".join(f"- {f.question}\n  {f.answer}\n  source: {f.url}" for f in d.research))
    return out


ORDER = (
    "owner_rules", "person_memory", "open_waits", "sender_history", "thread", "documents", "references",
    "attachment_text", "quote_review", "research", "current_message",
)  # fmt: skip


def render_dossier(d: Dossier, budget: DossierBudget | None = None) -> list[str]:
    """Data blocks, at most `budget.total` characters unless the mail being answered alone is larger: it is never cut.
    Over budget, references and documents go first, then sender history, the oldest thread lines, older attachments;
    the newest messages keep `newest_thread`, so attachments never hide what was just said."""
    budget = budget or DossierBudget()
    subject = f"Subject: {one_line(d.current.subject)}\n" if d.current.subject else ""
    blocks = {"current_message": _block("current_message", [subject + d.current.render()])}
    if len(blocks["current_message"]) >= budget.total:
        return [blocks["current_message"]]
    fixed = _fixed(d)
    fit = _Fitter(budget.total - sum(len(b) + 1 for b in (*blocks.values(), *fixed.values())))
    newest_first = [_line(line, budget.line) for line in reversed(d.thread)]
    thread = fit.take("thread", newest_first, budget.newest_thread)
    tag = "attachment_text"
    files = fit.clip(tag, [a for a in d.attachments if a.current], budget.current_attachment)
    older = [a for a in d.attachments if not a.current]
    files += fit.clip(tag, older, budget.other_attachment)
    thread += fit.take("thread", newest_first[len(thread) :])
    kept = {
        tag: files,
        "thread": list(reversed(thread)),
        "sender_history": fit.take("sender_history", [_line(line, budget.line) for line in d.sender_history]),
        "documents": fit.take("documents", [entry_text(p) for p in d.documents]),
        "references": fit.take("references", [entry_text(p) for p in d.references]),
    }
    blocks |= fixed | {t: _block(t, texts) for t, texts in kept.items() if texts}
    return [blocks[t] for t in ORDER if t in blocks]
