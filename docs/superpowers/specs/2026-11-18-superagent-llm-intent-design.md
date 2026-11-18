# Super Agent: LLM intent routing instead of keyword/regex pre-routers (short design)

Status: approved by the owner on 2026-11-18 (scope widened and re-approved the same day). Branch
`m-superagent-intent-llm`, based on `origin/dev`. Merge target is `dev`, never `main`.

## Intent and why
Before the concierge planner runs, the Super Agent tries a stack of exact-word, prefix and regex matchers. Each one that
matches answers on its own and the planner never sees the message. They are too strict ("can you hold off on proposals" is
not understood) and too loose (a message that merely contains `visit`, `lease` or `done` is acted on). The planner
(`ConciergePlan`) already has intents for most of what they do.

Where they live:
- `api/agent/routes.py::ask_agent` (dashboard Super Agent): standing-rule prefixes and the `remember to` regex
  (`memory_rule`), `parse_command` for `done`/`snooze` (`owner_command`), the calendar regex (`regex_calendar`), the
  document regex plus three exclusion regexes (`regex_document`), the count/list regex and `sql query` keywords
  (`query_agent`), and two keyword overrides that answer with stored standing rules instead of the model.
- `pipeline/concierge_turns.py::_outcome` (turn pipeline): `parse_command` before the planner, and `turn_state`
  detecting `resume` from the text.

## Goals
- Every dashboard message reaches the planner; the planner decides the intent.
- The planner can run on a fast model (Gemini Flash) while other agents keep `llm_model`.
- `pause`, `resume`, `tasks`, `waiting`, `help`, `done`, `snooze` keep working when the planner fails or the budget is hit.

## Non-goals and kept guards
- WhatsApp owner workflow (`workflows/owner_reply.py`) unchanged: there `parse_command` also separates commands from edits
  to an approval draft, a different decision.
- Kept: the plan filters `_is_prioritization_query` / `_is_multi_draft_request` (they constrain the model's plan, they
  never route) and `channel_note` (a sentence before a draft, not a router).
- NOT kept (owner, 2026-11-18, after seeing "draft a message about the unpaid rent" answered with the rent disclaimer):
  `rent_data_answer` and `rewrite_answer` also pre-empt the planner by keyword. Their honest answers become planner
  intents with deterministic handlers (`rent_status`; the stale rewrite guard is just deleted, see below), so they apply to their own step only and compose
  with other steps in the same message.
- No second classifier call in front of the planner.
- The executor still validates every step; recipients and ids come from the DB; the Super Agent never approves or sends.

## Anti-goals
- A model misread must never become a mutation without the existing safety screening (`record_owner_memory`
  screening, executor `check_step`). When unsure the planner returns `clarify`.
- `pause`/`resume` must not need the model during an outage.

## Approaches considered
- A planner does everything: `pause`/`help` die with the model or the budget.
- B separate Flash classifier before the planner: second call per turn, duplicated routing.
- **C (chosen)**: A, plus exact commands only as the degraded path when the planner fails or the budget is hit.

## Design
1. **Per-agent model.** `Settings.concierge_model` (default empty = use `llm_model`); `build_model` uses it for the
   `concierge` agent; `model_calls.model` records the model actually used.
2. **Prompt `concierge/v8`** (v7 stays published) adds intents `remember` (text = the rule or preference), `calendar`
   (text = the scheduling request), `rent_status` (who owes or paid rent; the handler gives the honest "not connected"
   answer while `RENT_DATA_AVAILABLE` is false) (no `rewrite_draft` intent: shorten, translate and rephrase are `draft_reply`, which already redrafts with the owner's own words as guidance; ruling 2026-11-18, the old `rewrite_answer` guard was stale). Documents and count/list questions use the existing
   `find_document`, `read_document` and `query_data` intents; `done`/`snooze` use `task_done`/`task_snooze`.
   The prompt also states: negation ("do NOT schedule yet") means no step for that action; a word is not an intent
   (drafting a message that mentions a visit or unpaid rent is `draft_reply`, not `calendar` or `rent_status`); several
   requests in one message become several steps (max 4), in the order asked.
2b. **Multi-task messages.** The planner already returns up to 4 steps. `ask_agent` runs them all: steps the API layer
   owns (`remember`, `calendar`) are answered by their response builders, the rest by `run_plan`, and the answer, cards
   and buttons are merged in plan order. A step that fails does not hide the others.
3. **Pipeline handlers** for `remember` (sanitize, then `record_owner_memory`) and `calendar` (the calendar helpers live
   in the API layer, which the pipeline may not import, so the pipeline handler returns a fixed pointer to the Calendar
   page: my call).
4. **`ask_agent`**: the regex/keyword branches are deleted, including the rent and rewrite pre-guards. After the planner
   returns, `remember` and `calendar` steps are answered by the existing response builders, moved unchanged into
   `api/agent/intent_responses.py` (routes.py is 3,000 lines). Same cards, same buttons; only the trigger changes.
   Known residual risk: the rent disclaimer used to be guaranteed by a regex; now it depends on the planner choosing
   `rent_status`. The v8 golden set pins it, and it must be run against the real model before merging.
5. **Fallback**: when the planner fails or the budget is hit, `parse_command` runs first (exact commands), then the
   existing fallbacks. `turn_state` reads `resume` from the stored plan, or from the text for the fallback path.
6. **Staged commits**, each shippable: model setting; v8 and handlers; turn pipeline; ask_agent branch by branch
   (remember, done/snooze, calendar, documents, count/list, rule overrides, fallback); docs and ADR.

## Calls made by me (not the owner)
- Setting name `concierge_model`; value is a Pydantic AI model string, e.g. `google-gla:<flash model>`. "3.8 flash"
  could not be verified (the repo references only `gemini-2.5-flash`); the owner sets the exact name in `.env`.
- The owner copies `GEMINI_API_KEY` into the worktree `.env` for live runs; code only reads `settings.gemini_api_key`.
- Gemini calls need `GOOGLE_GENAI_API_VERSION=v1beta` (pinned on `fix/onboarding-sweep`, check that `dev` has it).

## Left to the builder
Prompt wording; golden-set cases; exact helper shapes inside `intent_responses.py`.
