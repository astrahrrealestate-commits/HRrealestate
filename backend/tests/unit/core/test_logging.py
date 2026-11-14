import json

import pytest

from app.core.logging import configure_logging, get_logger


def test_json_logs_outside_dev(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("prod")
    get_logger("t").info("hello", company_id="c1")
    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert record["event"] == "hello"
    assert record["company_id"] == "c1"
    assert record["level"] == "info"
    assert "timestamp" in record
