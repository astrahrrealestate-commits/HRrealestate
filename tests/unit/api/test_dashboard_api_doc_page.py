"""docs/dashboard-api.md "Page context": the example request validates and the documented limits match the code."""

import json
import re
from pathlib import Path

from app.api.v1.schemas import AgentMessageIn
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

DOC = Path(__file__).resolve().parents[3] / "docs" / "dashboard-api.md"


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
