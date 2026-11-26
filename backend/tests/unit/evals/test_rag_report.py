"""The RAG evals leave a dated report per model, so a change has a before and an after to compare."""

from pathlib import Path

from evals.common import write_rag_report


def test_report_holds_the_models_scores_and_misses(tmp_path: Path) -> None:
    path = write_rag_report(
        "message-rag", "fake", "fake", {"context_hit": 0.5, "mrr": 0.25}, ["[said] Waar lekt het?"], folder=tmp_path
    )
    text = path.read_text(encoding="utf-8")
    assert path.parent == tmp_path
    assert path.name.startswith("message-rag-fake-")
    assert "embedding model: fake" in text
    assert "| context_hit | 0.50 |" in text
    assert "| mrr | 0.25 |" in text
    assert "- [said] Waar lekt het?" in text


def test_a_model_name_never_becomes_a_path(tmp_path: Path) -> None:
    path = write_rag_report("rag", "google-gla:gemini/../x", "fake", {}, [], folder=tmp_path)
    assert path.parent == tmp_path


def test_a_second_run_does_not_overwrite_the_baseline(tmp_path: Path) -> None:
    first = write_rag_report("rag", "fake", "fake", {"mrr": 0.1}, [], folder=tmp_path)
    second = write_rag_report("rag", "fake", "fake", {"mrr": 0.9}, [], folder=tmp_path)
    assert first != second
    assert "0.10" in first.read_text(encoding="utf-8")
