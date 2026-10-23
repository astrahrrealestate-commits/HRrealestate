from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.pipeline.dashboard_decisions import flags_for

M1, M2, CASE_A, CASE_B = uuid4(), uuid4(), uuid4(), uuid4()
FLAGGED: dict[str, Any] = {"suspicious": {"flag": True}}
CLEAN: dict[str, Any] = {"suspicious": {"flag": False}}


def _action(case: Any, refs: list[Any]) -> Any:
    return SimpleNamespace(id=uuid4(), case_id=case, context_ref=refs)


def test_refs_decide_when_present_and_case_is_the_fallback_only_without_refs() -> None:
    with_refs_clean = _action(CASE_A, [M2])
    with_refs_flagged = _action(CASE_A, [M1, M2])
    no_refs_flagged_case = _action(CASE_A, [])
    no_refs_clean_case = _action(CASE_B, [])
    by_message = {M1: [FLAGGED], M2: [CLEAN]}
    by_case = {CASE_A: [FLAGGED], CASE_B: [CLEAN]}
    got = flags_for([with_refs_clean, with_refs_flagged, no_refs_flagged_case, no_refs_clean_case], by_message, by_case)
    assert got == {
        with_refs_clean.id: False,  # the case holds a flagged message, but the action answers a clean one
        with_refs_flagged.id: True,
        no_refs_flagged_case.id: True,
        no_refs_clean_case.id: False,
    }


def test_missing_understandings_are_not_suspicious() -> None:
    a = _action(CASE_A, [M1])
    assert flags_for([a], {}, {}) == {a.id: False}
