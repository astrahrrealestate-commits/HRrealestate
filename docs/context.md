# Project context (auto)

Generated: 2026-10-09T05:54:23.451Z

## Detected stack

- Python
- GitHub Actions

## Git

- Branch: `m4-agents`
- HEAD: `e2e46df`

## Recent commits

- `e2e46df` feat(dev): API boots with a real mailbox and no Pub/Sub (pull-only, pushes 401); tests force fake providers whatever .env says _(Aditya Jain, 2026-10-09)_
- `dcc9cde` fix(gmail): draft idempotency by X-EstateOS-Key header (Gmail rewrites a draft's Message-ID); live draft check _(Aditya Jain, 2026-10-09)_
- `3a86a90` feat(dev): test a real Gmail mailbox locally - make gmail-pull / pending / approve; compose mounts token files _(Aditya Jain, 2026-10-09)_
- `7304a3c` test: force LLM_MODEL=fake for every test run except --live (a developer .env may select Gemini) _(Aditya Jain, 2026-10-08)_
- `65117e2` fix(dev): sim-demo accepts a real classifier filing the photo directly (review is the fake's outcome) _(Aditya Jain, 2026-10-08)_
- `b0bd7de` feat(llm): Gemini support for testing, evals that survive real-model quotas, photo-only messages never dropped as spam _(Aditya Jain, 2026-10-08)_
- `6a111e8` docs(progress): review rounds, G1/G2/G5 evidence, go-live readiness checklist _(Aditya Jain, 2026-10-08)_
- `9bd88d2` fix: book the next briefings before sending; gmail fixtures carry their mailbox like real ingest _(Aditya Jain, 2026-10-08)_
- `e5ee22e` feat(go-live): Drive token via make gmail-consent drive=1, live checks for Drive and the real LLM, go-live guide _(Aditya Jain, 2026-10-08)_
- `9fee0c9` fix(sender): draft gmail replies in the thread's own mailbox; retry review cards; escape <mode> _(Aditya Jain, 2026-10-08)_
- `1814361` fix(review-2): atomic send claim, stranded-pending sweep, lease renewal, refs-only task commands, scoping _(Aditya Jain, 2026-10-08)_
- `e2d2369` feat(tests): add polyfactory model factories, cache gmail client per thread, update progress _(Aditya Jain, 2026-10-08)_
- `c458a9f` feat(dev): make gmail-consent CLI for minimal-scope OAuth token generation _(Aditya Jain, 2026-10-08)_
- `3538b34` test: stop DBOS and let in-flight workflows finish before purging a committed company (flaky G2 teardown race) _(Aditya Jain, 2026-10-08)_
- `1bba1e2` feat(agents): harden prompt data blocks and make the fakes realistic _(Aditya Jain, 2026-10-08)_
- `87c90ee` chore(m8): schedule DBOS retention; integration tests export the test DATABASE_URL (no dependency on a dev .env) _(Aditya Jain, 2026-10-08)_
- `1caedbc` feat(db): migration 0006 - review indexes, one open wait per case without a party _(Aditya Jain, 2026-10-08)_
- `0865811` feat(dev): sim-demo document filing scenario (#9) _(Aditya Jain, 2026-10-08)_
- `6429f3c` feat(m8): daily DBOS system-table retention (30 days) with DBOS's garbage collector _(Aditya Jain, 2026-10-08)_
- `1a252ec` feat(m9): wire document filing; fix(review): owner-channel robustness, pipeline failure handling, chase/edit/task-ref fixes _(Aditya Jain, 2026-10-08)_

## Inferred recent decisions

- `e2e46df` feat(dev): API boots with a real mailbox and no Pub/Sub (pull-only, pushes 401); tests force fake providers whatever .env says
- `dcc9cde` fix(gmail): draft idempotency by X-EstateOS-Key header (Gmail rewrites a draft's Message-ID); live draft check
- `3a86a90` feat(dev): test a real Gmail mailbox locally - make gmail-pull / pending / approve; compose mounts token files
- `65117e2` fix(dev): sim-demo accepts a real classifier filing the photo directly (review is the fake's outcome)
- `b0bd7de` feat(llm): Gemini support for testing, evals that survive real-model quotas, photo-only messages never dropped as spam
- `9bd88d2` fix: book the next briefings before sending; gmail fixtures carry their mailbox like real ingest
- `e5ee22e` feat(go-live): Drive token via make gmail-consent drive=1, live checks for Drive and the real LLM, go-live guide
- `9fee0c9` fix(sender): draft gmail replies in the thread's own mailbox; retry review cards; escape <mode>
- `1814361` fix(review-2): atomic send claim, stranded-pending sweep, lease renewal, refs-only task commands, scoping
- `e2d2369` feat(tests): add polyfactory model factories, cache gmail client per thread, update progress
- `c458a9f` feat(dev): make gmail-consent CLI for minimal-scope OAuth token generation
- `1bba1e2` feat(agents): harden prompt data blocks and make the fakes realistic
- `1caedbc` feat(db): migration 0006 - review indexes, one open wait per case without a party
- `0865811` feat(dev): sim-demo document filing scenario (#9)
- `6429f3c` feat(m8): daily DBOS system-table retention (30 days) with DBOS's garbage collector
- `1a252ec` feat(m9): wire document filing; fix(review): owner-channel robustness, pipeline failure handling, chase/edit/task-ref fixes

## Hotspots

- 25x — `docs/PROGRESS.md`
- 16x — `pyproject.toml`
- 13x — `app/workflows/runtime.py`
- 11x — `tests/integration/conftest.py`
- 10x — `Makefile`
- 10x — `app/core/settings.py`
- 9x — `.env.example`
- 8x — `app/llm/fakes.py`
- 8x — `app/core/errors.py`
- 7x — `.claude/hooks/tests/test_guards.py`

## Top-level tree

```
.DS_Store
.claude/
.claude/.cache/
.claude/.cache/req.txt
.claude/.cache/stop_gate_green
.claude/agents/
.claude/agents/estateos-implementer.md
.claude/agents/estateos-reviewer.md
.claude/agents/test-runner.md
.claude/hooks/
.claude/hooks/__pycache__/
.claude/hooks/_common.py
.claude/hooks/guard_bash.py
.claude/hooks/guard_edit.py
.claude/hooks/post_edit.py
.claude/hooks/session_start.py
.claude/hooks/stop_gate.py
.claude/hooks/tests/
.claude/settings.json
.claude/skills/
.claude/skills/check/
.claude/skills/milestone/
.claude/skills/new-migration/
.claude/skills/new-prompt-version/
.claude/skills/record-fixture/
.claude/skills/ship/
.claude/worktrees/
.claude/worktrees/agents-phase1/
.coverage
.dockerignore
.env
.env.example
.hypothesis/
.hypothesis/constants/
.hypothesis/constants/0018aac87bd74f1f
.hypothesis/constants/00c306c2503e3401
.hypothesis/constants/020b42d5c9ec5bd3
.hypothesis/constants/025364ce523ac2e3
.hypothesis/constants/0299ab0ecd7b9af7
.hypothesis/constants/02af8e2877328043
.hypothesis/constants/02b19c2985618352
.hypothesis/constants/033bd937e52698ec
.hypothesis/constants/047dddab7d1e2042
.hypothesis/constants/0489319aba8b4266
.hypothesis/constants/05b7f95645c62968
.hypothesis/constants/05f6f9f5ce335b00
.hypothesis/constants/0741646aec08f0a4
.hypothesis/constants/079c977bde882be8
.hypothesis/constants/07a463fdfd5276cc
.hypothesis/constants/08678ced6d7ac7a0
.hypothesis/constants/08dd16c58dfc12eb
.hypothesis/constants/098e7a69d0ca8370
.hypothesis/constants/09c642a734fa75e8
.hypothesis/constants/0a6570335408273a
.hypothesis/constants/0b6a7a1a0067f347
.hypothesis/constants/0c2fc8cfd5a20235
.hypothesis/constants/0c4de379d7ee3d14
.hypothesis/constants/0d9c54784e959eed
.hypothesis/constants/0f39e532d13c7352
.hypothesis/constants/0f653f19c429ef93
.hypothesis/constants/101fbfc29d2d4be9
.hypothesis/constants/1127bbba5fd1bc74
.hypothesis/constants/12af14c4068abbfb
.hypothesis/constants/12ca5a8a7e159b1d
.hypothesis/constants/12fc7ebb940e41f5
.hypothesis/constants/140e1721e6d8af11
.hypothesis/constants/147a7b9b926e2e2f
.hypothesis/constants/14ce81f75dc62efe
.hypothesis/constants/14e86ed128eb8aa4
.hypothesis/constants/1540ebb0e0e9cbbf
.hypothesis/constants/15b46810e63c7047
.hypothesis/constants/169bc0d237350095
.hypothesis/constants/16d1427514f4f582
.hypothesis/constants/18ac05979d68b886
.hypothesis/constants/18cbaebcf558e677
.hypothesis/constants/19a164300f00d55a
.hypothesis/constants/1a8ea749b1a2d2be
.hypothesis/constants/1ad6c6e183522539
.hypothesis/constants/1b8f41e38f01284b
.hypothesis/constants/1be411ee2443de67
.hypothesis/constants/1c196534129813c5
.hypothesis/constants/1dc1ab6c5c65cc09
.hypothesis/constants/1e2dfba909fef86b
.hypothesis/constants/1e566dbb32834f38
.hypothesis/constants/1e5d0a2f24149f22
.hypothesis/constants/1f1e7e2e14fc52a5
.hypothesis/constants/1f8e5d0de39657df
.hypothesis/constants/1fc5bf9ad31f56a9
.hypothesis/constants/20827ccd9750d3d3
.hypothesis/constants/2142174f111588ae
.hypothesis/constants/2259aef991d03b0b
.hypothesis/constants/2449b03f5e30d950
.hypothesis/constants/24fc6d42a8d0ae99
.hypothesis/constants/2565d3ad32c02882
.hypothesis/constants/256dc7b3680fbc52
.hypothesis/constants/27b37a1c3daeaa48
.hypothesis/constants/2914df98f5205757
.hypothesis/constants/2931cb21b8d99daa
.hypothesis/constants/2a0499fe63fb96e2
.hypothesis/constants/2a3271688d9dd912
.hypothesis/constants/2b1db47352a9982b
.hypothesis/constants/2b2386e15fdf8e34
.hypothesis/constants/2b4540f778e84b31
.hypothesis/constants/2b47d0f4908b47a6
.hypothesis/constants/2bc4cf0d30b947d6
.hypothesis/constants/2cfb7ca432f35516
.hypothesis/constants/2d9cb9574e671cf2
.hypothesis/constants/30828794d1b5b326
.hypothesis/constants/30f0df4c8e4ac9b7
.hypothesis/constants/316f8965a07ce7a7
.hypothesis/constants/320ae8283ecddb99
.hypothesis/constants/32125b095f515b6d
.hypothesis/constants/329e4d001c2fced5
.hypothesis/constants/335e97c308af94b4
.hypothesis/constants/337829831d8b0e65
.hypothesis/constants/338ab226d18368c9
.hypothesis/constants/346fa2abedd0898e
.hypothesis/constants/34af8208fdfe2c92
.hypothesis/constants/353b8d87598fb3ca
.hypothesis/constants/35b815d7b2761471
.hypothesis/constants/35beee241fbcc05f
.hypothesis/constants/368d6942fda097cd
.hypothesis/constants/3760c1493ed2ad17
.hypothesis/constants/38539e4c250205c3
.hypothesis/constants/38fd7109a7f04c74
.hypothesis/constants/39190734e43752be
.hypothesis/constants/39f2cead6d3e8c8a
.hypothesis/constants/3a89b708b9e9eca9
.hypothesis/constants/3afd2908bf8e528c
.hypothesis/constants/3b03fc9925e00a3b
.hypothesis/constants/3b45b580f92c2113
.hypothesis/constants/3c65ec9dbb23823e
.hypothesis/constants/3cbff9b7334d2c2f
.hypothesis/constants/3d5a941ad5e31542
.hypothesis/constants/3dac131e55975f7b
.hypothesis/constants/3f17d84de0526a5c
.hypothesis/constants/3f1c2a137853b24a
.hypothesis/constants/3fb0d15bbf84f55e
.hypothesis/constants/3fc370c37685a4a1
.hypothesis/constants/4043691dede377e6
.hypothesis/constants/40cff6d3e2abb94f
.hypothesis/constants/42702cec73c800b8
.hypothesis/constants/43eeae193eccbf10
.hypothesis/constants/45bb751a6e99f27f
.hypothesis/constants/460c09199eeca90e
.hypothesis/constants/466260addd5e64e2
.hypothesis/constants/46b274c825592c24
.hypothesis/constants/46e70417a00f1c79
.hypothesis/constants/47c1fc7ba7a99ebc
.hypothesis/constants/484cb543d173ff60
.hypothesis/constants/48b4f5c686850b10
.hypothesis/constants/48f56763c748c24a
.hypothesis/constants/496653ba641686f1
.hypothesis/constants/49bcd9e6008de088
.hypothesis/constants/4a2b7272e71e06fc
.hypothesis/constants/4b239c936942f6ea
.hypothesis/constants/4d90c52c5544cc57
.hypothesis/constants/4e33c63462822c11
.hypothesis/constants/4eeb2e2f9a3bc02e
.hypothesis/constants/4f4afa560a4db830
.hypothesis/constants/4fb5c4122eaea8c0
.hypothesis/constants/50f9f0b170c78cfd
.hypothesis/constants/5204b68f1a7b17fd
.hypothesis/constants/5216dda74d56d897
.hypothesis/constants/536c9680579b3988
.hypothesis/constants/54c475215b319d99
.hypothesis/constants/559cb233a21d422c
.hypothesis/constants/56f456e675932dd6
.hypothesis/constants/58141bff2f379eac
.hypothesis/constants/585065cb3b391e00
.hypothesis/constants/5881dbda61a7858c
.hypothesis/constants/5a28f170ae8910b6
.hypothesis/constants/5aa92ffb1be1fe7c
.hypothesis/constants/5af250332137bddd
.hypothesis/constants/5b7c4bcef5ba07bb
.hypothesis/constants/5bb4d68507302e60
.hypothesis/constants/5c705c683cafa16e
.hypothesis/constants/5ca12d8c79d06ccb
.hypothesis/constants/5d14572ebdaf16c0
.hypothesis/constants/5d44a715ef4322ac
.hypothesis/constants/5d56267f73695625
.hypothesis/constants/5da60957d1a05469
.hypothesis/constants/5de4b5c0f04a2673
.hypothesis/constants/5df6e6cc077df56f
.hypothesis/constants/5e582f8a34d11afd
.hypothesis/constants/5e9f02be124e9dce
.hypothesis/constants/5f09a20b9557e8c5
.hypothesis/constants/60091fd3e118cb78
.hypothesis/constants/60b2eca6a533ffc6
.hypothesis/constants/60e7a947823edfed
.hypothesis/constants/618f32ff91752790
.hypothesis/constants/626d803d14f0042d
.hypothesis/constants/62957c6e08edbf4a
.hypothesis/constants/62a4facb0d2c0fd1
.hypothesis/constants/631f0a361eefc8e2
.hypothesis/constants/63f39d496b53b712
.hypothesis/constants/649ca6226d930da9
.hypothesis/constants/6540799791f90faf
.hypothesis/constants/6596491270c520cb
.hypothesis/constants/65aa7d30d78cea32
```
