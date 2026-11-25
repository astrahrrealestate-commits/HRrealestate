# M12 AI Staff: Categories, Drafting Context, Astra and 90-Day Reload — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harjot logs in, picks one of six categories, and sees the next actions of that area with the work already
done: drafts he would send (from the whole history, attachments, memory and web research), countered quotes, read
documents. Astra can open and search everything. 90 days of mail are reloaded cleanly through the real pipeline.

**Architecture:** Six categories replace the old ones end to end. One `Dossier` per mail feeds proposer `v6`, Astra and
the category briefs. Attachments are read, quotes compared and web research done before drafting. The reload uses a
`history` flag on the normal pipeline, then drafts only open, unanswered conversations.

**Tech Stack:** Python 3.12, FastAPI, DBOS, SQLAlchemy 2, Pydantic AI, Postgres + pgvector, Next.js, Firecrawl search.

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
- History-mode mail never creates an action, approval, owner card, alert, wait, chaser or document review card.
- Purge needs a preview, a DB snapshot, the worker stopped and a typed confirmation.
- Quality tier (reasoning `high`): proposer, research, Astra, doc reader, person memory, category brief. Fast tier
  (reasoning `low`, `google-gla:gemini-3.8-flash`): understanding, link check, case summary, price extraction.
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

---

## Schedule (2 developers, 2–3 days)

| When | Dev A: intelligence | Dev B: reload, research, dashboard |
|---|---|---|
| Day 1 AM | T4 categories (contract, `understanding/v4`, migration) | T1 history mode |
| Day 1 PM | T5 per-agent models · T6 dossier (start) | T2 purge / reingest / draft-open · T3 script |
| Day 1 end | **Sync 1:** merge; `make check` | |
| Day 2 AM | T6 dossier (finish) · T7 person memory | T8 Firecrawl, quote comparison, research, read-before-draft |
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
`backend/app/contracts/categories.py`; `Understanding.needs_research`, `.research_questions`.

- [ ] Failing tests: `test_categories_are_the_six_and_spam`; `test_old_values_map_on_migration` (each old value →
      new); `test_understanding_v4_prompt_lists_the_six_with_definitions`; `test_inbox_filter_by_each_category`.
- [ ] Run → FAIL; implement; `uv run pytest tests/unit/contracts tests/integration/test_category_migration.py -q` → PASS.
- [ ] `make eval agent=understanding version=v4` on the fast-tier model → category accuracy ≥ 0.9 on the relabelled set.
- [ ] `make check`; frontend `npx tsc --noEmit`, `npx vitest run`. Commit `feat(categories): six business categories`.

### T5 (Dev A): Per-agent model and reasoning

**Files:** `backend/app/core/settings.py` (`agent_models: dict[str, str]`, `agent_thinking: dict[str, str]`, env
`AGENT_MODELS`, `AGENT_THINKING` as JSON) · `backend/app/llm/runtime.py` (`model_name_for`, `anthropic:` provider) ·
`backend/app/llm/calls.py` (`thinking_for`) · `.env.example`, `docs/tech-stack.md` · test
`backend/tests/unit/llm/test_agent_models.py`

**Produces:** `model_name_for(settings, agent_name) -> str` (agent override, then `concierge_model`, then `llm_model`);
`thinking_for(settings, spec) -> ThinkingLevel | None`.

- [ ] Failing tests: `test_an_agent_override_wins`; `test_unset_agents_keep_llm_model`;
      `test_thinking_override_beats_the_spec`; `test_anthropic_model_builds_when_the_key_is_set`;
      `test_prod_refuses_an_override_to_fake`.
- [ ] Run → FAIL; implement; run → PASS. Commit `feat(llm): per-agent model and reasoning`.

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
def build_dossier(session, company_id: UUID, message_id: UUID, embedder: TextEmbedder | None) -> Dossier
def render_dossier(d: Dossier, budget: DossierBudget = DossierBudget()) -> list[str]  # data blocks; 60k chars
```
`PersonMemory`, `QuoteComparison`, `Finding` are defined first by T7/T8 as dataclasses; the dossier fills `None` or
`()` until those land.

- [ ] Failing tests: `test_dossier_holds_the_whole_thread_in_order_with_harjots_replies`;
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
`research_step` before `propose_step`; filing stays after) · create `backend/app/channels/prices/firecrawl.py`
(`FirecrawlSearchClient`), registry case `firecrawl`, secret `FIRECRAWL_API_KEY` · create
`backend/app/finance/comparison.py` · create `backend/app/llm/agents/research.py`, prompt
`backend/app/llm/prompts/v1/draft_research.md`, `backend/app/pipeline/draft_research.py` (findings stored on the
message's understanding row under `research`) · `backend/app/finance/triggers.py:quote_candidate` (also sender role
contractor or business) · `backend/app/pipeline/rules.py` (thread and attachment text count as seen) · ADR 0009 →
accepted · tests `backend/tests/integration/test_read_before_draft.py`, `backend/tests/unit/channels/test_firecrawl.py`,
`backend/tests/unit/pipeline/test_draft_research.py`

**Produces:** `QuoteComparison(lines, market_low, market_median, quoted_total, over_by_pct, sources)`;
`comparison_for(session, company_id, message_id) -> QuoteComparison | None`;
`research_for(engine, settings, company_id, message_id) -> tuple[Finding, ...]` (runs only when
`Understanding.needs_research`; at most 3 questions, 5 searches, each finding with a URL).

- [ ] Failing tests: `test_attachment_text_is_stored_before_the_proposer_runs`;
      `test_a_vendor_quote_has_a_comparison_before_the_proposer_runs`; `test_no_market_data_gives_no_comparison`;
      `test_research_runs_only_when_needed_and_every_finding_has_a_url`; `test_research_page_text_is_data`;
      `test_firecrawl_hits_are_pages_with_urls` (recorded fixture);
      `test_rules_hold_an_iban_only_found_in_an_attachment`.
- [ ] Run → FAIL; implement; run → PASS; `make live-check k=prices` once the key is set.
- [ ] `draft_open` (T2) runs the same comparison and `research_for` before each proposal (history mail skips research
      until then; reading and comparison run in history mode too).
- [ ] Commit `feat(pipeline): read, compare and research before drafting`.

### T9 (Dev A): Proposer v6 and its eval gate

**Files:** create `backend/app/llm/prompts/v6/proposer.md` · `backend/app/llm/agents/proposer.py`
(`ProposerContext.dossier: tuple[str, ...]`; `PROPOSER_V6`, reasoning `high`; owner redrafts use v6) ·
`backend/app/pipeline/propose.py:_load` (build and render the dossier) · eval cases under `backend/evals/proposer/`:
`thread_followup`, `lease_clause_in_pdf`, `quote_above_market`, `quote_no_market_data`, `sender_history_promise`,
`injected_attachment`, `legal_letter`, `new_project_offer` · tests `backend/tests/unit/llm/test_proposer_v6_prompt.py`,
`backend/tests/integration/test_propose_dossier.py`

v6 must: reply as Harjot after reading everything; answer every question and request; use only facts from the dossier
and research (never invent a price, date, amount, rule, name or promise); when `quote.over_by_pct > 10`, give the
market range with sources and ask for a lower price; ask for what is missing instead of guessing; keep the persona;
Dutch to tenants, the sender's language otherwise.

- [ ] Failing tests: `test_v6_prompt_holds_every_dossier_block_as_data`; `test_owner_redraft_uses_v6_with_the_dossier`;
      `test_propose_records_v6_and_its_sources_in_the_rationale`.
- [ ] Run → FAIL; implement; run → PASS.
- [ ] `make eval agent=proposer version=v6` on the quality tier → every case passes (facts present, nothing invented,
      counter-offer with a source on `quote_above_market`, nothing obeyed from `injected_attachment`). Pin v6, repin tests.
- [ ] Commit `feat(proposer): v6 drafts from the dossier`.

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

- [ ] Failing tests (vitest): `selects the category with the most urgent actions on first load`;
      `renders actions in server order with prepared text`; `hides empty categories' counts but keeps the tab`.
- [ ] Run `cd frontend && npx vitest run src/lib/categories.test.ts` → FAIL; implement; run → PASS; `npx tsc --noEmit`.
- [ ] Commit `feat(dashboard): category desks on Today`.

### T13 (both): Docs, rehearsal, prod run

**Files:** `docs/adr/0017-dossier-and-history-reload.md`, `docs/standards/security.md`, `docs/PROGRESS.md`,
`docs/go-live-channels.md` (run book)

- [ ] ADR 0017 (categories, dossier scope, history mode, per-agent models, research); security.md (web pages untrusted,
      reload report PII in CloudWatch, Drive dedupe, Anthropic data processing); PROGRESS ticked with `/check` evidence.
- [ ] Stage (Deploy 1): `scripts/mail_reload.sh stage preview|purge|reingest 7|draft-open`; check counts and cost in
      `model_calls`.
- [ ] Prod (Deploy 1, on the user's go): `preview`, `purge`, `reingest 90`. Prod (Deploy 2): `draft-open`.
- [ ] Hand-check 20 drafts across all six categories against their threads and attachments; fix, redraft.
- [ ] Commit `docs(m12): dossier, reload run book and evidence`.
