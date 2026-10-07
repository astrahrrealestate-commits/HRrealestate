# EstateOS Phase 1 agents: design

Date: 2026-10-07 · Status: **draft, awaiting user review** · Scope: every Phase 1 agent in the client's AI Agent
Catalogue (#1–#9), built as milestones M4 → M5 → M6 → M7 → M9 → M8. M3 (BRIXX import) is deferred by the user.
Parent docs: [build-plan.md](../../build-plan.md), [hld.md](../../hld.md), M1/M2 specs in this folder.

## Goal

Inbound tenant/contractor messages (already ingested by M2) become linked cases, tasks and waiting-for items, with
proposed actions and 2–3 drafts that Harjot approves on WhatsApp. Briefings arrive at 07:30 and on Friday. Chasers
are drafted when someone has not answered. Attachments are filed in Google Drive. Quality, cost and autonomy are
measured daily. **Phase 1 still sends nothing to tenants**: only Gmail drafts and WhatsApp messages to Harjot.

## Decisions

| Topic | Decision |
|---|---|
| Directory without BRIXX | **Identity-first.** An unknown phone/email creates a `people` row (`kind=other`, display name from the message) and a `channel_identities` row on first contact. Units and leases stay optional (`cases.unit_id`/`lease_id` are already nullable). The M3 importer later fills units/leases and upgrades `kind`; nothing here assumes BRIXX. |
| LLM runtime | Pydantic AI `Agent(output_type=<Contract>)` per agent (ADR 0002). Model string from settings `llm_model`. **Default `fake`**: per-agent deterministic `FunctionModel`s in `app/llm/fakes.py`, which produce valid, plausible contract output so `make sim-demo` runs the whole pipeline offline. Prod boot refuses `fake` (same pattern as `gmail_provider=fake`). Real model plugged in by the user once channels are live. |
| LLM tracing | Pydantic AI OTel instrumentation → Langfuse OTLP endpoint when the Langfuse keys are set; off otherwise. Every call also writes a `model_calls` row (thin wrapper, ADR 0002). Cost from `genai-prices`; null for `fake`. |
| Prompts | `app/llm/prompts/v1/<agent>.md`, loaded and sha256-hashed, immutable once committed. Tenant-facing drafts in **Dutch**, everything to Harjot in **English**. Untrusted text only inside `<message>…</message>` / `<data>…</data>` blocks. |
| Agents and tools | **No agent has tools.** Code gathers the context and passes it as data; the model returns a contract. Model output never chooses a recipient, a case outside the given candidates, or a contractor outside the company's list (all checked in code). |
| Orchestrator (#1) | A DBOS workflow (`pipeline.entry`, replacing the M2 stub), not an LLM. Each stage is a step. |
| Long waits | DB rows + `timers`, never sleeping workflows (invariant 2). The minute `timer_sweep` (M1, no-op today) becomes a dispatcher: claim due rows `FOR UPDATE SKIP LOCKED`, enqueue `timer.fire` with id `timer:{timer_id}:{attempts}`. |
| Company timezone | Default `Europe/Amsterdam` (Dutch market). Migration changes the server default and updates existing rows still on `Europe/Berlin`. |
| Drive (#9) | Google Drive API v3 via google-api-python-client (already a dependency), scope `drive.file` (only files the app created). New ADR 0005. Adapter in `app/storage/drive.py` with a fake. |
| PDF text | `pypdf` (text of the first pages is enough to classify). Docling (tech-stack) is deferred: it pulls PyTorch and models into the image for no Phase 1 gain. Recorded as an amendment in tech-stack.md. Photos/scans: model vision (fake returns `other`, low confidence → review queue). |
| New dependencies | `pydantic-ai-slim[openai]`, `pydantic-evals`, `genai-prices`, `opentelemetry-exporter-otlp-proto-http`, `rapidfuzz`, `pypdf`. Each needs the user's go (dependency hook). |

## Agent map

| # | Catalogue agent | Kind | Built in | Code |
|---|---|---|---|---|
| 1 | Orchestrator | DBOS workflow | M4 shell, grows to M7 | `app/workflows/pipeline.py` |
| 2 | Inbox / Message Triage | LLM `understanding` | M4 | `app/llm/agents/understanding.py` |
| 3 | Context Linking | code + LLM `link_check` + LLM `case_summary` | M4 agents, M5 engine | `app/pipeline/linking.py`, `app/directory/identity.py` |
| 4 | Reply Drafting | LLM `proposer` | M6 | `app/pipeline/proposals.py` |
| 5 | Follow-up / Chasing | code ladder + `proposer` (chase mode) | M5 waits, M6 chaser drafts, M7 escalation | `app/pipeline/waits.py`, `app/pipeline/chasing.py` |
| 6 | Task Manager | code | M5 table + rules, M7 owner commands | `app/pipeline/tasks.py` |
| 7 | Executive Briefing | code collector + LLM `briefing` | M7 | `app/owner/briefing.py` |
| 8 | Quality and Audit Monitor | code | M4 evals, M8 outcomes + drift | `app/outcomes/`, `evals/` |
| 9 | Document Filing | LLM `doc_classifier` + code | M9 | `app/pipeline/documents.py`, `app/storage/drive.py` |
| — | Owner Q&A (preview of #10) | LLM `owner_qa` | M7 | `app/owner/qa.py` |

## New contracts (`app/contracts/`)

Existing contracts are not changed. New LLM-facing ones follow the strict-schema rules in `common.py`.

| Contract | Fields | Code-side checks |
|---|---|---|
| `LinkDecision` | `case_id: UUID \| None`, `reason`, `confidence` | `case_id` must be one of the candidates passed in; else treated as `None` (new case) |
| `CaseSummary` | `summary` (≤1200 chars), `next_step` (≤200) | — |
| `Briefing` | `headline`, `sections: list[BriefingSection{title, items: list[str]}]` | rendered within WhatsApp length limits; fallback template if the agent fails |
| `DocumentClassification` | `doc_type: DocType`, `title` (≤80), `document_date: date \| None`, `confidence` | `DocType`: lease, invoice, quote, id_document, insurance, certificate, correspondence, photo, other |
| `OwnerAnswer` | `answer` (≤1500), `case_refs: list[UUID]` | `case_refs` filtered to cases passed in |
| `Proposal` (proposer output) | `actions: list[Action]` (1–4) | code overwrites `case_id` and `draft_version=1`; rules engine validates the rest |

## New tables (one migration per milestone that needs them)

| Table | Milestone | Columns (beyond id, company_id, created_at) | Constraints |
|---|---|---|---|
| `tasks` | M5 | `case_id`, `action_id?`, `title`, `assignee` (`owner` \| `person:<id>` \| `system`), `due_at?`, `priority` (p1–p3), `status` (open, done, snoozed, cancelled), `done_at?`, `source` | unique `(action_id, source)` where action_id not null |
| `waits` | M5 | `case_id`, `party_person_id?`, `about`, `expected_by`, `status` (waiting, received, chased, escalated, cancelled), `chase_count`, `last_chased_at?`, `source_action_id?` | one open wait per `(case_id, party_person_id)` (partial unique) |
| `documents` | M9 | `attachment_id`, `doc_type`, `title`, `file_name`, `confidence`, `status` (pending, filed, review, skipped, failed), `drive_file_id?`, `drive_folder?`, `model_call_id?` | unique `attachment_id` |
| `metric_snapshots` | M8 | `day` (date, company tz), `metric`, `value`, `baseline?`, `breached` | unique `(company_id, day, metric)` |

`companies` gains `chase_after_days` (default 3), `escalate_after_chases` (default 2), `briefing_time` (07:30),
`weekly_time` (Fri 16:00), drift thresholds as JSON. All settable by seed/SQL in Phase 1; no admin UI.

## M4 Understanding, LLM layer, evals (#2, #3 agents, #8 evals)

- `app/llm/`: `prompts.py` (load + hash `PromptRef`), `runtime.py` (build model from `llm_model`; `fake` →
  `fakes.py`), `calls.py` (`run_agent(agent, prompt_ref, data, company_id, purpose) -> Contract`: renders data
  blocks, runs `agent.run_sync`, writes `model_calls` with tokens/cost/latency/trace id, overwrites trusted fields),
  `agents/understanding.py`, `agents/link_check.py`, `agents/case_summary.py`.
- `app/workflows/pipeline.py`: `pipeline.entry(message_id)` = `understand` step (writes `understandings`, unique per
  message: a replayed step reuses the row). M5/M6/M7 append stages.
- Failure: migration adds `messages.pipeline_status` (pending, done, failed) + `pipeline_error`. LLM error after
  retries → `failed`; from M5 the case is still created with `category=other`, and Harjot is told (M7). Never
  silently dropped; the hourly requeue sweep also reruns `failed` pipeline runs (max 3).
- Evals: `evals/golden/understanding.yaml` (start: 30 hand-written Dutch/English cases from the simulator fixtures;
  the labeller's 100 emails replace them at M0), `evals/run.py` via pydantic-evals, `make eval agent=understanding
  version=v1` → `evals/reports/`. Category accuracy, urgency accuracy, suspicious recall.
- **Done when:** a simulated message produces an `understandings` row and a `model_calls` row (prompt version + sha);
  `make eval agent=understanding version=v1` prints a report against the fake model; prompt render snapshots pass.

## M5 Case engine, tasks, waits (#3 engine, #5 waits, #6 tasks)

- `app/directory/identity.py`: `resolve(company_id, channel, identity, display_name) -> person_id` (create on miss,
  upsert-safe via the existing partial unique index).
- `app/pipeline/linking.py`, in order: (1) same thread (Gmail thread id / WhatsApp conversation within 72 h) → that
  case; (2) the person has exactly one open case of a compatible category → that case; (3) several candidates →
  `link_check` agent picks one or none; (4) otherwise a new case. Writes `case_links` (method + confidence) and a
  `case_events` link row. Then `case_summary` agent refreshes the rolling summary (`summary_version + 1`).
- Inbound from a party with an open wait on that case → wait `received`, case `waiting_on_third_party → open`.
- `app/pipeline/tasks.py`: tasks are created by code, never by the model: one owner task per pending approval (due by
  urgency: emergency 1 h, high 4 h, normal 24 h, low 72 h), one per approved `create_reminder`, one per escalation.
  Closing the approval/escalation closes the task.
- Timers: dispatcher in `timer_sweep`; `timer.fire` routes by `kind` (`wait.due`, `task.due`, `briefing.daily`,
  `briefing.weekly`). Handlers registered by later milestones; unknown kind → timer `failed` + log.
- **Done when:** recorded payloads from the same tenant link to one case; a different topic opens a second case;
  linking accuracy is measured on a labelled set (`make eval agent=linking`); a due wait timer fires exactly once
  under two concurrent sweeps.

## M6 Proposals, rules, chaser drafts (#4, #5 drafts)

- `app/pipeline/proposals.py`: `proposer` agent gets message, understanding, case summary, state, open waits and
  the company's contractors (id + trade). Output `Proposal`. Reply drafts: 2–3 variants (Dutch for tenants).
- `app/pipeline/rules.py` (pure, exhaustive tests): every external action → `pending_approval`; `suspicious.flag`
  → `exception`; company paused → `paused`; `request_contractor` with an unknown contractor → `exception`; more than
  one `update_case_state` → keep the first. Returns decisions; the workflow writes them.
- Chasing ladder (`app/pipeline/chasing.py`, code): `wait.due` → if still waiting and `chase_count <
  escalate_after_chases` → proposer in chase mode drafts one `reply_draft` (polite reminder, Dutch) → approval;
  `chase_count + 1`, next `wait.due` after `chase_after_days`. At the limit → `escalate` action to Harjot.
- Waits are created when an approved `reply_draft`/`request_contractor` is executed (M7), `expected_by = now +
  chase_after_days` (business days, company tz).
- **Done when:** a simulated maintenance message ends with `pending_approval` actions holding 2–3 drafts; a
  suspicious message ends as `exception`; a paused company produces no approvals; an overdue wait produces a chaser
  draft, then an escalation.

## M7 Owner channel, sender, briefings, owner Q&A (#5 escalation, #6 commands, #7, Q&A)

- `app/owner/messages.py`: pure builders. Approval = text with numbered drafts + list menu (`d1..d3`, `edit`, `rej`)
  or reply buttons (`ok`, `edit`, `rej`) for single-draft actions; ids via `ButtonId`. Titles ≤ 20 chars.
- `app/owner/commands.py`: button taps (lock approval row, record decision, enqueue `exec:{action_id}:{version}`);
  `edit` → next owner text becomes revision `draft_version + 1` + new approval; text commands `pause`, `resume`,
  `tasks`, `done <n>`, `snooze <n> <dur>`, `waiting`, `help`; anything else → `owner_qa` (open case summaries passed
  as data; answer only).
- `app/sender/execute.py` (`execute_action` workflow): re-checks approval status, `draft_version`, company pause,
  Phase 1 allowlist (Harjot's number or a Gmail draft), `sends.idempotency_key`. Gmail reply → `drafts.create` in the
  thread. WhatsApp reply to a tenant → sent **to Harjot** as copyable text. Creates the wait (M6 rule).
- WhatsApp 24-hour window: if Harjot has not written in 24 h, owner messages queue and a template
  (`estateos_pending`, "N items need you") opens the session; queued messages flush on his next inbound.
- Briefings (`app/owner/briefing.py`): code collects urgent open cases, pending approvals, overdue tasks and waits,
  exceptions; weekly adds counts (opened, resolved, decisions, drafts unchanged/edited) and outstanding items.
  `briefing` agent writes the text; on failure the deterministic template is sent. 07:30 daily and Friday 16:00
  (company tz) via self-rescheduling timers. Emergency urgency → immediate alert, not batched.
- **Done when:** sim tap `apr:<id>:d2` creates exactly one Gmail draft (fake) in the right thread, twice-delivered
  tap = one draft; `pause` blocks execution; briefing and weekly render (syrupy) and fire once per day under DST
  change; a tenant-recipient send raises.

## M9 Document filing (#9)

- After linking, each attachment of the message → `file_document` workflow (`doc:{attachment_id}`): extract text
  (pypdf, first 3 pages) or image → `doc_classifier` agent → name
  `YYYY-MM-DD_<doc_type>_<person or case ref>_<title>.<ext>` → if confidence ≥ 0.80 upload to
  `EstateOS/<doc_type>/<YYYY>/`, else `documents.status=review` + owner list message (suggested type, other types,
  `skip`). Owner choice → file with that type.
- Drive idempotency: file `appProperties.estateos_attachment_id`; before upload, search by it; `documents` unique on
  attachment id. Folders created on demand, ids cached in `documents.drive_folder`.
- Unit-based folders arrive with M3 (BRIXX); the naming rule is versioned so the later re-file is explicit.
- **Done when:** a simulated PDF invoice is filed (fake Drive) with the expected name; a low-confidence photo goes to
  review and is filed after the owner's choice; replay files once.

## M8 Outcomes, drift, hardening (#8)

- Outcome capture (cron 15 min): Gmail Sent-folder diff and WhatsApp echo → match to executed drafts (rapidfuzz) →
  `outcomes` label unchanged (≥ 0.95) / edited (≥ 0.6) / rewritten.
- Drift (`app/outcomes/drift.py`, daily cron `drift:{company}:{day}`): metrics per company-day into
  `metric_snapshots`: approval-unchanged rate, edit rate, rejection rate (autonomy); LLM cost (cost); p95 model
  latency, model error rate, pipeline duration p95, failed raw events (performance); eval score when an eval report
  exists for the live prompt. Baseline = trailing 14-day median; breach when beyond the company threshold → owner
  alert + Sentry message, once per metric per day.
- Hardening (from build plan): Sentry alerts, a test proving no code path sends to a tenant, backup notes, DBOS
  retention, then one day of shadow running on live mail (needs the user's credentials).
- **Done when:** seeded week of outcomes produces the expected snapshots and one breach alert; the no-tenant-send
  test is green; the shadow day is run by the user.

## Error handling (all milestones)

- Every stage is a DBOS step with retries for transient errors (same `_RETRY` policy as ingestion). A step that
  outlives retries marks its row (`messages.pipeline_status=failed`, `documents.failed`, timer `failed`) and the owner hears
  about it in the next briefing; nothing is dropped silently.
- LLM output that fails contract validation gets Pydantic AI's built-in retry (2), then counts as a failure.
- Owner-facing fallbacks exist for every LLM step that feeds Harjot (template briefing, "could not draft, please
  look" approval).

## Testing

Per the dev-pipeline matrix: contracts (unit + property), rules (exhaustive), agents (FunctionModel + prompt render
snapshots + `model_calls` row), repositories and workflows (testcontainers + DBOS), owner builders (syrupy), sender
guards (95 % branch), end-to-end sim scenarios extended per milestone in `make sim-demo`.

## Out of scope

BRIXX import (M3), Phase 2 agents (#10–#16), any send to a tenant, admin UI, real-model eval gates in CI (run once a
real model is configured).

## Open points for the user

1. Approve the new dependencies listed above.
2. Docling deferred in favour of pypdf: OK?
3. Drive scope `drive.file` means Harjot sees only EstateOS-created files/folders through the app; filing into his
   existing folders would need full `drive` scope. OK to start with `drive.file`?
