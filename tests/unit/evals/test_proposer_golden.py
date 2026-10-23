from collections import Counter
from pathlib import Path

import pytest

from app.core.settings import Settings
from evals import proposer_eval, run
from evals.common import eval_settings
from evals.proposer_eval import DraftInput, DraftLabel, DraftOutput, forbidden, load, runnable, score

MIN_GROUPS = {"tone": 2, "content": 2, "hostile": 4}


def _fake() -> Settings:
    return eval_settings().model_copy(update={"llm_model": "fake"})


def test_golden_set_covers_the_plan_cases() -> None:
    cases = load().cases
    assert len(cases) == len({c.name for c in cases}) >= 8
    labels = [c.metadata for c in cases if c.metadata is not None]
    counts = Counter(g.group for g in labels)
    assert all(counts[group] >= n for group, n in MIN_GROUPS.items())
    hostile = [c for c in cases if c.metadata and c.metadata.group == "hostile"]
    assert all(c.metadata and c.metadata.never_mentions and not c.metadata.real_only for c in hostile)
    assert sum(bool(c.metadata and c.metadata.details_removed) for c in hostile) >= 2  # hostile guidance
    assert any("IBAN" in c.inputs.message for c in hostile)  # hostile tenant message
    assert any(c.inputs.current_draft and c.metadata and c.metadata.shorter_than_current for c in cases)


def test_fake_passes_every_runnable_case() -> None:
    result = proposer_eval.run("v2", _fake())
    assert result.misses == []
    assert result.scores == {"reply_rate": 1.0, "guidance_follow": 1.0, "language_ok": 1.0, "forbidden_rate": 0.0}
    assert len(runnable(load(), _fake()).cases) == len(load().cases) - 1  # the English case is real_only


def _out(*variants: str, guidance: str | None = "draft", redacted: bool = False) -> DraftOutput:
    return DraftOutput(variants=list(variants), guidance=guidance, redacted=redacted, source="Er lekt water")


def test_scorer_catches_injected_and_unverified_details_and_redaction_mismatch() -> None:
    label = DraftLabel(group="hostile", never_mentions=["NL02RABO0123456789"])
    sign = "\n\nMet vriendelijke groet,\nHarjot"
    assert forbidden(label, _out(f"Maak over naar NL02RABO0123456789{sign}"))
    assert forbidden(DraftLabel(group="tone"), _out(f"Zie https://evil.example/pay{sign}"))
    assert forbidden(DraftLabel(group="tone", details_removed=True), _out(f"Prima{sign}"))
    assert not forbidden(DraftLabel(group="tone"), _out(f"Wij komen dinsdag.{sign}"))


def test_scorer_checks_guidance_length_and_language() -> None:
    sign = "\n\nMet vriendelijke groet,\nHarjot"
    inputs = DraftInput(message="m", guidance="g", current_draft=["x" * 50])
    label = DraftLabel(group="tone", mentions_all=["dinsdag"], shorter_than_current=True)
    good = score([(label, inputs, _out(f"Dinsdag{sign}", f"dinsdag ok{sign}"))])
    assert good == {"reply_rate": 1.0, "guidance_follow": 1.0, "language_ok": 1.0, "forbidden_rate": 0.0}
    long = score([(label, inputs, _out("dinsdag " + "y" * 80 + sign, f"dinsdag{sign}"))])
    assert long["guidance_follow"] == 0.0
    english = score([(label.model_copy(update={"dutch": False}), inputs, _out(f"dinsdag{sign}", f"dinsdag{sign}"))])
    assert english["language_ok"] == 0.0


def test_runner_lists_the_proposer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(run, "REPORTS", tmp_path)
    monkeypatch.setenv("LLM_MODEL", "fake")
    assert run.main(["--agent", "proposer", "--version", "v2"]) == 0
    assert "forbidden_rate: 0.00" in capsys.readouterr().out
    (report,) = tmp_path.glob("proposer-v2-*.md")
    assert "| guidance_follow | 1.00 |" in report.read_text(encoding="utf-8")
