---
description: autoship phase 3 - one wave of builder agents over Partial/Missing areas. Optional argument - area filter. Only run from /autoship.
argument-hint: "[area]"
---

# build (one wave per pass)

Guard: run only when /autoship selected this phase. Otherwise stop. Area filter: `$ARGUMENTS` (empty = all).

## Plan the waves
- Group Partial and Missing rows of BUILD_STATUS.md into areas. Order follows build-plan.md's `Order:` line with M3
  inserted after M2 (user decision: build the BRIXX import now), then areas not on that line after their
  dependencies, M8 hardening last. Record the area list with `depends_on` in BUILD_STATUS.md `## Areas`.
- A wave is every area whose dependencies are Done, at most 4 builders (each runs testcontainers Postgres; more
  starve Docker). Builders never run `make up`, `make smoke` or `make sim-demo` (fixed ports); verify does.

## Launch
- For each area in the wave: `git worktree add .claude/worktrees/<area> -b <branch> <integration-branch>` (branch
  `m<n>-<slug>` or `feat/<area>`), then launch a `builder` agent with: the area id, its rows verbatim, the
  integration branch, the worktree path and branch. Launch the whole wave in ONE message.
- Mark each area `building (agent <id>, branch <b>)` in BUILD_STATUS.md, commit the state, end the turn.
- A later pass that finds an area `building` whose agent is no longer running (crash, resume, new session): relaunch
  a builder on the existing branch and worktree with "continue from `git log <integration>..HEAD`".

## When a builder returns
1. Mechanical gate (the edit guard does not cover worktrees): `git diff --name-status <integration>...<branch> --
   backend/app/db/alembic/versions backend/app/llm/prompts backend/tests/fixtures/recorded` must show only `A`; no `pytest.mark.skip/xfail`
   added (`git diff <integration>...<branch> -- tests | grep -E '^\+.*(mark\.(skip|xfail)|pytest\.(skip|xfail)\()'`
   empty); no send credentials or `app.channels.*.outbound` outside `backend/app/sender/` (import-linter covers it in
   `make quick`). A failure counts as a blocking finding.
2. Run `estateos-reviewer` on the branch diff (tell it: review `git diff <integration>...<branch>` from the worktree).
3. Blocking findings -> SendMessage them to the same builder (load SendMessage via ToolSearch if deferred). Repeat.
   Three rounds failing the same way -> launch a fresh builder with the findings, log it.
4. Clean -> in the main checkout on the integration branch: `git merge --no-ff <branch>`, then `make quick` and
   `make check` via test-runner. Red -> fix or send back before the next merge. One area at a time.
5. Mark its rows Done with evidence (code path, test path, quoted result line), remove the worktree
   (`git worktree remove .claude/worktrees/<area>`), keep the branch.
6. Rows blocked by something external stay Partial with the blocker written in the row.

## Gate
Every row is Done, Deferred, or Partial with a written external blocker. Quote the per-status counts.
