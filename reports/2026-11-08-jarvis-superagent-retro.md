# Retro: Jarvis Super Agent slices 0-3 (2026-11-06 to 2026-11-08)

Branch `m-jarvis-superagent`: conversational prompt, Gemini through Pydantic AI, read-only research loop, and
`concierge/v7` with `needs_research`. Gates at the end: `make quick` 2750 passed; `make check` 807 passed and 5 failed
(the stale mock-data tests in `test_frontend_data_api_integration.py`, not touched by this work).

## What happened
Four slices, each RED -> GREEN -> `make quick` -> `make check` -> reviewer -> commit -> push. The reviewer returned
`ship` every time and found no blocking issues. Real Gemini golden-set numbers backed the v7 default switch
(intent match 0.78 -> 0.85, forbidden 0.02 -> 0.00, reply rate 0.38 -> 0.50).

## What slowed us down
1. **A flaky unit test hid for three slices.** `test_system_prompt_is_a_conversational_copilot_not_a_bullet_capped_parser`
   built cases with `uuid4()` and asserted the text "2-4" was absent; a UUID contains "2-4" about 6% of the time. It
   failed once during a commit, passed on every rerun, and was logged as "unidentified flaky test" until a reviewer
   traced it. Cost: a failed commit, three reruns and a reviewer cycle.
2. **A prompt-version bump touches many files nobody listed.** Moving the default to `concierge/v7` broke two unit tests
   that pinned `concierge/v6`, one integration test, `docs/dashboard-api.md` (via the doc-sync test) and a test that
   compared the stored plan to a literal dict. Found by running the suite, one gate at a time.
3. **A new argument broke a test spy and the turn swallowed the error.** `_outcome` gained a `research` parameter; an
   integration spy with a fixed signature raised `TypeError`, `run_turn` caught it as a generic failure, and the symptom
   was `seen == []` three layers away from the cause.
4. **The golden-set eval aborts the whole run when any one case crashes.** Three `ReadTimeout`s from Gemini threw away
   a 10-minute run; the rerun was needed to get any numbers.
5. **Baseline debt arrived with the merge.** Ruff, format and mypy were red on the merged tree and blocked the first
   commit; a slice went to clearing a backlog that was not ours.
6. **CI covers less than the repo contains.** `frontend/` had no CI job (and 87 ESLint errors nobody saw), there was no
   single required check, and no static analysis beyond ruff and gitleaks.

## Knowledge captured
- Test determinism and "prove the test can fail" rules -> `docs/dev-pipeline.md` (Test rules).
- Prompt-bump checklist (every place that pins a version) -> `.claude/skills/new-prompt-version/SKILL.md`.
- Security policy and the unauthenticated legacy routers -> `docs/standards/security.md` (Known gaps) and the new
  `estateos-security` agent, mandatory in G3 for API/sender/channels/LLM/auth changes.
- This retro loop itself -> `/retro` skill, `reports/`, CLAUDE.md "Self-improvement loop" and "Quality gates".
- CI: frontend typecheck and build, single required check `ci-success`, CodeQL and dependency-review behind
  `GHAS_ENABLED` (`.github/workflows/`).

## Follow-ups
- Make the eval harness retry or skip a crashed case instead of aborting (`evals/common.py`), and report the count.
- Clear the 87 frontend ESLint errors, then drop `continue-on-error` from the advisory lint step in `ci.yml`.
- Decide the 5 stale mock-data integration tests (seed their own rows, or change what they assert); until then
  `ci-success` is red on `main` by design.
- Run `estateos-security` on `app/api` and fix the legacy routers' missing principal before a second tenant.
- Enable GitHub Advanced Security, set the `GHAS_ENABLED` variable, and make `ci-success` the required check.
