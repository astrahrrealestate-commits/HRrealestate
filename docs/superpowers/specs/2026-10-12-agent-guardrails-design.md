# Agent guardrails — design

Status: approved in conversation 2026-10-12, pending written-spec review.

## Intent

Stop misuse of the LLM agents: (1) owner Q&A used as a general chatbot, (2) cost runaway, (3) prompt injection through
tenant/contractor mail. Only reasonable, in-scope requests are fulfilled; everything else gets a fixed refusal.

Out of scope: tenant-facing bot guardrails (no such bot in Phase 1); sender allowlist for Harjot (already exists).

## Decisions

- Scope is enforced by the contract, not by an extra LLM call.
- **Usage limits ship disabled.** Budget and call-cap settings exist but default to `None` (unlimited). Enabling a limit
  is a config change only. Structural safety caps (input length, token caps, tenant-text truncation) stay on.

## 1. Owner Q&A scope

- `OwnerAnswer` gains `in_scope: bool` and `refusal_reason: str | None`.
- New prompt `owner_qa/v2` (v1 stays immutable). Scope: Harjot's cases, tasks, tenants, contractors, properties,
  deadlines, and the app's commands.
- `in_scope=False` → reply is a fixed refusal text; model text discarded.
  Refusal: "I only answer about your cases and tasks. Try `tasks` or `waiting`."
- Deterministic pre-checks in `app/pipeline/owner_commands.py` before any LLM call: max 500 chars, reject empty or
  non-text input.
- Post-checks: filter `case_refs` to known cases (exists), truncate answer to 1500 chars.
- Optional daily question cap: `owner_qa_daily_cap: int | None = None`.
- Golden set (in-scope, off-topic, injection questions) run via `make eval agent=owner_qa version=v2`.

## 2. Cost guardrails

- `run_agent` (`app/llm/calls.py`) checks, before each call, per company: spend (`sum(model_calls.cost_usd)`) and call
  count for the current day and month.
- Settings (all default `None` = no limit): `llm_daily_budget_usd`, `llm_monthly_budget_usd`,
  `llm_daily_calls_cap`, plus per-purpose caps (owner Q&A has its own sub-budget so it cannot starve ingestion).
- Exceeded → `BudgetExceededError(EstateOSError)`, non-transient (no DBOS retry); the blocked attempt writes a
  `model_calls` row with the reason.
  - Owner Q&A: reply "Daily limit reached."
  - Pipeline agents: event stays unprocessed in Postgres, a "needs manual review" task is created. Nothing dropped
    (invariant 1).
- Owner alerts at 80% and 100% of any enabled limit, once per day each (DB-backed marker, idempotent).
- `max_tokens` per agent via `ModelSettings`; tenant text truncated to a fixed length before prompting.
- With fakes (no price), call caps are the only effective limit.

## 3. Prompt injection from inbound mail

- Deterministic scanner in ingestion (`app/ingestion/`): instruction-like patterns, forged delimiter tags
  (`<data>`, `<message>`), invisible/bidi Unicode. Sets `suspicious` in message meta; strips forged delimiter tags.
- `understanding` contract gains `injection_suspected: bool`; model may also set it (new prompt version).
- Flagged cases: card shows a warning banner; auto-actions disabled so a human approves everything. Recipients still
  come only from the DB (invariant 6).
- Draft output check: any URL, IBAN or phone number in a draft absent from the case thread/DB is flagged on the card.

## 4. Observability and tests

- structlog events + Langfuse counters for refusals, budget blocks, injection flags. No message bodies at info level.
- Unit: scanner, budget math (limits on and off), scope refusal with fake model, input pre-checks.
- Integration (G2): budget exhaustion in a workflow leaves the event pending and creates the review task; alert sent once.
- Eval: owner_qa v2 golden set.

## Contract and migration impact

- Contracts changed: `OwnerAnswer`, understanding output. Prompts: new versions only.
- Migration: alert-marker table or columns for once-per-day budget alerts; `suspicious` lives in existing
  `messages.meta` (no schema change).
- import-linter: guardrail modules sit below `app/pipeline` and `app/llm`; none touch sender.
