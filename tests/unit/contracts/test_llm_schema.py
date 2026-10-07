"""LLM-facing contracts must be valid OpenAI strict-mode structured-output schemas."""

from typing import Any

import pytest
from pydantic import BaseModel

from app.contracts import Action, CaseSummary, LinkDecision, OwnerAnswer, Proposal, Understanding

FORBIDDEN_KEYS = {"oneOf", "discriminator", "default", "minLength", "maxLength"}


def _walk(node: Any, path: str = "$") -> list[str]:
    problems: list[str] = []
    if isinstance(node, dict):
        problems += [f"{path}: forbidden keyword {k!r}" for k in FORBIDDEN_KEYS & node.keys()]
        if node.get("type") == "object" or "properties" in node:
            props = list(node.get("properties", {}))
            if node.get("additionalProperties") is not False:
                problems.append(f"{path}: additionalProperties must be false")
            if sorted(node.get("required", [])) != sorted(props):
                problems.append(f"{path}: required must list every property")
        pattern = node.get("pattern")
        if isinstance(pattern, str) and ("(?=" in pattern or "(?!" in pattern):
            problems.append(f"{path}: lookaround in pattern")
        for key, child in node.items():
            problems += _walk(child, f"{path}.{key}")
    elif isinstance(node, list):
        for i, child in enumerate(node):
            problems += _walk(child, f"{path}[{i}]")
    return problems


@pytest.mark.parametrize("model", [Understanding, Action, LinkDecision, CaseSummary, Proposal, OwnerAnswer])
def test_strict_mode_compatible(model: type[BaseModel]) -> None:
    assert _walk(model.model_json_schema()) == []
