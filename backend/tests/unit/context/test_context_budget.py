"""Unit tests for enforcing a ContextSpec's declared character budgets."""

from app.context.budget import clip, fit_to_budget
from app.context.spec import CONCIERGE_SPEC, ContextSpec, Slice


def test_clip_leaves_short_text_alone() -> None:
    assert clip("short", 100) == "short"


def test_clip_never_exceeds_limit_and_marks_the_cut() -> None:
    text = "\n".join(f"line {i}" for i in range(200))
    out = clip(text, 120)
    assert len(out) <= 120
    assert out.endswith("[…trimmed]")
    assert out.startswith("line 0")


def test_clip_cuts_on_a_line_boundary_when_one_is_near() -> None:
    out = clip("alpha\nbravo\ncharlie\ndelta", 24)
    assert "charl" not in out
    assert "bravo" in out


def test_clip_zero_limit_is_empty() -> None:
    assert clip("anything", 0) == ""


def test_under_budget_is_unchanged_and_nothing_dropped() -> None:
    contents = {"data": "cases", "history": "earlier", "message": "question"}
    fitted, dropped = fit_to_budget(CONCIERGE_SPEC, contents)
    assert fitted == contents
    assert dropped == ()


def test_each_slice_is_clipped_to_its_own_budget() -> None:
    fitted, _ = fit_to_budget(CONCIERGE_SPEC, {"history": "h" * 9000, "message": "question"})
    assert len(fitted["history"]) <= 5000
    assert fitted["message"] == "question"


def test_total_overflow_trims_lowest_drop_order_first_and_keeps_the_message() -> None:
    spec = ContextSpec(
        agent="t",
        slices=(
            Slice(name="data", stability=2, budget_chars=1000, trusted=True, drop_order=3),
            Slice(name="snapshot", stability=5, budget_chars=1000, trusted=False, drop_order=1),
            Slice(name="message", stability=6, budget_chars=1000, trusted=False, drop_order=6),
        ),
        total_chars=1500,
    )
    fitted, dropped = fit_to_budget(spec, {"data": "d" * 1000, "snapshot": "s" * 1000, "message": "m" * 400})
    assert sum(len(v) for v in fitted.values()) <= 1500
    assert fitted["data"] == "d" * 1000
    assert fitted["message"] == "m" * 400
    assert len(fitted["snapshot"]) < 1000
    assert dropped == ()


def test_a_slice_squeezed_to_nothing_is_reported_as_dropped() -> None:
    spec = ContextSpec(
        agent="t",
        slices=(
            Slice(name="data", stability=2, budget_chars=1000, trusted=True, drop_order=3),
            Slice(name="snapshot", stability=5, budget_chars=1000, trusted=False, drop_order=1),
            Slice(name="message", stability=6, budget_chars=1000, trusted=False, drop_order=6),
        ),
        total_chars=1000,
    )
    fitted, dropped = fit_to_budget(spec, {"data": "d" * 900, "snapshot": "s" * 400, "message": "m" * 100})
    assert fitted["snapshot"] == ""
    assert dropped == ("snapshot",)
    assert sum(len(v) for v in fitted.values()) <= 1000


def test_names_outside_the_spec_pass_through() -> None:
    fitted, dropped = fit_to_budget(CONCIERGE_SPEC, {"message": "q", "extra": "x" * 50000})
    assert fitted["extra"] == "x" * 50000
    assert dropped == ()
