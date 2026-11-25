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
7. **Erasure reaches the call log.** Calls record the messages in their prompt (`model_calls.message_ids`); erasure
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
