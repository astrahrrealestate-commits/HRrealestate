# ADR 0003: pywa for WhatsApp, 360dialog for Coexistence

Status: proposed — confirm the partner at M0

## Context
The tenant-facing number is Harjot's existing WhatsApp Business app number. Using it with the Cloud API ("Coexistence")
requires onboarding through a Meta Solution Partner / Tech Provider via Embedded Signup. The owner channel uses a
separate agent number, for which plain Cloud API is fine.

## Decision
- **pywa** handles webhook parsing, signature verification and typed messages (buttons, lists, templates).
- **360dialog** (Berlin, EU) is the Coexistence partner for the tenant-facing number. The agent number can go direct
  to Meta Cloud API or also through 360dialog. Pick one at M0 to keep a single integration.
- Everything behind `channels/whatsapp/{inbound,outbound}.py`. If a partner's outbound API differs from Cloud API,
  only `outbound.py` changes.

## Consequences
- Webhook payloads stay in Cloud API format, so the same fixtures work for both routes.
- Partner fees apply. Partner choice is reversible (adapter boundary).
- Phase 1 never sends to tenants, so the tenant number is inbound-only plus echo capture.
