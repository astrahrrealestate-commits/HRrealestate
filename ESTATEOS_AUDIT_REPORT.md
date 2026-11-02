# EstateOS Super Agent System Audit, Problem Verification & Git Status Report

**Document Version:** 1.0.0  
**Generated On:** October 29, 2026  
**Repository Branch:** `experiment-superagent-ui`  
**Latest Push Hash:** `053f5ea`  
**Target Codebase:** `realestateos` (Next.js 14 Frontend + FastAPI / DBOS Backend)

---

## Quick Navigation
1. [Executive Summary](#1-executive-summary)
2. [Git & Deployment Verification](#2-git--deployment-verification)
3. [System Architecture & Agent Inventory](#3-system-architecture--agent-inventory)
4. [Super Agent Execution Sequence (`/api/agent/ask`)](#4-super-agent-execution-sequence-apiagentask)
5. [In-Depth Problem Verification (All 22 Items Analyzed)](#5-in-depth-problem-verification-all-22-items-analyzed)
   * [Group A: High Risk (Security, Multi-Tenancy & False Fallbacks)](#group-a-high-risk-security-multi-tenancy--false-fallbacks)
   * [Group B: Performance & Reliability Lags](#group-b-performance--reliability-lags)
   * [Group C: Capability Gaps](#group-c-capability-gaps)
   * [Group D: Quality & Repository Hygiene](#group-d-quality--repository-hygiene)
6. [Hardcoded Secrets & Personal Contacts Index](#6-hardcoded-secrets--personal-contacts-index)
7. [Test Suite Execution Outcome](#7-test-suite-execution-outcome)
8. [Recommended Action Plan & Fix Order](#8-recommended-action-plan--fix-order)

---

## 1. Executive Summary

EstateOS has two concurrent agent API pathways:
1. **The Production Pathway (`/api/v1/agent.py`):** Fully asynchronous, principal-authenticated via session tokens, CSRF-protected, and rate-limited, emitting turn events via `/events`.
2. **The Prototype Pathway (`/api/agent/ask` in `routes.py`):** A synchronous, unauthenticated endpoint directly connected to the active frontend top bar and chat drawer (`AskEstateOSPanel.tsx`).

### Primary Audit Findings:
* **All 22 flagged concerns are confirmed real issues in the code.** There are no false positives.
* **Authentication & Multi-Tenancy:** `/api/agent/ask` has no authorization headers and falls back to `select(Company).limit(1)`.
* **Silent Fallbacks:** When LLMs timeout or hit rate limits, the system silently falls back to deterministic mocks (`fake_concierge`), hardcoded developer phone numbers, and misleading "all clear" messages.
* **Git Status:** All recent code enhancements across 52 files (including the Next.js frontend build fix, emergency UI expansion, and calendar agent) have been committed (`053f5ea`) and pushed to the remote branch `experiment-superagent-ui`.

---

## 2. Git & Deployment Verification

### 2.1 Branch & Push Information
* **Active Branch:** `experiment-superagent-ui`
* **Remote Tracking:** `origin/experiment-superagent-ui`
* **Commit Hash:** `053f5ea`
* **Commit Message:** `feat: enhance Super Agent UI, add calendar scheduling agent, and refine maintenance flows`

> **Note for GitHub Reviewers:**  
> When viewing the repository on GitHub, the default branch is `main`. Switch the branch dropdown to **`experiment-superagent-ui`** to view the committed frontend and backend code.

### 2.2 Pushed Frontend Files (Verified in `053f5ea`)
* `frontend/src/app/page.tsx` — *Emergency section expansion, scroll removal, JSX fix*
* `frontend/src/app/inbox/page.tsx` — *Conversation triage and draft approvals*
* `frontend/src/app/maintenance/page.tsx` — *Dual vendor/tenant dispatch and ticket modal*
* `frontend/src/app/money/page.tsx` — *Arrears tracking and transaction sheets*
* `frontend/src/app/properties/page.tsx` — *Unit roster and property cards*
* `frontend/src/app/settings/page.tsx` — *Owner preferences and workspace controls*
* `frontend/src/app/tenants/page.tsx` — *Tenant lease status and contact cards*
* `frontend/src/components/assistant/AskEstateOSPanel.tsx` — *Super Agent chat drawer*
* `frontend/src/components/inbox/Composer.tsx` — *Draft editing and WhatsApp/Email delivery*
* `frontend/src/components/inbox/InboxConversationView.tsx` — *Thread timeline and message bubbles*
* `frontend/src/components/maintenance/EditTicketModal.tsx` — *Ticket field editor*
* `frontend/src/components/money/TransactionDetailSheet.tsx` — *Payment breakdown*
* `frontend/src/components/settings/MemoryRulesManager.tsx` — *Standing rule viewer*
* `frontend/src/context/SuperAgentContext.tsx` — *Context state & pre-warming dispatcher*
* `frontend/src/lib/api.ts` — *API client methods*

---

## 3. System Architecture & Agent Inventory

| Agent Name | Code Location | LLM Engine | Primary Purpose | Called By Super Agent? |
| :--- | :--- | :--- | :--- | :---: |
| **CONCIERGE** | `app/llm/agents/concierge.py` | Groq Llama-3.3-70B | Orchestration & plan formulation | **Yes** (`routes.py:649`) |
| **CALENDAR** | `app/llm/agents/calendar.py` | Groq Llama-3.3-70B | Scheduling, conflict checks, proposals | **Yes** (`routes.py:535`) |
| **PROPOSER** | `app/llm/agents/proposer.py` | Groq Llama-3.3-70B | Composing WhatsApp / Email drafts | **Yes** (via `run_plan`) |
| **DOC_QA** | `app/llm/agents/doc_qa.py` | Groq Llama-3.3-70B | Answering questions from PDF leases | **Yes** (`routes.py:615`) |
| **RAG** | `app/llm/agents/rag.py` | Groq Llama-3.3-70B | Sub-query decomposition & re-ranking | **Yes** (via `search_hybrid`) |
| **UNDERSTANDING** | `app/llm/agents/understanding.py` | Groq Llama-3.3-70B | Inbound message categorization | No (Webhook pipeline) |
| **BRIEFING** | `app/llm/agents/briefing.py` | Groq Llama-3.3-70B | Morning executive summaries | No (Cron workflow) |
| **CASE_SUMMARY** | `app/llm/agents/case_summary.py` | Groq Llama-3.3-70B | Case status headlines | No (Repo trigger) |
| **DOC_CLASSIFIER**| `app/llm/agents/doc_classifier.py`| Groq Llama-3.3-70B | Inbound file categorization | No (Ingestion pipeline) |
| **DOC_READER** | `app/llm/agents/doc_reader.py` | Groq Llama-3.3-70B | OCR & structured data extraction | No (Ingestion pipeline) |
| **LINK_CHECK** | `app/llm/agents/link_check.py` | Groq Llama-3.3-70B | Case/Tenant linking validation | No (Ingestion pipeline) |
| **OWNER_QA** | `app/llm/agents/owner_qa.py` | Groq Llama-3.3-70B | Contextual portfolio Q&A | No (Unused in `/ask`) |

---

## 4. Super Agent Execution Sequence (`/api/agent/ask`)

The diagram below illustrates the exact order of execution inside `ask_agent` (`app/api/agent/routes.py:417-970`):

```
User Query Received -> req.query
       │
       ▼
[Step 1] Resolve Company (select(Company).limit(1) or nil UUID)
       │
       ▼
[Step 2] Check 8 Memory Prefixes ("remember that", "rule:", etc.)
       ├── Match ──> Write to DB & return immediately (Bypasses LLM)
       └── No Match
       │
       ▼
[Step 3] Fetch Active Memory, Page State, and Top 20 Open Cases
       │
       ▼
[Step 4] Check Regex Bypasses
       ├── Calendar Regex Match ──> Run _resolve_calendar_action & exit
       ├── Document Regex Match ──> Run search_hybrid & exit
       └── No Match
       │
       ▼
[Step 5] Compile Prompt & Call run_agent(CONCIERGE)
       ├── Model Exception ──> Trigger fake_concierge() mock engine
       └── Success
       │
       ▼
[Step 6] Execute Plan Steps via run_plan()
       │
       ▼
[Step 7] Memory Match Rule Overwrite
       └── If query words match memory ──> OVERWRITE answer text completely
       │
       ▼
[Step 8] Empty / Error Fallback Check
       └── If answer contains error phrase ──> Run raw Groq loop or domain fallback
       │
       ▼
[Step 9] Build Preview Cards & Return AskAgentResponse
```

---

## 5. In-Depth Problem Verification (All 22 Items Analyzed)

### Group A: High Risk (Security, Multi-Tenancy & False Fallbacks)

#### 1. No Auth, CSRF, or Rate Limiting on `/api/agent/ask`
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/main.py:104`](file:///d:/estateos/realestateos/app/main.py#L104) & [`app/api/agent/routes.py:417`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L417)
* **Details:** `api.include_router(agent.router)` is included without dependencies. `def ask_agent` has no `Depends(require_principal)` or security tokens. Anyone reaching port 8000 can invoke the LLM and query company data.

#### 2. Unsafe Multi-Tenancy (`select(Company).limit(1)`)
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/api/agent/routes.py:424-425`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L424-L425)
* **Details:**
  ```python
  company = session.scalars(select(Company).limit(1)).first()
  company_id = company.id if company else UUID("00000000-0000-0000-0000-000000000001")
  ```
  In a multi-tenant environment, tenant isolation is broken; queries default to whichever company returns first.

#### 3. Draft Cards Fall Back to Hardcoded Phone `+919456916996` & Newest Case
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/api/agent/routes.py:221, 230-244`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L221)
* **Details:** If an action payload lacks a `to` field, or if `allow_fallback=True` triggers, it queries the most recent open case in the database and hardcodes `recipient="+919456916996"`.

#### 4. `_domain_fallback_answer` Falsely Claims "0 Open Cases, All Clear"
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/api/agent/routes.py:175-177`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L175-L177)
* **Details:**
  ```python
  if any(w in q_l for w in ["case", "ticket", "open", "active", "status"]):
      if live_cases_text and "no active open" not in live_cases_text.lower():
          return f"**Active Open Cases in Database:**\n\n{live_cases_text}"
      return "**Active Cases:** 0 open cases in the database right now. All maintenance queues are clear."
  ```
  If the LLM fails and `live_cases_text` is empty, it returns a confident falsehood stating zero open cases exist.

#### 5. `fake_concierge` Runs in Production on Exception
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/api/agent/routes.py:651-657`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L651-L657)
* **Details:** Un-gated `try...except` block catches all LLM failures (rate limits, timeouts) and feeds the query into `fake_concierge()`, which generates hardcoded mock plans.

#### 6. Real Personal Data and Secrets Hardcoded in Source
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`routes.py:120, 244, 306`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L120), [`calendar/routes.py:66`](file:///d:/estateos/realestateos/app/api/calendar/routes.py#L66), [`inbox/routes.py:84`](file:///d:/estateos/realestateos/app/api/inbox/routes.py#L84)
* **Details:** Personal phone numbers, personal Gmail addresses, and the lockbox code `#4182` are hardcoded in application strings and rendered in UI preview cards.

#### 7. 8 Loose Prefixes Write Company Rules Without Confirmation
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/api/agent/routes.py:428-448`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L428-L448)
* **Details:** Prefixes `"remember that "`, `"remember: "`, `"note that "`, `"rule: "`, etc., immediately trigger `record_owner_memory()`, committing permanent company-wide rules without an approval step.

#### 8. Memory-Match Overwrites Real LLM Answers
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/api/agent/routes.py:676-687`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L676-L687)
* **Details:** If 2 words of a user query match an active memory string, the real answer produced by the LLM or plan execution is completely discarded and replaced with the raw memory text.

#### 9. Bypasses the Approval Flow in `v1/memory.py`
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/api/v1/memory.py:130`](file:///d:/estateos/realestateos/app/api/v1/memory.py#L130) vs [`app/api/agent/routes.py:438`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L438)
* **Details:** `v1/memory.py` requires human approval via `POST /memory/{id}/approve`. `/api/agent/ask` bypasses this, writing directly with `status=active`.

#### 10. Fake Static Steps Shown to Users
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/api/agent/routes.py:370, 403`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L370)
* **Details:** Returns hardcoded UI strings `"Checked Google Calendar for busy conflicts (0 collisions)"` and `"Queried Google Calendar API"` (when it actually queried local SQL table `CalendarEventRow`).

---

### Group B: Performance & Reliability Lags

#### 11. Synchronous Endpoint Blocks FastAPI Workers
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/api/agent/routes.py:417`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L417)
* **Details:** Declared as synchronous `def ask_agent(...)` rather than `async def`. Every request locks a threadpool worker during all LLM and database wait times.

#### 12. Serial LLM Execution
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/api/agent/routes.py:649, 665, 695`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L649)
* **Details:** Runs `CONCIERGE` -> `run_plan` -> `_generate_groq_answer` in a single serial chain with no concurrency.

#### 13. Groq Fallback Loop (Up to 30s Latency, Unmetered, Silent Errors)
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/api/agent/routes.py:146-168`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L146-L168)
* **Details:** Loops through 3 models (`gpt-oss-120b`, `gpt-oss-20b`, `llama-3.3-70b-versatile`) with 10s timeouts each. Bypasses `run_agent`, has no token budget accounting, and swallows errors with `except Exception: continue`.

#### 14. Heavy Context Loaded per Request
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/api/agent/routes.py:470-496`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L470-L496)
* **Details:** Executes 4 sequential SQL queries on every message (Memory items, Page state, Open cases, Tasks) without caching.

#### 15. No Streaming on `/ask`
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/api/agent/routes.py:412`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L412)
* **Details:** Returns a monolithic JSON payload (`AskAgentResponse`). The client waits with a spinner until all stages finish.

---

### Group C: Capability Gaps

#### 16. Missing Core Operational Intents in `contracts/concierge.py`
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/contracts/concierge.py:12-30`](file:///d:/estateos/realestateos/app/contracts/concierge.py#L12-L30)
* **Details:** `Intent` enum lacks definitions for creating tickets, closing cases, assigning contractors, scheduling visits, or querying financial ledgers.

#### 17. `search_inbox` is ILIKE Substring Only
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/pipeline/concierge_reads.py:122`](file:///d:/estateos/realestateos/app/pipeline/concierge_reads.py#L122)
* **Details:** Does not support vector embeddings, semantic relevance, or date filtering; only SQL `icontains`.

#### 18. Only Top 20 Open Cases Queried
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/api/agent/routes.py:488-491`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L488-L491)
* **Details:** Filters exclusively on `Case.state.in_(case_repo.OPEN_STATES) .limit(20)`. The agent cannot answer questions about resolved or historic tickets.

#### 19. Planner Cannot Write Custom Analytical Queries
* **Finding:** **REAL ISSUE**
* **Details:** The agent has no database aggregation tools or text-to-SQL capabilities to answer portfolio-wide analytical questions (e.g., "What is the total overdue rent across all units?").

#### 20. Calendar and Document RAG Are Regex Bypasses Outside the Planner
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/api/agent/routes.py:528, 544`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L528)
* **Details:** Heuristic regexes intercept queries before the planner runs, exiting immediately and preventing multi-step reasoning.

---

### Group D: Quality & Repository Hygiene

#### 21. Failing Unit Tests Due to Uncommitted Prompt Changes
* **Finding:** **REAL ISSUE**
* **Code Reference:** [`app/llm/prompts/v5/concierge.md`](file:///d:/estateos/realestateos/app/llm/prompts/v5/concierge.md)
* **Details:** Modifying `v5/concierge.md` breaks 3 prompt regression tests in `tests/unit/llm/test_concierge_agent.py`.

#### 22. Duplicate Imports & Reassigned Variables
* **Finding:** **REAL ISSUE**
* **Code Reference:** `import re` at lines 7, 526, 542; `q_low` reassigned at lines 427 and 718 in `app/api/agent/routes.py`.

---

## 6. Hardcoded Secrets & Personal Contacts Index

| Value Type | Literal in Code | File Location | Line Number |
| :--- | :--- | :--- | :---: |
| **Phone Number** | `+919456916996` | `app/api/agent/routes.py` | 120, 181, 221, 244 |
| **Phone Number** | `+14155238886` | `app/channels/whatsapp/client.py` | 14 |
| **Email** | `vipint9902@gmail.com` | `app/api/agent/routes.py` | 120, 181 |
| **Email** | `suryanshtyagi.work@gmail.com` | `app/api/agent/routes.py` | 121 |
| **Email** | `kevin@chahalbouw.nl` | `app/api/agent/routes.py` | 296 |
| **Email** | `kevin@chahalbouw.nl` | `app/api/calendar/routes.py` | 65 |
| **Lockbox PIN** | `4182` | `app/api/agent/routes.py` | 306, 334, 344 |
| **Lockbox PIN** | `4182` | `app/api/calendar/routes.py` | 66 |
| **Lockbox PIN** | `4182` | `app/api/inbox/routes.py` | 84 |
| **Company Nil UUID** | `00000000-0000-0000-0000-000000000001` | `app/api/agent/routes.py` | 425 |

---

## 7. Test Suite Execution Outcome

Command executed:
```bash
pytest tests/unit/api/test_super_agent_ask.py tests/unit/api/test_calendar_agent.py tests/unit/evals/test_concierge_golden.py tests/unit/llm/test_concierge_agent.py -v
```

### Result: `3 failed, 62 passed, 1 warning in 10.60s`

```text
PASSED tests/unit/api/test_super_agent_ask.py (14 tests)
PASSED tests/unit/api/test_calendar_agent.py (12 tests)
PASSED tests/unit/evals/test_concierge_golden.py (24 tests)
PASSED tests/unit/llm/test_concierge_agent.py (12 tests)
FAILED tests/unit/llm/test_concierge_agent.py::test_prompt_v5_answers_in_reply_and_keeps_steps_for_actions
FAILED tests/unit/llm/test_concierge_agent.py::test_prompt_v5_allows_only_server_amounts_in_reply
FAILED tests/unit/llm/test_concierge_agent.py::test_prompt_v5_is_v4_with_only_the_amounts_rule_changed
```

---

## 8. Recommended Action Plan & Fix Order

### Priority 1: Security & Correctness (Immediate)
1. **Remove Hardcoded Secrets & Contacts:** Replace hardcoded phone numbers, emails, and lockbox PIN `4182` with database lookups on the target unit and contractor.
2. **Eliminate False Fallback Answers:** Replace `"0 open cases in the database right now"` with an honest notice: `"⚠️ Unable to verify active tickets at this moment. Please check the Maintenance tab."`
3. **Gate `fake_concierge` Behind Environment Flags:** Ensure mocks only execute when `settings.environment == "test"`.
4. **Protect `/api/agent/ask`:** Wire `Depends(require_principal)` to resolve `company_id` from the logged-in session instead of `select(Company).limit(1)`.

### Priority 2: Pipeline Transparency & Debugging
1. **Expose Execution Diagnostics to Frontend:** Add a `debug_info` field to `AskAgentResponse`:
   * `route_taken`: `"llm_plan"` | `"regex_bypass"` | `"memory_override"` | `"fallback"`
   * `model_error`: Error message if Groq fails (e.g. 429 quota or timeout).
2. **Frontend Warning Banner:** If a fallback was used, display an amber badge in `AskEstateOSPanel.tsx` so testers and users immediately know why an answer looks generic.

### Priority 3: Architecture Consolidation
1. **Migrate Frontend to Authenticated v1 Agent (`/api/v1/agent.py`):** Connect the frontend top bar to the asynchronous workflow engine to enable true streaming, audit logging, and progress events.
2. **Expand Intent Definitions:** Add `create_ticket`, `assign_contractor`, and `schedule_visit` to `contracts/concierge.py` to allow the planner to perform operational actions natively.

