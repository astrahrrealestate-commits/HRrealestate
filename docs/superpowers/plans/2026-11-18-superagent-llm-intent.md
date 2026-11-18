# Super Agent LLM Intent Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the keyword/regex pre-routers in the Super Agent with the concierge planner running on a Flash model, keeping exact commands only as the outage fallback.

**Architecture:** `Settings.concierge_model` picks the planner's model. Prompt `concierge/v8` adds `remember`, `calendar`, `rent_status` and `rewrite_draft` intents and states the rules for negation, "a word is not an intent" and several requests in one message. The regex branches and guards in `ask_agent` and the `parse_command` gate in `concierge_turns` are deleted; `remember`/`calendar` plan steps reuse the existing response builders, and `ask_agent` merges the answers and cards of all steps in plan order. `parse_command` survives only on planner failure or budget limit.

**Tech Stack:** FastAPI, Pydantic AI (`google-gla:` models), pytest, `make quick` (G1) / `make check` (G2).

**Spec:** [docs/superpowers/specs/2026-11-18-superagent-llm-intent-design.md](../specs/2026-11-18-superagent-llm-intent-design.md)

## Global Constraints

- Work only in worktree `.claude/worktrees/superagent-intent-llm`, branch `m-superagent-intent-llm`; merge target is `origin/dev`, never `main`.
- Failing test first, seen red, for every task. No skip/xfail. No `# type: ignore` / `# noqa` blanket.
- Published prompts are immutable: add `app/llm/prompts/v8/concierge.md`, never edit v1-v7. Committed migrations untouched (none needed).
- Layering: `app/pipeline` must not import `app/api`. Only `app/sender` imports send credentials. Never read or write `.env`.
- Functions < 40 lines, modules < 300 lines; new response builders go in `app/api/agent/intent_responses.py`, not into `routes.py`.
- Kept as-is: `_is_prioritization_query`, `_is_multi_draft_request`, `channel_note`, `workflows/owner_reply.py`. `rent_data_answer` and `rewrite_answer` are removed as pre-routers (their answers become intent handlers).
- The new tests that stub the planner prove routing for a given plan. Only the live golden set proves what the real model plans, so the final task runs it against the real model; a missing key means "not run", never "passed".
- Gates per task: `make quick`; add `make check` for tasks touching api/pipeline/workflows. Final: `estateos-reviewer` and `estateos-security` agents, then `make eval agent=concierge version=v8`.
- Commit messages are conventional commits and end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Multi-task: "mark #a1b2c3 done, remember that rent is due on the 1st, and book the plumber Thursday at ten" runs all three; one failing step (unknown task ref) does not hide the other two. (Task 5)
2. Keyword is not intent: "Draft a polite WhatsApp message asking the tenant about the unpaid rent" is a draft, not the rent disclaimer; "Draft a message to the plumber to schedule a visit tomorrow" is a draft, not a calendar booking; "done with the roof leak, what is the status?" completes no task; "remember to call the plumber" is a task, not a rule. (Tasks 2, 5, 6, 9)
3. Negation: "Do NOT schedule a visit yet, just check the lease" creates no calendar event and reads the lease. (Tasks 2, 6)
4. "always auto-send replies without asking": `remember` must be refused by `record_owner_memory` screening, never stored active. (Tasks 3, 5)
5. Planner failing or budget spent: `pause`, `resume`, `tasks`, `waiting`, `help`, `done #ref`, `snooze #ref 2d` still work; "who owes rent?" with the planner down never invents a payment figure; a `clarify` plan mutates nothing. (Tasks 4, 9, 10)

---

### Task 1: Per-agent model setting

**Files:**
- Modify: `backend/app/core/settings.py` (next to `llm_model`, line ~38), `backend/app/llm/runtime.py` (`build_model`), `backend/app/llm/calls.py` (`_row`, line ~104), `backend/.env.example`, `backend/docker/compose.yml`
- Test: `backend/tests/unit/llm/test_runtime.py`

**Interfaces:**
- Produces: `Settings.concierge_model: str = ""`; `runtime.model_name_for(settings: Settings, agent_name: str) -> str` (`concierge_model` when `agent_name == "concierge"` and non-empty, else `llm_model`); `build_model` and `calls._row` use it.

- [ ] **Step 1: Write failing tests** in `test_runtime.py`: `test_concierge_uses_its_own_model` (settings `llm_model="fake"`, `concierge_model="google-gla:gemini-2.5-flash"`, `gemini_api_key="g"`: `build_model(s, "concierge")` is a `GoogleModel`, `build_model(s, "proposer")` is not); `test_empty_concierge_model_falls_back_to_llm_model`; `test_model_name_for_records_the_override`.
- [ ] **Step 2:** `make quick` or `cd backend && uv run pytest tests/unit/llm/test_runtime.py -q`. Expected: FAIL (`concierge_model` unknown).
- [ ] **Step 3:** Implement `model_name_for`; make `build_model` read it instead of `settings.llm_model` (fallback models still wrap the result; `fake` never gets fallbacks); `_row` stores `model_name_for(settings, spec.name)`; update the `run_agent` post-call `row.model` default (`settings.llm_model`, calls.py ~148) the same way. Add `CONCIERGE_MODEL=` with a comment to `.env.example` and compose.
- [ ] **Step 4:** Same pytest command plus `test_model_fallback.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(llm): per-agent concierge_model setting`.

### Task 2: Concierge prompt v8, contract intents, fake model

**Files:**
- Create: `backend/app/llm/prompts/v8/concierge.md`
- Modify: `backend/app/contracts/concierge.py` (`Intent`), `backend/app/llm/agents/concierge.py` (`PROMPT_VERSION = "v8"`, comment), `backend/app/llm/fakes_concierge.py`, `backend/evals/golden/` concierge cases, `backend/evals/concierge_eval.py` if it lists intents
- Test: `backend/tests/unit/llm/test_concierge_agent.py`, `backend/tests/unit/llm/test_concierge_fake_reply.py`

**Interfaces:**
- Produces: `Intent.remember`, `Intent.calendar`, `Intent.rent_status`, `Intent.rewrite_draft` (string values equal the names). `remember`/`calendar` use `PlanStep.text` (rule text, scheduling request); `rent_status`/`rewrite_draft` need no text; all four leave `case_id`/`task_ref`/`view` null, except `rewrite_draft` which may carry the draft's `case_id`.

- [ ] **Step 1: Write failing tests:** `test_v8_prompt_names_the_four_new_intents_and_the_three_rules` (loaded v8 text mentions each intent, negation, "a word is not an intent", several requests in one message; v7's sha256 is unchanged); `test_fake_planner_emits_remember_for_a_rule` ("from now on never promise a repair date": one `remember` step with that text); `test_fake_planner_emits_calendar_for_a_visit` ("book a visit with the plumber on Thursday": one `calendar` step); `test_fake_planner_does_not_book_a_payment_schedule`; `test_fake_planner_drafts_about_unpaid_rent` ("Draft a polite WhatsApp message asking the tenant about the unpaid rent": `draft_reply`, no `rent_status`); `test_fake_planner_drafts_about_a_visit` ("Draft a message to the plumber to schedule a visit tomorrow": `draft_reply`, no `calendar`); `test_fake_planner_respects_negation` ("Do NOT schedule a visit yet, just check the lease": no `calendar`, one document step); `test_fake_planner_returns_several_steps` ("mark #a1b2c3 done and snooze #d4e5f6 2d": two steps in that order).
- [ ] **Step 2:** `uv run pytest tests/unit/llm/test_concierge_agent.py tests/unit/llm/test_concierge_fake_reply.py -q`. Expected: FAIL.
- [ ] **Step 3:** Add the four `Intent` members; write v8 as v7 plus: `remember` (standing rule or preference to keep; reminders and to-dos are `create_task`), `calendar` (book, move or look up a visit or appointment; not a payment or maintenance schedule), `rent_status` (who owes or paid rent, arrears, collection), `rewrite_draft` (shorten, translate or rephrase an existing draft), the negation rule, "a word is not an intent", and the several-requests-several-steps rule with the 4-step cap. Bump `PROMPT_VERSION`. In `fakes_concierge.py` map the new intents, reusing its existing regexes (test-only). Add golden cases in `evals/golden` for every Review Focus example (2, 3, 4) and the multi-task example (1).
- [ ] **Step 4:** Same pytest command. Expected: PASS. Also `uv run pytest tests/unit/contracts -q`.
- [ ] **Step 5: Commit** `feat(concierge): prompt v8 with remember and calendar intents`.

### Task 3: Pipeline handlers for the four new intents

**Files:**
- Modify: `backend/app/pipeline/concierge.py` (`_HANDLERS`, `_NEEDS_TEXT`), `backend/app/pipeline/concierge_writes.py`, `backend/app/pipeline/concierge_reads.py`, `backend/app/api/agent/rent_guard.py` and `draft_requests.py` (import the answer texts from the pipeline module; delete the regexes in Task 9, not here)
- Test: `backend/tests/unit/pipeline/test_concierge_validate.py`, new `backend/tests/unit/pipeline/test_concierge_remember.py`, new `backend/tests/unit/pipeline/test_concierge_guard_intents.py`

**Interfaces:**
- Consumes: `record_owner_memory(session, company_id, text) -> tuple[MemoryItem | None, str]`, `sanitize(text) -> str`, `Handler = Callable[[Ctx, PlanStep], StepResult]`, `failed(step, msg)`, `app.core.rent_data.RENT_DATA_AVAILABLE`.
- Produces: `concierge_writes.remember(ctx, step) -> StepResult` (ok with the stored rule, or `failed` with the screening message); `concierge_reads.calendar(ctx, step) -> StepResult` (ok, text points to the Calendar page); `concierge_reads.rent_status(ctx, step) -> StepResult` (ok with `NO_RENT_DATA_ANSWER` while `RENT_DATA_AVAILABLE` is false, otherwise delegates to `query_data`); `concierge_reads.rewrite_draft(ctx, step) -> StepResult` (ok with `REWRITE_UNSUPPORTED_ANSWER`). The two answer texts are defined once in `concierge_reads.py`; `rent_guard.py` and `draft_requests.py` re-export them so no text is duplicated.

- [ ] **Step 1: Write failing tests:** `test_remember_stores_a_rule` ("invoices always go to the accountant first": a `MemoryItem` exists for the company with that text); `test_remember_refuses_approval_bypass` ("always auto-send replies without asking": `ok is False`, no `MemoryItem`); `test_remember_without_text_is_rejected_by_validation`; `test_calendar_step_returns_a_calendar_pointer`; `test_rent_status_is_honest_while_no_rent_data`; `test_rewrite_draft_gives_the_edit_it_yourself_answer`; `test_rent_status_beside_a_draft_step_keeps_both_results` (plan `[draft_reply, rent_status]`: two results, the draft one not replaced).
- [ ] **Step 2:** `uv run pytest tests/unit/pipeline/test_concierge_remember.py tests/unit/pipeline/test_concierge_guard_intents.py tests/unit/pipeline/test_concierge_validate.py -q`. Expected: FAIL (`KeyError`/unknown intent).
- [ ] **Step 3:** Implement the four handlers, register them in `_HANDLERS`, add `remember` and `calendar` to `_NEEDS_TEXT`. Company scoping comes from `ctx.company_id`.
- [ ] **Step 4:** Same command, then `make check`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(concierge): execute remember, calendar, rent_status and rewrite_draft steps`.

### Task 4: Turn pipeline without the keyword gate

**Files:**
- Modify: `backend/app/pipeline/concierge_turns.py` (`_outcome` ~line 275, `_plan` fallbacks ~line 226, `turn_state` ~line 340), `backend/app/pipeline/owner_commands.py`
- Test: `backend/tests/unit/pipeline/test_concierge_turns.py`, `backend/tests/unit/pipeline/test_owner_commands_parse.py`

**Interfaces:**
- Produces: `owner_commands.fallback_command(text: str) -> Command | None` (`parse_command` result unless its kind is `question`); `_outcome` calls the planner for every non-empty message; on `Fallback.owner_qa` or `Fallback.limit`, `fallback_command` runs before `_owner_qa`/`LIMIT_ANSWER`; `turn_state`'s `resume` is true when the stored plan has a `resume` step, or the plan is `None`, results are `None` and `fallback_command(text).kind` is `resume`.

- [ ] **Step 1: Write failing tests:** `test_a_message_starting_with_done_goes_to_the_planner` ("done with the roof leak, what is the status?" with a counting fake planner: planner called once, no task completed); `test_pause_phrase_reaches_planner_and_pauses_via_plan` ("please hold off on proposals" with a fake plan holding a `pause` step: company paused); `test_planner_failure_runs_exact_command` (planner raises `AgentFailedError`, text `tasks`: reply starts "Open tasks" or "No open tasks."); `test_budget_limit_still_pauses` (planner raises `BudgetExceededError`, text `pause`: company paused); `test_turn_state_resume_from_plan`.
- [ ] **Step 2:** `uv run pytest tests/unit/pipeline/test_concierge_turns.py -q`. Expected: FAIL.
- [ ] **Step 3:** Delete the `parse_command` gate in `_outcome` (keep `screen_question` and `_page`); add `fallback_command` and call it in the two fallback branches; update `turn_state`. Update the module docstring that still describes the fast path.
- [ ] **Step 4:** Same command, then `make check`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(concierge): planner decides intent; exact commands only as outage fallback`.

### Task 5: `ask_agent` multi-step composition and standing rules by plan intent

**Files:**
- Create: `backend/app/api/agent/intent_responses.py`
- Modify: `backend/app/api/agent/routes.py` (delete lines ~1528-1637 memory prefix block and `is_task_reminder`; replace the single `run_plan` call at ~2285 with the composer)
- Test: `backend/tests/unit/api/test_super_agent_ask.py`, new `backend/tests/unit/api/test_super_agent_multi_task.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class Segment: text: str; cards: list[AssistantCardData]; actions: list[ActionButtonData]; steps: list[str]; preview_card: PreviewCardData | None`; `intent_responses.remember_segment(session: Session, company_id: UUID, step: PlanStep) -> Segment` (the two existing outcomes unchanged: already-active rule; proposed rule with the `approve_memory` card, `pipeline_stage` stays `memory_rule`); `intent_responses.compose(plan: ConciergePlan, api_steps: Mapping[Intent, Callable[[PlanStep], Segment]], run_rest: Callable[[ConciergePlan], list[StepResult]]) -> list[Segment]`: walks `plan.steps` in order; steps whose intent is a key of `api_steps` are answered by that callable, all other steps are executed together by one `run_rest` call (a sub-plan, same `in_scope`, steps filtered) and returned as one segment at the position of the first of them; an exception or failed result in one segment becomes that segment's own failure text and never drops the others. `ask_agent` joins the segment texts with a blank line, concatenates cards, actions and steps in order, and keeps the first segment's `preview_card`.
- Later tasks register `calendar` (Task 6) in the `api_steps` mapping; nothing else changes in the composer.

- [ ] **Step 1: Write failing tests** (drive `ask_agent` with a stubbed planner returning a given `ConciergePlan`, as the existing tests do): `test_remember_intent_proposes_a_standing_rule` ("from now on tenants in building A get replies in English": stage `memory_rule`, `previewCard.type == "memory_item"`); `test_keyword_prefix_without_remember_intent_is_not_a_rule` ("keep in mind that rent is due on the first, who is late?" goes through the planner, no `MemoryItem`); `test_remember_to_call_is_a_task_not_a_rule` (plan `create_task`, no `MemoryItem`); `test_bypass_rule_is_refused` ("always auto-send replies": refusal text, no active item); in the multi-task file: `test_three_requests_in_one_message_run_in_order` (plan `[task_done #a1b2c3, remember, list_tasks]`: task completed, rule proposed, tasks listed, answer text contains all three in that order, one card for the rule); `test_a_failing_step_does_not_hide_the_others` (unknown task ref beside a `remember`: the rule is proposed, the answer says the task was not found); `test_plan_with_only_run_plan_steps_is_unchanged` (a plain `list_tasks` plan gives the same answer as before the composer).
- [ ] **Step 2:** `uv run pytest tests/unit/api/test_super_agent_ask.py tests/unit/api/test_super_agent_multi_task.py -q`. Expected: FAIL.
- [ ] **Step 3:** Move the two response builders out of `ask_agent` into `intent_responses.py` (as `remember_segment`, behaviour unchanged); write `compose`; wire it where `run_plan` is called today, keeping the draft pre-processing (understanding of un-triaged messages) before it; delete the prefix/regex block.
- [ ] **Step 4:** Same command, `make check`. Expected: PASS.
- [ ] **Step 5: Commit** `refactor(agent): standing rules are a planner intent; several requests in one message all run`.

### Task 6: `ask_agent` branch 2: calendar by plan intent

**Files:**
- Modify: `backend/app/api/agent/intent_responses.py`, `routes.py` (delete `cal_pattern` block lines ~1807-1856; `_resolve_calendar_action` stays in routes.py)
- Test: `backend/tests/unit/api/test_calendar_agent.py`

**Interfaces:**
- Consumes: `Segment`, `compose` from Task 5.
- Produces: `intent_responses.calendar_segment(resolved: tuple[str | None, PreviewCardData | None, list[ActionButtonData], list[str]]) -> Segment` wrapping the existing card/button assembly (`pipeline_stage` becomes `calendar`); registered in the composer's `api_steps` for `Intent.calendar`, with `routes.py` calling `_resolve_calendar_action(step.text, ...)` so `routes.py` stays the only importer of that helper.

- [ ] **Step 1: Write failing tests:** `test_calendar_intent_books_a_visit` ("can the plumber come Thursday at ten": calendar card present, stage `calendar`); `test_payment_schedule_is_not_a_calendar_request` ("what is the payment schedule for unit 3": no calendar card); `test_draft_that_mentions_a_visit_is_a_draft` (plan `draft_reply` for "Draft a message to the plumber to schedule a visit tomorrow": draft card, no calendar card, `_resolve_calendar_action` not called); `test_negated_schedule_books_nothing` (plan `read_document` for "Do NOT schedule a visit yet, just check the lease": no calendar event row); `test_calendar_and_draft_in_one_message` (plan `[draft_reply, calendar]`: both a draft card and a calendar card); update existing tests that assert `regex_calendar` to the new stage name.
- [ ] **Step 2:** `uv run pytest tests/unit/api/test_calendar_agent.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement, delete the regex block.
- [ ] **Step 4:** Same command, `make check`. Expected: PASS.
- [ ] **Step 5: Commit** `refactor(agent): calendar requests are a planner intent, not a keyword`.

### Task 7: `ask_agent` branch 3: `done`/`snooze` bypass and document regex removed

**Files:**
- Modify: `routes.py` (delete the `task_command` block ~1749-1767 and the `doc_pattern`/`is_doc_task` block ~1857-1983)
- Test: `backend/tests/unit/api/test_super_agent_ask.py`, `backend/tests/unit/api/test_dashboard_agent.py`

- [ ] **Step 1: Write failing tests:** `test_done_ref_is_completed_through_the_plan` ("done #a1b2c3" with a fake plan `task_done`: task completed via `run_plan`); `test_done_in_a_sentence_does_not_complete_a_task` ("I am done with the paint, what is next" completes nothing); `test_lease_question_uses_document_intents` (fake plan with `find_document`: no `regex_document` stage, answer comes from `run_plan`); remove or rewrite tests asserting `owner_command`/`regex_document`.
- [ ] **Step 2:** `uv run pytest tests/unit/api -q`. Expected: FAIL.
- [ ] **Step 3:** Delete both blocks; confirm no remaining reference to `doc_pattern`, `search_hybrid`, `build_embedder` imports that became unused (ruff will say).
- [ ] **Step 4:** Same command, `make check`. Expected: PASS.
- [ ] **Step 5: Commit** `refactor(agent): document and task commands go through the planner`.

### Task 8: `ask_agent` branch 4: count/list regex removed

**Files:**
- Modify: `routes.py` (delete `is_draft_or_action_cmd`, `is_count_or_list_query`, `is_database_keyword` and the `query_agent` block ~1985-2075)
- Test: `backend/tests/unit/api/test_super_agent_ask.py`, `backend/tests/unit/tools/test_query_agent.py`

- [ ] **Step 1: Write failing tests:** `test_count_question_runs_query_data_via_plan` ("how many open ticketes do I have" with a fake plan `query_data`: query agent called once, via the plan); `test_dutch_count_question` ("hoeveel huurders heb ik"); `test_clarify_plan_mutates_nothing` (plan with only `clarify`: no task, rule, draft or pause row changes).
- [ ] **Step 2:** `uv run pytest tests/unit/api tests/unit/tools/test_query_agent.py -q`. Expected: FAIL.
- [ ] **Step 3:** Delete the block; the result of `query_data` already reaches the answer through `assemble_answer`. If the old card (`_build_query_preview_card`) is lost for plan-run queries, keep it by reading `StepResult.data` in the existing results-to-cards code.
- [ ] **Step 4:** Same command, `make check`. Expected: PASS.
- [ ] **Step 5: Commit** `refactor(agent): count and list questions go through query_data`.

### Task 9: Rent and rewrite pre-guards become intents

**Files:**
- Modify: `routes.py` (delete the `rewrite_answer` block ~1770-1784 and the `rent_data_answer` block ~1788-1803), `backend/app/api/agent/rent_guard.py` (delete `_RENT_MONEY_QUESTION` and `rent_data_answer`, keep the re-exported text if anything imports it), `backend/app/api/agent/draft_requests.py` (delete `_REWRITE`, `_ABOUT_A_DRAFT`, `rewrite_answer`; keep `channel_note`)
- Test: `backend/tests/unit/api/test_super_agent_ask.py`, existing tests of `rent_guard` and `draft_requests` (rewrite or delete the ones that test the removed regexes, keeping the answer-text assertions)

**Interfaces:**
- Consumes: `concierge_reads.rent_status` and `concierge_reads.rewrite_draft` from Task 3, which `run_plan` already executes; no API-layer registration needed.

- [ ] **Step 1: Write failing tests:** `test_unpaid_rent_in_a_draft_request_is_drafted` (plan `draft_reply` for "Draft a polite WhatsApp message asking the tenant about the unpaid rent": a draft card is returned and the answer does not contain `NO_RENT_DATA_ANSWER`); `test_who_owes_rent_gets_the_honest_answer_via_rent_status` (plan `rent_status`: answer equals `NO_RENT_DATA_ANSWER`, stage not `rent_data_unavailable`); `test_draft_and_rent_status_in_one_message` (plan `[draft_reply, rent_status]`: draft card plus the disclaimer text); `test_make_it_shorter_uses_rewrite_draft` (plan `rewrite_draft`: answer equals `REWRITE_UNSUPPORTED_ANSWER`); `test_word_rewrite_in_a_question_is_not_a_rewrite_request` ("what is the rewrite deadline for the lease" with an `answer` plan: not the rewrite text).
- [ ] **Step 2:** `uv run pytest tests/unit/api -q`. Expected: FAIL.
- [ ] **Step 3:** Delete both pre-guard blocks and the two regex helpers; fix imports.
- [ ] **Step 4:** Same command, `make check`. Expected: PASS.
- [ ] **Step 5: Commit** `refactor(agent): rent and rewrite answers are planner intents, not keyword guards`.

### Task 10: Rule keyword overrides removed, outage fallback in `ask_agent`

**Files:**
- Modify: `routes.py` (the `any(k in q_low for k in ["rule", ...])` branch ~1715-1743, the `matching_rule` word-overlap override ~2308-2320, the `llm_failed` path ~2160-2180)
- Test: `backend/tests/unit/api/test_super_agent_ask.py`

**Interfaces:**
- Consumes: `owner_commands.fallback_command(text) -> Command | None` from Task 4.

- [ ] **Step 1: Write failing tests:** `test_rule_word_in_a_question_is_answered_by_the_model_with_rules_in_context` ("is there a rule about contractor visits?" goes to the planner, which already receives `owner_preferences`); `test_planner_down_runs_exact_pause` (planner raises, text `pause`: company paused, reply "Paused: ..."); `test_planner_down_runs_exact_tasks`; `test_planner_down_free_text_uses_existing_fallback` ("who owes rent?" keeps the current offline answer).
- [ ] **Step 2:** `uv run pytest tests/unit/api/test_super_agent_ask.py -q`. Expected: FAIL.
- [ ] **Step 3:** Delete both keyword overrides; in the `llm_failed` path call `fallback_command` first and `run_command` when it returns a command, with `pipeline_stage="owner_command_fallback"`.
- [ ] **Step 4:** Same command, `make check`. Expected: PASS.
- [ ] **Step 5: Commit** `refactor(agent): no keyword overrides; exact commands only when the planner is down`.

### Task 11: Docs, ADR, eval, review, merge to dev

**Files:**
- Create: `docs/adr/0013-per-agent-model.md`
- Modify: `docs/PROGRESS.md`, `docs/tech-stack.md`, `docs/hld.md` (Super Agent routing), `docs/dashboard-api.md` if it lists pipeline stages (`regex_calendar`, `owner_command`, `regex_document`, `query_agent`)

- [ ] **Step 1:** Write the ADR (decision: `concierge_model`, why not a classifier call, fallback-only commands) and update the docs; list the removed and renamed pipeline stages.
- [ ] **Step 2:** `make check` and `make harness-test`. Expected: all green; quote the result lines.
- [ ] **Step 3:** Live eval, needs the owner's key in the worktree `.env`: `CONCIERGE_MODEL=google-gla:<flash model> make eval agent=concierge version=v8`. Expected: no regression versus v7, and every Review Focus golden case (multi-task, keyword-is-not-intent, negation, rent disclaimer) passes. The rent disclaimer used to be guaranteed by a regex and now depends on the model, so if the key is absent or a case fails: do NOT push to `dev`; report it and stop.
- [ ] **Step 4:** Dispatch `estateos-reviewer` and `estateos-security` on the branch diff; fix findings.
- [ ] **Step 5:** `git fetch origin dev && git rebase origin/dev`, rerun `make check`, then `git push origin m-superagent-intent-llm:dev` (standing OK; fast-forward only; no force push). Report what was and was not tested, and the production-behaviour change: every dashboard message now makes one planner call, and the rent disclaimer is model-chosen.
