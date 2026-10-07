"""The live gate in tests/conftest.py: live tests never run by default, `--live` runs only them, and only after
every setting they need is present (exit 2, names only). Runs the real conftest in an isolated pytester session."""

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]
ROOT_CONFTEST = Path(__file__).resolve().parents[1] / "conftest.py"
NAME = "LIVE_GATING_TEST_SETTING"

TESTS = f"""
import pytest

@pytest.mark.live("{NAME}")
def test_live(request):
    assert request.node.get_closest_marker("enable_socket") is not None

def test_plain(request):
    assert request.node.get_closest_marker("enable_socket") is None
"""


@pytest.fixture
def session(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    monkeypatch.delenv(NAME, raising=False)
    pytester.makeconftest(ROOT_CONFTEST.read_text())
    pytester.makeini("[pytest]\nmarkers =\n    live(*settings): real provider check\n")
    pytester.makepyfile(test_gate=TESTS)
    return pytester


def test_live_tests_are_deselected_by_default(session: pytest.Pytester) -> None:
    result = session.runpytest_inprocess()
    result.assert_outcomes(passed=1, deselected=1)


def test_missing_setting_stops_the_run_before_any_test(session: pytest.Pytester) -> None:
    result = session.runpytest_inprocess("--live")
    assert result.ret == 2
    result.stdout.fnmatch_lines([f"*live-check: missing {NAME}*"])
    result.assert_outcomes()


def test_live_runs_only_live_tests_with_sockets_enabled(
    session: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(NAME, "set")
    result = session.runpytest_inprocess("--live")
    result.assert_outcomes(passed=1, deselected=1)
