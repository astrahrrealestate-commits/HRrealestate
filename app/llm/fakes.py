"""Deterministic fake LLM models (FunctionModel) for offline tests, eval and simulation."""

import re

from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.contracts import Category, Urgency


def _extract_user_text(messages: list[ModelMessage]) -> str:
    for m in reversed(messages):
        for part in getattr(m, "parts", []):
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                return part.content
    return ""


_SUSPICIOUS = (
    r"ignore previous|iban|bankrekening wijzig"
    r"|rekeningnummer\b.{0,40}\bgewijzigd|gewijzigd\b.{0,40}\brekeningnummer|nieuw(e)? rekeningnummer"
    r"|verify your (bank|account|payment) details|update your (bank|payment) details"
)


def _fake_understanding(prompt: str) -> dict[str, object]:
    low = prompt.lower()
    if re.search(r"(contract|kündigung|opzeg|verhuis)", low):
        category = Category.lease
        intent = "Lease inquiry"
    elif re.search(r"(lek|leak|overstrom|flood|heizung|verwarming|kapot|broken|gaslucht|\bgas\b|brand|fire)", low):
        category = Category.maintenance
        intent = "Maintenance request"
    elif re.search(r"(huur|miete|\brent\b|betal)", low):
        category = Category.payment
        intent = "Payment inquiry"
    elif re.search(r"(offerte|quote|factuur|invoice)", low):
        category = Category.contractor_update
        intent = "Contractor update"
    else:
        category = Category.other
        intent = "General inquiry"

    if re.search(r"(overstrom|flood|gaslucht|\bgas\b|\bbrand\b|fire|rook|smoke|water staat)", low):
        urgency = Urgency.emergency
    elif category is Category.maintenance:
        urgency = Urgency.high
    else:
        urgency = Urgency.normal

    if re.search(_SUSPICIOUS, low):
        suspicious = {"flag": True, "reason": "Suspicious instruction or payment details"}
    else:
        suspicious = {"flag": False, "reason": None}

    return {
        "category": category.value,
        "intent": intent,
        "urgency": urgency.value,
        "entities": {"people": [], "unit_refs": [], "dates": [], "amounts": []},
        "suspicious": suspicious,
        "confidence": 0.6,
        "prompt_version": "understanding/v1",
    }


_WORD = re.compile(r"[a-zà-ÿ]{4,}")
_STOPWORDS = frozenset(
    [
        "deze",
        "niet",
        "maar",
        "voor",
        "heeft",
        "hebben",
        "wordt",
        "worden",
        "zijn",
        "naar",
        "over",
        "onder",
        "alle",
        "weer",
        "still",
        "with",
        "this",
        "that",
        "have",
        "from",
        "been",
        "were",
        "will",
        "they",
        "their",
        "about",
        "again",
        "since",
    ]
)
# Summaries are English (case_summary writes them), messages mostly Dutch: map common Dutch terms so the offline
# fake can see an overlap a real model would see.
_NL_EN = {
    "lekt": "leak", "lekkage": "leak", "lekken": "leak", "gootsteen": "sink", "keuken": "kitchen",
    "badkamer": "bathroom", "deurbel": "doorbell", "schimmel": "mould", "plafond": "ceiling", "borg": "deposit",
    "huur": "rent", "verwarming": "heating", "kachel": "radiator", "opzegging": "notice", "onderhuur": "sublet",
    "onderverhuren": "sublet", "wonen": "sublet", "raam": "window", "foto": "photos", "betaalbewijs": "rent",
}  # fmt: skip


def _terms(text: str) -> set[str]:
    words = {w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS}
    return words | {_NL_EN[w] for w in words if w in _NL_EN}


def _fake_link_check(prompt: str) -> dict[str, object]:
    """Pick the candidate whose summary shares the most words with the message; none shared → new case."""
    blocks = re.findall(r"<message>\n(.*?)\n</message>", prompt, flags=re.S)
    message = _terms(blocks[-1]) if blocks else set()
    best, best_score = None, 0
    for case_id, summary in re.findall(r"candidate:\s*([0-9a-fA-F-]{36})[^\n]*\n\s*([^\n]*)", prompt):
        score = len(message & _terms(summary))
        if score > best_score:
            best, best_score = case_id, score
    if best is None:
        return {"case_id": None, "reason": "No shared topic with any open case", "confidence": 0.7}
    return {"case_id": best, "reason": "Shares the topic of this open case", "confidence": 0.8}


def _fake_case_summary(prompt: str) -> dict[str, object]:
    blocks = re.findall(r"<message>\n(.*?)\n</message>", prompt, flags=re.S)
    text = " ".join(blocks[-1].split())[:200] if blocks else "Case opened."
    return {"summary": text, "next_step": "Review and reply"}


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


def _fake_proposer(prompt: str) -> dict[str, object]:
    case_id, channel = _field(prompt, "case_id"), _field(prompt, "channel") or "whatsapp"
    subject = _field(prompt, "Subject")
    reply_subject = f"Re: {subject}" if channel == "gmail" and subject not in ("", "-") else None
    if "<mode>chase</mode>" in prompt:
        variants = [
            "Geachte heer/mevrouw,\n\nGraag herinneren wij u aan ons eerdere bericht. Kunt u reageren?"
            "\n\nMet vriendelijke groet,\nHarjot",
            "Beste,\n\nWij wachten nog op uw reactie. Laat u het ons weten?\n\nMet vriendelijke groet,\nHarjot",
        ]
        return {
            "actions": [
                _action(
                    case_id,
                    "reply_draft",
                    {"channel": channel, "subject": reply_subject, "body_variants": variants},
                    "Friendly chaser",
                )
            ]
        }
    variants = [
        "Geachte heer/mevrouw,\n\nDank voor uw bericht. Wij nemen dit in behandeling en komen zo snel "
        "mogelijk bij u terug.\n\nMet vriendelijke groet,\nHarjot",
        "Geachte heer/mevrouw,\n\nDank voor uw bericht. Kunt u een foto sturen, zodat wij de juiste "
        "vakman kunnen inschakelen?\n\nMet vriendelijke groet,\nHarjot",
    ]
    actions = [
        _action(
            case_id,
            "reply_draft",
            {"channel": channel, "subject": reply_subject, "body_variants": variants},
            "Acknowledge and ask for details",
        )
    ]
    if _field(prompt, "urgency") == "emergency":
        actions.append(_action(case_id, "escalate", {"reason": "Emergency reported by tenant"}, "Emergency"))
    return {"actions": actions}


def _fake_owner_qa(prompt: str) -> dict[str, object]:
    cases = re.findall(r"^case: ([0-9a-f-]{36})", prompt, flags=re.M)
    return {"answer": f"You have {len(cases)} open cases. (offline answer)", "case_refs": cases[:3]}


def _fake_briefing(prompt: str) -> dict[str, object]:
    sections: list[dict[str, object]] = []
    items: list[str] = []
    for line in prompt.splitlines():
        if line.startswith("## "):
            items = []
            sections.append({"title": line[3:][:40], "items": items})
        elif line.startswith("- ") and sections and len(items) < 8:
            items.append(line[2:][:240])
    return {"headline": f"{len(sections)} topics today (offline briefing).", "sections": sections[:6]}


_DOC_KEYWORDS = (
    (r"factuur|invoice|\bnota\b", "invoice", "Invoice"),
    (r"huurcontract|huurovereenkomst|\blease\b", "lease", "Lease agreement"),
    (r"offerte|prijsopgave|\bquote\b", "quote", "Quote"),
    (r"paspoort|passport|id-kaart|identiteitskaart|rijbewijs", "id_document", "Identity document"),
    (r"polis|verzekering|insurance", "insurance", "Insurance document"),
    (r"keuring|certifica|energielabel|attest", "certificate", "Certificate"),
)


def _fake_doc_classifier(prompt: str) -> dict[str, object]:
    low = prompt.lower()
    for pattern, doc_type, title in _DOC_KEYWORDS:
        if re.search(pattern, low):
            return {"doc_type": doc_type, "title": title, "document_date": None, "confidence": 0.85}
    if "mime_type: image/" in low:
        return {"doc_type": "photo", "title": "Photo", "document_date": None, "confidence": 0.5}
    return {"doc_type": "other", "title": "Document", "document_date": None, "confidence": 0.4}


def model_for(agent_name: str) -> FunctionModel:
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        user_text = _extract_user_text(messages)
        tool_name = info.output_tools[0].name if info.output_tools else "output"

        if agent_name == "understanding":
            args = _fake_understanding(user_text)
        elif agent_name == "link_check":
            args = _fake_link_check(user_text)
        elif agent_name == "case_summary":
            args = _fake_case_summary(user_text)
        elif agent_name == "proposer":
            args = _fake_proposer(user_text)
        elif agent_name == "owner_qa":
            args = _fake_owner_qa(user_text)
        elif agent_name == "briefing":
            args = _fake_briefing(user_text)
        elif agent_name == "doc_classifier":
            args = _fake_doc_classifier(user_text)
        else:
            args = {}

        return ModelResponse(parts=[ToolCallPart(tool_name, args)])

    return FunctionModel(fn)
