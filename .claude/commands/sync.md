---
description: autoship phase 1 - merge every branch and open PR into the integration branch. Only run from /autoship.
---

# sync

Guard: run only when /autoship selected this phase (BUILD_STATUS.md has no `- sync: done` line). Otherwise stop.

1. `git fetch --all --prune` and `git fetch origin '+refs/pull/*/head:refs/remotes/origin/pr/*'`.
2. If BUILD_STATUS.md has no `backup_tag:`, run `git tag backup/pre-merge-<UTC yyyyMMdd-HHmm> main` and record the tag
   and `integration_branch:` (the current `autoship/*` branch) in BUILD_STATUS.md.
3. Stray work: `git status --porcelain`. Commit tracked changes and intended new files on the integration branch with
   explicit paths. Never `git add -A` or `git add .`. Never add `realestateos/` (a separate nested clone).
4. Candidates, ignoring `realestateos/`:
   - `origin/main` first.
   - Every local and remote branch with commits not in HEAD: `git branch -a --no-merged HEAD`.
   - Open PRs: `gh pr list --state open --json number,headRefName,isCrossRepository,createdAt` when `gh` is
     authenticated. Otherwise treat PR refs whose head equals a live branch tip as open, and refs whose branch is gone
     as closed. Closed PRs are never merged. Read-only `gh` only: never `gh pr merge/close/comment`.
   Order the rest oldest first by their oldest unique commit. Skip a branch whose README or commit says "do not
   merge" and log it. When one branch already contains another's work (`git merge-base --is-ancestor`, `git cherry`),
   merge the superset first and log why.
5. Per candidate: `git merge --no-ff --no-commit <ref>`.
   - Dependabot (`dependabot/*`): run `make check`. Green -> commit. Red or unable to run -> `git merge --abort`, log
     the branch and the failing line in DECISIONS.md.
   - Others: resolve conflicts keeping both sides' intent. Migrations: one linear Alembic chain. Never edit a
     committed migration; add a merge or renumber only files not yet on origin, and log it. Use `git merge-file`
     with base/ours/theirs from the index (`git show :1:`/`:2:`/`:3:`), never from CRLF working copies. Log the
     non-obvious resolutions in DECISIONS.md.
   - Then `make quick` (via test-runner when noisy). Fix breakage before the next merge. Commit
     `chore(merge): <ref> into the autoship integration` with the quoted G1 lines in the body.
6. Gate: `git branch -a --no-merged HEAD` lists only branches aborted or skipped on purpose (each logged), and
   `make check` is green. Quote both.
