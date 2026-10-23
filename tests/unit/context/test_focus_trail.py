"""Unit tests for focus trail (Task C9)."""

from uuid import uuid4

from app.context.focus_trail import append_focus_trail, page_to_focus_item, render_focus_trail
from app.contracts import PageContext, PageView


def test_page_to_focus_item_extraction() -> None:
    case_id = uuid4()
    approval_id = uuid4()

    # Generic page with no entities
    page1 = PageContext(view=PageView.inbox)
    item1 = page_to_focus_item(page1)
    assert item1 == {"view": "inbox"}

    # Page with case and approval
    page2 = PageContext(view=PageView.case, case_id=case_id, approval_id=approval_id)
    item2 = page_to_focus_item(page2)
    assert item2 == {
        "view": "case",
        "case_id": str(case_id),
        "approval_id": str(approval_id),
    }


def test_append_focus_trail_bounds_and_deduplication() -> None:
    case_1 = str(uuid4())
    case_2 = str(uuid4())
    case_3 = str(uuid4())
    case_4 = str(uuid4())
    case_5 = str(uuid4())
    case_6 = str(uuid4())

    trail: list[dict[str, str]] = []

    # Non-entity page is not appended
    trail = append_focus_trail(trail, {"view": "dashboard"})
    assert trail == []

    # Append first entity page
    item1 = {"view": "case", "case_id": case_1}
    trail = append_focus_trail(trail, item1)
    assert trail == [item1]

    # Consecutive duplicate is ignored
    trail = append_focus_trail(trail, item1)
    assert trail == [item1]

    # Fill up to max (5)
    for c in [case_2, case_3, case_4, case_5]:
        trail = append_focus_trail(trail, {"view": "case", "case_id": c})
    assert len(trail) == 5
    assert trail[0]["case_id"] == case_5

    # 6th entity drops the oldest
    trail = append_focus_trail(trail, {"view": "case", "case_id": case_6})
    assert len(trail) == 5
    assert trail[0]["case_id"] == case_6
    assert case_1 not in [x["case_id"] for x in trail]


def test_render_focus_trail() -> None:
    assert render_focus_trail([]) == ""

    case_id = str(uuid4())
    trail = [{"view": "case", "case_id": case_id}]
    rendered = render_focus_trail(trail)
    assert rendered.startswith("Focus trail: view:case case_id:")
    assert case_id[:8] in rendered
