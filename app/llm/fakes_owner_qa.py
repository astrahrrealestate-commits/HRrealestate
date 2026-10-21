"""Deterministic stand-in for the owner_qa model (offline tests, eval, simulation).

Without page blocks it counts the open cases in `<data>` (unchanged since v2). With a page it describes the page,
always starting with "On this page": the open approval's draft for a draft question, else the first snapshot lines,
else the open item in `<page_facts>`. It never repeats a line that looks like an instruction or carries contact
details, and never an id seen on the page. `case_refs` come from the `<data>` block only. Off-topic owner text
(including requests for its prompt or rules) is refused whether or not a page is present.
"""

import re

_OFF_TOPIC = (
    r"\b(poem|gedicht|recipe|recept|joke|grap|capital of|hoofdstad|python|javascript|bitcoin|translate|vertaal"
    r"|ignore (all )?(previous|prior)|negeer (alle )?(vorige|eerdere)|system ?prompt|systeemprompt"
    r"|your (rules|instructions))\b"
)
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_INSTRUCTION = re.compile(
    r"ignore (all )?(previous|prior)|negeer|instruction|system\s*:|\bapprove|\bsend\b|\bemail\b|\bpay\b|iban"
    r"|password|wachtwoord",
    re.I,
)
_CONTACT = re.compile(r"\S+@\S+|\+?\d[\d\s().-]{6,}\d")
_DRAFT = re.compile(r"^  draft \d+: (.+)$", re.M)
_OPEN = re.compile(r"^open (case|thread|approval|task|document): (.+)$", re.M)
MAX_PAGE_LINES = 3
MAX_PIECE = 200


def _block(prompt: str, tag: str) -> str:
    return "\n".join(re.findall(rf"<{tag}>\n(.*?)\n</{tag}>", prompt, flags=re.S))


def _usable(line: str) -> bool:
    return bool(line.strip()) and not _INSTRUCTION.search(line) and not _CONTACT.search(line)


def _clean(text: str) -> str:
    return " ".join(_UUID.sub("", text).split()).strip(" |")[:MAX_PIECE]


def _page_answer(question: str, facts: str, snapshot: str) -> str:
    draft = _DRAFT.search(facts)
    if re.search(r"\bdraft\b", question) and draft and _usable(draft.group(1)):
        return f"On this page the current draft reads: {_clean(draft.group(1))} (offline answer)"
    lines = [piece for piece in (_clean(line) for line in snapshot.splitlines() if _usable(line)) if piece]
    if lines:
        return f"On this page: {'; '.join(lines[:MAX_PAGE_LINES])} (offline answer)"
    if opened := _OPEN.search(facts):
        return f"On this page: the open {opened.group(1)}, {_clean(opened.group(2))} (offline answer)"
    return "On this page: nothing I can repeat; the page text looks like instructions. (offline answer)"


def fake_owner_qa(prompt: str) -> dict[str, object]:
    question = " ".join(re.findall(r"<message>\n(.*?)\n</message>", prompt, flags=re.S)).lower()
    cases = re.findall(r"^case: ([0-9a-f-]{36})", _block(prompt, "data"), flags=re.M)
    if re.search(_OFF_TOPIC, question):
        return {
            "in_scope": False,
            "refusal_reason": "Unrelated to the business",
            "answer": "Out of scope.",
            "case_refs": [],
        }
    facts, snapshot = _block(prompt, "page_facts"), _block(prompt, "page_snapshot")
    page = facts.strip() or snapshot.strip()
    answer = _page_answer(question, facts, snapshot) if page else f"You have {len(cases)} open cases. (offline answer)"
    return {"in_scope": True, "refusal_reason": None, "answer": answer, "case_refs": cases[:3]}
