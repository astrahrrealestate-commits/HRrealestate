"""docs/dashboard-api.md "Page pre-warm": the example body validates and the documented numbers match the code."""

import json
import re
from pathlib import Path

from app.api.v1.ratelimit import PAGE_PER_MIN
from app.contracts import PageContext, PageView
from app.pipeline.page_state import FRESHNESS_MARGIN, PAGE_TTL

DOC = Path(__file__).resolve().parents[3] / "docs" / "dashboard-api.md"


def _section() -> str:
    text = DOC.read_text(encoding="utf-8")
    start = text.index("### Page pre-warm")
    return text[start : text.index("### thread_key", start)]


def test_documented_example_is_a_valid_page() -> None:
    block = re.search(r"```json\n(.*?)\n```", _section(), flags=re.S)
    assert block is not None
    page = PageContext.model_validate(json.loads(block.group(1)))
    assert page.view is PageView.case
    assert page.case_id is not None


def test_documented_ttl_debounce_and_limit_match_the_code() -> None:
    section = _section()
    assert f"at most {int(PAGE_TTL.total_seconds())} seconds before the message" in section
    assert "debounced about 300 ms" in section
    assert "`204`" in section
    assert f"anything from {int(FRESHNESS_MARGIN.total_seconds())} seconds before the pre-warm" in section
    for source in ("a message (any", "an approval created or decided", "a case event"):
        assert source in section
    assert "SSE event for it" not in section  # no such event exists: freshness is server-side
    text = DOC.read_text(encoding="utf-8")
    assert f"| `PUT /agent/page` | {PAGE_PER_MIN} / min | owner" in text
