---
name: ship
description: Run the EstateOS development pipeline for one task — RED → GREEN → REFACTOR → G1 quick → G2 full (if needed) → G3 review → commit. Use when implementing any plan task, feature, or bug fix in EstateOS, or when the user says "ship", "implement task N", "build this".
---

# /ship — one task through the pipeline

Pipeline reference: `docs/dev-pipeline.md`. Never skip a gate; never claim a gate passed without its result line.

## 0. Frame (30 seconds)
- Task text, acceptance command, and the layer(s) touched. If no approved spec/plan covers this and it is not a
  bounded fix, stop and run `superpowers:brainstorming`.
- Look up the layer's row in "Test strategy per layer". That decides the test type and tools.
- Prefer an existing library over new code (`docs/tech-stack.md`). If you are about to write >50 lines of generic
  plumbing (retries, parsing, scheduling, HTTP clients), stop: find the tool or ask.

## 1. RED
Write the test. Run only it: `uv run pytest <path>::<name> -q`. Quote the failure line; it must fail for the
expected reason (not ImportError from a typo).

## 2. GREEN
Minimum code. Rerun the single test. Quote the pass line.

## 3. REFACTOR
Names, duplication, function size (<40 lines), types. The post-edit hook formats; rerun the test.

## 4. G1 — `make quick`
Must be green. On red, use `superpowers:systematic-debugging`; fix the root cause, never the test.

## 5. G2 — `make check`
Required if you touched `db/`, `workflows/`, `channels/`, `sender/`, `api/`, or migrations. Long output → delegate
to the `test-runner` agent.

## 6. G3 — review
Diff > ~50 lines or touches invariants (sender, rules, workflows, tenancy, prompts): dispatch `estateos-reviewer`.
Fix every critical/high. Re-run G1 (and G2 if applicable) after fixes.

## 7. Commit
`git add <specific paths>`; message `type(scope): summary` (`feat(m2): dedupe whatsapp webhooks`). Pre-commit runs.
Tick the PROGRESS.md item with the evidence line.

## Report
`task · tests added · G1 result · G2 result|n/a · reviewer verdict|n/a · commit sha`
