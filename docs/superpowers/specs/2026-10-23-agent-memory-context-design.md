# Agent memory, context and live page reading: high-level design

Date: 2026-10-23 · Status: **draft, awaiting review** · Branch base: `d-dashboard` (HEAD `0d289fc`)
Parents: [dashboard spec](2026-10-15-dashboard-super-agent-design.md) (and its amendments of 10-16 and 10-22),
[phase-1 agents](2026-10-07-estateos-phase1-agents-design.md), [ADR 0008](../../adr/0008-advanced-rag.md).

## 1. Problem

Harjot works only in the dashboard and talks only to the Super Agent. Two needs follow:

1. **Live page awareness, fast.** When he asks "what does this say", "draft a reply to her", or "which of these is
   late", the agent must already know what is on his screen, and the answer must show within a couple of seconds.
2. **Memory across many agents.** There are 12 LLM agents (understanding, link_check, case_summary, proposer,
   owner_qa, briefing, doc_classifier, doc_reader, doc_ocr, doc_qa, RAG planner/reranker, concierge). Each needs a
   different slice of what the system knows, within a token budget, without leaking across companies and without
   letting tenant text become instructions or permanent "memory".

## 2. What exists today (and what is missing)

| Area | Built | Gap |
|---|---|---|
| Page context | `PageContext` (view, open ids, `visible_ids`, filters, 6000-char unverified `snapshot`), resolved company-scoped into `<page_facts>` and stored on the turn | Most of the snapshot repeats data the server already served; it costs up to ~1.5k tokens and is unverified |
| Pre-warm | `PUT /agent/page` resolves facts into one `agent_page_state` row per owner; reused when `page_key` matches and age ≤ 120 s | A TTL is both too short (he reads a thread for 3 min, facts are thrown away) and unsafe-ish (a message landing at second 30 is not in the facts) |
| Memory pack | ≤30 messages, case summary, timeline, directory, waits, earlier drafts; 12000-char budget with a fixed drop order | Good. No per-person memory, no owner preferences, no conversation memory beyond 6 turns |
| Turn speed | One planner call, `concierge` queue (poll 0.25 s), SSE turn poll 0.5 s, per-turn `timings` | No streaming, no progress stages, no provider prompt-cache layout, full UUIDs in prompts, no real-model measurement yet |
| Long-term memory | Rolling `cases.summary`, `case_events`, `action_revisions`, `outcomes` (unchanged/edited/rewritten), documents + hybrid RAG | Outcomes and owner edits never feed back into drafting; nothing remembers "Harjot always…"; nothing remembers a tenant across cases |
| Usage log | `model_calls` (tokens in/out, cost, latency, prompt version) | No cached-token count, so prompt-cache gains are invisible |

The direction below keeps every invariant (Postgres first, deterministic workflows, company scoping, send isolation,
message content as data, no write tools for agents). It adds **no new infrastructure**: Postgres (tables,
`LISTEN/NOTIFY`, pgvector), DBOS queues, and the LLM provider's own prompt cache.

## 3. Principles

1. **Memory is rows with provenance, never hidden model state.** Every memory item points to its sources (message,
   turn, outcome, revision). That makes it auditable, rebuildable, and erasable (GDPR: a tenant's erasure cascades to
   everything derived from their messages).
2. **Agents never write memory.** Code writes memory from validated events. A model may *propose* a memory
   (a distilled preference); it becomes active only through code rules or the owner's click. Tenant text can never
   become an active instruction-like memory on its own (poisoning defence, invariant 6).
3. **Do the work at write time, not ask time.** Summaries, profiles, embeddings, drafts and page facts are computed
   when the data changes or when the owner navigates, so a question only has to concatenate ready blocks and make one
   model call.
4. **Freshness by version, not by clock.** Cached context is valid while the versions of its sources are unchanged.
5. **Server knows what it served.** What the page shows is reconstructed from the server's own read models (signed
   view tokens), not scraped from the DOM. The client sends only state the server cannot know (unsaved edits,
   selection, scroll window).
6. **One context compiler.** Every agent's prompt is assembled by one module from a declared `ContextSpec`: slices,
   order, budgets, escaping. No agent hand-builds its context.
7. **Stable first, volatile last.** Prompt blocks are ordered by how often they change, so the provider's prefix cache
   hits and the time to first token drops.
8. **Measure before tuning.** Every turn records where its time and tokens went.

## 4. Architecture

```
 Dashboard SPA
   │ GET read models ──► response carries view_token (signed: route, params, owner, company, source versions)
   │ PUT /agent/page {view_tokens[], client_state, focus}    (on navigation, debounced 200 ms)
   │ POST /agent/prepare                                       (chat box focused)
   │ POST /agent/messages {text, page}                         (send)
   ▼                                   ▲ SSE /events: feed · turn progress · reply chunks · page_changed
 FastAPI /api/v1 ──────────────────────┤        (LISTEN estateos_events; 0.5 s poll stays as fallback)
   │                                   │
   ▼                                   │
 ┌──────────────── Context layer (app/context/) ────────────────┐
 │ view_tokens   sign / verify / re-run the read model            │
 │ page_state    resolve facts + source_versions, version check    │
 │ compiler      ContextSpec → ordered, budgeted, escaped blocks  │
 │ memory        read API over every memory tier (company-scoped)  │
 │ aliases       short handles (c1, t2, m07) ⇄ ids, per turn       │
 └───────────────────────────────────────────────────────────────┘
   │ reads                                   ▲ NOTIFY page_dirty / turn_progress
   ▼                                         │
 Postgres: domain rows · memory tiers · agent_page_state · agent_turns · model_calls · DBOS
   ▲
 DBOS worker: pipeline (write-time memory) · concierge turns · `context` queue (warm, distill, profiles)
```

`app/context/` sits beside `app/pipeline/` in the import-linter layers (`workflows → context → {db, llm, contracts,
core}`); it reads only, never imports `app.sender` or outbound channels. Existing `page_facts`, `page_memory`,
`page_text`, `page_state` and `concierge_page` move into it (or are re-exported) in the first task.

## 5. Live page reading

### 5.1 What "the page" is: three layers

| Layer | Source | Trust | Size in the prompt |
|---|---|---|---|
| **Served data** | Signed view tokens of every read model the page has mounted (thread, case, inbox list, approvals…), re-run server-side | Authoritative (server rows, company-scoped) | Compact fact lines, aliases instead of UUIDs |
| **Client state** | What only the browser knows: unsaved draft-editor text, selected text, focused row, visible window (first/last visible index), open tab | Unverified, escaped | ≤ 1500 chars |
| **Snapshot** (legacy) | Free page text, today's `snapshot` | Unverified, escaped | Only when no view token covers the view (`other`), cap stays 3000/6000 |

**Signed view tokens.** Each read-model response (`GET /threads/{key}`, `/cases/{id}`, `/inbox`, `/approvals`, …)
gets a `view_token` field: `itsdangerous`-signed (already a dependency) `{route, params, owner_id, company_id,
versions, issued_at}`. Stateless: nothing is written per GET. On `PUT /agent/page` the server verifies each token
(signature, owner, company, age ≤ 12 h) and re-runs the same read query to build facts. Benefits:

- The agent sees exactly what the screen shows, verified, without the SPA serialising DOM text.
- `versions` in the token tell the server what the owner *saw*; if the data moved on, the facts say so:
  "since this page loaded: 1 new message from the tenant (msg 31)". The agent can answer "you have not seen this yet".
- The snapshot shrinks to client-only state, saving ~1–1.5k tokens per turn and removing most unverified text.

`PageContext` gains `view_tokens: list[str]` (≤ 8), `client_state` (contract below) and keeps every current field, so
older SPA builds keep working. A token that fails verification is dropped and reported in `dropped`, like a foreign id.

```
ClientState:  editor_text ≤ 1500   (unsaved draft text in the edit box)
              selection   ≤ 500    (text the owner selected)
              focused_id           (a visible id; validated like visible_ids)
              window      [first, last] visible row indexes
```

### 5.2 Freshness by version (replaces the 120 s TTL)

`agent_page_state` gains `source_versions jsonb`: for each source the facts read, its version:

| Source | Version |
|---|---|
| thread | `(max(messages.created_at), count)` for that thread key (index from migration 0012) |
| case | `cases.updated_at`, `summary_version` |
| approvals/actions in view | `max(updated_at)` |
| tasks/waits in view | `max(updated_at)` |
| directory rows | `updated_at` of person/lease rows used |

At `create_turn`, one indexed query reads the current versions of exactly those sources (≈1–3 ms). Equal → reuse the
facts (hard cap 15 min). Different → re-resolve only the changed sections (thread lines, case block…) and store.
A lost notification can never serve stale facts, because the turn always checks versions.

### 5.3 Push, not poll: `LISTEN/NOTIFY`

- Writers (`ingestion`, pipeline stages, decisions, turn updates) call `pg_notify('estateos_events', json)` **inside
  the same transaction**, so the notification fires only on commit. Payload is ids only (`{company, kind, thread,
  case, turn}`), never text.
- Each API process holds **one** listening psycopg connection and fans events out to its open SSE streams in memory.
- The existing 0.5 s / 1.5 s polls stay as a safety net at a slower 2 s; Postgres stays the source of truth. Turn
  answers then appear ~10–30 ms after commit instead of up to 500 ms.
- On a `page_dirty` that touches a source in an owner's `source_versions`, the server (a) pushes `event: page_changed`
  so the SPA refetches its read model, and (b) enqueues a re-warm on the `context` queue (workflow id
  `warm:{owner_id}:{page_key}:{versions_hash}`, so duplicates collapse). The facts are fresh before he asks.

### 5.4 Using the owner's idle time ("stealing time")

Every action the owner takes before he presses send is a chance to finish work. Nothing in this table calls the
planner model; the only optional model cost is marked.

| Owner action | Signal | Work done meanwhile | Budget |
|---|---|---|---|
| Opens a page | `PUT /agent/page` (debounced 200 ms, previous request aborted) | Verify tokens, resolve facts + versions, upsert `agent_page_state` | ≤ 60 ms, sync |
| Stays on the page > 1.5 s | server timer from the PUT | **Deep warm** on `context` queue: memory pack, person profile + case memory, owner preferences for this case, linked-document top passages (hybrid RAG, no LLM rerank), render all blocks in compiler order and store the rendered prefix (`agent_page_state.blocks`, `blocks_hash`) | ≤ 300 ms, async |
| Data on the open page changes | `NOTIFY page_dirty` | Delta re-warm, `page_changed` to the SPA | async |
| Focuses the chat box | `POST /agent/prepare` | Brief (open cases/tasks) + conversation history + summary rendered; aliases fixed; optional provider cache warm-up (below) | ≤ 50 ms |
| Types (pause ≥ 400 ms, ≥ 12 chars) | `POST /agent/prepare {partial}` (flag `context_typing_hints`, off by default) | Client mirror of `owner_commands` regexes flags fast-path commands instantly; server embeds the partial text (embedding only, cached by hash) and pre-fetches retrieval candidates when the page is a case/thread/documents view | ≤ 1 embedding call |
| Sends | `POST /agent/messages` | Turn takes the warmed blocks by `blocks_hash` (no resolve, no brief), one planner call, stream | see §5.5 |
| Navigates during a turn | new PUT | The running turn keeps the page it was sent on (stored on the turn); the new page warms independently | — |
| Reads the answer | — | Precompute likely follow-ups' data: when the plan named a case, warm that case's memory | async |

**Provider cache warm-up (optional, flag `context_cache_warmup`, off by default).** When the rendered stable prefix is
above the provider's minimum cacheable size (OpenAI: 1024 tokens), `prepare` sends one request with that prefix and
`max_tokens=1`, so the real call hits a warm prefix (lower time to first token, cached input billed at a discount).
It costs one uncached prefix per focus; turn it on only if §9 measurements show the gain. Rate-limited to once per
`blocks_hash` per 5 minutes.

**Instant answers without a model.** Before planning, the turn checks precomputed results: a pending proposal for the
open thread's newest inbound message answers "draft a reply" with no new guidance; the stored case summary answers
"summarise this"; exact commands already take the fast path. The planner runs only when these do not match.

### 5.5 The turn's critical path

Target on a real model: **first visible text ≤ 1.2 s p50, full answer ≤ 3 s p50** for page questions; draft and
document turns ≤ 6 s p50. Where the time goes and what removes it:

| Stage | Today | After | How |
|---|---|---|---|
| POST → turn row → enqueue | ~15 ms | ~15 ms | unchanged |
| Queue pickup | 0–250 ms | 0–100 ms | `concierge` queue `polling_interval_sec` 0.1 (≈10 cheap queries/s per worker) |
| Page facts | 0 (warm) or 20–80 ms | ~2 ms | version check + stored rendered blocks |
| Brief + history | ~10 ms | ~0 | rendered at `prepare` |
| Planner model call | 1.5–6 s | 0.6–2.5 s to first reply token | cached stable prefix, aliases (fewer input tokens), small fast model for plans with a stronger model only for `draft_reply` |
| Executor | ms (reads) to 2–6 s (drafts, RAG) | same work, overlapped | speculative retrieval started in parallel with the planner when the page is a documents/case view; discarded if the plan does not use it |
| Delivery | 0–500 ms poll | ~20 ms | `NOTIFY` → SSE |

**Streaming the reply, safely.** The `reply` is screened today (`concierge_reply`, `redact_contact`) before anyone sees
it, so tokens cannot go straight to the browser. Use Pydantic AI structured streaming (`run_stream`, partial
`ConciergePlan`) inside the same DBOS step; a **sentence gate** buffers the `reply` field and releases only complete
sentences, each passed through the same screen. Released text is written to `agent_turns.partial_reply` (one short
update every ≥ 150 ms) with `NOTIFY turn_progress`; the SSE sends `event: turn_delta`. The stored final `reply` is the
whole screened text, as today. If the plan turns out to contain an action step (reply must then be null by the
fix-round-1 rule), the stream is cleared with `turn_delta {reset: true}` before any action result shows. Because a
retried step re-runs from the stored plan, a crash mid-stream only repeats chunks the SPA de-duplicates by offset.

**Progress stages** (no content, always safe): `queued → reading page → planning → drafting → searching documents →
done`, emitted from the existing `TurnTimer` stage boundaries.

## 6. Memory model

### 6.1 Tiers

| Tier | Lifetime | Store | Written by | Read by |
|---|---|---|---|---|
| **T0 Working** | one model call | the compiled prompt; stored resolved on the turn (`page_context.resolved`, `plan`, `results`) | compiler | the one agent |
| **T1 Session** | minutes–hours | `agent_page_state` (facts, versions, rendered blocks, **focus trail**: last 5 pages' entity ids), last 6 turns | API + `context` queue | concierge |
| **T2 Conversation** | days | `agent_conversations.summary` (rolling, ≤ 1200 chars) + `summary_through` turn | code after every 6th turn (one small model call) | concierge |
| **T3 Entity** | life of the entity | `cases.summary` (exists), **`person_profiles`** (new), `case_events`, `action_revisions`, waits, tasks | pipeline stages at write time | proposer, concierge, briefing, link_check |
| **T4 Knowledge** | years | documents + chunks + vectors (ADR 0008), directory (people, units, leases), `lease` key facts | ingestion, doc_reader, BRIXX import | doc_qa, proposer, concierge |
| **T5 Preferences** | until retired | **`memory_items`** (new): owner rules, preferences, standing facts | owner (explicit) or distiller (proposed → owner approves) | proposer, concierge, briefing |
| **T6 Audit** | retention policy | `model_calls`, `outcomes`, turns | `run_agent`, outcome capture | evals, drift, distiller |

The **focus trail** answers "the case I looked at before" without a model: the last 5 page keys with their entity ids
and aliases ride in the session block.

### 6.2 New tables

```
person_profiles   id, company_id, person_id (unique), language, preferred_channel, summary (≤ 800),
                  open_cases, closed_cases, last_contact_at, response_hours_p50 (contractors), source_max_message_at,
                  profile_version, updated_at
memory_items      id, company_id, scope (company|owner|person|unit|case), scope_id, kind (rule|preference|fact|note),
                  text (≤ 300), status (proposed|active|retired), origin (owner|distilled|system),
                  source_refs jsonb (message/turn/outcome/revision ids), evidence_count, confidence,
                  embedding vector, last_used_at, valid_until, created_at, updated_at
                  unique (company_id, scope, scope_id, lower(text)) where status <> 'retired'
agent_conversations  + summary text, summary_through uuid, summary_version int
agent_page_state     + source_versions jsonb, blocks text, blocks_hash text, focus_trail jsonb
agent_turns          + partial_reply text, stage text
model_calls          + tokens_cached int, prefix_hash text
```

### 6.3 How memory is written

| Event | Memory written | Model? |
|---|---|---|
| Inbound message linked | case summary (exists); person profile `source_max_message_at` marked stale | case_summary (exists) |
| Case closed, or profile stale and ≥ 5 new messages | person profile refreshed on `context` queue, id `profile:{person_id}:{version}` | one small call |
| Owner says "remember …" / "from now on …" (new intent `remember`) | `memory_items` `origin=owner`, **active** immediately, shown in a Memory list he can edit or delete | no (the text is his own, sanitised like guidance) |
| Owner edits or rewrites a draft (`action_revisions`, `outcomes` edited/rewritten) | nightly **distiller** compares draft vs sent text for that company, proposes ≤ 3 `memory_items` (`proposed`, with source refs) | one call per night |
| Owner approves a proposed memory (feed kind `memory_review`) | `active` | no |
| Same proposal seen again | `evidence_count + 1`, never duplicated (unique index) | no |
| A memory unused 180 days, or contradicted by a newer owner memory | `retired` (owner sees it in the weekly briefing) | no |
| Tenant/person erased (GDPR) | every row whose `source_refs` include their messages is deleted or rebuilt; profiles deleted | no |

Tenant text can appear inside a profile or summary (it is a summary of their messages), so those always stay inside
escaped data blocks. Only `memory_items` with `origin=owner`, or approved by the owner, are ever rendered in the
`<owner_preferences>` block, which the proposer prompt treats as the owner's wishes, still never as permission to
send, pick recipients or skip approval.

### 6.4 How memory is retrieved

Deterministic first, semantic last:

1. **By id** (cheap, exact): the open entity, its case, person, lease, unit → their T3 rows.
2. **By scope** (exact): active `memory_items` for company + owner + the entities in focus, newest and most-evidenced
   first.
3. **By relevance** (only when 1 and 2 leave budget, and only for documents or many memories): hybrid search over
   `memory_items.embedding` and document chunks (existing RRF), with the relevance floor from ADR 0008.

Every read takes `company_id` (invariant 4). `last_used_at` is updated in batch after the turn (not in the hot path).

## 7. Context compiler (one module for every agent)

### 7.1 `ContextSpec`

Each agent declares what it reads; the compiler fetches, budgets, orders, escapes and records:

```python
@dataclass(frozen=True)
class Slice:
    name: str            # "brief", "page_facts", "case_memory", "owner_preferences", ...
    stability: int       # 0 static … 5 per-message; sets the order
    budget_chars: int
    trusted: bool        # server facts vs unverified text; picks the block label
    drop_order: int      # who gives way first when the total budget is hit

@dataclass(frozen=True)
class ContextSpec:
    agent: str
    slices: tuple[Slice, ...]
    total_chars: int
```

Output: `CompiledContext(blocks, prefix_hash, aliases, dropped)`. `prefix_hash` covers the stable part (stability
0–2) and is stored on `model_calls.prefix_hash`, so cache hits can be measured per agent.

### 7.2 Block order (stable first, for the provider's prefix cache)

```
0 instructions        prompt file vN (static, versioned)
1 company constants   glossary, contractor list, company settings, owner preferences  (changes: days)
2 brief               open cases/tasks with aliases                                    (changes: minutes)
3 conversation        rolling summary + last 6 turns                                   (changes: per turn)
4 page facts          served data (view tokens) + memory pack                          (changes: per page)
5 client state        editor text, selection, focus (unverified)                       (per message)
6 message             the owner's text                                                 (per message)
```

Today's concierge order is data, history, page, message, which already starts well; the instructions are the
system prompt. The change is adding level 1 and keeping levels 0–2 byte-identical between turns (sorted, no
timestamps in them; "now" goes in level 3+). Pass a stable cache key per company and agent where the provider API
accepts one (OpenAI `prompt_cache_key`).

### 7.3 Aliases instead of UUIDs

A UUID costs ~20–25 tokens and invites copy errors. The compiler maps each entity in the prompt to a short handle
(`c1…` cases, `t1…` tasks, `a1…` approvals, `m01…` messages, `d1…` documents), stored on the turn
(`page_context.aliases`). The plan contract accepts aliases; the executor maps them back and rejects any alias not
issued for that turn. That is also a safety gain: the model cannot name an id it was not shown. Aliases are stable
within a session (the brief's `c3` stays `c3` while the case stays open) so cached prefixes stay identical.

### 7.4 Budgets per agent

| Agent | Slices (in order) | Total | Notes |
|---|---|---|---|
| concierge | instr · company consts · brief · conversation · page facts · client state · message | ≈ 6k tokens | page facts 12000 chars (exists); snapshot only for `other` views |
| proposer | instr · company consts + owner preferences · person profile · case memory · document excerpts · message · guidance | ≈ 5k | preferences only `active` |
| owner_qa | instr · brief · page facts · message | ≈ 4k | fallback path only |
| understanding | instr · glossary · message · attachment metadata | ≈ 2k | no memory: classify the message as it is |
| link_check | instr · candidate cases (summary 300 each) · person profile line · message | ≈ 2.5k | |
| case_summary | instr · previous summary · new message · last 5 events | ≈ 2k | rolling, versioned |
| briefing | instr · company consts · collected items | ≈ 3k | code collects, model phrases |
| doc_reader / doc_ocr / doc_classifier | instr · document text or metadata | per ADR 0007 | no owner memory |
| doc_qa / RAG planner / reranker | instr · question · passages | per ADR 0008 | |
| profile / distiller / conversation summariser (new) | instr · sources | ≈ 3k | `context` queue only, never in a turn |

Only the concierge and proposer read T5 preferences. Classification agents stay memory-free so a remembered
preference can never change how a tenant's message is triaged or flagged suspicious.

### 7.5 Agents talk through Postgres, not through each other

No agent passes free text to another agent. Each writes its contract output to its table (understanding, case link,
proposal, document facts); the next agent reads the stored contract through the compiler. Postgres is the
blackboard; DBOS orders the steps. This keeps every hand-off typed, replayable and visible in the audit trail.

## 8. Safety (unchanged rules, new surfaces)

| New surface | Rule |
|---|---|
| View tokens | Signed, bound to owner + company, ≤ 12 h; the server re-runs its own scoped query; a bad token is dropped, never trusted |
| Client state | Unverified, escaped block, capped; never an id source, recipient or permission (same as the snapshot today) |
| `remember` intent | Owner text only, sanitised like draft guidance (links, emails, phones, IBANs redacted); cannot hold instructions about approvals, recipients or sending (screened, refused with a fixed message) |
| Distilled memories | `proposed` until the owner approves; sources shown in the review card |
| Profiles and summaries | Contain tenant text, so always inside escaped data blocks, never in `<owner_preferences>` |
| Streaming | Sentence gate + same screen as the final reply; action plans never stream a reply |
| `NOTIFY` payloads | Ids and kinds only; no text, no secrets |
| Erasure | `source_refs` make every derived row findable; erasure job deletes or rebuilds them |

Invariants 1–9 hold: warm, distil and profile jobs are DBOS workflows with deterministic ids on the `context` queue;
every write is a scoped repository call; agents still have no tools.

## 9. Measurement (first, before any tuning)

Per turn (extend `agent_turns.timings`): `queue_wait_ms`, `page_resolve_ms`, `warm_hit` (none | facts | blocks),
`first_delta_ms` (time to first visible text), `planner_ms`, `executor_ms`, `total_ms`. Per model call:
`tokens_in`, `tokens_cached`, `tokens_out`, `prefix_hash`. A `make context-report` target prints p50/p95 per stage,
warm hit rate, cache hit ratio and tokens per turn over the last N turns. Gate: no task in §10 counts as done without
before/after numbers on a real model (the fake model measures only plumbing; see the memory note that a real model is
plugged in once Gmail/WhatsApp are live).

## 10. Build order (each a `/ship` task: RED → GREEN → G1 → G2 → reviewer)

| # | Task | Migration | Depends on |
|---|---|---|---|
| C1 | Measurement: `tokens_cached`, `prefix_hash`, `first_delta_ms`, `warm_hit`, `make context-report` | 0016 | — |
| C2 | `app/context/` package: move page modules, `ContextSpec` + compiler for concierge (byte-identical prompt first) | — | C1 |
| C3 | Aliases + stable block order + company-constants block, concierge `v6` (v5 stays published), eval parity | — | C2 |
| C4 | `source_versions` on `agent_page_state`, version check replaces TTL (hard cap 15 min), delta re-resolve | 0017 | C2 |
| C5 | `LISTEN/NOTIFY`: in-transaction notify helper, one listener per API process, SSE push, polls slowed to 2 s; `page_changed` + re-warm on the `context` queue | — | C4 |
| C6 | Signed view tokens on read models; `PageContext.view_tokens` + `client_state`; snapshot only for `other` | — | C4 |
| C7 | Deep warm (rendered blocks, `blocks_hash`), `POST /agent/prepare`, instant answers from precomputed proposals/summaries | 0018 | C3, C6 |
| C8 | Streaming reply with sentence gate, `partial_reply`, `turn_delta` and `stage` events; queue poll 0.1 s | 0018 | C5 |
| C9 | Conversation summary (T2) and focus trail | 0019 | C2 |
| C10 | `person_profiles` (T3) + refresh workflow; proposer/link_check read them | 0019 | C2 |
| C11 | `memory_items` (T5): `remember` intent, Memory list API, distiller + `memory_review` feed, retirement | 0020 | C10 |
| C12 | Compiler specs for the other agents; GDPR erasure via `source_refs` | — | C11 |
| C13 | Optional, flagged: provider cache warm-up, typing hints, speculative retrieval; keep only what C1 numbers justify | — | C7, C8 |

C1–C8 are the speed track (live page reading); C9–C12 the memory track. They can proceed in parallel after C2.

## 11. Not adopted

- **Redis or an in-memory cache:** Postgres reads here are 1–5 ms; the latency is the model. Guard-forbidden anyway.
- **A vector database or a "memory framework" (Mem0, Zep, LangGraph memory):** they would hold tenant data outside
  our scoped tables, write memory from model output, and duplicate pgvector + DBOS.
- **Agents with memory-write tools:** breaks invariant 6; code writes memory.
- **Speculative planner calls while typing:** costs a full call per pause for a small gain; retrieval-only
  speculation is allowed behind a flag.
- **DOM scraping as the main page source:** unverified and token-heavy; view tokens replace it.
- **Long-lived workflows waiting for the owner:** invariant 2; session state is rows, not a sleeping workflow.

## 12. Open points for the user

1. Turn on the `remember` intent with immediate activation of the owner's own memories (proposed), or require a
   confirm click for those too?
2. Distiller cadence: nightly (proposed) or after every 10 edited drafts?
3. Planner model split: a small fast model for plans and page answers, the stronger model only for `draft_reply` and
   documents. Needs a model choice once the real LLM is plugged in.
4. Retention of `memory_items` and `person_profiles` (part of the M0 retention decision with Harjot).
5. Frontend work needed: view tokens passthrough, `client_state`, `prepare` on focus, `turn_delta`/`page_changed`
   handling. The SPA is built elsewhere; this spec's API changes go into `docs/dashboard-api.md` with each task.
