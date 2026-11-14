"""quote_reader and job_items evals (M11): extraction accuracy, VAT flags, non-quotes and injected text.

On `LLM_MODEL=fake` these measure the deterministic fake, not a real model.
"""

from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_evals import Dataset

from app.contracts import ExtractedQuote, JobItems, PromptRef
from app.contracts.finance import MAX_JOB_ITEMS
from app.core.property_terms import normalise_item_key
from app.core.settings import Settings
from app.llm.agents.job_items import JOB_ITEMS, job_items_prompt
from app.llm.agents.quote_reader import QUOTE_READER, quote_reader_prompt
from app.llm.prompts import load_prompt
from evals.common import MAX_CONCURRENCY, EvalResult, crash_message, spec_agent, task_retry
from evals.scoring import GOLDEN_DIR

MISS_HEADER = "| case | expected | got |\n|---|---|---|"


class QuoteIn(BaseModel):
    text: str
    received_on: date
    subject: str | None = None
    attachments: list[str] = []


class QuoteLabel(BaseModel):
    is_quote: bool
    line_count: int
    amounts: list[str]
    total: str | None
    vat_included: bool | None
    work_date: date | None = None
    attack: bool = False


class JobIn(BaseModel):
    case_summary: str
    messages: list[str]


class JobLabel(BaseModel):
    expected: list[str]
    max_items: int = MAX_JOB_ITEMS


def load_quotes(path: Path = GOLDEN_DIR / "quote_reader.yaml") -> Dataset[QuoteIn, Any, QuoteLabel]:
    return Dataset[QuoteIn, Any, QuoteLabel].from_file(path)


def load_job_items(path: Path = GOLDEN_DIR / "job_items.yaml") -> Dataset[JobIn, Any, JobLabel]:
    return Dataset[JobIn, Any, JobLabel].from_file(path)


def _flags(label: QuoteLabel, out: ExtractedQuote) -> dict[str, bool]:
    total = f"{out.total.amount:.2f}" if out.total else None
    amounts = [f"{line.amount.amount:.2f}" for line in out.lines]
    return {
        "line_count_match": len(out.lines) == label.line_count,
        "amount_match": amounts == label.amounts and total == label.total,
        "vat_flag_match": out.vat_included is label.vat_included,
        "is_quote_match": out.is_quote is label.is_quote,
        "date_match": label.work_date is None or out.work_date == label.work_date,
    }


def run_quote_reader(version: str, settings: Settings) -> EvalResult:
    loaded = load_prompt(PromptRef(name="quote_reader", version=version))
    agent = spec_agent(settings, QUOTE_READER.name, ExtractedQuote, loaded, gemini_prompted=True)

    async def task(inputs: QuoteIn) -> ExtractedQuote:
        prompt = quote_reader_prompt(inputs.subject, inputs.text, inputs.attachments, inputs.received_on)
        return QUOTE_READER.finalize((await agent.run(prompt)).output, loaded)

    report = load_quotes().evaluate_sync(
        task, name=f"quote_reader-{version}", progress=False, max_concurrency=MAX_CONCURRENCY, retry_task=task_retry()
    )
    if report.failures:
        raise SystemExit(crash_message(report.failures))
    done = [(c.name, c.metadata, c.output) for c in report.cases if c.metadata is not None]
    flags = {name: _flags(g, o) for name, g, o in done}
    n = len(done) or 1
    attacks = [name for name, g, _ in done if g.attack]
    scores = {
        key: sum(f[key] for f in flags.values()) / n
        for key in ("line_count_match", "amount_match", "vat_flag_match", "is_quote_match")
    }
    scores["injection_resistance"] = sum(all(flags[name].values()) for name in attacks) / (len(attacks) or 1)
    misses = [
        f"| {name} | {g.line_count} lines {g.amounts} total {g.total} | "
        f"{', '.join(k for k, ok in flags[name].items() if not ok)} |"
        for name, g, _ in done
        if not all(flags[name].values())
    ]
    return EvalResult(scores, misses, MISS_HEADER, loaded)


def run_job_items(version: str, settings: Settings) -> EvalResult:
    loaded = load_prompt(PromptRef(name="job_items", version=version))
    agent = spec_agent(settings, JOB_ITEMS.name, JobItems, loaded)

    async def task(inputs: JobIn) -> JobItems:
        return JOB_ITEMS.finalize(
            (await agent.run(job_items_prompt(inputs.case_summary, inputs.messages))).output, loaded
        )

    report = load_job_items().evaluate_sync(
        task, name=f"job_items-{version}", progress=False, max_concurrency=MAX_CONCURRENCY, retry_task=task_retry()
    )
    if report.failures:
        raise SystemExit(crash_message(report.failures))
    done = [(c.name, c.metadata, c.output) for c in report.cases if c.metadata is not None]
    keys = {name: {normalise_item_key(i.description) for i in o.items} for name, _, o in done}
    wanted = sum(len(g.expected) for _, g, _ in done) or 1
    found = sum(len(set(g.expected) & keys[name]) for name, g, _ in done)
    capped = {name: len(o.items) <= g.max_items for name, g, o in done}
    scores = {"item_recall": found / wanted, "cap_ok": sum(capped.values()) / (len(done) or 1)}
    misses = [
        f"| {name} | {g.expected} | {sorted(keys[name])}{'' if capped[name] else ' over cap'} |"
        for name, g, _ in done
        if not set(g.expected) <= keys[name] or not capped[name]
    ]
    return EvalResult(scores, misses, MISS_HEADER, loaded)
