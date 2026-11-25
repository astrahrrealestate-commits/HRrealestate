"""Sources of a research answer: only what a tool returned in this run can be cited or opened."""

from uuid import uuid4

import pytest

from app.contracts.sourced_answer import Source, SourcedAnswer
from app.superagent.sources import NOT_FOUND, SourceLog, screen


def test_each_source_gets_a_short_reference_by_kind() -> None:
    log = SourceLog()
    assert log.add("message", str(uuid4()), "Anna, 1 Sep") == "m1"
    assert log.add("document", str(uuid4()), "Lease") == "d1"
    assert log.add("message", str(uuid4()), "Bram, 2 Sep") == "m2"
    assert log.add("web", "https://wetten.overheid.nl/x", "Wet") == "w1"
    assert log.add("data", "query", "Checked the database") == "q1"


def test_the_same_thing_found_twice_keeps_one_reference() -> None:
    log = SourceLog()
    ref = str(uuid4())
    assert log.add("message", ref, "Anna") == log.add("message", ref, "Anna") == "m1"


def test_only_references_handed_out_in_this_run_resolve() -> None:
    log, mid = SourceLog(), uuid4()
    log.add("message", str(mid), "Anna")
    assert log.message_id("m1") == mid
    assert log.message_id(" M1 ") == mid
    for forged in ("m2", "d1", str(uuid4()), "", "../m1"):
        assert log.message_id(forged) is None


def test_a_reference_of_another_kind_never_opens() -> None:
    log, did = SourceLog(), uuid4()
    log.add("document", str(did), "Lease")
    assert log.document_id("d1") == did
    assert log.message_id("d1") is None


def test_a_source_the_tools_never_returned_is_dropped() -> None:
    log = SourceLog()
    log.add("message", "00000000-0000-0000-0000-000000000001", "Anna, 1 Sep")
    got = screen(SourcedAnswer(answer="She asked for a plumber.", sources=["m1", "m9", "https://evil.test"]), log)
    assert got.answer == "She asked for a plumber."
    assert got.sources == (Source(kind="message", ref="00000000-0000-0000-0000-000000000001", label="Anna, 1 Sep"),)


def test_answer_without_sources_says_not_found() -> None:
    log = SourceLog()
    log.add("message", "00000000-0000-0000-0000-000000000001", "Anna")
    got = screen(
        SourcedAnswer(answer="The rent is 900 euro.", sources=["m9"]), log, steps=["Searched messages (1 match)"]
    )
    assert got.sources == ()
    assert "900" not in got.answer
    assert got.answer.startswith(NOT_FOUND)
    assert "Searched messages (1 match)" in got.answer


def test_greeting_needs_no_source() -> None:
    got = screen(SourcedAnswer(answer="Good morning, Harjot.", sources=[]), SourceLog())
    assert got.answer == "Good morning, Harjot."


def test_an_honest_not_found_is_kept_as_written() -> None:
    log = SourceLog()
    answer = SourcedAnswer(answer="I found nothing about a wifi password.", sources=[], found=False)
    got = screen(answer, log, steps=["Searched messages (0 matches)"])
    assert got.answer == "I found nothing about a wifi password."


def test_duplicate_citations_appear_once_in_order() -> None:
    log = SourceLog()
    log.add("message", "a", "A")
    log.add("document", "b", "B")
    got = screen(SourcedAnswer(answer="x", sources=["d1", "m1", "d1"]), log)
    assert [s.label for s in got.sources] == ["B", "A"]


@pytest.mark.parametrize("label", ["Anna anna@example.test", "Bel +31 6 12345678"])
def test_labels_carry_no_contact_details(label: str) -> None:
    log = SourceLog()
    log.add("message", "a", label)
    [source] = screen(SourcedAnswer(answer="x", sources=["m1"]), log).sources
    assert "@" not in source.label
    assert "12345678" not in source.label.replace(" ", "")
