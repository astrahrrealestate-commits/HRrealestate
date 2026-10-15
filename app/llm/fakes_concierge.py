"""Deterministic keyword router standing in for the concierge model (offline tests, eval, simulation)."""

import re

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_INJECTION = re.compile(
    r"ignore previous|iban|bankrekening wijzig|nieuw(e)? rekeningnummer|approve all|\bsend\b.{0,60}\bto\b"
    r"|verify your (bank|account|payment) details|update your (bank|payment) details"
)
_EMAIL = re.compile(r"\S+@\S+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")


def _step(
    intent: str, case_id: str | None = None, task_ref: str | None = None, text: str | None = None
) -> dict[str, object]:
    return {"intent": intent, "case_id": case_id, "task_ref": task_ref, "text": text, "view": None}


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
        return _plan(_step("draft_reply", case_id=case_id))
    if "status of" in low:
        return _plan(_step("case_status", case_id=case_id))
    return None


def fake_concierge(prompt: str) -> dict[str, object]:
    question = " ".join(re.findall(r"<message>\n(.*?)\n</message>", prompt, flags=re.S))
    data = "\n".join(re.findall(r"<data>\n(.*?)\n</data>", prompt, flags=re.S))
    low = question.lower()
    if _INJECTION.search(low):
        return {"in_scope": False, "steps": []}
    return _by_ref(low) or _by_case(low, data.lower()) or _simple(low) or _plan(_step("answer", text=_safe(question)))
