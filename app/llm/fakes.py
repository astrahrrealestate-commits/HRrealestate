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
    if re.search(r"\b(lek|lekkage|leak|leaking|heizung|verwarming|kapot|broken)\b", low):
        category = Category.maintenance
        intent = "Maintenance request"
    elif re.search(r"\b(huur|miete|rent|betaling)\b", low):
        category = Category.payment
        intent = "Payment inquiry"
    elif re.search(r"\b(contract|kündigung|opzeg)\b", low):
        category = Category.lease
        intent = "Lease inquiry"
    elif re.search(r"\b(offerte|quote|factuur|invoice)\b", low):
        category = Category.contractor_update
        intent = "Contractor update"
    else:
        category = Category.other
        intent = "General inquiry"

    urgency = Urgency.emergency if re.search(r"\b(lek|lekkage|wasser|water|gas|brand|fire)\b", low) else Urgency.normal

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
        else:
            args = {}

        return ModelResponse(parts=[ToolCallPart(tool_name, args)])

    return FunctionModel(fn)
