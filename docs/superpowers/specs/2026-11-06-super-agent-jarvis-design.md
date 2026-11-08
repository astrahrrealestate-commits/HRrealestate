# Super Agent 2.0 ("Jarvis"): conversational orchestrator on the existing turn pipeline

Status: draft for review · Date: 2026-11-06 · Branch: `m-jarvis-superagent`
Source proposal: `SUPER_AGENT_JARVIS_ARCHITECTURE.md` (not in the repo; reviewed from the pasted text).
Related: [ADR 0006](../../adr/0006-dashboard-owner-channel.md), [dashboard spec](2026-10-15-dashboard-super-agent-design.md),
[agent memory/context](2026-10-23-agent-memory-context-design.md), [BRIXX mirror](2026-10-31-brixx-data-mirror-design.md).

## 1. Decisions (owner, 2026-11-06)
1. **Model:** Gemini through Pydantic AI (`llm_model = "google-gla:..."`, already wired in `app/llm/runtime.py`). No new
   raw-HTTP model calls; the Groq httpx helpers are retired.
2. **Execution:** the orchestration loop runs inside a **DBOS step** of the existing `concierge:{turn_id}` workflow.
3. **Rent/arrears data:** built as curated read-only views (see §5, depends on the BRIXX mirror).

## 2. What the proposal got wrong about the code
- There are **two Super Agent paths**. The proposal diagnoses only the first.
  - `POST /api/agent/ask` (`app/api/agent/routes.py`, 2242 lines): synchronous, regex-gated, Groq via httpx, no DBOS.
    The frontend (`askAgent` in `frontend/src/lib/api.ts`) calls this one.
  - `POST /api/v1/agent/messages` → `concierge:{turn_id}` workflow → `concierge_turns.run_turn` → `ConciergePlan` →
    `run_plan` executor (`app/pipeline/concierge*.py`). Durable, budgeted, guarded, SSE. Not used by the SPA.
- `propose_draft_reply` does not exist; drafting is the plan step `draft_reply` → proposer (`concierge_proposals.py`).
- `search_messages`/`search_hybrid`/`run_query_agent` need `session|engine`, `company_id`, `embedder`, `DocFilter`.
- No live Drive/Gmail search exists (`DriveStore` has no search; `gmail_sync` is ingestion).
- "Calendar Agent" is regex time extraction + `propose_calendar_event`, not an LLM agent.
- Leases/units/people/messages are already queryable (`app/tools/query_agent/allowlist.py`). Rent, arrears and
  deposits are not: there is no payments table in our models.

## 3. Target design
One orchestration path: the DBOS turn pipeline. `/api/agent/ask` becomes a thin adapter over it (create turn, run, wait
for the terminal state, map to `AskAgentResponse`), then its regex gates are deleted.

```
owner text → create_turn → concierge:{turn_id} (DBOS)
   step concierge.run_turn:
     1. exact owner commands (rule:, ...)      deterministic, no model
     2. planner (ConciergePlan, one call)      in_scope / reply / steps / suggestions
     3. if plan.needs_research:  read-only tool loop  (new, §4)  → evidence block
     4. run_plan executor                      proposals only; sender untouched
     5. answer = screened reply / step summaries / loop answer
```

Tier 1 (greeting, simple lookup) is the planner's own `reply` (already one call). Tier 2 adds the tool loop.

## 4. Tool loop (`app/superagent/`, new package)
- A Pydantic AI `Agent` with typed deps `SuperAgentDeps(engine, settings, company_id, embedder, now)`. `company_id`
  is never a tool argument (invariant 4).
- Tools (read-only, each returns an escaped data block, invariant 6):
  `query_database` (wraps `run_query_agent`), `search_communications` (wraps `search_messages`),
  `search_documents` (wraps `search_hybrid`), `get_case`.
- Hard caps: 3 tool calls, per-tool row/character caps, one wall-clock budget, `check_budget` before the loop, one
  `model_calls` row per model request.
- No write tools. Anything that changes state is still a `ConciergePlan` step the executor validates, so recipients
  come from the DB and `app/sender/` is untouched (invariant 5).
- Determinism/idempotency (invariants 2, 3): the loop runs in the existing step; its result is stored on the turn
  before the answer is assembled, so a retried step reuses it (same pattern as the stored plan).
- Live step labels (`steps?: string[]` in `SuperAgentContext.tsx`) come from the stored tool trace: tool name and
  counts only, never message bodies.

### 4.1 Status of the first cut (`app/superagent/research.py`)
Built: `query_database`, `search_communications`, `search_documents`; 3-call cap; escaped data blocks; deps-only
`company_id`; a failing lookup becomes a result the model explains; one `model_calls` row per run including failures;
step chips from tool name and counts. Wired into `/api/agent/ask` for questions the regex gates and the planner do not
claim (the fallback branch).
Deferred: `get_case` (cases are already in the system prompt's ranked brief); a wall-clock deadline across tool calls
(only per-request timeouts today); storing the loop result on the turn so a retry reuses it (needs the DBOS turn
adapter, slice 1b: `ask_agent` is not a DBOS step today).

### 4.2 Status of the turn-pipeline hook (slice 3)
`ConciergePlan.needs_research` (additive, default false) lets an answer-only plan ask for the loop instead of writing a
`reply`. `concierge_reply.prepare_plan` honours the flag only beside read steps (`answer`, `open_view`) without a usable
reply, and appends the `answer` step it needs. The `answer` step calls an injected `Researcher`
(`concierge_base.Researcher`); `app/superagent/turn.py::make_researcher` builds it from `run_research` and the
`concierge.run_turn` DBOS step passes it down, so `app.pipeline` never imports the loop (`app.superagent` is its own
layer between `app.workflows` and `app.pipeline`). The loop's text is screened like a reply; an empty loop falls back to
`owner_qa`. Step labels ride in `StepResult.data["steps"]`.
Deferred: conversation history is not passed to the loop on this path (the planner already saw it); a retried turn that
crashed between the loop and storing its results repeats the (read-only) loop.

## 5. Rent / arrears views
Source of truth is BRIXX (invoices, payment rules, arrears), mirrored by the unmerged `m-brixx-mirror` work. The mirror
spec (§ "BRIXX lookup") already plans curated views. Order of work: merge the mirror mapper, add
`v_rent_position` / `v_arrears` over mirrored tables, add them to `ALLOWED_VIEWS` with a migration. Until then the
agent must say it has no rent data instead of guessing. We do **not** invent a payments table.

## 6. Prompt and contracts
- `super_agent_prompt.py` (direct-answer path): done in this branch (conversational, propose-only, no ids).
- `concierge` prompt: new immutable `v7` (adds `needs_research`, conversational tone); `ConciergePlan` change is
  additive with defaults; golden set run via `make eval agent=concierge version=v7`.

## 7. Slices
| # | Slice | Gate |
|---|---|---|
| 0 | Conversational prompt, token cap, baseline lint/type/migration fixes | done (`e2ebff1`, `57491ad`, `b7f63bc`) |
| 1 | `/api/agent/ask` adapter over the turn pipeline; Groq path removed; Gemini via Pydantic AI | G1, G2 |
| 2 | `app/superagent/` read-only tool loop, caps, trace storage, fake-model tests | G1, G2, reviewer |
| 3 | `concierge/v7` prompt + contract + goldens | eval on real Gemini |
| 4 | Step streaming to the SPA | G1, frontend check |
| 5 | Clarify-and-offer flow when retrieval is empty (pills) | G1 |
| 6 | Rent/arrears views after the BRIXX mapper lands | G2, migration |
| 7 | Live Drive/Gmail search: needs its own ADR (new adapter methods, scopes) | — |

## 8. Risks
- Prompt injection through tool results: data blocks, no write tools, recipients from DB, call caps.
- Latency: query agent can take up to 4 SQL attempts; the "<600 ms / 1.5-3.5 s" targets are goals, not guarantees.
- Gemini rejects deeply nested tool schemas: keep tool arguments flat; use `gemini_prompted` if an output nests.
- `routes.py` is 2242 lines; deleting the regex gates in slice 1 is also the chance to split it.
