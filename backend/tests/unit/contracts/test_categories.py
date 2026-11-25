"""The six business categories (M13 spec, goal 1): one enum for understanding, cases, inbox and the dashboard."""

import pytest

from app.contracts import Category
from app.contracts.categories import CATEGORY_LABELS, LEGACY_CATEGORIES, SHOWN_CATEGORIES, current_category
from app.contracts.understanding import Understanding


def test_categories_are_the_six_and_spam() -> None:
    assert [c.value for c in Category] == [
        "maintenance",
        "finance",
        "legal",
        "business",
        "administration",
        "new_projects",
        "spam",
    ]


def test_shown_categories_are_the_six_in_display_order_without_spam() -> None:
    assert [c.value for c in SHOWN_CATEGORIES] == [
        "maintenance",
        "finance",
        "legal",
        "business",
        "administration",
        "new_projects",
    ]
    assert [CATEGORY_LABELS[c] for c in SHOWN_CATEGORIES] == [
        "Maintenance",
        "Finance",
        "Legal",
        "Business",
        "Administration",
        "New projects",
    ]


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("maintenance", "maintenance"),
        ("contractor_update", "maintenance"),
        ("complaint", "maintenance"),
        ("payment", "finance"),
        ("lease", "legal"),
        ("admin", "administration"),
        ("other", "administration"),
        ("spam", "spam"),
    ],
)
def test_old_values_map_to_the_new_categories(old: str, new: str) -> None:
    assert LEGACY_CATEGORIES.get(old, old) == new
    assert current_category(old) == Category(new)


def test_current_category_keeps_new_values() -> None:
    assert current_category("new_projects") is Category.new_projects


def test_research_fields_default_for_stored_bodies() -> None:
    body = {
        "category": "finance",
        "intent": "Huur",
        "urgency": "normal",
        "requires_reply": True,
        "entities": {"people": [], "unit_refs": [], "dates": [], "amounts": []},
        "suspicious": {"flag": False, "reason": None},
        "confidence": 0.9,
        "sender_role": None,
        "prompt_version": "understanding/v3",
    }
    u = Understanding.model_validate(body)
    assert u.needs_research is False
    assert u.research_questions == []


def test_research_questions_are_capped_at_three() -> None:
    with pytest.raises(ValueError):
        Understanding.model_validate(
            {
                "category": "maintenance",
                "intent": "Offerte",
                "urgency": "normal",
                "requires_reply": True,
                "entities": {"people": [], "unit_refs": [], "dates": [], "amounts": []},
                "suspicious": {"flag": False, "reason": None},
                "confidence": 0.9,
                "sender_role": None,
                "prompt_version": "understanding/v4",
                "needs_research": True,
                "research_questions": ["a?", "b?", "c?", "d?"],
            }
        )
