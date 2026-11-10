"""The step badges under a Super Agent answer only name work that really happened."""

from app.api.agent.steps import display_steps

DRAFT = ["Retrieved ticket context", "Prepared draft reply", "Queued for approval"]


def test_no_steps_and_no_draft_means_no_badges_not_invented_ones() -> None:
    assert display_steps([], has_draft_card=False) == []


def test_chatter_instead_of_steps_is_dropped() -> None:
    assert display_steps(["Opening cases.", "Which case do you mean?"], has_draft_card=False) == []


def test_a_draft_card_gets_the_draft_steps() -> None:
    assert display_steps([], has_draft_card=True) == DRAFT
    assert display_steps(["Opening cases."], has_draft_card=True) == DRAFT


def test_real_steps_are_kept() -> None:
    assert display_steps(["Searched documents", "Read the lease"], has_draft_card=False) == [
        "Searched documents",
        "Read the lease",
    ]


def test_a_long_step_is_shortened() -> None:
    assert display_steps(["x" * 85], has_draft_card=False) == ["x" * 77 + "..."]


def test_model_text_posing_as_a_step_is_dropped() -> None:
    assert display_steps(["Based on active portfolio data, the answer is 3"], has_draft_card=False) == []
    assert display_steps(["First, I will look at the queue"], has_draft_card=False) == []
