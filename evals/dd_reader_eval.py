"""dd_reader eval: kind, claim recall, quote precision (every quote is in the text), garbage and injected text."""

from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_evals import Dataset

from app.contracts import PromptRef
from app.contracts.diligence import DDDocRead
from app.core.settings import Settings
from app.diligence.verify import verify_read
from app.llm.agents.dd_reader import DD_READER, dd_reader_prompt
from app.llm.prompts import load_prompt
from evals.common import MAX_CONCURRENCY, EvalResult, crash_message, spec_agent, task_retry
from evals.scoring import GOLDEN_DIR

MISS_HEADER = "| case | expected | got |\n|---|---|---|"


class DocIn(BaseModel):
    filename: str
    text: str


class DocLabel(BaseModel):
    doc_kind: str
    claims: dict[str, str] = {}
    flags: int = 0
    max_confidence: float | None = None
    attack: bool = False
    forbidden: dict[str, str] = {}


def load(path: Path = GOLDEN_DIR / "dd_reader.yaml") -> Dataset[DocIn, Any, DocLabel]:
    return Dataset[DocIn, Any, DocLabel].from_file(path)


def _value(claim: Any) -> str:
    raw = claim.number if claim.number is not None else claim.text if claim.text is not None else claim.day
    text = str(raw)
    return text.rstrip("0").rstrip(".") if "." in text else text


def _reported(out: DDDocRead) -> set[tuple[str, str]]:
    return {(c.field.value, _value(c)) for c in out.claims}


def _problems(label: DocLabel, out: DDDocRead, text: str) -> list[str]:
    found: list[str] = []
    if out.doc_kind.value != label.doc_kind:
        found.append(f"kind {out.doc_kind.value}")
    reported = _reported(out)
    found += [f"missing {f}={v}" for f, v in label.claims.items() if (f, v) not in reported]
    found += [f"reported forbidden {f}={v}" for f, v in label.forbidden.items() if (f, v) in reported]
    if len(out.flags) < label.flags:
        found.append("flag missing")
    if label.max_confidence is not None and out.confidence > label.max_confidence:
        found.append(f"overconfident {out.confidence:.2f}")
    if verify_read(out, text)[1]:
        found.append("quote not in text")
    return found


def run(version: str, settings: Settings) -> EvalResult:
    loaded = load_prompt(PromptRef(name="dd_reader", version=version))
    agent = spec_agent(settings, DD_READER.name, DDDocRead, loaded, gemini_prompted=True)

    async def task(inputs: DocIn) -> DDDocRead:
        return DD_READER.finalize((await agent.run(dd_reader_prompt(inputs.filename, inputs.text))).output, loaded)

    report = load().evaluate_sync(
        task, name=f"dd_reader-{version}", progress=False, max_concurrency=MAX_CONCURRENCY, retry_task=task_retry()
    )
    if report.failures:
        raise SystemExit(crash_message(report.failures))
    texts = {c.name: c.inputs.text for c in report.cases}
    done = [(c.name, c.metadata, c.output) for c in report.cases if c.metadata is not None]
    bad = {name: _problems(g, o, texts[name]) for name, g, o in done}
    n = len(done) or 1
    expected = sum(len(g.claims) for _, g, _ in done) or 1
    hit = sum(len(g.claims) - sum(p.startswith("missing") for p in bad[name]) for name, g, _ in done)
    quoted = sum(len(o.claims) + len(o.flags) for _, _, o in done) or 1
    dropped = sum(verify_read(o, texts[name])[1] for name, _, o in done)
    scores = {
        "kind_accuracy": sum(o.doc_kind.value == g.doc_kind for _, g, o in done) / n,
        "claim_recall": hit / expected,
        "quote_precision": (quoted - dropped) / quoted,
        "clean_rate": sum(not p for p in bad.values()) / n,
    }
    misses = [f"| {name} | {g.doc_kind} | {', '.join(bad[name])} |" for name, g, _ in done if bad[name]]
    return EvalResult(scores, misses, MISS_HEADER, loaded)
