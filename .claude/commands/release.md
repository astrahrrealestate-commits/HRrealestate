---
description: autoship phase 5 - sensitive-content check, docs, FINAL_REPORT.md, fast-forward and push main (or the fallback). Only run from /autoship.
---

# release

Guard: run only when /autoship selected this phase, or as the fallback (pass cap, verify cap). Otherwise stop.

## 1. Nothing sensitive since the backup tag
- `git diff --name-status <backup_tag>..HEAD` and inspect the list: no `.env*` (except `.env.example`), keys,
  `*.pem`, service accounts, token files, real tenant data. Do not grep for `.env` with a shell pattern (the bash
  guard blocks it); read the list.
- Secrets in content: use the Grep tool over the changed files for `sk-`, `EAA[A-Za-z0-9]{60}`, `AIza`,
  `PRIVATE KEY`, `sk-lf-`, `AKIA`, JWTs `eyJ[A-Za-z0-9_-]{10,}\.eyJ`. Exception (DECISIONS.md): the BRIXX PDF at the
  repo root, blob `f932f4fa475db0f63c8d81ca7d26f0eae44fb9d1`. Its token anywhere else, or the PDF changed, blocks.
- Size: `git diff --name-only --diff-filter=AM <backup_tag>..HEAD -z | xargs -0 -r du -k | awk '$1 > 5120'` is empty.

## 2. Docs
Update README.md, docs/PROGRESS.md and the docs for each new feature (dashboard-api.md for routes, specs/ADRs).

## 3. FINAL_REPORT.md
Backup tag; branches and PRs merged, aborted or skipped (why); features built; test counts and result lines; the
decisions from DECISIONS.md; what is incomplete and why; the final commit hash. Commit it on the integration branch.

## 4. Push
- `git fetch origin`. If origin/main is not an ancestor of HEAD: merge it, log `release: origin moved`, and run one
  more verify iteration (next pass) before returning here.
- Gate passed: `git switch main`, `git merge --ff-only <integration_branch>`, `git push origin main`, then
  `git rev-parse main origin/main` must print the same hash twice (quote it). Never force. Never commit on main.
- Push rejected (protection, non-fast-forward): `git switch <integration_branch>`, `git push origin
  <integration_branch>`, and write in FINAL_REPORT.md that a PR is needed.
- **Fallback** (gate not met, pass cap or verify cap): `git push origin <integration_branch>:wip/autoship-<UTC ts>`.
  Never push main. Say so in FINAL_REPORT.md.

## 5. Done
Create `.claude/DONE` (gitignored) so the next pass ends the loop.
