# 0017. Drafts from a per-mail dossier, six categories, two Gemini tiers

Date: 2026-11-26 · Status: accepted for the drafting lane (M13, spec 2026-11-25-m13-ai-staff-design). The history
reload, read-review-research before drafting, and the category desk are added to this record by their lanes.

## Context
The client found drafts too basic: the proposer saw the newest mail, a 300-character profile line, the rolling case
summary and three document snippets, ran at minimal reasoning, and was told in code and prompt to acknowledge
maintenance reports, legal letters and emergencies. Harjot's standing rules never reached a draft. Harjot's own
replies mostly exist only as quoted history in later mail. Categories followed message types, not the areas of his
business. Prompts, now much larger, stayed in `model_calls` after a person was erased.

## Decision
1. **One dossier per mail** (`app/pipeline/dossier.py`), read by every proposal and owner redraft: the thread and the
   case's mail (each message's new part), Harjot's replies found only as quotes, the sender's other mail, attachment
   text, the case's own documents, the company reference library (`documents.is_reference`), person memory, owner
   rules and open waits. `render_dossier` fits it into 60,000 characters and never cuts the mail being answered.
2. **Scope by person, not by thread.** A tenant's dossier holds their own mail and papers and what was sent to them; a
   contractor's adds the report of the case's main person; anyone the directory does not know sees only their own
   words. Unit documents are left out (they include earlier tenants' papers).
3. **Harjot's own mail is context, never an addressee.** Inbound mail from an owner address is marked
   `owner_authored` and never drafted to. Quoted "Harjot wrote" text is shown as "not verified": `From` and quotes can
   be forged, so neither is ever treated as an approval.
4. **`proposer/v6`** carries Harjot's drafting standard verbatim instead of every acknowledgement rule. Code checks
   the result (`draft_quality.is_generic`): generic variants are dropped, a reply left with fewer than two is redrafted
   once with feedback, and then no reply is offered ("draft with Astra"). No canned draft exists anywhere in the
   backend. Every reply lists its commitments for Harjot to read before he approves.
5. **Six categories**: maintenance, finance, legal, business, administration, new projects (+ internal spam), mapped
   from the old eight by migration 0054, including the stored understanding bodies.
6. **Two model tiers, Gemini API only.** Proposer, draft research, Astra's research loop and person memory use
   `LLM_QUALITY_MODEL` at reasoning `high`; everything else keeps the fast model and its own reasoning level. Prod
   refuses any other provider, fallback or embedding.
7. **Read before drafting; tenancy and older mail in view.** A pipeline step before the draft reads the mail's
   attachments and reviews a contractor's quote (`prepare_for_draft`). The dossier adds the person's tenancy as the
   directory and the BRIXX rent ledger hold it (unit, lease, latest rent, overdue invoices, work order) and their
   older mail that matches this one. Facts are read at draft time, never copied into memory, so they stay current.
8. **Erasure reaches the call log.** Calls record the messages in their prompt (`model_calls.message_ids`); erasure
   blanks those and any untagged call whose text holds the person's addresses, full name or a line of their mail.

## Consequences
- Proposals cost more (a quality-tier call with up to 60k characters, sometimes two). Person memory adds one quality
  call per person with newer mail; it never blocks a draft.
- v6 runs before its real-model eval: the spec forbids generic acknowledgements anywhere, and v5 asked for them. The
  eval (`evals/proposer_v6_eval.py`) gates Deploy 2; a failure is fixed in a new prompt version.
- Unit documents and other tenants' mail are never in a draft, even where they would help; Harjot adds a document to
  the reference library when every dossier should see it.
- Rejected: a separate drafting service with its own retrieval (duplicates the scoping rules); proposer with free
  tools (unbounded, harder to keep inside one tenant's data).

## Lane C: search and Astra (M13 T11, T14, T15, T16; added 2026-11-26)
### Decision
8. **Questions are embedded as queries, stored text as documents** (Gemini task types). Chunks were embedded through
   the query path before; the 90-day reload re-embeds them.
9. **Message search** fuses an all-words list, an any-words list (Dutch/English glossary, header words left out) and
   vectors. Astra's searches are reranked by the document reranker; a hit is dropped only when the model scored it
   unhelpful, and a search by date or channel lists what it found. The reranker sees the stretch of a long chunk that
   matches, always under that line's real `[time | sender | direction]` head; bodies cannot write a head of their own.
   Reranker calls store sizes only (`AgentSpec.redact_input`).
10. **An email adds its new part once**; a reply of Harjot's that exists only as a quote is indexed once per chunk as
    "Harjot (quoted in a later mail, not verified)", never as his outbound line. Re-indexing a message rebuilds its
    chunk from its messages as they are now (corrected sender, direction, person, case; refused messages leave).
11. **Astra cites, never names.** Every row or page a tool returns gets a short reference (`m1`, `d2`, `w1`, `q1`,
    `p1`); tools open and the answer cites only those, and citations the tools never handed out are dropped. An answer
    that looked things up but cites nothing real is replaced by what was searched. Research has a deadline
    (`SUPER_AGENT_DEADLINE_SEC`, 35 s; the browser gives up at 55 s): lookups stop at 60 % of it, past it the owner is
    told what was checked.
12. **The planner resolves names** (people, vendors by trade, units, open and closed cases) with `rapidfuzz` and the
    glossary inside the company; their case ids may be acted on. It keeps 12 turns and the conversation summary as
    its own block. `concierge/v10` adds research for every content question; it stays unpinned until its gate passes.
13. **Draft quality is counted, not judged**: per category and prompt version (`actions.prompt_version`, 0058),
    approvals, owner edits, sent-folder outcomes, "no usable draft", minutes to draft and cost; counts only.

### Consequences
- Every Astra research question is one quality-tier call plus a reranker call per message search; a web search adds a
  grounding call and page fetches. The 35 s deadline trades depth for an answer the browser still waits for.
- The dashboard chat's document shortcut stays until `find_document` renders the Drive card; the standing-rule
  shortcuts are gone.
- A cross-language question about a long mail can pick the wrong stretch for the reranker (one miss in the real-model
  eval); embedding windows would fix it.
