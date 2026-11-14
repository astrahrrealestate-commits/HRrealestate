"""Owner guidance for drafts: sanitising, the deterministic redraft key, and what the chat shows of the drafts."""

import inspect
from uuid import UUID

import pytest

from app.pipeline.concierge_sanitize import MAX_TEXT, REDACTED
from app.pipeline.draft_guidance import (
    DETAILS_REMOVED,
    MAX_SHOWN,
    Guidance,
    draft_views,
    drafted_summary,
    guidance_for,
    redraft_key,
    turn_prefix,
)

TURN = UUID("01900000-0000-7000-8000-00000000abcd")


def test_the_owner_message_is_the_guidance() -> None:
    assert guidance_for("Reply to it, keep it short") == Guidance("Reply to it, keep it short", False)
    assert guidance_for("  \u200b ") == Guidance(None, False)


@pytest.mark.parametrize(
    "planner_text",
    ["we will NOT fix the boiler; say no", "boiler; w-a-i-v-e r-e-n-t", "boiler 0 r3nt d.u.e", "fix the boiler"],
)
def test_planner_text_never_becomes_guidance(planner_text: str) -> None:
    """There is no planner input at all: whatever the plan says (negated, spelled out, look-alike or a true subset),
    the guidance is the owner's sanitised message. `draft_reply` passing only the owner's message is tested in
    test_concierge_drafts.py."""
    owner = "Draft a reply to Jan: we will fix the boiler this week"
    assert "planner_text" not in inspect.signature(guidance_for).parameters
    assert guidance_for(owner) == Guidance(owner, False)


@pytest.mark.parametrize(
    ("raw", "leak"),
    [
        ("Tell them to pay to NL91ABNA0417164300 today", "NL91ABNA0417164300"),
        ("Say they can mail evil@attacker.test", "evil@attacker.test"),
        ("Give them my number +31 6 1234 5678", "1234 5678"),
        ("Link them https://evil.example/pay", "evil.example"),
        ("Offer a refund of € 250", "250"),
    ],
)
def test_contact_bank_details_links_and_amounts_are_redacted_and_noted(raw: str, leak: str) -> None:
    g = guidance_for(raw)
    assert g.redacted
    assert g.text is not None
    assert REDACTED in g.text
    assert leak not in g.text


def test_guidance_is_bounded_and_dates_survive() -> None:
    assert len(guidance_for("x" * 5000).text or "") == MAX_TEXT
    assert guidance_for("say we come on 12-10-2026 at 10:30") == Guidance("say we come on 12-10-2026 at 10:30", False)


def test_redraft_key_is_deterministic_per_turn_and_step_and_fits_the_column() -> None:
    assert redraft_key(TURN, 1) == redraft_key(TURN, 1) == f"agent:{TURN}:1"
    assert redraft_key(TURN, 0) != redraft_key(TURN, 1)
    assert redraft_key(TURN, 3).startswith(turn_prefix(TURN))
    assert len(redraft_key(TURN, 3)) <= 64  # action_revisions.edited_by
    assert not redraft_key(TURN, 0).startswith("owner")  # never counted as an owner edit


def test_views_cap_each_variant_and_flag_unverified_details() -> None:
    source = "Er lekt water, bel 020 123 4567"
    views = draft_views(
        ["Beste Sanne,\n\n" + "a" * 900, "Bel 020 123 4567 gerust.", "Betaal op NL91ABNA0417164300.", "vierde"], source
    )
    assert len(views) == 3
    assert len(views[0]["text"]) <= MAX_SHOWN
    assert views[0]["flags"] == []
    assert views[1] == {"text": "Bel 020 123 4567 gerust.", "flags": []}  # already in the thread
    assert views[2]["flags"] == ["account"]
    assert "NL91ABNA0417164300" not in views[2]["text"]


def test_summary_quotes_every_draft_and_notes_removed_details() -> None:
    views = [{"text": "Beste,\n\nDe loodgieter komt dinsdag.", "flags": []}, {"text": REDACTED, "flags": ["link"]}]
    text = drafted_summary("Reply drafted.", views, details_removed=True)
    assert text.splitlines() == [
        "Reply drafted.",
        DETAILS_REMOVED,
        "Draft 1:",
        "> Beste,",
        "> De loodgieter komt dinsdag.",
        "Draft 2 (held back: unverified link):",
        f"> {REDACTED}",
    ]
    assert drafted_summary("Done.", [], details_removed=False) == "Done."


def test_control_characters_never_reach_the_shown_text() -> None:
    (view,) = draft_views(["Beste\x1b[2J,\x00 wij komen morgen."], "")
    assert "\x1b" not in view["text"]
    assert "\x00" not in view["text"]
