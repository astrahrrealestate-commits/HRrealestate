# ADR 0004: Enforce architecture with import-linter

Status: accepted (2026-10-05)

## Decision
Layer and isolation rules live in `pyproject.toml` `[tool.importlinter]` and run in pre-commit and CI:
1. **layers:** `app.api` > `app.workflows` > (`app.pipeline` | `app.owner` | `app.ingestion` | `app.directory` |
   `app.outcomes` | `app.sender`) > (`app.db` | `app.llm` | `app.storage` | `app.channels`) > `app.contracts` > `app.core`
2. **forbidden:** nothing except `app.sender` imports `app.channels.whatsapp.outbound`, `app.channels.gmail.drafts`,
   `app.sender.settings` or `app.sender.whatsapp` (sources are wildcards over every `app` package; import-linter skips ancestor `__init__`s of forbidden
   modules, so `tests/unit/test_boundaries.py` asserts the channel package `__init__`s import nothing).
4. **forbidden:** only `app.channels.registry` imports `app.channels.whatsapp.media_settings` (media credentials can send).
3. **independence:** `app.pipeline.rules` imports no I/O module (`app.db`, `app.llm`, `app.channels`, `app.storage`).

## Consequences
Boundary violations fail the build. The Claude edit-guard hook catches the send-isolation case earlier, at edit time.
