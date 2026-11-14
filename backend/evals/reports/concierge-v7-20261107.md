# Eval: concierge/v7

- date: 2026-11-07T16:27:48+00:00
- model: google-gla:gemini-2.5-flash
- prompt sha256: db6b0fc3f3a7422037ed34b23d8694e0e1e6fa6136a97e2d58431de3ae03c324

| metric | score |
|---|---|
| intent_sequence_match | 0.85 |
| scope_accuracy | 1.00 |
| forbidden_intent_rate | 0.00 |
| invariant_pass_rate | 0.97 |
| reply_rate | 0.50 |
| research_recall | 1.00 |
| research_false_rate | 0.04 |

## Misses (13)

| case | expected | got | text |
|---|---|---|---|
| read-03 | in_scope=True ['list_waiting'] | in_scope=True ['answer'] reply=False research=True | Who are we waiting on for the quote? |
| read-05 | in_scope=True ['answer'] | in_scope=True ['case_status'] reply=True research=False | How is the rent situation with Piet going? |
| read-06 | in_scope=True ['answer'] | in_scope=True ['answer'] reply=False research=True | What did the contractor say about the boiler? |
| pause-04 | in_scope=True ['resume'] | in_scope=True ['answer'] reply=True research=False | You can resume sending now |
| reply-04 | in_scope=True ['chase_now'] | in_scope=True ['clarify'] reply=False research=False | Nudge the contractor again about the boiler |
| page-01 | in_scope=True ['case_status'] | in_scope=True ['answer'] reply=True research=False | summarise this |
| page-02 | in_scope=True ['open_view', 'answer'] | in_scope=True ['show_drafts'] reply=False research=False | is this draft okay? |
| page-07 | in_scope=True ['answer'] | in_scope=True ['answer'] reply=True research=False | summarise this |
| page-08 | in_scope=True ['case_status'] | in_scope=True ['answer'] reply=True research=False | summarise this |
| page-12 | in_scope=True ['case_status'] | in_scope=True ['answer'] reply=True research=False | summarise this |
| page-14 | in_scope=True ['open_view'] | in_scope=True ['show_drafts'] reply=False research=False | open the first one |
| page-15 | in_scope=True ['answer'] | in_scope=True ['answer'] reply=True research=False | what did the tenant ask last? |
| page-16 | in_scope=True ['answer'] | in_scope=True ['answer'] reply=True research=False | what does the latest message say? |
