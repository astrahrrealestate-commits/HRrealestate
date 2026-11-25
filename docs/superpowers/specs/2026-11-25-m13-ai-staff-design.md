# M13: AI staff for Harjot: six categories, drafts he would send, a 90-day reload, and an Astra that can do anything

Date: 2026-11-25 · Status: approved by the user in conversation (reload option A; six categories; category dashboard;
"Added: RAG and Astra" awaits approval);
revised the same day after a codebase audit (see "Changed after the codebase audit").
Team: planned for two developers; RAG and Astra need a third lane to keep 3 days (third lane not yet confirmed by the
user; see "Added: RAG and Astra"). (M12 is "Due diligence lite" in `docs/PROGRESS.md`, so this is M13.)

## Why
The client saw the product. Drafts were too basic and the dashboard is a generic overview. Harjot wants AI staff that
work like employees: per area of the business, they know what needs doing, have done the reading and research, and put
the next step in front of him ready to approve. Quality of every reply and every piece of research matters most;
speed matters too.

## What is wrong today (found 2026-11-25)
- The 30-day import (`backend/scripts/backfill_vastgoed_30d.py`) bypassed the pipeline: own 2–4-sentence prompt on
  `gemini-2.5-flash`, thinking off, attachments marked read without reading, no understanding, links or memory.
- The proposer runs at thinking `minimal` and sees only the newest mail, a one-line profile, the rolling case summary
  and three document snippets (`app/pipeline/propose.py:_load`).
- Attachments are read and quotes reviewed after the draft (`app/workflows/pipeline.py:166-173`).
- Market prices are fake: no web search provider (ADR 0009).
- Person memory is a counted one-liner.
- Astra: 3 lookups, 5 hits of 300 characters; cannot open a mail, thread or document, or search the web.
- Categories are `maintenance, payment, lease, complaint, contractor_update, admin, spam, other`; the dashboard is not
  organised by them.
- The code asks for acknowledgements: `propose.py:157-165` tells the model to acknowledge every maintenance report
  without a BRIXX ticket, prompt `proposer/v5` asks for one in six rules, and canned acknowledgements are offered by
  the inbox, contacts, emergency path and six screens. Today shows invented demo rows when the API fails.
- Harjot's standing rules ("remember …") never reach a draft: the function that would add them is never called.
- Owner redrafts see no documents; the sender's role comes from the case's main person, not the mail's sender.
- Quotes from vendors not in the directory are never reviewed, and the review runs before attachment text exists.
- Harjot's own mail in the mailbox is treated as inbound mail from him, and could be drafted to. His replies mostly live
  only in the quoted history of later forwarded mail, so most conversations look unanswered.

## Goals
1. **Six categories** everywhere (understanding, cases, inbox, dashboard): `maintenance`, `finance`, `legal`,
   `business`, `administration`, `new_projects`. `spam` stays an internal value, never shown.
2. **Category dashboard:** on login Harjot picks a category; he sees a short brief and the ranked next actions of that
   area, each with the work already prepared (draft written, quote countered, document summarised).
3. **One context dossier per mail:** whole thread (both directions), the sender's earlier mail, attachment text,
   that person's case, unit and lease documents, person memory, owner rules, open waits, quote comparison, research.
4. **Drafts Harjot would send:** proposer `v6` from the dossier, top-quality model, reasoning on, no invention.
5. **Research wherever needed:** web search for prices, rules, products and anything the mail asks that our data cannot
   answer; findings carry their URLs. A quote above market gets a counter-offer with numbers and sources.
6. **Read before drafting:** attachments (PDF, Word, scans, photos) read and indexed before the proposer runs.
7. **Astra can do anything an employee would:** open any mail, thread or document, search mail, documents, data and the
   web, draft and improve replies with the same dossier.
8. **Reload:** delete the Gmail data of `info@hrrealestate.nl`, reload 90 days in history mode (read, link, remember, no
   drafts or notices), then draft only conversations still waiting for Harjot (option A).
9. **Harjot's own words count:** his mail in the mailbox and his replies quoted in later mail are context and mark a
   conversation answered; nothing is ever drafted to him.
10. **Search finds the right mail:** message search embeds the question as a query, matches any of its words in Dutch
    or English, indexes each mail's new part once, reranks, and is measured by its own eval next to the document one.
11. **Astra understands what he means:** names, addresses, vendors and "he / that quote" resolve to the right rows;
    it keeps 12 turns and the conversation summary; any question about content, amounts, dates or rules is researched,
    never answered from summaries; every research answer lists sources that open.
12. **Better is measured:** the share of drafts approved unchanged or lightly edited, drafts dropped as generic,
    latency and cost per draft, per category and prompt version, before and after.

## Drafting standard (Harjot's words, 2026-11-25; binding for every draft, including Astra's)
> The Super Agent should never draft generic acknowledgements or basic responses. Every draft must be commercially
> sharp and substantively complete.
>
> Before drafting, it must always review:
> - the full email thread and relevant historical correspondence;
> - all attachments, quotations, contracts and specifications;
> - the property, address, parties involved and previous agreements;
> - whether prices and terms are market-conform;
> - applicable ROZ provisions and relevant laws and regulations.
>
> For quotations: verify scope, quantities, individual costs, risks and omissions, and always negotiate improved
> pricing and terms.
> For works: clarify scope, planning, duration, access, disruption and tenant coordination.
> If information is missing: ask specific questions and never assume or invent facts.
>
> Every draft must be concise, strategic, complete, immediately usable and one step ahead. Financial or legal
> commitments (or any) remain subject to my approval. Avoid empty responses such as: "Thank you for your message; I
> will get back to you."

What this means for the build (my reading, to be corrected):
- No canned acknowledgement anywhere: the inbox fallback drafts (`app/api/inbox/routes.py:_build_drafts`), the
  emergency acknowledgement (`app/pipeline/propose.py:_ensure_emergency_reply`), the contacts fallback
  (`app/api/contacts/routes.py:510`) and the screen templates (`frontend/src/lib/replyTicket.ts`,
  `EditTicketModal.tsx`, `app/page.tsx:427`, `TransactionDetailSheet.tsx`) go. With no real draft, the screen says so
  and offers "Draft with Astra".
- A generic draft is rejected in code and redrafted once; if still generic, no draft is offered.
- ROZ provisions and law: a **reference library** of company documents not tied to any tenant (the ROZ general
  provisions the leases use, Harjot's standard terms), readable by every dossier; legal web research limited to
  official sources (`wetten.overheid.nl`, `rechtspraak.nl`, `roz.nl`) with URLs.
- Every draft lists, for Harjot, each financial, legal or other commitment it contains (amount, date, promise) next to
  the approve button. Nothing is committed until he approves.
- Quotes: the review checks scope, quantities, unit costs, risks and omissions against the request and the market, and
  the draft always negotiates price or terms.

## Non-goals
Automatic sending (send mode stays off); running the forwarded-mail repair or label pass; WhatsApp history reload.

## Anti-goals
- Another tenant's data in a draft, a brief or a reply.
- Text in a mail, attachment or web page steering an agent.
- A reload that floods Harjot or duplicates messages, cases or Drive files.
- A draft or brief stating a price, date, amount, rule or promise that is not in its sources.
- A dashboard that summarises instead of telling him what to do next.
- A generic acknowledgement or basic response offered as a draft, anywhere.

## Approaches
- **A, chosen:** one dossier builder feeding the proposer, owner redrafts and Astra; history mode on the existing
  pipeline; next actions and the brief computed from the database; models write only the prepared work.
- B: a separate drafting service with its own retrieval. Rejected: duplicates RAG and the scoping rules.
- C: proposer with free tools. Rejected for tenant drafts: unbounded and harder to keep inside one tenant's data. Astra
  and the research step get tools; they answer Harjot, not tenants.

## Decided
- Drafts only for the newest unanswered incoming mail of each open case after the reload (user, option A).
  "Unanswered" (my call): the newest message is inbound and needs a reply, is at most 14 days old, has no outbound
  message after it, and no later mail quotes a reply from Harjot. Cases quiet for 14 days after the reload are
  resolved; they reopen on new mail as usual. `draft-open` runs as a dry run first and the user reads the list.
- History mail runs in sent order per sender (one history queue partitioned by sender), so a reply is never linked
  before the mail it answers; live mail keeps its own queue.
- Six categories as above; old values map: `maintenance`, `contractor_update`, `complaint` → `maintenance`; `payment`
  → `finance`; `lease` → `legal`; `admin`, `other` → `administration`; `spam` stays. (my call on the mapping; the
  reload re-reads all Gmail with the new prompt, so the map matters mainly for WhatsApp cases)
- **Gemini only** (user, 2026-11-25): every model call and web search uses the Gemini API key. No other LLM, search
  or embedding provider; the non-Gemini fallback in prod (`openai:gpt-4.1-mini`) is removed and prod refuses any
  non-`google-gla:` model.
- Models (my call, the user asked for the best quality with thinking on and reasonable speed):
  - quality tier, reasoning `high`, 180 s and 16k output tokens per call: proposer, draft research, Astra's research
    loop, person memory. The strongest Gemini Pro model the key lists (`GET /v1beta/models`), fallback
    `google-gla:gemini-3.8-flash` at high reasoning.
  - fast tier, each agent's current reasoning: understanding, link check, case summary, document classifier, document
    reader and OCR, quote reader, price extraction, web search: `google-gla:gemini-3.8-flash`. The document reader is
    fast tier because the proposer reads the attachment text itself; this keeps 90 days of attachments affordable.
  - embeddings stay `google-gla:gemini-embedding-001`.
- The category brief is one sentence built from the action counts by code, not by a model: nothing to invent, nothing
  to cache. The prepared work under each action is where the AI's effort shows.
- Quotes: the existing quote review (`app/finance/quotes.py`) runs before the draft and also for vendors not in the
  directory (market prices only). Scope, quantities, risks and omissions are judged by the proposer from the quote, the
  request and the review; no separate comparison agent.
- Mail whose real sender is one of Harjot's addresses is "owner-authored": linked and indexed, shown in drafts' context
  as his words (marked unverified, since From can be forged), never drafted to.
- Related context: same person, same unit or lease, company vendor data only.
- Web search: Gemini's Google Search grounding on the same key, behind the existing `SearchClient` port and shared by
  prices, research and Astra. Grounding returns source URLs; each page is then fetched (size and time capped) so
  findings and prices are checked against the page text. Pages are untrusted data.
- Prompts change by new versions: `understanding/v4`, `proposer/v6` (built on the unpinned role-aware `v5`), each
  pinned after a real-model eval.

## Needs from the user (does not block building)
1. Confirmation that the Gemini key's project has Google Search grounding enabled and enough quota for the reload
   (90 days of mail at the fast tier, plus quality-tier drafts and research).
2. Harjot's own replies forwarded by the Apps Script, so drafts see what he already said.
3. Reload scope: all of `info@hrrealestate.nl` for 90 days except spam, trash and drafts (default).
4. Merging to `main` (prod deploy) at the two deploy points in the plan.
5. The ROZ general provisions (algemene bepalingen) versions the leases refer to, and Harjot's standard terms, as PDFs
   for the reference library. Without them, ROZ answers rely on public sources only.

## Changed after the codebase audit (2026-11-25)
The first version planned parts the code already has and missed problems the code has. Changes:
- **Reuse instead of rebuild:** per-agent model lookup, the web-search port with evidence checks, the quote review,
  attachment reading, message and document search, owner rules, person profiles, the dashboard's attention and radar
  data. No new quote-comparison module and no category-brief agent.
- **Added:** removing the acknowledgement instructions in code and prompt; wiring Harjot's rules into drafts; owner
  redrafts with full context; sender role from the mail's sender; owner-authored mail; reading quoted history;
  ordered history runs; old mail never closing a newer wait; purge removing raw events (otherwise the reload records
  nothing); quotes from unknown vendors reviewed; reading and reviewing before the draft; a fetch guard against
  internal addresses for web pages; removing demo data and every canned draft on screens; a fake model that writes
  real drafts so tests keep working.
- **Removed:** `backend/scripts/import_historical_emails.py` too (it also bypasses the pipeline); a dead context
  function; invented "confidence" numbers on drafts.
- **Changed:** milestone M13; `lease` maps to `legal`; document reader on the fast tier; two model tiers set in code
  instead of per-agent JSON settings; the category API under `/api/dashboard`; research findings in their own column.

## Added: RAG and Astra (2026-11-25)
The user asked for RAG and Astra to be covered on the same schedule. The details below are my call and not yet approved.

Found in the code (full list: plan, "Wrong today" 20-29):
- Queries are embedded as documents; message search needs every word; quoted history is indexed again in every reply;
  Astra uses neither the document planner nor the reranker; message search has no eval.
- Astra's planner sees five 400-character summaries and 12 short lines, and on the dashboard chat not the conversation
  summary. It reaches only the 20 newest open cases, the page's and the focus case. Keyword shortcuts bypass the planner
  or replace its answer. Planned research runs without the conversation, and answers have no sources. The chat stops
  waiting after 55 s.
- Draft quality is measured per company-day, not per category or prompt version.

Decided:
- Message eval and baselines come first, so every search change has a before and after. Query task type, OR words with the
  glossary, rerank for Astra only, and Gmail chunks with each mail's new part. No separate reindex.
- Entities resolve with `rapidfuzz` and the existing glossary, inside the company: no new extension or migration.
- The keyword shortcuts go; the planner's existing intents cover them.
- Research answers carry sources, checked against what the tools returned in that run.
- Research has a deadline: 35 s, or 90 s once the load balancer and the client allow 120 s. Depth and speed trade off here.
- The draft report extends the existing outcome capture. Its baseline is taken before the purge, which deletes its rows.
- The purge keeps `sends` with a null action and deletes the outcomes of purged actions.
- Gates: message `context_hit` ≥ 0.85 and `mrr` above baseline, isolation 0, documents not lower; `v10` intent accuracy ≥
  `v9`; research correctness ≥ 0.85. The numbers are starting points, to be set against the baselines.

## Left to the builders
Dossier budgets, reload queue concurrency, purge order, prompt wording within the rules, dashboard visual detail
within the sketch in the plan.
