"""No canned draft anywhere in the backend (M13 T9): only the generic-draft check may name those phrases."""

import re
from pathlib import Path

APP = Path(__file__).parents[3] / "app"
CANNED = re.compile(
    r"in goede orde|zo snel mogelijk|zo spoedig mogelijk|get back to you|will reply shortly|reaching out|"
    r"looking into this|in behandeling",
    re.IGNORECASE,
)


def test_no_canned_draft_anywhere() -> None:
    hits = [
        f"{path.relative_to(APP)}:{n}"
        for path in APP.rglob("*.py")
        if path.name != "draft_quality.py"
        for n, line in enumerate(path.read_text("utf-8").splitlines(), 1)
        if CANNED.search(line)
    ]
    assert hits == []
