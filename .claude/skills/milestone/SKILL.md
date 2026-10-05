---
name: milestone
description: Start, track or close an EstateOS milestone (M1–M8). Use when the user says "start M<n>", "next milestone", "where are we", "close M<n>", or "what's left".
---

# /milestone

Source of truth: `docs/PROGRESS.md` (checkboxes) + `docs/build-plan.md` ("Done when" column).

## Start M<n>
1. Read the M<n> row in `docs/build-plan.md` and any existing spec under `docs/superpowers/specs/`.
2. If no spec exists for M<n>: run `superpowers:brainstorming` (architectural path) → spec → user approval.
3. Run `superpowers:writing-plans` → `docs/superpowers/plans/<date>-m<n>-<topic>.md`. Each task: files, failing
   test, acceptance command.
4. Create a branch `m<n>-<slug>` (worktree via `superpowers:using-git-worktrees` if parallel work is running).
5. Copy plan task titles as unchecked items under `## M<n>` in `docs/PROGRESS.md`.
6. Execute with `superpowers:subagent-driven-development` (one `estateos-implementer` per task, review between
   tasks) unless the user chooses inline execution.

## Track
Tick items in `docs/PROGRESS.md` only after `/check` evidence for that item. One line per item, no essays.

## Close M<n>
1. `/check` stack tier green.
2. `estateos-reviewer` verdict `ship`.
3. Every "Done when" clause from build-plan demonstrated — quote the command/output that proves each one.
4. Tick the milestone header, commit `chore(m<n>): close milestone`, then `superpowers:finishing-a-development-branch`.
