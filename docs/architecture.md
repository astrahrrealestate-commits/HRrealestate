# EstateOS Phase 1: architecture

> Runtime per [ADR 0001](adr/0001-dbos-durable-workflows.md): DBOS replaces Celery/Beat/Redis. Detail: [hld.md](hld.md).

```
WHATSAPP                              GMAIL
Meta Cloud API (or partner, if         Gmail API + Pub/Sub
Coexistence needs one)                 (watch renewal = timer)
   └──────────────┬──────────────────────┘
                  ▼
INGESTION (FastAPI)
  verify signature
  INSERT raw_event   ← Postgres FIRST; unique on provider_msg_id
  return 200
  enqueue raw_event.id
                  │
         ┌────────┴──────────────┐
         ▼                       ▼
  OWNER COMMAND HANDLER     TENANT/CONTRACTOR PIPELINE (DBOS worker)
  (owner number, button     │
  replies)                  ├─ UNDERSTANDING AI (one structured call)
  ├─ match button ID to     │    classify · entities · urgency · intent · suspicious
  │  pending approval       ├─ CASE ENGINE
  ├─ record decision        │    channel identity → person → unit → lease
  └─ questions → read-only  │    link to open case / create case
     answer step            ├─ PROPOSAL ENGINE
         │                  │    case summary · typed actions · 2–3 drafts
         │                  └─ RULES ENGINE
         │                        permissions · approval needed? · safety
         │                             │
         └──────────────► OWNER CHANNEL (agent's own WhatsApp number)
                            briefing · alerts · drafts · approve/edit/reject
                                       │
                                       ▼
                          SENDER (only component with send credentials)
                            Phase 1: Gmail drafts + messages to Harjot only
                            re-checks approval + draft version before acting
                            idempotency key per action

ACROSS EVERYTHING
  timers table in Postgres + DBOS cron `system.timer_sweep` every minute
    (07:30 briefing, re-checks, overdue flags, Gmail watch renewal)
  outcome capture (Gmail Sent + phone-reply echoes → unchanged/edited/rewritten)
  model-call log (prompt version, context, output, cost) · error alerts
```
