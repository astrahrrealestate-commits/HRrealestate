# DECISIONS

Decisions made during the autoship setup and run. Newest last. `user` = decided by the user; `auto` = taken by the
agent and open to reversal.

## Setup session, 2026-11-03

1. **user** - Push policy: when every gate is green, fast-forward local main to the integration branch and
   `git push origin main`. Gate not met -> push the integration branch to `wip/autoship-<ts>`. Push to main rejected
   -> push the integration branch and report that a PR is needed.
2. **user** - Dependabot branches: `git merge --no-commit`, run `make check`, commit if green, else `git merge --abort`
   and log.
3. **user** - BRIXX: build the M3 import now, despite the build-plan "deferred" note. Tests use redacted recorded
   fixtures, never live BRIXX calls.
4. **user** - Also merge every open PR. Closed PRs are not merged.
5. **user** - `BRIXXonline_API_Documentation_hrrealestate_EN.pdf` stays in the repo as is, although page 3 holds a live
   BRIXX "HR Dashboard" access token (IP-whitelisted, expiry about 2036, already on origin since 70b7a6f). The release
   secret scan treats exactly this file (blob `f932f4fa475db0f63c8d81ca7d26f0eae44fb9d1`) as known; the token anywhere
   else blocks release. Rotating the token in BRIXXonline is still advisable.
6. **user** - Removed the pre-commit hooks installed in this Windows clone (it had none before): pre-commit cannot set
   up gitleaks here (Go download returns HTTP 403) and its mypy/unit hooks fail on Windows-only issues. G1 runs
   manually and is quoted in each merge commit. Reinstall with `make setup` on Linux/WSL.
7. **auto** - Merge order: origin/experiment-superagent-ui before origin/main. It already contained local main (minus 2
   merge commits) and origin/main (minus 2 merge commits), with the migration chain renumbered 0019..0029.
8. **auto** - Migrations: kept experiment's renumbered single chain. Local-main 0022_readonly_analytics,
   0023_message_chunks and 0024_agent_conversation_threads are superseded by 0023/0024/0025. A dev DB migrated on old
   local main must be recreated.
9. **auto** - Not merged: `wip/brixx-uncommitted-snapshot` (its README says "Not reviewed; do not merge"; it does not
   apply on HEAD).
10. **auto** - Union-merged independent constant/function additions (workflow_names.py, registry.py, queues.py) from
    the index blobs; CRLF working copies make `git merge-file` treat every line as changed.
11. **open, user** - `app/llm/prompts/v5/concierge.md` was edited after publication (PR #15, +2 maintenance
    `open_view` lines; breaks invariant 9). The runtime uses v6, which already carries that guidance
    (v6/concierge.md:53 and :59), so no v7 is needed. Session estateos-69 relayed that the user chose to restore v5;
    restoring it rewrites a published prompt past the edit guard, so it waits for the user's direct confirmation.
    A test pins the edit until then.
12. **auto** - Build order: build-plan's `Order:` line with M3 inserted after M2, other areas after their
    dependencies, M8 last. At most 4 builders per wave.
13. **auto** - The edit guard matches repo-relative paths, so it does not protect files under `.claude/worktrees/`.
    build.md adds a mechanical check (migrations/prompts/fixtures only added, no skip/xfail) on every builder branch.
14. **auto** - Integration tests can run without Docker: `ESTATEOS_TEST_PG_ADMIN_URL` (opt-in, unset by default) makes
    the session fixture create and drop a throwaway database on an existing Postgres 16 + pgvector server instead of
    a testcontainer. On this machine that server is pgserver (PyPI; Postgres 16.2, pgvector 0.6.2; the migrations only
    need `vector(n)` + HNSW). testcontainers stays the default and the CI path.
15. **auto** - frontend/package-lock.json was out of sync with package.json (`npm ci`: Missing @emnapi/runtime,
    @emnapi/core); regenerated with `npm install --package-lock-only` (adds the WASM runtime entries, drops stale
    `peer` flags, no version changes).

## Environment (Windows dev machine, 2026-11-03)

- No admin rights: WSL, Docker Desktop and Hyper-V need IT. Without Docker, `make check` (testcontainers),
  `make up/smoke/sim-demo` cannot run.
- No GNU make (SourceForge and repo.msys2.org blocked); the Makefile's commands are run directly.
- python3 3.12.14 (uv `--default`), Node 24.19.0 / npm 11.17.0 (PyPI `nodejs-wheel`), Git Bash via
  `CLAUDE_CODE_GIT_BASH_PATH`; `~/.local/bin` and Git `bin` are first on the user PATH.
- Windows-only test failures (not code bugs on Linux): 0600 permissions and symlinks (gmail_consent, gmail push,
  storage and mailbox contracts), CRLF prompt text (fixed in ec61950 via .gitattributes), `fcntl` in `app/channels/gmail/fake.py`
  (mypy, fixed in 310fbc7), time-bounded quote stripping, worker SIGTERM (TerminateProcess exits 1).
