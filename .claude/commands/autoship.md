---
description: One bounded pass of the unattended EstateOS pipeline (sync -> audit -> build -> verify -> release). Run as `/loop /autoship`.
---

# /autoship: one pass

You are the thin orchestrator. Read state, dispatch subagents, merge, decide. Do ONE bounded step, update the state
files, end the turn. The "Autonomy rules" in CLAUDE.md apply. Never ask the user anything.

## 0. Stop or preflight
1. If `.claude/DONE` exists: print the summary section of `FINAL_REPORT.md` and end the loop (under `/loop`, call
   ScheduleWakeup with `stop: true`). Do nothing else.
2. Shell: use the Bash tool for every shell command (the `guard_bash` hook only covers Bash). If this session has no
   Bash tool, log `preflight: no Bash tool (guards would not fire)` and stop as in step 4.
3. Preflight, quoting output: `git --version`, `uv --version`, `make --version`, `python3 --version`,
   `docker info --format '{{.ServerVersion}}'`, `node --version`, `npm --version`.
4. A missing tool: append `- preflight: FAILED <UTC> - <what>` to the phase log, bump `preflight_failures:` in
   BUILD_STATUS.md, change nothing else, end the turn. At 3 consecutive failures, write FINAL_REPORT.md
   ("blocked: preflight", with the exact fix) and create `.claude/DONE`.
5. Setup gate (once): if `.claude/commands/autoship.md` is untracked or modified, run `make harness-test` and
   `make quick`; green -> `git add .claude/agents/builder.md .claude/agents/reviewer.md .claude/commands CLAUDE.md
   .gitignore DECISIONS.md BUILD_STATUS.md` and commit `chore(harness): add autoship pipeline`; red -> fix first.

## 1. State
- Read `BUILD_STATUS.md`, `DECISIONS.md`, `FINAL_REPORT.md`. If BUILD_STATUS.md is missing, create it with
  `passes: 0`, `integration_branch:`, `backup_tag:`, `verify_iterations: 0` and a `## Phase log` section.
- Increment `passes:`. If it is now above 60: run the fallback in `.claude/commands/release.md` and end.
- Confirm you are on the integration branch (`git branch --show-current`); switch to it if not. Never commit on main.

## 2. One phase
Phases in order: **sync -> audit -> build -> verify -> release**. Run the first one without a
`- <phase>: done` line in the phase log: read `.claude/commands/<phase>.md` and follow it.
- build and verify span several passes; record where this pass got to (`- build: wave 2 launched ...`).
- When a phase's gate passes, append `- <phase>: done <UTC> - <evidence: quoted result lines>`.
- A step that fails 3 times the same way: change approach, log it in DECISIONS.md and the phase log, move on.

## 3. Builder notifications
If you were woken by a subagent completion (not a /loop tick), handle it per build.md "When a builder returns"
before anything else, then end the turn.

## 4. End the pass
- Commit state changes on the integration branch: `git add BUILD_STATUS.md DECISIONS.md FINAL_REPORT.md` (whichever
  exist), message `chore(autoship): pass <n> <phase> state`.
- Under `/loop` (dynamic): if builders or test-runners are still running, ScheduleWakeup 1800 s (they re-invoke you
  on completion); otherwise ScheduleWakeup 60 s. Prompt: `/autoship`.
