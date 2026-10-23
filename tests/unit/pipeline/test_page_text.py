"""Page facts text helpers: normalised one-line values, UTC stamps, the size budget and its drop order."""

from datetime import UTC, datetime, timedelta, timezone

from app.llm.page_blocks import MAX_PAGE_FACTS
from app.pipeline import page_text as pt
from app.pipeline.page_text import Line, fit, one_line, render, stamp


def test_budget_is_the_page_facts_block_cap() -> None:
    assert pt.FACTS_BUDGET == MAX_PAGE_FACTS == 12000


def test_one_line_normalises_before_capping() -> None:
    expanding = chr(0xFDFA) * 50  # NFKC expands this one character to 18
    capped = one_line(expanding, 100)
    assert len(capped) == 100
    assert one_line("a b c\x85d\x1ce\vf\fg", 50) == "a b c d e f g"
    assert one_line("<／page_facts>", 50) == "</page_facts>"  # fullwidth solidus folded (escaped later)


def test_stamp_is_utc_minutes() -> None:
    amsterdam = timezone(timedelta(hours=2))
    assert stamp(datetime(2026, 10, 20, 11, 15, 59, tzinfo=amsterdam)) == "2026-10-20 09:15Z"
    assert stamp(datetime(2026, 10, 20, 9, 15, tzinfo=UTC)) == "2026-10-20 09:15Z"


def _sizes(lines: list[Line]) -> int:
    return sum(len(x.text) + 1 for x in lines)


def test_fit_drops_lower_groups_first_and_lowest_order_first() -> None:
    lines = [
        Line("keep " + "k" * 20),
        Line("old-1", pt.OLD_MESSAGES, 1),
        Line("old-2", pt.OLD_MESSAGES, 2),
        Line("row-a", pt.VISIBLE, 0),
        Line("row-b", pt.VISIBLE, -1),
        Line("new-9", pt.NEWEST_MESSAGES, 9),
    ]
    assert fit(lines, 10_000) == lines
    kept = fit(lines, _sizes(lines) - 6)
    assert [x.text for x in kept][1:] == ["old-2", "row-a", "row-b", "new-9"]
    kept = fit(lines, _sizes(lines) - 18)
    assert [x.text for x in kept][1:] == ["row-a", "new-9"]  # both old messages, then the bottom row
    kept = fit(lines, 1)
    assert [x.text for x in kept] == ["keep " + "k" * 20]  # never-dropped lines stay even over budget


def test_render_marks_message_gaps_and_what_was_left_out() -> None:
    lines = [
        Line("conversation (thread, 40 messages, oldest first, times UTC):"),
        *(Line(f"  msg {s:02d} | m", pt.OLD_MESSAGES, s, s) for s in (1, 2, 17, 18)),
        Line("  msg 40 | newest", pt.NEWEST_MESSAGES, 40, 40),
        Line("- row", pt.VISIBLE, 0),
        Line("  event: e", pt.EVENTS, 0),
    ]
    text = render(lines, _sizes(lines) - 5 + pt.MARKER_RESERVE)  # the first message must go
    assert text.splitlines() == [
        "conversation (thread, 40 messages, oldest first, times UTC):",
        "  (1 message not shown)",
        "  msg 02 | m",
        "  (14 messages not shown)",
        "  msg 17 | m",
        "  msg 18 | m",
        "  (21 messages not shown)",
        "  msg 40 | newest",
        "- row",
        "  event: e",
        "left out to fit the size limit: 1 message",
    ]


def test_render_names_every_left_out_group() -> None:
    lines = [Line("x" * 30), Line("- a", pt.VISIBLE, 0), Line("  event: e", pt.EVENTS, 0), Line("  d", pt.DRAFTS, 0)]
    assert render(lines, 31 + pt.MARKER_RESERVE).splitlines() == [
        "x" * 30,
        "left out to fit the size limit: 1 visible row, 1 event, 1 draft",
    ]


def test_render_never_emits_a_line_break_inside_a_line() -> None:
    text = render([Line("a\nb\rc d e\x85f"), Line("g")], 10_000)
    assert text.splitlines() == ["a b c d e f", "g"]
