# ADR 0002: Pydantic AI for LLM agents

Status: accepted (2026-10-05)

## Context
The AI calls are structured extraction and drafting whose outputs are our Pydantic contracts. We need provider swap,
deterministic tests, tracing, and evals.

## Decision
**Pydantic AI** `Agent(output_type=<Contract>)` per AI task, model `openai:<model>` from settings. Instrument with
OpenTelemetry → **Langfuse** (EU). Golden sets in **pydantic-evals**. Tests use `TestModel` / `FunctionModel`.

## Consequences
- No custom LLM client. The contracts are the schema, so there is no drift.
- Switching provider (e.g. Anthropic, Mistral EU) is a config change, re-validated by evals.
- We still own the prompt files (versioned, hashed, immutable) and the `model_calls` table (cost/audit), written by a
  thin wrapper around `agent.run_sync` (the wrapper adds the `model_calls` row; the call itself is plain Pydantic AI).
- LangGraph was rejected: our orchestration lives in DBOS, so a second graph runtime adds nothing.
