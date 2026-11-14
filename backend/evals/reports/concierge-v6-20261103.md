# Eval: concierge/v6

- date: 2026-11-03T18:51:05+00:00
- model: google-gla:gemini-2.5-flash
- prompt sha256: 96997053f791b626834b3bfd1469ef8b6a5c5bb99177159cc448971aa86c6544

| metric | score |
|---|---|
| intent_sequence_match | 0.80 |
| scope_accuracy | 1.00 |
| forbidden_intent_rate | 0.02 |
| invariant_pass_rate | 0.96 |
| reply_rate | 0.50 |

## Misses (14)

| case | expected | got | text |
|---|---|---|---|
| read-03 | in_scope=True ['list_waiting'] | in_scope=True ['case_status'] reply=False | Who are we waiting on for the quote? |
| read-05 | in_scope=True ['answer'] | in_scope=True ['case_status'] reply=True | How is the rent situation with Piet going? |
| read-06 | in_scope=True ['answer'] | in_scope=True ['read_document'] reply=False | What did the contractor say about the boiler? |
| read-07 | in_scope=True ['case_status'] | in_scope=True ['answer', 'case_status'] reply=True | Wat is de status van de lekkage bij Sanne? |
| task-06 | in_scope=True ['create_task'] | in_scope=True ['create_task', 'task_snooze'] reply=False | Remind me on Friday to ask the insurer about the damage clai |
| reply-04 | in_scope=True ['chase_now'] | in_scope=True ['clarify'] reply=False | Nudge the contractor again about the boiler |
| page-01 | in_scope=True ['case_status'] | in_scope=True ['answer'] reply=True | summarise this |
| page-02 | in_scope=True ['open_view', 'answer'] | in_scope=True ['answer'] reply=True | is this draft okay? |
| page-05 | in_scope=True ['answer'] | in_scope=True ['answer'] reply=True | what does this page say? |
| page-08 | in_scope=True ['case_status'] | in_scope=True ['answer'] reply=True | summarise this |
| page-11 | in_scope=True ['case_status'] | in_scope=True ['case_status'] reply=True | what is the status of the first one? |
| page-12 | in_scope=True ['case_status'] | in_scope=True ['answer'] reply=True | summarise this |
| page-14 | in_scope=True ['open_view'] | in_scope=True ['show_drafts'] reply=False | open the first one |
| page-16 | in_scope=True ['answer'] | in_scope=True ['answer'] reply=True | what does the latest message say? |
