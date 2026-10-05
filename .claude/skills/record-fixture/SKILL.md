---
name: record-fixture
description: Add a recorded webhook/API payload (WhatsApp Cloud API, Gmail history/messages, Pub/Sub push, OpenAI response) as a test fixture with PII redacted. Use when a test needs a realistic provider payload or the user shares a real payload.
---

# /record-fixture

Fixtures live in `tests/fixtures/recorded/<provider>/<scenario>.json` and are immutable once committed (hook-enforced).
Tests never call real providers (pytest-socket blocks the network).

1. Source: provider docs example, or a payload the user pastes. Never fetch live with shell tools (blocked).
2. **Redact before writing:**
   - phone numbers → `+4915550000NNN` (reserved fictional range), keep E.164 shape
   - emails → `tenant-NNN@example.test`, `owner@example.test`
   - names → `Tenant NNN`, addresses → `Teststraße N, 10115 Berlin`
   - tokens, signatures, `wamid` ids → deterministic fakes (`wamid.TEST000N`), keep lengths/prefixes
   - Gmail bodies: base64url re-encode after editing text
3. Keep provider structure byte-faithful otherwise (field order/nesting matter for parsers).
4. Signed webhooks (WhatsApp `X-Hub-Signature-256`): store the body file exactly as bytes; tests compute the
   signature with the test app secret from `tests/conftest.py` — never store real signatures.
5. Add a sibling `<scenario>.md` (2–3 lines): source, what it exercises, redactions applied.
6. Use via the `recorded(provider, scenario)` fixture loader in `tests/conftest.py`.
