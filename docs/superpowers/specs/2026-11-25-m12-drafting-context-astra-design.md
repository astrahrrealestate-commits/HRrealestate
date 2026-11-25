# M12: AI staff for Harjot: six categories, drafts he would send, a 90-day reload, and an Astra that can do anything

Date: 2026-11-25 · Status: approved by the user in conversation (reload option A; six categories; category dashboard)
Team: two developers, 2–3 days.

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
- **A, chosen:** one dossier builder feeding the proposer, Astra and category briefs; history mode on the existing
  pipeline; next actions computed from the database, a model only writes the brief and the prepared work.
- B: a separate drafting service with its own retrieval. Rejected: duplicates RAG and the scoping rules.
- C: proposer with free tools. Rejected for tenant drafts: unbounded and harder to keep inside one tenant's data. Astra
  and the research step get tools; they answer Harjot, not tenants.

## Decided
- Drafts only for the newest unanswered incoming mail of each open case after the reload (user, option A).
- Six categories as above; old values map: `maintenance`, `contractor_update`, `complaint` → `maintenance`; `payment`
  → `finance`; `lease`, `admin`, `other` → `administration`; `spam` stays. (my call on the mapping)
- Models (my call, the user asked for the best quality with thinking on and reasonable speed):
  - quality tier, reasoning `high`: proposer, research, Astra, document reader, person memory, category brief.
    Default `anthropic:claude-opus-5-5` (needs an Anthropic key and a data-processing check for EU tenant data);
    otherwise the strongest Gemini Pro model on the existing key.
  - fast tier, reasoning `low`: understanding, link check, case summary, price extraction: `google-gla:gemini-3.8-flash`.
- Related context: same person, same unit or lease, company vendor data only.
- Web search: Firecrawl search behind the existing `SearchClient` port, shared by prices, research and Astra.
- Prompts change by new versions: `understanding/v4`, `proposer/v6`, each pinned after a real-model eval.

## Needs from the user (does not block building)
1. A Firecrawl API key.
2. The quality-tier model and key (Anthropic key, or confirm Gemini Pro).
3. Harjot's own replies forwarded by the Apps Script, so drafts see what he already said.
4. Reload scope: all of `info@hrrealestate.nl` for 90 days except spam, trash and drafts (default).
5. Merging to `main` (prod deploy) at the two deploy points in the plan.
6. The ROZ general provisions (algemene bepalingen) versions the leases refer to, and Harjot's standard terms, as PDFs
   for the reference library. Without them, ROZ answers rely on public sources only.

## Left to the builders
Dossier budgets, reload queue concurrency, purge order, prompt wording within the rules, dashboard visual detail
within the sketch in the plan.
