# EstateOS development pipeline

Every change flows through the same stages. A stage passes only when its gate shows evidence (a command plus its result
line). `/ship` runs this pipeline for one task.

```
 INTAKE ─► SPEC ─► PLAN ─► [ RED ─► GREEN ─► REFACTOR ─► G1 quick ] ─► G2 full ─► G3 review ─► COMMIT ─► G4 CI ─► G5 milestone
           (arch only)        ▲──────────── per task ─────────────┘
```

| Stage | What | Tool / skill | Gate (must pass) |
|---|---|---|---|
| Intake | classify: spike / bounded / architectural | `superpowers:brainstorming` | user agrees with classification |
| Spec | design doc for architectural work | brainstorming → `docs/superpowers/specs/` | user approves spec |
| Plan | tasks with files, failing test, acceptance command | `superpowers:writing-plans` | user picks execution mode |
| RED | write the failing test first | pytest | test fails for the *right* reason (quote it) |
| GREEN | minimum code to pass | — | that test passes |
| REFACTOR | clean up; no behaviour change | ruff (post-edit hook) | tests still pass |
| **G1 quick** | `make quick`: ruff, format, mypy, import-linter, unit tests | stop hook enforces | all green |
| **G2 full** | `make check`: + integration (testcontainers PG, DBOS), migration round-trip, drift | `/check full`, `test-runner` agent | all green; required when DB/workflows/adapters/API touched |
| **G3 review** | invariants + correctness | `estateos-reviewer` agent (`/code-review` for large diffs) | `VERDICT: ship` |
| Commit | conventional commit on milestone branch | pre-commit: ruff, gitleaks, import-linter, mypy, unit | hooks pass (never `--no-verify`) |
| **G4 CI** | GitHub Actions: lint, types, boundaries, unit, integration, migrations, pip-audit, docker build; evals if prompts/contracts changed | GH Actions | green before merge |
| **G5 milestone** | `make smoke` + every "Done when" clause demonstrated | `/milestone close` | reviewer `ship` + evidence quoted in PROGRESS |

## Test strategy per layer

| Layer | Test type | Tools | Must cover |
|---|---|---|---|
| `contracts` | unit + property | pytest, hypothesis | JSON round-trip, validators, state matrix, ButtonId fuzz |
| `pipeline.rules` | unit, exhaustive | pytest parametrize | every rule × every outcome; no I/O |
| `db` repositories | integration | testcontainers PG, polyfactory | company scoping, unique constraints, partial indexes |
| `channels` inbound | unit | recorded fixtures, syrupy | every recorded payload → expected `Message` |
| `channels` outbound / `sender` | unit + integration | respx, fakes | guards (approval, version, pause, allowlist), idempotency |
| `llm` agents | unit | Pydantic AI `TestModel`/`FunctionModel`, syrupy | prompt render snapshot, output parsing, model_calls row |
| `workflows` | integration | DBOS on testcontainers PG | step order, retry → resume, duplicate enqueue = one run |
| `api` | integration | FastAPI TestClient + recorded webhooks | signature/OIDC reject, dedupe, 200 fast |
| end-to-end | integration | recorded payload in → DB rows out | golden pipeline scenarios with fake LLM |
| AI quality | eval (not pass/fail CI by default) | pydantic-evals, Langfuse | accuracy per category, suspicious recall; regressions block a prompt switch |

**Coverage floor:** 85 % line overall; 95 % branch on `pipeline/rules`, `sender`, `contracts`, `owner/commands`.
**Never:** network in tests (pytest-socket), SQLite in place of Postgres, skipped or xfailed tests to get green,
mocking the unit under test.

## Definition of done (per task)
- [ ] Test written first and seen failing
- [ ] G1 green (G2 when the layer requires it), result line quoted
- [ ] Invariants in CLAUDE.md respected (reviewer checked for non-trivial diffs)
- [ ] No TODOs without an issue link; no commented-out code; no `print`
- [ ] Docs touched if behaviour or contract changed (spec / HLD / ADR)
- [ ] PROGRESS.md item ticked with evidence

## Open gate notes
- **G2 outstanding for dashboard tasks 1-9** (D1-D3): written while Docker was down, so their integration tests
  (collected and mypy-clean, never run) and the migration round-trip have not been executed. Run `make check` once
  Docker is available and fix what it finds before relying on send mode.
- **G2 and G5 outstanding for all dashboard tasks (D1-D5, tasks 1-15):** `make check`, `make smoke` and `make sim-demo`
  (now including the `dashboard` scenario in `app/dev/demo_dashboard.py`) were never run, because Docker was down;
  `make cov` needs Docker too (it runs the integration tests); `make live-check k=outbound` needs credentials. G1,
  `make audit`, `make harness-test` and the concierge eval on the fake model did run (numbers in PROGRESS.md).
