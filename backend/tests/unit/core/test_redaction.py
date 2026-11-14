"""Log and error-report redaction: secrets, BRIXX personal columns and row payloads never leave the process."""

import json

import pytest

from app.core.logging import configure_logging, get_logger
from app.core.redaction import REDACTED, redact_event, sentry_denylist

TOKEN = "tok-not-a-real-secret-123"


def test_secret_keys_are_redacted_case_insensitively() -> None:
    event = {"event": "brixx.request", "Authorization": f"Bearer {TOKEN}", "access_token": TOKEN, "table": "PRG_X"}
    out = redact_event(None, "info", event)
    assert out["Authorization"] == REDACTED
    assert out["access_token"] == REDACTED
    assert out["table"] == "PRG_X"
    assert out["event"] == "brixx.request"


def test_brixx_personal_columns_and_rows_are_redacted_recursively() -> None:
    event = {
        "event": "x",
        "headers": {"authorization": TOKEN, "accept": "application/json"},
        "detail": [{"ZOEKID": "00001011990A", "PRG_RELATIEID": 7}],
        "rows": [{"naam": "Invented Person"}],
        "row": {"naam": "Invented Person"},
    }
    out = redact_event(None, "info", event)
    assert out["headers"] == {"authorization": REDACTED, "accept": "application/json"}
    assert out["detail"] == [{"ZOEKID": REDACTED, "PRG_RELATIEID": 7}]
    assert out["rows"] == REDACTED
    assert out["row"] == REDACTED


def test_bearer_tokens_inside_strings_are_masked() -> None:
    out = redact_event(None, "warning", {"event": "failed", "error": f"header was Bearer {TOKEN} for PRG_A"})
    assert TOKEN not in out["error"]
    assert "PRG_A" in out["error"]


def test_configured_logger_never_prints_the_token(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("prod")
    get_logger("t").info("brixx.call", authorization=TOKEN, zoekid="00001011990A", rows=[{"a": 1}], page=2)
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert TOKEN not in line
    assert "00001011990A" not in line
    record = json.loads(line)
    assert record["page"] == 2


def test_sentry_denylist_covers_the_same_keys() -> None:
    keys = {k.lower() for k in sentry_denylist()}
    assert {"authorization", "zoekid", "rows", "row"} <= keys
    assert "password" in keys  # Sentry's own defaults are kept
