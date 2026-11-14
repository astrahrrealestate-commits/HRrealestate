"""docs/dashboard-api.md "Page context": the example request validates and the documented limits match the code."""

import json
import re
from pathlib import Path

from app.api.v1.events import POLL_INTERVAL_S
from app.api.v1.schemas import AgentMessageIn
from app.api.v1.turn_events import TURN_POLL_SECONDS
from app.contracts.concierge import MAX_REPLY
from app.contracts.page_context import (
    MAX_FILTER_KEY,
    MAX_FILTER_VALUE,
    MAX_FILTERS,
    MAX_RAW_SNAPSHOT,
    MAX_SNAPSHOT,
    MAX_VISIBLE,
    MAX_VISIBLE_ID,
    PageView,
)
from app.contracts.thread_key import MAX_THREAD_KEY
from app.llm.agents.concierge import CONCIERGE
from app.llm.page_blocks import MAX_SNAPSHOT as MODEL_SNAPSHOT
from app.llm.page_blocks import MAX_SNAPSHOT_WITH_MEMORY
from app.pipeline import page_memory as pm
from app.pipeline.concierge_reply import MAX_REPLY_LINES
from app.pipeline.draft_guidance import MAX_SHOWN, MAX_VARIANTS
from app.pipeline.page_facts import MAX_SUMMARY
from app.pipeline.page_memory_lines import KEEP_NEWEST
from app.pipeline.page_text import FACTS_BUDGET
from app.pipeline.turn_timings import KEYS
from app.workflows.queues import CONCIERGE_POLL_SECONDS

DOC = Path(__file__).resolve().parents[4] / "docs" / "dashboard-api.md"


def _section() -> str:
    text = DOC.read_text(encoding="utf-8")
    start = text.index("### Page context")
    return text[start : text.index("### thread_key", start)]


def test_documented_example_is_a_valid_request() -> None:
    block = re.search(r"```json\n(.*?)\n```", _section(), flags=re.S)
    assert block is not None
    body = AgentMessageIn.model_validate(json.loads(block.group(1)))
    assert body.page is not None
    assert body.page.view is PageView.approvals


def test_documented_limits_match_the_contract() -> None:
    section = _section()
    for phrase in (
        f"at most {MAX_SNAPSHOT} characters after whitespace is collapsed",
        f"raw input over {MAX_RAW_SNAPSHOT} characters",
        f"at most {MAX_VISIBLE} strings ({MAX_VISIBLE + 1} or more is `422`)",
        f"each a UUID or task ref of at most {MAX_VISIBLE_ID} chars, or a thread key of at most {MAX_THREAD_KEY} chars",
        "`\\r\\n` and a lone `\\r` become `\\n`",
        f"at most {MAX_FILTERS} pairs, key 1 to {MAX_FILTER_KEY} chars, value at most {MAX_FILTER_VALUE}",
    ):
        assert phrase in section, phrase
    assert all(f"`{v.value}`" in section for v in PageView)


def test_documented_answers_use_the_page() -> None:
    section = _section()
    assert "`answer` step" in section
    assert "owner_qa/v3" in section
    assert "advisory" in section
    assert "follow-up" not in section.lower()


def test_documented_memory_pack_limits_match_the_code() -> None:
    section = _section()
    for phrase in (
        f"Up to {pm.MAX_MESSAGES}: all of them when there are {pm.MAX_MESSAGES} or",
        f"else the first {pm.FIRST} and the newest {pm.NEWEST}",
        f"the text's first {pm.MAX_MESSAGE} characters",
        f"summary ({MAX_SUMMARY} chars)",
        f"at most {pm.MAX_LEASES})",
        f"what in {pm.MAX_ABOUT} chars, expected",
        f"by; at most {pm.MAX_WAITS})",
        f"the last {pm.MAX_EVENTS} timeline events",
        f"note in {pm.MAX_NOTE} chars",
        f"the case's latest {pm.MAX_DRAFTS}",
        f"first draft variant in {pm.MAX_EARLIER_DRAFT} chars",
        f"at most {FACTS_BUDGET} characters",
        f"older messages (down to the newest {KEEP_NEWEST})",
        "that thread's messages only",
    ):
        assert phrase in section, phrase


def test_documented_draft_reply_result_matches_the_code() -> None:
    section = _section().split("### Drafts from the Super Agent", 1)[1]
    assert f"up to {MAX_VARIANTS} variants (each at most {MAX_SHOWN} characters" in section
    example = json.loads(section.split("```json\n", 1)[1].split("```", 1)[0].replace("\n", " "))
    keys = {"approval_ids", "case_id", "draft_version", "drafts", "details_removed", "superseded_approval_id"}
    assert set(example) == keys
    assert set(example["drafts"][0]) == {"text", "flags"}


def test_documented_fast_turns_match_the_code() -> None:
    text = DOC.read_text(encoding="utf-8")
    section = _section()
    for phrase in (
        f"only the first {MAX_SNAPSHOT_WITH_MEMORY} characters of the\nsnapshot",
        f"otherwise up to {MODEL_SNAPSHOT}.",
        CONCIERGE.prompt.key,
        "only when every step of the plan is `answer` or\n`open_view`",
        "Amounts are allowed",
        "links, email addresses, phone numbers and IBANs replaced by\n`[redacted]`",
        f"at most {MAX_REPLY_LINES} lines and {MAX_REPLY} characters",
        "ids are never taken from it",
        "never the raw one",
    ):
        assert phrase in section, phrase
    assert f"Turns are checked every {TURN_POLL_SECONDS} s (the\n    feed every {POLL_INTERVAL_S} s)" in text
    timings = text[text.index("### Turn timings") : text.index("### thread_key")]
    assert all(f"`{key}`" in timings for key in KEYS)
    assert f"within about {CONCIERGE_POLL_SECONDS} s" in timings
