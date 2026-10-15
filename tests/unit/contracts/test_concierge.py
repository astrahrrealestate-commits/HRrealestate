from typing import Any

import pytest
from pydantic import ValidationError

from app.contracts import ConciergePlan, Intent, PlanStep


def _step(**kw: Any) -> dict[str, Any]:
    return {"intent": "list_tasks", "case_id": None, "task_ref": None, "text": None, "view": None, **kw}


def test_valid_plan() -> None:
    plan = ConciergePlan.model_validate({"in_scope": True, "steps": [_step(task_ref="a1b2c3", text="2d")]})
    assert plan.steps[0].intent is Intent.list_tasks


def test_intent_list_is_exact() -> None:
    assert len(Intent) == 16


def test_rejects_five_steps() -> None:
    with pytest.raises(ValidationError):
        ConciergePlan.model_validate({"in_scope": True, "steps": [_step()] * 5})


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
