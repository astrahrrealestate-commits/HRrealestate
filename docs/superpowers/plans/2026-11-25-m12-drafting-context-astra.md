# M12 AI Staff: Categories, Drafting Context, Astra and 90-Day Reload — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harjot logs in, picks one of six categories, and sees the next actions of that area with the work already
done: drafts he would send (from the whole history, attachments, memory and web research), countered quotes, read
documents. Astra can open and search everything. 90 days of mail are reloaded cleanly through the real pipeline.

**Architecture:** Six categories replace the old ones end to end. One `Dossier` per mail feeds proposer `v6`, Astra and
the category briefs. Attachments are read, quotes compared and web research done before drafting. The reload uses a
`history` flag on the normal pipeline, then drafts only open, unanswered conversations.

**Tech Stack:** Python 3.12, FastAPI, DBOS, SQLAlchemy 2, Pydantic AI, Postgres + pgvector, Next.js. **Gemini API only** (models,
embeddings, Google Search grounding).

**Spec:** `docs/superpowers/specs/2026-11-25-m12-drafting-context-astra-design.md`

**Branch:** `m12-ai-staff` from `m-chats` at `a0a076a`. Two worktrees: `m12-a` (Dev A), `m12-b` (Dev B); merge into
`m12-ai-staff` at each sync point.

## Global Constraints
- Categories, exactly: `maintenance`, `finance`, `legal`, `business`, `administration`, `new_projects` (+ internal `spam`).
  Display names: Maintenance, Finance, Legal, Business, Administration, New projects.
- CLAUDE.md invariants hold, above all 4 (`company_id` on every query), 5 (send isolation), 6 (untrusted text only in
  `data_block`; agents have no write tools; recipients from the DB), 9 (published prompts never edited: new versions).
- Related context: same person, same unit or lease, company vendor data. Never another tenant's mail or documents.
- Web pages are untrusted data, like mail; every research finding carries its URL; no finding without one.
- Send mode stays off. Nothing here sends; drafts still need Harjot's approval.
- **Harjot's drafting standard** (spec, "Drafting standard", quoted verbatim) binds every draft from every path:
  proposer, owner redraft, Astra, `draft-open`. No generic acknowledgement is ever offered as a draft.
- History-mode mail never creates an action, approval, owner card, alert, wait, chaser or document review card.
- Purge needs a preview, a DB snapshot, the worker stopped and a typed confirmation.
- Gemini API key only: every model, embedding and web search goes through it; no other provider, key or fallback.
- Quality tier (reasoning `high`): proposer, research, Astra, doc reader, person memory, category brief, on the
  strongest Gemini Pro model the key lists. Fast tier (reasoning `low`, `google-gla:gemini-3.8-flash`): understanding,
  link check, case summary, price extraction.
- Failing test first; `make check` green before each commit; `estateos-security` pass on tasks touching `app/api`,
  `app/sender`, `app/channels`, `app/llm`, prompts or external input.

## Review Focus
1. Another tenant's mail or document reaching a dossier or a category brief → excluded.
   Tests: `test_dossier_never_holds_another_tenants_mail_or_documents` (T6), `test_brief_only_sees_listed_actions` (T11).
2. Instructions inside an attachment, earlier mail or web page → stay data; the rules engine still holds an unverified
   IBAN or link. Tests: eval case `injected_attachment` (T9), `test_research_page_text_is_data` (T8).
3. A 300-page PDF or a 60-mail thread → older material clipped first, the current mail never cut.
   Test: `test_dossier_keeps_the_current_mail_whole_when_over_budget` (T6).
4. Reload interrupted and rerun → no duplicate messages, cases, drafts or Drive files.
   Tests: `test_reingest_twice_records_each_mail_once`, `test_history_filing_does_not_duplicate_drive_files` (T2).
5. Live mail during the reload → drafted as usual, not stuck behind history.
   Test: `test_live_mail_is_drafted_while_history_runs` (T1).
6. A model answering with a polite empty acknowledgement → never shown as a draft.
   Tests: `test_a_generic_draft_is_redrafted_then_dropped` (T9), `test_no_canned_draft_anywhere` (T9, T12).

---

## Schedule (2 developers, 2–3 days)

| When | Dev A: intelligence | Dev B: reload, research, dashboard |
|---|---|---|
| Day 1 AM | T4 categories (contract, `understanding/v4`, migration) | T1 history mode |
| Day 1 PM | T5 per-agent models · T6 dossier (start) | T2 purge / reingest / draft-open · T3 script |
| Day 1 end | **Sync 1:** merge; `make check` | |
| Day 2 AM | T6 dossier (finish) · T7 person memory | T8 Gemini web search, quote comparison, research, read-before-draft |
| Day 2 midday | **Deploy 1 (needs merge to `main`):** T1–T5, T8. Stage: reload 7 days, check. Prod: `preview`, `purge`, `reingest 90` starts and runs overnight. | |
| Day 2 PM | T9 proposer `v6` + real-model eval | T10 category next-actions API |
| Day 3 AM | T11 Astra tools · category brief agent | T12 category dashboard UI |
| Day 3 midday | **Deploy 2:** T6, T7, T9–T12. Prod: `draft-open`. Hand-check 20 drafts across all six categories. | |
| Day 3 PM | Fixes from the hand check · T13 docs | Fixes · T13 run book |

Reingest is the long pole: start it on Deploy 1 so understanding, linking, reading and indexing finish overnight; the
drafts come on Deploy 2 from `draft-open`, after `v6` and memory are live.

---

### T1 (Dev B): History mode in the pipeline

**Files:** `backend/app/ingestion/process.py` (copy `payload["history"]` into `meta.history`) · create
`backend/app/ingestion/history.py` · `backend/app/workflows/pipeline.py:154-174` · `backend/app/workflows/documents.py`
(`review_card_step`) · `backend/app/pipeline/link.py:_after_link` · `backend/app/core/workflow_names.py`,
`backend/app/workflows/queues.py` · test `backend/tests/integration/test_history_mode.py`

**Produces:** `is_history(msg: MessageRow) -> bool`; `HISTORY_QUEUE: str` (concurrency setting
`history_queue_concurrency`, default 4); raw event payload key `"history": True`.

- [ ] Failing tests: `test_history_mail_is_understood_linked_and_indexed_but_never_drafted` (understanding, case link,
      message chunk exist; actions, approvals, owner feed, waits = 0); `test_history_attachment_gets_no_review_card`;
      `test_live_mail_is_drafted_while_history_runs` (20 history events queued, one live event drafted first).
- [ ] Run `cd backend && uv run pytest tests/integration/test_history_mode.py -q` → FAIL.
- [ ] Implement: history returns from `_after_understanding` after index, attachment reading, filing and quote review.
- [ ] Run → PASS; `make check` → exit 0. Commit `feat(pipeline): history mode reads and links mail without drafting`.

### T2 (Dev B): Purge, reingest, draft-open

**Files:** create `backend/app/workflows/mail_reload.py`, `backend/app/workflows/mail_reload_cli.py` · Drive filing:
skip upload when a file with the same sha256 exists in the target folder · delete
`backend/scripts/backfill_vastgoed_30d.py`, `.github/workflows/backfill_vastgoed.yml` · test
`backend/tests/integration/test_mail_reload.py`

**Produces:** `preview(engine, mailbox: str) -> ReloadPreview`; `purge(engine, mailbox: str, *, confirm: bool) ->
ReloadPreview`; `reingest(engine, mailboxes, mailbox: str, *, days: int) -> int`; `draft_open(engine, settings,
mailbox: str) -> int`. CLI: `--mailbox` plus one of `--preview | --purge --worker-stopped | --reingest --days N |
--draft-open`.

- [ ] Failing tests: `test_purge_removes_gmail_data_and_keeps_whatsapp_and_directory`;
      `test_purge_is_scoped_to_one_company`; `test_reingest_records_history_events_oldest_first` (5 mails over 120 days,
      `days=90` → 4); `test_reingest_twice_records_each_mail_once`;
      `test_draft_open_drafts_only_the_newest_unanswered_mail_of_open_cases` (unanswered → 1; answered, closed,
      `requires_reply=false` → 0); `test_history_filing_does_not_duplicate_drive_files`.
- [ ] Run `uv run pytest tests/integration/test_mail_reload.py -q` → FAIL.
- [ ] Implement: purge in one transaction, child tables first, every statement filtered by `company_id` and channel
      `gmail`; cases left without messages removed. `draft_open` first calls T7's `refresh_person_memory` for each person
      in the reload (no-op until T7 lands), then `propose_for_message` per open case.
- [ ] Run → PASS; `make check`. Commit `feat(reload): purge and reload a mailbox in history mode`.

### T3 (Dev B): Run script

**Files:** create `scripts/lib/ecs_task.sh` (helpers moved from `scripts/repair_mail.sh`), `scripts/mail_reload.sh
<stage|prod> <preview|purge|reingest|draft-open> [mailbox] [days]` · `scripts/repair_mail.sh` sources the helpers ·
test `backend/tests/unit/test_mail_reload_script.py` (stub `aws`, as `test_repair_mail_script.py`)

- [ ] Failing tests: preview only reads; purge needs `purge <env>` typed, stops the worker, waits for its tasks,
      snapshots, runs, restores; reingest and draft-open leave the worker running; an interrupted purge stops its own
      task before restoring; existing repair script tests unchanged.
- [ ] Run both test files → FAIL; implement; run → PASS under `/bin/bash` and Homebrew bash.
- [ ] Commit `feat(ops): mail reload script for deployed environments`.

### T4 (Dev A): Six categories end to end

**Files:** `backend/app/contracts/understanding.py:Category` (`maintenance, finance, legal, business,
administration, new_projects, spam`) and `Understanding` (`needs_research: bool`, `research_questions: list[str]` max
3) · create `backend/app/llm/prompts/v4/understanding.md` and pin it · migration (CHECK constraints on
`cases.category`, `understandings.category`; data map as in the spec) · every `Category.` use in `app/` (rules BRIXX
note, finance triggers, inbox stats and filters, briefings) · frontend labels and filters (`frontend/src/lib/inboxFilters.ts`,
`frontend/src/types/*`, inbox and dashboard) · golden set under `backend/evals/understanding/` relabelled · tests
`backend/tests/unit/contracts/test_categories.py`, `backend/tests/integration/test_category_migration.py`

**Produces:** `Category` with the six values plus `spam`; `CATEGORY_LABELS: dict[Category, str]` in
`backend/app/contracts/categories.py`; `Understanding.needs_research`, `.research_questions`. `understanding/v4` sets
`needs_research` for every quotation, every legal or lease question (ROZ, law), every works request, and any question
our data cannot answer.

- [ ] Failing tests: `test_categories_are_the_six_and_spam`; `test_old_values_map_on_migration` (each old value →
      new); `test_understanding_v4_prompt_lists_the_six_with_definitions`; `test_inbox_filter_by_each_category`.
- [ ] Run → FAIL; implement; `uv run pytest tests/unit/contracts tests/integration/test_category_migration.py -q` → PASS.
- [ ] `make eval agent=understanding version=v4` on the fast-tier model → category accuracy ≥ 0.9 on the relabelled set.
- [ ] `make check`; frontend `npx tsc --noEmit`, `npx vitest run`. Commit `feat(categories): six business categories`.

### T5 (Dev A): Per-agent model and reasoning, Gemini only

**Files:** `backend/app/core/settings.py` (`agent_models: dict[str, str]`, `agent_thinking: dict[str, str]`, env
`AGENT_MODELS`, `AGENT_THINKING` as JSON; prod validator refuses any model or fallback not starting `google-gla:`) ·
`backend/app/llm/runtime.py` (`model_name_for`) · `backend/app/llm/calls.py` (`thinking_for`) · create
`backend/app/dev/gemini_models.py` (lists models on the key) · `.env.example`, `docs/tech-stack.md` · test
`backend/tests/unit/llm/test_agent_models.py`

**Produces:** `model_name_for(settings, agent_name) -> str` (agent override, then `concierge_model`, then `llm_model`);
`thinking_for(settings, spec) -> ThinkingLevel | None`.

- [ ] Failing tests: `test_an_agent_override_wins`; `test_unset_agents_keep_llm_model`;
      `test_thinking_override_beats_the_spec`; `test_prod_refuses_a_non_gemini_model_or_fallback`;
      `test_prod_refuses_an_override_to_fake`.
- [ ] Run → FAIL; implement; run → PASS.
- [ ] `uv run python -m app.dev.gemini_models` with the prod key → pick the strongest Pro model listed; record it and the
      `AGENT_MODELS` / `AGENT_THINKING` values in `docs/go-live-channels.md`; remove `openai:gpt-4.1-mini` from the prod
      `LLM_FALLBACK_MODELS` task definition (replace with `google-gla:gemini-3.8-flash`).
- [ ] Commit `feat(llm): per-agent Gemini model and reasoning`.

### T6 (Dev A): The dossier

**Files:** create `backend/app/context/dossier.py`, `backend/app/context/dossier_render.py` · tests
`backend/tests/integration/test_dossier.py`, `backend/tests/unit/context/test_dossier_render.py`

**Produces:**
```python
ThreadLine(message_id, sent_at, direction, sender, subject, text, flagged)
AttachmentText(attachment_id, filename, text, flagged)
Finding(question, answer, url)              # T8
@dataclass(frozen=True)
class Dossier:
    thread: tuple[ThreadLine, ...]          # thread and case, both directions, oldest first
    sender_history: tuple[ThreadLine, ...]  # same person, other cases, newest first
    attachments: tuple[AttachmentText, ...]
    documents: tuple[Passage, ...]          # person, case, unit, lease documents via search_hybrid
    memory: PersonMemory | None             # T7
    owner_rules: tuple[str, ...]            # active memory items
    waiting: tuple[str, ...]
    quote: QuoteComparison | None           # T8
    research: tuple[Finding, ...]           # T8
    references: tuple[Passage, ...]         # company reference library: ROZ provisions, standard terms
def build_dossier(session, company_id: UUID, message_id: UUID, embedder: TextEmbedder | None) -> Dossier
def render_dossier(d: Dossier, budget: DossierBudget = DossierBudget()) -> list[str]  # data blocks; 60k chars
```
`PersonMemory`, `QuoteComparison`, `Finding` are defined first by T7/T8 as dataclasses; the dossier fills `None` or
`()` until those land.

Reference library: `documents.is_reference: bool` (migration, default false; set from the documents page or by
Astra's `file_document` with "as reference"). Reference documents are company material, never a tenant's, and are
searched for every dossier (ROZ articles, Harjot's standard terms, price lists).

- [ ] Failing tests: `test_dossier_includes_matching_reference_documents_for_any_tenant`;
      `test_dossier_holds_the_whole_thread_in_order_with_harjots_replies`;
      `test_dossier_holds_the_senders_mail_from_their_other_cases`; `test_dossier_holds_this_mails_attachment_text`;
      `test_dossier_never_holds_another_tenants_mail_or_documents` (same thread ref, same building, closer vector hit);
      `test_dossier_keeps_the_current_mail_whole_when_over_budget`; `test_dossier_marks_injected_attachment_text`.
- [ ] Run → FAIL; implement (scope = `case_scope` + person, lease, unit; every block a `data_block`); run → PASS.
- [ ] Commit `feat(context): one dossier per mail`.

### T7 (Dev A): Person memory

**Files:** create `backend/app/llm/agents/person_memory.py`, `backend/app/llm/prompts/v1/person_memory.md`,
`backend/app/pipeline/person_memory.py` · `PersonProfile.memory` jsonb + migration (`/new-migration`) · pipeline
refresh after link when stale (live mail) · `backend/app/pipeline/gdpr.py` clears it · test
`backend/tests/integration/test_person_memory.py`

**Produces:** `PersonMemory(summary, commitments, preferences, open_issues)` (tuples of str);
`refresh_person_memory(engine, settings, company_id, person_id) -> PersonMemory | None`.

- [ ] Failing tests: `test_memory_lists_what_harjot_promised`; `test_memory_refreshes_only_when_stale`;
      `test_memory_uses_this_persons_mail_only`; `test_erasure_clears_memory`.
- [ ] Run → FAIL; implement; run → PASS; `make check` (migration round-trip). Commit `feat(memory): person memory`.

### T8 (Dev B): Read, compare and research before drafting

**Files:** `backend/app/workflows/pipeline.py:154-174` (`read_attachments_step`, quote comparison and
`research_step` before `propose_step`; filing stays after) · create `backend/app/channels/prices/gemini_search.py`
(`GeminiSearchClient(SearchClient)`: Gemini with Google Search grounding on the existing key, the grounding source URLs
followed and each page fetched with `httpx`, 2 MB and 10 s caps), registry case `price_search_provider="gemini"` · create
`backend/app/finance/comparison.py` · create `backend/app/llm/agents/research.py`, prompt
`backend/app/llm/prompts/v1/draft_research.md`, `backend/app/pipeline/draft_research.py` (findings stored on the
message's understanding row under `research`) · `backend/app/finance/triggers.py:quote_candidate` (also sender role
contractor or business) · `backend/app/pipeline/rules.py` (thread and attachment text count as seen) · ADR 0009 →
accepted · tests `backend/tests/integration/test_read_before_draft.py`, `backend/tests/unit/channels/test_gemini_search.py`,
`backend/tests/unit/pipeline/test_draft_research.py`

**Produces:** `QuoteComparison(lines, market_low, market_median, quoted_total, over_by_pct, sources)`;
`comparison_for(session, company_id, message_id) -> QuoteComparison | None`;
`research_for(engine, settings, company_id, message_id) -> tuple[Finding, ...]` (runs only when
`Understanding.needs_research`; at most 3 questions, 5 searches, each finding with a URL). Legal questions search the
reference library first, then only `wetten.overheid.nl`, `rechtspraak.nl` and `roz.nl`. Quote review also checks
scope, quantities, unit costs, risks and omissions against the request, and `QuoteComparison` gains
`omissions: tuple[str, ...]`, `risks: tuple[str, ...]`.

- [ ] Failing tests: `test_attachment_text_is_stored_before_the_proposer_runs`;
      `test_a_vendor_quote_has_a_comparison_before_the_proposer_runs`; `test_no_market_data_gives_no_comparison`;
      `test_research_runs_only_when_needed_and_every_finding_has_a_url`; `test_research_page_text_is_data`;
      `test_legal_research_uses_the_reference_library_and_official_sources_only`;
      `test_quote_review_lists_missing_scope_items`;
      `test_gemini_search_returns_fetched_pages_with_their_urls` (recorded grounding response and pages);
      `test_gemini_search_drops_a_source_it_cannot_fetch`;
      `test_rules_hold_an_iban_only_found_in_an_attachment`.
- [ ] Run → FAIL; implement; run → PASS; `make live-check k=prices` once the key is set.
- [ ] `draft_open` (T2) runs the same comparison and `research_for` before each proposal (history mail skips research
      until then; reading and comparison run in history mode too).
- [ ] Commit `feat(pipeline): read, compare and research before drafting`.

### T9 (Dev A): Proposer v6 and its eval gate

**Files:** create `backend/app/llm/prompts/v6/proposer.md` · `backend/app/llm/agents/proposer.py`
(`ProposerContext.dossier: tuple[str, ...]`; `PROPOSER_V6`, reasoning `high`; owner redrafts use v6) ·
`backend/app/pipeline/propose.py:_load` (build and render the dossier) · create
`backend/app/pipeline/draft_quality.py` · `backend/app/contracts/action.py` (`ReplyDraftPayload.commitments:
list[str]`, default empty) · remove canned drafts: `backend/app/api/inbox/routes.py:_build_drafts` fallback,
`backend/app/pipeline/propose.py:_ensure_emergency_reply` (an emergency gets a v6 draft or none),
`backend/app/api/contacts/routes.py:510` · eval cases under `backend/evals/proposer/`: `thread_followup`,
`lease_clause_in_pdf`, `roz_lease_question`, `quote_above_market`, `quote_scope_omissions`, `quote_no_market_data`,
`works_planning_and_access`, `missing_information`, `sender_history_promise`, `injected_attachment`, `legal_letter`,
`new_project_offer`, `emergency_leak` · tests `backend/tests/unit/llm/test_proposer_v6_prompt.py`,
`backend/tests/unit/pipeline/test_draft_quality.py`, `backend/tests/integration/test_propose_dossier.py`

**The v6 prompt carries Harjot's drafting standard verbatim** (spec, "Drafting standard") as its rules, plus: use only
facts from the dossier, references and research, never invent a price, date, amount, rule, name or promise; on a quote
always negotiate price or terms, using `quote` (market range with sources, omissions, risks); on works, settle scope,
planning, duration, access, disruption and tenant coordination; missing information becomes specific questions; list
every financial, legal or other commitment in `commitments`; keep Harjot's persona; Dutch to tenants, the sender's
language otherwise.

**Produces:** `is_generic(text: str) -> bool` (true when the draft is only an acknowledgement, a promise to come back,
or a canned phrase from `GENERIC_PHRASES` in Dutch and English, e.g. "Thank you for your message", "we komen er zo snel
mogelijk op terug", "in goede orde ontvangen", with no answer, question, figure or decision); `propose` redrafts once
with that feedback when every variant is generic, and offers no draft if it still is (Harjot sees "No usable draft:
draft with Astra").

- [ ] Failing tests: `test_v6_prompt_holds_every_dossier_block_as_data`;
      `test_v6_prompt_carries_the_drafting_standard_verbatim`; `test_owner_redraft_uses_v6_with_the_dossier`;
      `test_propose_records_v6_and_its_sources_in_the_rationale`; `test_is_generic_on_dutch_and_english_acknowledgements`;
      `test_is_generic_false_for_a_substantive_reply_that_starts_with_thanks`;
      `test_a_generic_draft_is_redrafted_then_dropped`; `test_commitments_are_stored_on_the_payload`;
      `test_no_canned_draft_anywhere` (inbox with no proposal offers no draft text; emergency without a model draft
      offers none; grep of `GENERIC_PHRASES` over `app/` finds none outside `draft_quality.py`).
- [ ] Run → FAIL; implement; run → PASS.
- [ ] `make eval agent=proposer version=v6` on the quality tier, scored by a rubric judge on the standard (reviewed
      everything, commercially sharp, complete, concise, one step ahead, questions instead of assumptions, no invention,
      commitments listed) plus hard checks: counter-offer with a source on `quote_above_market`, every missing item asked
      on `quote_scope_omissions`, planning/access/disruption covered on `works_planning_and_access`, ROZ article cited
      from the library on `roz_lease_question`, nothing obeyed from `injected_attachment`, `is_generic` false on all.
      Every case passes → pin v6, repin tests.
- [ ] Commit `feat(proposer): v6 drafts to Harjot's standard from the dossier`.

### T10 (Dev B): Category next actions API

**Files:** create `backend/app/pipeline/next_actions.py`, `backend/app/api/v1/categories.py` (router registered,
section `dashboard`) · OpenAPI snapshot · test `backend/tests/integration/test_next_actions.py`

**Produces:**
```python
class NextAction(Contract):
    id: str; category: Category
    kind: Literal["approve_draft", "reply_needed", "quote_over_market", "overdue_wait",
                  "document_review", "brixx_ticket", "rent_arrears", "deadline"]
    title: str; why: str; urgency: Urgency; due_at: AwareDatetime | None
    case_id: UUID | None; approval_id: UUID | None; prepared: str | None; target_url: str
def next_actions(session, company_id: UUID, category: Category, limit: int = 15) -> list[NextAction]
GET /api/v1/dashboard/categories -> [{category, label, open_actions, urgent}]
GET /api/v1/dashboard/categories/{category} -> {brief: str | None, actions: list[NextAction]}
```
Ranking: urgency (emergency, high, normal, low), then due date, then waiting age; `approve_draft` and
`quote_over_market` first on a tie. `prepared` is the first line of the ready draft or the counter-offer.

- [ ] Failing tests: `test_each_category_lists_only_its_own_actions`; `test_actions_rank_by_urgency_then_due_date`;
      `test_another_companys_actions_never_appear`; `test_headline_only_profiles_get_no_message_text`;
      `test_unknown_category_is_422`.
- [ ] Run → FAIL; implement (brief is `None` until T11); run → PASS. Commit `feat(dashboard): category next actions`.

### T11 (Dev A): Astra can open anything; category brief

**Files:** `backend/app/superagent/research.py` (tools `open_message`, `open_thread`, `open_document(document_id,
page=1)`, `search_web`; `MAX_TOOL_CALLS = 8`, `MAX_HITS = 10`, `SNIPPET_CHARS = 600`; hits carry ids) · concierge
`read_document` and `draft_reply` use `open_document` and v6 · create `backend/app/llm/agents/category_brief.py`,
prompt `v1/category_brief.md` (3 sentences from the listed actions only; cached 10 minutes) · tests
`backend/tests/unit/superagent/test_research_tools.py`, `backend/tests/integration/test_research_open.py`,
`backend/tests/unit/llm/test_category_brief.py`

- [ ] Failing tests: `test_open_message_returns_the_whole_mail_and_attachments`;
      `test_open_thread_returns_both_directions`; `test_open_document_pages_long_text`;
      `test_open_tools_refuse_another_companys_ids`; `test_search_web_returns_pages_as_data_with_urls`;
      `test_read_the_attachment_then_draft`; `test_brief_only_sees_listed_actions`.
- [ ] Run → FAIL; implement (ids from the model checked against `company_id`); run → PASS; `estateos-security` pass.
- [ ] Commit `feat(superagent): Astra opens and searches everything; category briefs`.

### T12 (Dev B): Category dashboard UI

**Files:** `frontend/src/app/page.tsx` (top of Today) · create `frontend/src/components/today/CategoryDesk.tsx`,
`frontend/src/components/today/CategoryTabs.tsx`, `frontend/src/lib/categories.ts` (API calls and labels) · test
`frontend/src/lib/categories.test.ts`

```
[ Maintenance 4 ●] [ Finance 2 ] [ Legal 1 ●] [ Business ] [ Administration 3 ] [ New projects ]
Finance desk — "Two vendor quotes are above market; one invoice is due Friday."
 1  Counter Bouwbedrijf X's quote — €4.800 vs market €3.900–4.200 (3 sources)   [Review draft] [Ask Astra]
 2  Approve reply to J. de Vries about the deposit — draft ready                  [Review draft] [Done]
 3  Rent arrears Singel 1 — 2 months; reminder draft ready                        [Review draft] [Snooze]
```
On login the category with the most urgent actions is selected. Buttons open the inbox thread or Astra with the item in
context; nothing approves from this screen.

Also in this task: remove every canned draft template from the screens (`frontend/src/lib/replyTicket.ts` generic
text, `frontend/src/components/maintenance/EditTicketModal.tsx:55`, `frontend/src/app/page.tsx:427`,
`frontend/src/components/money/TransactionDetailSheet.tsx:217`). With no real draft the reply box is empty with a
"Draft with Astra" button. Show the draft's `commitments` above Approve in the inbox composer ("This reply commits
you to: …"). Documents page: an "Add to reference library" toggle (`is_reference`, T6).

- [ ] Failing tests (vitest): `selects the category with the most urgent actions on first load`;
      `renders actions in server order with prepared text`; `hides empty categories' counts but keeps the tab`;
      `replyTicket offers no generic draft`; `the composer lists a draft's commitments above Approve`.
- [ ] Run `cd frontend && npx vitest run src/lib/categories.test.ts` → FAIL; implement; run → PASS; `npx tsc --noEmit`.
- [ ] Commit `feat(dashboard): category desks on Today`.

### T13 (both): Docs, rehearsal, prod run

**Files:** `docs/adr/0017-dossier-and-history-reload.md`, `docs/standards/security.md`, `docs/PROGRESS.md`,
`docs/go-live-channels.md` (run book)

- [ ] ADR 0017 (categories, dossier scope, history mode, per-agent models, research); security.md (web pages untrusted,
      reload report PII in CloudWatch, Drive dedupe, Gemini-only providers); PROGRESS ticked with `/check` evidence.
- [ ] Stage (Deploy 1): `scripts/mail_reload.sh stage preview|purge|reingest 7|draft-open`; check counts and cost in
      `model_calls`.
- [ ] Prod (Deploy 1, on the user's go): `preview`, `purge`, `reingest 90`. Prod (Deploy 2): `draft-open`.
- [ ] Hand-check 20 drafts across all six categories against their threads and attachments; fix, redraft.
- [ ] Commit `docs(m12): dossier, reload run book and evidence`.
