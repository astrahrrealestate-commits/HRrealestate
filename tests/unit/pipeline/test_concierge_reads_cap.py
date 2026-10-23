from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy import Engine

from app.contracts import Intent, PlanStep
from app.core.settings import Settings
from app.pipeline import case_repo, concierge_reads, owner_commands
from app.pipeline.concierge_base import Ctx


class _Session:
    def __init__(self, _engine: object) -> None: ...
    def __enter__(self) -> "_Session":
        return self

    def __exit__(self, *_: object) -> None: ...


def test_case_status_caps_the_untrusted_case_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    value = SimpleNamespace(value="open")
    case = SimpleNamespace(id=UUID(int=1), state=value, urgency=value, category=value, summary="x" * 5000)
    monkeypatch.setattr(concierge_reads, "Session", _Session)
    monkeypatch.setattr(case_repo, "get_case", lambda *_: case)
    monkeypatch.setattr(owner_commands, "case_label", lambda *_: "Sanne")
    ctx = Ctx(cast(Engine, None), cast(Settings, None), UUID(int=2), datetime.now(UTC), "q")
    step = PlanStep(intent=Intent.case_status, case_id=case.id, task_ref=None, text=None, view=None)
    result = concierge_reads.case_status(ctx, step)
    assert result.data is not None
    assert len(result.data["summary"]) == concierge_reads.MAX_SUMMARY == 400
