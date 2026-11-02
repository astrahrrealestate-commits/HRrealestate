# EstateOS Agent System: Technical Audit & Problem Verification Report

**Document Title:** EstateOS Codebase & Super Agent Audit  
**Target Codebase:** `realestateos`  
**Date of Audit:** October 29, 2026  
**Scope:** `app/llm/agents/`, `app/pipeline/`, `app/context/`, `app/channels/`, `app/api/agent/`, `app/db/models/`, `app/contracts/`, and `tests/`  

---

## Executive Summary

This document presents a comprehensive, factual technical verification of the 22 reported issues across the **EstateOS Super Agent** architecture. Every finding is verified directly against the live code on disk, citing exact file paths, line numbers, and verbatim code snippets.

### Verification Status Overview
* **Total Items Analyzed:** 22
* **Confirmed Real Issues:** 14
* **Under Discussion:** 2 (Issues 1.7, 1.8)
* **Resolved & Verified (Fixed):** 6 (Issues 1.3, 1.4, 1.5, 1.6, 1.9, 1.10)
* **False Alarms:** 0

---

## Table of Contents
1. [Section 1: High Risk (Security, Multi-Tenancy & False Fallbacks)](#1-high-risk-security-multi-tenancy--false-fallbacks)
2. [Section 2: Lags (Speed & Reliability)](#2-lags-speed--reliability)
3. [Section 3: Capability Gaps](#3-capability-gaps)
4. [Section 4: Quality & Repository Hygiene](#4-quality--repository-hygiene)
5. [Summary Checklist of All 22 Issues](#5-summary-checklist-of-all-22-issues)

---

## 1. High Risk (Security, Multi-Tenancy & False Fallbacks)

### 1.1 No Auth, CSRF, or Rate Limiting on `/api/agent/ask`
* **Status:** 🔴 **REAL ISSUE**
* **Severity:** Critical
* **Code Evidence:**
  * [`app/main.py:104`](file:///d:/estateos/realestateos/app/main.py#L104):
    ```python
    api.include_router(agent.router)  # Mounted with zero dependencies or auth
    ```
  * [`app/api/agent/routes.py:417-422`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L417-L422):
    ```python
    def ask_agent(
        req: AskAgentRequest,
        engine: Annotated[Engine, Depends(get_engine)],
        settings: Annotated[Settings, Depends(get_settings_dep)],
    ) -> AskAgentResponse:
    ```
* **Why it matters:** Unlike the production v1 endpoint ([`app/api/v1/agent.py:48`](file:///d:/estateos/realestateos/app/api/v1/agent.py#L48)) which enforces `require_principal`, `require_csrf`, and `agent_limit`, the `/api/agent/ask` endpoint is completely open. Anyone with access to the server can trigger LLM calls, read sensitive portfolio data, generate draft messages, and write memories.

---

### 1.2 Unsafe Multi-Tenancy (`select(Company).limit(1)`)
* **Status:** 🔴 **REAL ISSUE**
* **Severity:** Critical
* **Code Evidence:**
  * [`app/api/agent/routes.py:424-425`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L424-L425):
    ```python
    company = session.scalars(select(Company).limit(1)).first()
    company_id = company.id if company else UUID("00000000-0000-0000-0000-000000000001")
    ```
* **Why it matters:** When no `company_id` is passed, the endpoint blindly selects the first company record found in the database. In a multi-tenant deployment, Company B's users will execute against Company A's database entities.

---

### 1.3 Draft Cards Fall Back to Newest Case & Hardcoded Phone (`+919456916996`)
* **Status:** 🟢 **FIXED** (Resolved in commit `30f5b66`)
  * **Fix Summary:** Eliminated hardcoded `+919456916996`. Implemented dynamic database recipient resolution via `_find_case_recipient()` querying `MessageRow.thread_ref` (joined via `CaseLink`) and `ChannelIdentity.identity`. If no recipient is found in DB, safely defaults to empty string `""` and the frontend UI disables dispatch with warning badge `⚠️ No recipient phone on file`. Added full test coverage in `test_super_agent_ask.py`.
* **Severity:** High
* **Code Evidence:**
  * [`app/api/agent/routes.py:221`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L221):
    ```python
    recipient=payload.get("to") or "+919456916996",
    ```
  * [`app/api/agent/routes.py:230-244`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L230-L244):
    ```python
    if allow_fallback:
        target_case = session.scalars(
            select(Case).where(Case.state.in_(case_repo.OPEN_STATES)).order_by(Case.opened_at.desc()).limit(1)
        ).first()
        if target_case:
            unit = session.get(Unit, target_case.unit_id) if target_case.unit_id else None
            unit_label = unit.address if unit else "Portfolio Unit"
            case_id = str(target_case.id)
            body_text = "Beste bewoner,\n\nDank voor uw bericht..."

            return PreviewCardData(
                type="draft_message",
                channel="whatsapp",
                recipient="+919456916996",
                unitLabel=unit_label,
                body=body_text,
                actionId=f"act-{case_id[:8]}",
                caseId=case_id,
            )
    ```
* **Why it matters:** If an action has no explicit recipient or triggers `allow_fallback`, the draft message defaults to the newest open case in the system and targets a hardcoded developer phone number.

---

### 1.4 `_domain_fallback_answer` Falsely Claims "0 Open Cases, All Clear"
* **Status:** 🟢 **FIXED** (Resolved in commit `25afd97`)
  * **Fix Summary:** Removed false blanket assurance `"All maintenance queues are currently clear."`. Replaced with truthful database-grounded status (`"**Active Cases:** 0 open cases found in database."`). When the AI model times out or fails on non-ticket queries, it now transparently warns: `⚠️ Assistant Degraded: The AI model timed out or was rate-limited. No automated actions were performed.`
* **Severity:** High
* **Code Evidence:**
  * [`app/api/agent/routes.py:175-177`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L175-L177):
    ```python
    if any(w in q_l for w in ["case", "ticket", "open", "active", "status"]):
        if live_cases_text and "no active open" not in live_cases_text.lower():
            return f"**Active Open Cases in Database:**\n\n{live_cases_text}"
        return "**Active Cases:** 0 open cases in the database right now. All maintenance queues are clear."
    ```
* **Why it matters:** If the LLM call fails and `live_cases_text` is empty, the system gives the user a false sense of security by asserting that all queues are clear, even when critical maintenance cases are open.

---

### 1.5 `fake_concierge` Runs in Production on Model Failure
* **Status:** 🟢 **FIXED** (Resolved in commit `25afd97`)
  * **Fix Summary:** Enforced environment boundary `if settings.env == "test":` before allowing `fake_concierge`. In production and live environments (`settings.env != "test"`), `plan = None` is strictly enforced upon LLM failure, completely preventing offline keyword regex mocks from executing mutations (`task_done`, `draft_reply`, `snooze`) against live databases. Surface debug tag `stage: llm_error`.
* **Severity:** High
* **Code Evidence:**
  * [`app/api/agent/routes.py:651-657`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L651-L657):
    ```python
    except Exception as exc:
        log.warning("api.superagent.llm_fallback", error=str(exc))
        # If model call failed (e.g. 429 quota or offline), use the deterministic fake_concierge router
        try:
            fake_dict = fake_concierge(prompt)
            plan = ConciergePlan.model_validate(fake_dict)
    ```
* **Why it matters:** There is no check for `settings.environment == "test"`. If the Groq API experiences an outage, network timeout, or 429 rate limit in production, the system silently executes canned mock plans against the real database.

---

### 1.6 Real Personal Data & Lockbox Code Hardcoded in Source
* **Status:** 🟢 **FIXED**
  * **Fix Summary:** Eliminated hardcoded lockbox PIN `4182` defaults from `app/llm/agents/calendar.py`, `app/api/calendar/routes.py`, and `app/api/agent/routes.py`. The agent now resolves lockbox access dynamically from `Unit.lockbox_code`, defaulting cleanly to tenant direct access when none is registered. Removed all developer personal emails (`tyagisurya.04@gmail.com`, `suryanshtyagi.work@gmail.com`) and developer phone numbers (`+919456916996`, `916364840587`) across `Settings`, maintenance dispatchers, and inbox routes, safely routing through authenticated settings or standard portfolio contractor addresses (`dispatch@chahalbouw.nl`).
* **Severity:** High (Privacy & Security Risk)
* **Code Evidence:**
  * Personal Phone: `+919456916996` ([`routes.py:120, 181, 221, 244`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L120))
  * Personal Emails: `vipint9902@gmail.com` ([`routes.py:120, 181`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L120)), `suryanshtyagi.work@gmail.com` ([`routes.py:121`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L121))
  * Contractor Email: `kevin@chahalbouw.nl` ([`routes.py:296`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L296), [`calendar/routes.py:65`](file:///d:/estateos/realestateos/app/api/calendar/routes.py#L65))
  * Physical Lockbox Code: `#4182` ([`routes.py:306, 334, 344`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L306), [`calendar/routes.py:66`](file:///d:/estateos/realestateos/app/api/calendar/routes.py#L66), [`inbox/routes.py:84`](file:///d:/estateos/realestateos/app/api/inbox/routes.py#L84))
  * Printed in Chat Text: [`routes.py:334`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L334):
    ```python
    f"  **Lockbox Access**: #{proposal.lockbox_code or '4182'}\n\n"
    ```
* **Why it matters:** Real personal contact information and property access credentials are baked into version-controlled source files and rendered directly on client-facing cards.

---

### 1.7 Memory Writes: 8 Loose Prefixes Create Permanent Company Rules
* **Status:** 🟡 **NEED DISCUSSION** (Reviewing confirmation flow vs explicit prefix trigger)
* **Severity:** High
* **Code Evidence:**
  * [`app/api/agent/routes.py:428-448`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L428-L448):
    ```python
    rule_prefixes = [
        "remember that ",
        "remember: ",
        "remember ",
        "note that ",
        "note: ",
        "keep in mind that ",
        "keep in mind ",
        "rule: ",
    ]
    for prefix in rule_prefixes:
        if q_low.startswith(prefix):
            rule_text = q_clean[len(prefix):].strip().strip('"\'“”`')
            if rule_text:
                memory_items.record_owner_memory(
                    session,
                    company_id=company_id,
                    text=rule_text,
                    scope=MemoryScope.company,
                    kind=MemoryKind.preference,
                )
                session.commit()
                return AskAgentResponse(...)
    ```
* **Why it matters:** Any casual user query starting with "remember to..." immediately writes a permanent, company-wide preference rule to the database without confirmation or human review.

---

### 1.8 Memory-Match Step Overwrites Real Answers
* **Status:** 🟡 **NEED DISCUSSION** (Evaluating hybrid approach: pure rule answers for policy queries + rule badge injection for live ticket queries)
* **Severity:** High
* **Code Evidence:**
  * [`app/api/agent/routes.py:676-687`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L676-L687):
    ```python
    matching_rule = None
    q_words = [w for w in q_low.split() if len(w) > 3 and w not in ["what", "which", "tell", "show", "about"]]
    if q_words:
        for m in approved_memories:
            matches = sum(1 for w in q_words if w in m.lower())
            if matches >= 2 or (len(q_words) == 1 and q_words[0] in m.lower()):
                matching_rule = m
                break

    if matching_rule:
        ans_text = f"**Authoritative Standing Rule (T5 Memory):**\n\n• {matching_rule}"
    ```
* **Why it matters:** Even if the LLM correctly processed the request and `run_plan()` produced an answer, matching just 2 keywords with an existing memory rule causes the actual answer to be discarded and replaced with the memory snippet.

---

### 1.9 Bypasses the Approval Flow Built in `v1/memory.py`
* **Status:** 🟢 **FIXED**
* **Severity:** Medium
* **Code Evidence & Remediation:**
  * [`app/context/memory_items.py`](file:///d:/estateos/realestateos/app/context/memory_items.py): Added `status` parameter to `record_owner_memory()`, defaulting to proposed memories when submitted via chat. Added deduplication against existing active/proposed policies.
  * [`app/api/agent/routes.py`](file:///d:/estateos/realestateos/app/api/agent/routes.py): Classified task reminders (e.g. "remember to call...") away from policy rules. Saves standing policies with `status = MemoryStatus.proposed` and returns a 1-click `approve_memory` action card targeting `/api/v1/memory/{id}/approve`.
  * [`frontend/src/components/assistant/AskEstateOSPanel.tsx`](file:///d:/estateos/realestateos/frontend/src/components/assistant/AskEstateOSPanel.tsx): Connected the `approve_memory` action button to `approveStandingRule(memoryId)` with live UI activation feedback.

---

### 1.10 Fake "Steps" Shown to Users
* **Status:** 🟢 **FIXED**
* **Severity:** Medium (Trust & Safety)
* **Code Evidence & Remediation:**
  * [`app/api/agent/routes.py`](file:///d:/estateos/realestateos/app/api/agent/routes.py): Replaced fake static strings with truthful, telemetry-derived steps. Database calendar reads now report `"Queried scheduled property visits from database"`, and conflict checks dynamically reflect actual collision detection (`proposal.conflict_reason` or `"0 schedule conflicts detected in database"`).

---

## 2. Lags (Speed & Reliability)

### 2.1 Synchronous Endpoint Blocks FastAPI Worker Threads
* **Status:** 🟡 **REAL ISSUE**
* **Severity:** High
* **Code Evidence:**
  * [`app/api/agent/routes.py:417`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L417): Defined as `def ask_agent(...)` (synchronous) instead of `async def`.
* **Why it matters:** FastAPI executes synchronous routes in an external threadpool. Long-running LLM calls hold onto threadpool workers, quickly leading to thread starvation and API latency under concurrent load.

---

### 2.2 Serial LLM Calls
* **Status:** 🟡 **REAL ISSUE**
* **Severity:** Medium
* **Code Evidence:**
  * Step 1: `run_agent(..., CONCIERGE, ...)` ([`routes.py:649`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L649))
  * Step 2: `run_plan(...)` ([`routes.py:665`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L665)) which can call `proposer`
  * Step 3: `_generate_groq_answer(...)` ([`routes.py:695`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L695)) fallback
* **Why it matters:** Multiple LLM calls are chained sequentially in a single blocking HTTP request, causing cumulative response latencies of 10–30+ seconds.

---

### 2.3 Groq Fallback Loop (Up to 30s Worst-Case, Unmetered, Silent Errors)
* **Status:** 🟡 **REAL ISSUE**
* **Severity:** High
* **Code Evidence:**
  * [`app/api/agent/routes.py:146-168`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L146-L168):
    ```python
    for model in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"]:
        try:
            resp = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 300,
                },
                timeout=10.0,
            )
            if resp.status_code == 200:
                ans = resp.json()["choices"][0]["message"]["content"].strip()
                if ans:
                    return ans
        except Exception:
            continue
    ```
* **Why it matters:** In the worst-case scenario where models time out, this loop holds the request for 30 seconds (3 models × 10s). It bypasses `run_agent()`, ignores budget tracking (`CONCIERGE_PURPOSE`), logs no telemetry, and silences all network failures.

---

### 2.4 Heavy Context Loaded per Request
* **Status:** 🟡 **REAL ISSUE**
* **Severity:** Medium
* **Code Evidence:**
  * [`app/api/agent/routes.py:470-496`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L470-L496): Runs 4 un-cached database queries on every query:
    1. Active memory items (`limit 10`)
    2. Page state (`limit 1`)
    3. Open cases (`limit 20`)
    4. Open tasks (`limit 20`)
* **Why it matters:** Repeatedly querying up to 50 relational objects adds unnecessary database overhead to every single message turn.

---

### 2.5 No Streaming on `/ask`
* **Status:** 🟡 **REAL ISSUE**
* **Severity:** Medium
* **Code Evidence:**
  * [`app/api/agent/routes.py:412`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L412): Returns a monolithic Pydantic `AskAgentResponse` only after all work completes.
* **Why it matters:** Unlike the v1 architecture ([`app/api/v1/events.py`](file:///d:/estateos/realestateos/app/api/v1/events.py)) which streams turn progress and tokens over SSE, `/api/agent/ask` leaves the user staring at a blank loading spinner until the final response is ready.

---

## 3. Capability Gaps

### 3.1 Missing Operational Intents in `contracts/concierge.py`
* **Status:** 🟠 **REAL ISSUE**
* **Severity:** Medium
* **Code Evidence:**
  * [`app/contracts/concierge.py:12-30`](file:///d:/estateos/realestateos/app/contracts/concierge.py#L12-L30):
    ```python
    class Intent(StrEnum):
        answer = "answer"
        list_tasks = "list_tasks"
        list_waiting = "list_waiting"
        case_status = "case_status"
        search_inbox = "search_inbox"
        briefing_now = "briefing_now"
        task_done = "task_done"
        task_snooze = "task_snooze"
        create_task = "create_task"
        pause = "pause"
        resume = "resume"
        draft_reply = "draft_reply"
        chase_now = "chase_now"
        file_document = "file_document"
        find_document = "find_document"
        read_document = "read_document"
        open_view = "open_view"
        clarify = "clarify"
    ```
* **Why it matters:** The agent has no native intents for core property management actions like `create_ticket`, `close_ticket`, `assign_contractor`, `schedule_visit`, or `query_financials`.

---

### 3.2 `search_inbox` is ILIKE Substring Only
* **Status:** 🟠 **REAL ISSUE**
* **Severity:** Medium
* **Code Evidence:**
  * [`app/pipeline/concierge_reads.py:122`](file:///d:/estateos/realestateos/app/pipeline/concierge_reads.py#L122):
    ```python
    .where(MessageRow.company_id == ctx.company_id, MessageRow.text.icontains(query, autoescape=True))
    ```
* **Why it matters:** The inbox search does not support semantic vector search, fuzzy matching, sender filters, or date ranges. Queries that do not match exact substring text fail to return results.

---

### 3.3 Only Top 20 Open Cases Are Loaded
* **Status:** 🟠 **REAL ISSUE**
* **Severity:** Medium
* **Code Evidence:**
  * [`app/api/agent/routes.py:488-491`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L488-L491):
    ```python
    select(Case)
    .where(Case.company_id == company_id, Case.state.in_(case_repo.OPEN_STATES))
    .order_by(Case.opened_at.desc(), Case.id.desc())
    .limit(20)
    ```
* **Why it matters:** The agent has zero visibility into closed, resolved, or historic maintenance cases, making it impossible to answer questions like "When was unit 42-A's boiler last serviced?".

---

### 3.4 Planner Cannot Write Custom Analytical Queries
* **Status:** 🟠 **REAL ISSUE**
* **Severity:** Medium
* **Why it matters:** The planner is limited to emitting fixed `PlanStep` intents. It lacks Text-to-SQL or database aggregation capabilities to answer questions requiring arithmetic over multiple rows (e.g., "What is the total overdue rent across all units?").

---

### 3.5 Calendar and Documents Are Regex Bypasses Outside the Planner
* **Status:** 🟠 **REAL ISSUE**
* **Severity:** Medium
* **Code Evidence:**
  * Calendar Regex: [`routes.py:528`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L528) (`cal_pattern = r"\b(calendar|schedule|...)\b"`)
  * Document Regex: [`routes.py:544`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L544) (`doc_pattern = r"\b(lease|agreement|contract|...)\b"`)
* **Why it matters:** If either regex matches, the endpoint executes hardcoded subroutines and exits immediately, bypassing the `CONCIERGE` agent and preventing complex multi-intent reasoning.

---

## 4. Quality & Repository Hygiene

### 4.1 Failing Unit Tests Due to Prompt Changes
* **Status:** 🔵 **REAL ISSUE**
* **Severity:** Medium
* **Code Evidence:** Running `pytest tests/unit/llm/test_concierge_agent.py` fails 3 tests:
  1. `test_prompt_v5_answers_in_reply_and_keeps_steps_for_actions`
  2. `test_prompt_v5_allows_only_server_amounts_in_reply`
  3. `test_prompt_v5_is_v4_with_only_the_amounts_rule_changed`
* **Why it matters:** Additions to [`app/llm/prompts/v5/concierge.md`](file:///d:/estateos/realestateos/app/llm/prompts/v5/concierge.md) for UI navigation (`open_view` and `tasks`) violate the test assertion that `v5` must strictly equal `v4` with only the amounts rule altered.

---

### 4.2 Untracked Root Artifacts
* **Status:** 🔵 **REAL ISSUE**
* **Severity:** Low
* **Code Evidence:** Loose test artifacts exist in the repository root:
  * `invoice_sample_INV-2026-104.pdf`
  * `leaking_pipe_sample.jpg`
  * `lease_agreement_sample.pdf`
  * `scratch/`
* **Why it matters:** Clutters git status and risks accidentally committing binary test files to version control.

---

### 4.3 Mock Data in Dashboard and Inbox Routes
* **Status:** 🔵 **REAL ISSUE**
* **Severity:** Medium
* **Code Evidence:**
  * [`app/api/dashboard/routes.py:100-150`](file:///d:/estateos/realestateos/app/api/dashboard/routes.py#L100-L150): `DEFAULT_RADAR_ITEMS` and hardcoded metric dicts (`"openRentTotalEur": 165734.99`).
  * [`app/api/inbox/routes.py:50-120`](file:///d:/estateos/realestateos/app/api/inbox/routes.py#L50-L120): `STATIC_MOCK_THREADS` with fictional messages, Dutch draft texts, and lockbox PIN 4182.
* **Why it matters:** The dashboard and inbox views do not strictly reflect database state, displaying mock data alongside live rows.

---

### 4.4 Duplicate `import re` and `q_low` Reassignments
* **Status:** 🔵 **REAL ISSUE**
* **Severity:** Low (Code Cleanliness)
* **Code Evidence:**
  * `import re` appears at line 7, line 526, and line 542 in `app/api/agent/routes.py`.
  * `q_low` is calculated at line 427 (`q_low = q_clean.lower()`), and then overwritten at line 718 (`q_low = req.query.lower()`) with different normalization rules.

---

### 4.5 No Audit Log of Agent Actions
* **Status:** 🔵 **REAL ISSUE**
* **Severity:** Medium
* **Code Evidence:**
  * Memory writes at [`routes.py:441`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L441) execute `session.commit()` with no audit table row.
  * Calendar proposals at [`routes.py:328`](file:///d:/estateos/realestateos/app/api/agent/routes.py#L328) commit with no audit record.
* **Why it matters:** There is no persistent trace of autonomous decisions, rule alterations, or fallback invocations.

---

## 5. Summary Checklist of All 22 Issues

| # | Category | Issue Description | Verified Status |
| :-: | :--- | :--- | :-: |
| 1 | High Risk | `/api/agent/ask` has no auth, CSRF, or rate limiting | 🔴 **REAL ISSUE** |
| 2 | High Risk | Unsafe multi-tenancy via `select(Company).limit(1)` | 🔴 **REAL ISSUE** |
| 3 | High Risk | Draft cards fall back to newest case & phone `+919456916996` | 🟢 **FIXED** (`30f5b66`) |
| 4 | High Risk | `_domain_fallback_answer` gives false "0 cases, all clear" message | 🟢 **FIXED** (`25afd97`) |
| 5 | High Risk | `fake_concierge` mock runs in production on error | 🟢 **FIXED** (`25afd97`) |
| 6 | High Risk | Real personal phones, emails, and lockbox PIN 4182 hardcoded | 🟢 **FIXED** |
| 7 | High Risk | 8 loose prefixes write permanent rules without confirmation | 🟡 **NEED DISCUSSION** |
| 8 | High Risk | Memory-match keyword step overwrites real answers | 🟡 **NEED DISCUSSION** |
| 9 | High Risk | Memory writes bypass approval flow built in `v1/memory.py` | 🟢 **FIXED** |
| 10 | High Risk | Fake static steps shown ("0 collisions", "Queried Google Calendar") | 🟢 **FIXED** |
| 11 | Reliability | Synchronous endpoint (`def`) blocks FastAPI worker threads | 🟡 **REAL ISSUE** |
| 12 | Reliability | Serial LLM calls (CONCIERGE -> run_plan -> Groq fallback) | 🟡 **REAL ISSUE** |
| 13 | Reliability | Groq fallback loop: up to 30s timeout, unmetered, silent errors | 🟡 **REAL ISSUE** |
| 14 | Reliability | Heavy context per request: 4 un-cached DB queries every time | 🟡 **REAL ISSUE** |
| 15 | Reliability | No streaming or progress events on `/api/agent/ask` | 🟡 **REAL ISSUE** |
| 16 | Capability | Missing intents for ticket creation, contractor assignment, visits | 🟠 **REAL ISSUE** |
| 17 | Capability | `search_inbox` is ILIKE keyword substring only (no semantic RAG) | 🟠 **REAL ISSUE** |
| 18 | Capability | Only top 20 open cases loaded; closed tickets cannot be queried | 🟠 **REAL ISSUE** |
| 19 | Capability | Planner cannot write custom analytical queries (e.g. overdue rent) | 🟠 **REAL ISSUE** |
| 20 | Capability | Calendar and documents are regex branches outside planner | 🟠 **REAL ISSUE** |
| 21 | Quality | 3 failing prompt regression tests in `test_concierge_agent.py` | 🔵 **REAL ISSUE** |
| 22 | Quality | Duplicate imports (`re`), variable reassignments, mock data | 🔵 **REAL ISSUE** |
