"""Deterministic stand-in for the proposer model (offline tests, eval, simulation).

An owner-requested draft (`<owner_guidance>` present) is honoured through a few allowed keywords only: length
("kort"/"short"), a day ("dinsdag"/"Tuesday", "vandaag", "morgen") and a trade ("loodgieter"/"plumber"). The reply is
built from fixed Dutch phrases, so the guidance text itself (and anything redacted out of it) is never echoed.
"""

import re

_SIGN = "\n\nMet vriendelijke groet,\nHarjot"
_SHORT = re.compile(r"\b(kort|korter|short|shorter|brief|briefly)\b")
_DAYS = (
    (r"maandag|monday", "maandag"), (r"dinsdag|tuesday", "dinsdag"), (r"woensdag|wednesday", "woensdag"),
    (r"donderdag|thursday", "donderdag"), (r"vrijdag|friday", "vrijdag"), (r"zaterdag|saturday", "zaterdag"),
    (r"vandaag|today", "vandaag"), (r"morgen|tomorrow", "morgen"),
)  # fmt: skip
_WHO = ((r"loodgieter|plumber", "De loodgieter"), (r"elektricien|electrician", "De elektricien"),
        (r"vakman|contractor|monteur", "De vakman"))  # fmt: skip


def _block(prompt: str, tag: str) -> str | None:
    found = re.search(rf"<{tag}>\n(.*?)\n</{tag}>", prompt, flags=re.S)
    return found.group(1) if found else None


def _field(prompt: str, name: str) -> str:
    m = re.search(rf"^{name}: (.*)$", prompt, flags=re.M)
    return m.group(1).strip() if m else ""


def _action(case_id: str, kind: str, payload: dict[str, object], rationale: str) -> dict[str, object]:
    return {
        "type": kind,
        "case_id": case_id,
        "payload": {"kind": kind, **payload},
        "rationale": rationale,
        "context_ref": [],
        "draft_version": 1,
    }


def _pick(table: tuple[tuple[str, str], ...], low: str) -> str | None:
    return next((word for pattern, word in table if re.search(rf"\b({pattern})\b", low)), None)


def _sentence(low: str) -> str:
    day, who = _pick(_DAYS, low), _pick(_WHO, low)
    if day and who:
        return f"{who} komt {day} bij u langs."
    if day:
        return f"Wij komen {day} bij u langs."
    if who:
        return f"{who} neemt zo snel mogelijk contact met u op."
    return "Wij nemen uw bericht in behandeling."


def guided_variants(guidance: str) -> list[str]:
    """Two Dutch replies from the guidance keywords; short ones when asked (or when shortening a current draft)."""
    low = guidance.lower()
    sentence = _sentence(low)
    if _SHORT.search(low):
        return [f"Beste,\n\n{sentence}{_SIGN}", f"Geachte heer/mevrouw,\n\n{sentence} Dank voor uw geduld.{_SIGN}"]
    return [
        f"Geachte heer/mevrouw,\n\nDank voor uw bericht. {sentence} Wij houden u op de hoogte.{_SIGN}",
        f"Geachte heer/mevrouw,\n\nDank voor uw bericht. {sentence} Laat u het ons weten als er iets verandert?{_SIGN}",
    ]


_CHASE = [
    "Geachte heer/mevrouw,\n\nGraag herinneren wij u aan ons eerdere bericht. Kunt u reageren?" + _SIGN,
    "Beste,\n\nWij wachten nog op uw reactie. Laat u het ons weten?" + _SIGN,
]
_REPLY = [
    "Geachte heer/mevrouw,\n\nDank voor uw bericht. Wij nemen dit in behandeling en komen zo snel "
    "mogelijk bij u terug." + _SIGN,
    "Geachte heer/mevrouw,\n\nDank voor uw bericht. Kunt u een foto sturen, zodat wij de juiste "
    "vakman kunnen inschakelen?" + _SIGN,
]


_ENTRY = re.compile(r"\[ref [0-9a-f]{8}\] ([^\n]*)\n(.*?)(?=\n\n---\n\n|\Z)", re.S)


def _cited_clause(prompt: str) -> tuple[str, str] | None:
    """The excerpt sentence that shares the most words with the tenant's message, with its document title."""
    asked = set(re.findall(r"[^\W_]{5,}", (_block(prompt, "message") or "").lower()))
    best: tuple[int, str, str] = (0, "", "")
    for head, text in _ENTRY.findall(_block(prompt, "excerpts") or ""):
        for sentence in re.split(r"(?<=[.!?\n])\s+", text):
            score = len(asked & set(re.findall(r"[^\W_]{5,}", sentence.lower())))
            if score > best[0]:
                best = (score, head.split(" (")[0], sentence.strip()[:240])
    return (best[1], best[2]) if best[0] else None


def fake_proposer(prompt: str) -> dict[str, object]:
    case_id, channel = _field(prompt, "case_id"), _field(prompt, "channel") or "whatsapp"
    subject = _field(prompt, "Subject")
    reply_subject = f"Re: {subject}" if channel == "gmail" and subject not in ("", "-") else None
    guidance = _block(prompt, "owner_guidance")
    if "<mode>chase</mode>" in prompt:
        variants, rationale = _CHASE, "Friendly chaser"
    elif guidance is not None:
        variants, rationale = guided_variants(guidance), "Reply as the owner asked"
    else:
        variants, rationale = list(_REPLY), "Acknowledge and ask for details"
        if cited := _cited_clause(prompt):
            title, sentence = cited
            variants.append(f"Geachte heer/mevrouw,\n\nVolgens {title} geldt: {sentence}{_SIGN}")
            rationale = f"Answer from {title}"
    payload: dict[str, object] = {"channel": channel, "subject": reply_subject, "body_variants": variants}
    actions = [_action(case_id, "reply_draft", payload, rationale)]
    if "<mode>chase</mode>" not in prompt and _field(prompt, "urgency") == "emergency":
        actions.append(_action(case_id, "escalate", {"reason": "Emergency reported by tenant"}, "Emergency"))
    return {"actions": actions}
