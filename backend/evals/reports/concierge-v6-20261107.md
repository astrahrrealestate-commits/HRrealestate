# Eval: concierge/v6

- date: 2026-11-07T16:09:02+00:00
- model: google-gla:gemini-2.5-flash
- prompt sha256: 96997053f791b626834b3bfd1469ef8b6a5c5bb99177159cc448971aa86c6544

| metric | score |
|---|---|
| intent_sequence_match | 0.78 |
| scope_accuracy | 0.98 |
| forbidden_intent_rate | 0.02 |
| invariant_pass_rate | 0.95 |
| reply_rate | 0.38 |

## Misses (17)

| case | expected | got | text |
|---|---|---|---|
| read-05 | in_scope=True ['answer'] | in_scope=True ['case_status'] reply=False research=False | How is the rent situation with Piet going? |
| read-06 | in_scope=True ['answer'] | in_scope=True ['read_document'] reply=False research=False | What did the contractor say about the boiler? |
| task-06 | in_scope=True ['create_task'] | in_scope=True ['create_task', 'task_snooze'] reply=False research=False | Remind me on Friday to ask the insurer about the damage clai |
| pause-04 | in_scope=True ['resume'] | in_scope=False [] reply=False research=False | You can resume sending now |
| reply-04 | in_scope=True ['chase_now'] | in_scope=True ['clarify'] reply=False research=False | Nudge the contractor again about the boiler |
| page-01 | in_scope=True ['case_status'] | in_scope=True ['answer'] reply=True research=False | summarise this |
| page-02 | in_scope=True ['open_view', 'answer'] | in_scope=True ['answer'] reply=True research=False | is this draft okay? |
| page-05 | in_scope=True ['answer'] | in_scope=True ['answer'] reply=True research=False | what does this page say? |
| page-08 | in_scope=True ['case_status'] | in_scope=True ['answer'] reply=True research=False | summarise this |
| page-11 | in_scope=True ['case_status'] | in_scope=True ['case_status'] reply=True research=False | what is the status of the first one? |
| page-12 | in_scope=True ['case_status'] | in_scope=True ['answer'] reply=True research=False | summarise this |
| page-14 | in_scope=True ['open_view'] | in_scope=True ['show_drafts'] reply=False research=False | open the first one |
| page-15 | in_scope=True ['answer'] | in_scope=True ['answer'] reply=True research=False | what did the tenant ask last? |
| page-16 | in_scope=True ['answer'] | in_scope=True ['answer'] reply=True research=False | what does the latest message say? |
| research-01 | in_scope=True ['answer'] | in_scope=True ['search_inbox', 'read_document'] reply=False research=False | Has anyone mentioned the roof lately, and what does the leas |
| research-02 | in_scope=True ['answer'] | in_scope=True ['query_data', 'read_document'] reply=False research=True | Did any tenant complain about noise this year, and is there  |
| research-03 | in_scope=True ['answer'] | in_scope=True ['find_document', 'find_document'] reply=False research=False | What did tenants write about the heating, and is anything ab |
