"""Deterministic keyword router standing in for the concierge model (offline tests, eval, simulation).

Page awareness: a message with a pronoun (it, that, this, them, him, her) resolves to the open entity in the
`<page_facts>` block (server facts); "the first one" is the first visible row of any kind, never the open entity
(no rows: clarify). The `<page_snapshot>` block is never read, so ids that appear only there are never acted on.
A `draft_reply` step carries the owner's wording (emails and phone numbers redacted) as `text`: the draft guidance.
"""

import re
from dataclasses import dataclass

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_INJECTION = re.compile(
    r"ignore previous|iban|bankrekening wijzig|nieuw(e)? rekeningnummer|approve all|\bsend\b.{0,60}\bto\b"
    r"|\b(email|send)\b.{0,60}@"
    r"|verify your (bank|account|payment) details|update your (bank|payment) details"
)
_PRONOUN = re.compile(r"\b(mark|snooze|reply to|chase|nudge)\s+(it|that|this|him|her|them)\b")
_DEICTIC = re.compile(r"\b(it|that|this|them|him|her)\b")
_FIRST_ONE = re.compile(r"\bthe first one\b")
_EMAIL = re.compile(r"\S+@\S+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
_PAGE_CASE = re.compile(rf"^open case: ({_UUID})", re.M)
_PAGE_THREAD_CASE = re.compile(rf"^open thread: \S+ \| \w+ \| case ({_UUID})", re.M)
_PAGE_APPROVAL = re.compile(rf"^open approval: {_UUID} \|.*\| case ({_UUID})$", re.M)
_PAGE_TASK = re.compile(r"^open task: #([0-9a-f]{6,8}) ", re.M)
_FIRST_VISIBLE = re.compile(r"^- (\w+) #?(\S+) (.*)$", re.M)  # the first row, whatever its kind
_ROW_CASE = re.compile(rf"\| case ({_UUID})$")


@dataclass(frozen=True)
class _Page:
    case_id: str | None  # the open case, the open thread's case or the open approval's case
    task_ref: str | None
    approval: bool
    first: tuple[str, str, str] | None  # (kind, id, rest of the line) of the first visible row


def _step(
    intent: str,
    case_id: str | None = None,
    task_ref: str | None = None,
    text: str | None = None,
    view: str | None = None,
) -> dict[str, object]:
    return {"intent": intent, "case_id": case_id, "task_ref": task_ref, "text": text, "view": view}


def _plan(*steps: dict[str, object]) -> dict[str, object]:
    return {"in_scope": True, "steps": list(steps)}


def _safe(text: str) -> str:
    return _PHONE.sub("[redacted]", _EMAIL.sub("[redacted]", " ".join(text.split())))[:400]


def _simple(low: str) -> dict[str, object] | None:
    if re.search(r"\bresume\b", low):
        return _plan(_step("resume"))
    if re.search(r"\bpause\b", low):
        return _plan(_step("pause"))
    if re.search(r"briefing|summary of the day", low):
        return _plan(_step("briefing_now"))
    if re.search(r"waiting", low):
        return _plan(_step("list_waiting"))
    if re.search(r"tasks?\b|\bopen\b", low):
        return _plan(_step("list_tasks"))
    return None


def _by_ref(low: str) -> dict[str, object] | None:
    if m := re.search(r"\bsnooze\s+#([0-9a-f]{6,8})\s+(?:for\s+)?(\d+[mhdw])\b", low):
        return _plan(_step("task_snooze", task_ref=m.group(1), text=m.group(2)))
    if m := re.search(r"\bdone\s+#([0-9a-f]{6,8})\b", low):
        return _plan(_step("task_done", task_ref=m.group(1)))
    return None


def _by_case(low: str, data: str) -> dict[str, object] | None:
    found = re.search(_UUID, low) or re.search(rf"^case: ({_UUID})", data, flags=re.M)
    if found is None:
        return None
    case_id = found.group(1) if found.groups() else found.group(0)
    if re.search(r"reply to|draft", low):
        return _plan(_step("draft_reply", case_id=case_id, text=_safe(low)))  # the owner's wording as guidance
    if "status of" in low:
        return _plan(_step("case_status", case_id=case_id))
    return None


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    found = pattern.search(text)
    return found.group(1) if found else None


def _page(prompt: str) -> _Page | None:
    """The page entity from the server facts block only; None when there is no entity to refer to."""
    facts = "\n".join(re.findall(r"<page_facts>\n(.*?)\n</page_facts>", prompt, flags=re.S))
    approval_case = _first(_PAGE_APPROVAL, facts)
    case_id = _first(_PAGE_CASE, facts) or _first(_PAGE_THREAD_CASE, facts) or approval_case
    first = _FIRST_VISIBLE.search(facts)
    row = (first.group(1), first.group(2), first.group(3)) if first else None
    page = _Page(case_id, _first(_PAGE_TASK, facts), approval_case is not None, row)
    return page if (page.case_id or page.task_ref or page.first) else None


def _first_row(low: str, page: _Page) -> dict[str, object]:
    if page.first is None:
        return _plan(_step("clarify", text="Which one do you mean?"))
    kind, ident, rest = page.first
    if kind == "task":
        return _plan(_step("task_done", task_ref=ident)) if "done" in low else _plan(_step("list_tasks"))
    if kind == "case" and re.fullmatch(_UUID, ident):
        return _plan(_step("case_status", case_id=ident))
    if kind == "approval":
        return _plan(_step("open_view", case_id=_first(_ROW_CASE, rest), view="approvals"))
    if kind == "document":
        return _plan(_step("file_document", text="the first document on the page"))
    return _plan(_step("open_view", view="inbox"))


def _task_page(low: str, ref: str) -> dict[str, object] | None:
    if re.search(r"\bsnooze\b", low):
        duration = re.search(r"\b(\d+[mhdw])\b", low)
        if duration is None:
            return _plan(_step("clarify", text="For how long should I snooze it?"))
        return _plan(_step("task_snooze", task_ref=ref, text=duration.group(1)))
    if re.search(r"\bdone\b|\bcomplete", low):
        return _plan(_step("task_done", task_ref=ref))
    return None


def _case_page(low: str, page: _Page) -> dict[str, object] | None:
    if page.approval and re.search(r"\b(okay|ok|good|fine|right)\b|\bdraft\b", low):
        return _plan(_step("open_view", case_id=page.case_id, view="approvals"), _step("answer", text=_safe(low)))
    if re.search(r"\breply\b|\bdraft\b|\banswer (him|her|them)\b", low):
        return _plan(_step("draft_reply", case_id=page.case_id, text=_safe(low)))
    if re.search(r"\b(chase|nudge)\b", low):
        return _plan(_step("chase_now", case_id=page.case_id))
    if re.search(r"summari[sz]e|status|about|what is (this|it)", low):
        return _plan(_step("case_status", case_id=page.case_id))
    return None


def _on_page(low: str, page: _Page) -> dict[str, object] | None:
    if _FIRST_ONE.search(low):
        return _first_row(low, page)
    if not _DEICTIC.search(low):
        return None
    found = _task_page(low, page.task_ref) if page.task_ref else None
    if found is None and page.case_id:
        found = _case_page(low, page)
    return found


def fake_concierge(prompt: str) -> dict[str, object]:
    question = " ".join(re.findall(r"<message>\n(.*?)\n</message>", prompt, flags=re.S))
    data = "\n".join(re.findall(r"<data>\n(.*?)\n</data>", prompt, flags=re.S))
    low = question.lower()
    if _INJECTION.search(low):
        return {"in_scope": False, "steps": []}
    page = _page(prompt)
    if page is not None and (planned := _on_page(low, page)) is not None:
        return planned
    if _PRONOUN.search(low):
        return _plan(_step("clarify", text="Which one do you mean?"))
    return _by_ref(low) or _by_case(low, data.lower()) or _simple(low) or _plan(_step("answer", text=_safe(question)))
