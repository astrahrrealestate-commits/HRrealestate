---
description: autoship phase 2 - one row per intended Phase 1 feature with status and evidence. Only run from /autoship.
---

# audit

Guard: run only when /autoship selected this phase. Otherwise stop.

1. Dispatch three Explore agents in ONE message (parallel), each read-only, each returning rows
   `key | area | title | status | code path | test path | doc line | missing / blocker`:
   - **plan**: `docs/build-plan.md`, `docs/PROGRESS.md` (every unchecked item, "not run", "decision for user").
   - **design**: `docs/superpowers/specs/*`, `docs/adr/*`, `docs/hld.md`, `docs/tech-stack.md`. Agents #1-#9 by name,
     agent memory (2026-10-23 spec), dashboard + Super Agent, M10-M12, M3 BRIXX (user decided to build it now; source
     also `BRIXXonline_API_Documentation_hrrealestate_EN.pdf`).
   - **code**: `backend/app/`, `backend/tests/`, `frontend/`, wiring (agent registry, mounted routers, worker-registered workflows and
     queues, routed pages), TODO/FIXME/NotImplementedError, `git log --oneline -60`.
2. Merge into the `## Features` table of BUILD_STATUS.md, one row per feature, grouped by area. Status:
   - **Done**: code exists, is wired in, and a test exercises it. No test -> not Done.
   - **Partial**: say exactly what is missing (including "tests never run", per PROGRESS).
   - **Missing**.
   - **Deferred**: only for a cited user decision or an external blocker (credentials, provider approval, human
     decision), named in the row.
   Phase 2 agents and documented non-goals get no rows; list them under `## Out of scope` with doc refs.
3. When in doubt between two statuses, choose the less-done one.
4. Gate: every row has a status and evidence (code path, test path or doc line). Quote the row counts per status.
