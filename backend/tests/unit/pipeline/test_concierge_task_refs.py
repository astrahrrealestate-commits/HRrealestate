"""The planner brief names every open task by its short ref, so a plan can carry a resolvable `task_ref`."""

import re
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from app.contracts import ConciergePlan, Intent
from app.llm.fakes_concierge import fake_concierge
from app.pipeline import concierge_turns as ct
from app.pipeline.concierge_base import task_ref
from app.pipeline.concierge_outcome import build_prompt, task_brief
from app.pipeline.work_repo import short_ref

AT = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
TASK_ID = UUID("0192f0a0-0000-7000-8000-00000000abc1")
M = "app.pipeline.concierge_brief"  # the brief's queries (concierge_turns._brief delegates to it)


def _brief_tasks() -> list[str]:
    start = ct.TurnStart(uuid4(), uuid4(), uuid4(), "what is open?", AT, None, None)
    session = MagicMock()
    session.scalars.return_value.all.return_value = []  # no open cases
    with (
        patch(f"{M}.Session") as session_cls,
        patch(f"{M}.work_repo.open_tasks", return_value=[SimpleNamespace(id=TASK_ID, title="Call plumber")]),
        patch(f"{M}.read_turns.earlier_exchanges", return_value=[]),
    ):
        session_cls.return_value.__enter__.return_value = session
        _, tasks, _ = ct._brief(MagicMock(), start)
    return tasks


def test_brief_tasks_carry_their_short_ref() -> None:
    tasks = _brief_tasks()
    assert tasks == [f"#{short_ref(TASK_ID)} Call plumber"] == [task_brief(TASK_ID, "Call plumber")]
    data = re.search(r"<data>\n(.*?)\n</data>", build_prompt("what is open?", [], [], tasks), flags=re.S)
    assert data is not None
    assert f"task: #{short_ref(TASK_ID)} Call plumber" in data.group(1)


def test_a_ref_taken_from_the_brief_resolves_to_the_task() -> None:
    prompt = build_prompt("what is open?", [], [], _brief_tasks())
    found = re.search(r"task: #([0-9a-f]{6}) ", prompt)
    assert found is not None
    ref = found.group(1)
    plan = ConciergePlan.model_validate(fake_concierge(build_prompt(f"done #{ref}", [], [], _brief_tasks())))
    [step] = plan.steps
    assert step.intent is Intent.task_done
    resolved = task_ref(step.task_ref)
    assert resolved == short_ref(TASK_ID)
    assert str(TASK_ID).endswith(resolved)  # work_repo.resolve_task matches the id's string suffix
