from typing import Any

import pytest
from pydantic import ValidationError

from app.contracts import ConciergePlan, Intent, PlanStep


def _step(**kw: Any) -> dict[str, Any]:
    return {"intent": "list_tasks", "case_id": None, "task_ref": None, "text": None, "view": None, **kw}


def test_valid_plan() -> None:
    plan = ConciergePlan.model_validate(
        {"in_scope": True, "steps": [_step(task_ref="a1b2c3", text="2d")], "reply": None}
    )
    assert plan.steps[0].intent is Intent.list_tasks


def test_intent_list_is_exact() -> None:
    assert len(Intent) == 23
    assert Intent.query_data in Intent
    assert Intent.show_drafts in Intent
    for name in ("remember", "calendar", "rent_status"):  # concierge/v8
        assert Intent(name).value == name
    assert "rewrite_draft" not in {i.value for i in Intent}  # a redraft is `draft_reply`


def test_rejects_five_steps() -> None:
    with pytest.raises(ValidationError):
        ConciergePlan.model_validate({"in_scope": True, "steps": [_step()] * 5, "reply": None})


@pytest.mark.parametrize(
    "bad", [_step(intent="approve_all"), _step(text="x" * 401), _step(task_ref="a" * 9), _step(view="settings")]
)
def test_rejects_bad_step(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PlanStep.model_validate(bad)


def test_boundary_lengths_pass() -> None:
    PlanStep.model_validate(_step(text="x" * 400, task_ref="a" * 8))


def test_missing_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        PlanStep.model_validate({"intent": "pause"})
    with pytest.raises(ValidationError):
        ConciergePlan.model_validate({"in_scope": True})


def test_reply_is_required_nullable_and_capped_at_1200() -> None:
    with pytest.raises(ValidationError):  # strict schema: required, like every other nullable field
        ConciergePlan.model_validate({"in_scope": True, "steps": []})
    assert ConciergePlan.model_validate({"in_scope": True, "steps": [], "reply": None}).reply is None
    assert ConciergePlan.model_validate({"in_scope": True, "steps": [], "reply": "x" * 1200}).reply == "x" * 1200
    with pytest.raises(ValidationError):
        ConciergePlan.model_validate({"in_scope": True, "steps": [], "reply": "x" * 1201})


def test_reply_is_in_the_strict_schema_as_a_required_nullable_string() -> None:
    schema = ConciergePlan.model_json_schema()
    assert "reply" in schema["required"]
    assert {"type": "null"} in schema["properties"]["reply"]["anyOf"]


def test_suggestions_defaults_to_empty_and_capped_at_three() -> None:
    plan = ConciergePlan.model_validate({"in_scope": True, "steps": [], "reply": None})
    assert plan.suggestions == []

    plan_with_sugg = ConciergePlan.model_validate(
        {
            "in_scope": True,
            "steps": [],
            "reply": None,
            "suggestions": ["Draft payment reminder", "Show lease PDF", "Open in Money"],
        }
    )
    assert len(plan_with_sugg.suggestions) == 3

    with pytest.raises(ValidationError):
        ConciergePlan.model_validate(
            {
                "in_scope": True,
                "steps": [],
                "reply": None,
                "suggestions": ["One", "Two", "Three", "Four"],
            }
        )
