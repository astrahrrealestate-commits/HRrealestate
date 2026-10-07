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

    if re.search(r"(ignore previous|iban|bankrekening wijzig)", low):
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


def _fake_link_check(prompt: str) -> dict[str, object]:
    m = re.search(r"candidate:\s*([0-9a-fA-F-]{36})", prompt)
    if m:
        return {"case_id": m.group(1), "reason": "Matched candidate case", "confidence": 0.8}
    return {"case_id": None, "reason": "No matching candidate case", "confidence": 0.8}


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
        else:
            args = {}

        return ModelResponse(parts=[ToolCallPart(tool_name, args)])

    return FunctionModel(fn)
