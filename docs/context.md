# Project context (auto)

Generated: 2026-10-14T11:31:09.978Z

## Detected stack

- Python
- GitHub Actions

## Git

- Branch: `m4-agents`
- HEAD: `60e2afb`

## Recent commits

- `60e2afb` fix(docs): guardrail limit notes, plan deviation, progress status _(Aditya Jain, 2026-10-14)_
- `8e227d6` fix(pipeline): dotted times in output guard, budget-blocked messages and documents wait instead of being dropped, scanner escapes and false positive _(Aditya Jain, 2026-10-14)_
- `860acab` docs: agent guardrail settings and progress _(Aditya Jain, 2026-10-14)_
- `30dc95e` test(evals): owner Q&A scope golden set _(Aditya Jain, 2026-10-14)_
- `57ae115` fix(pipeline): do not treat numeric dates as phone numbers in the draft guard _(Aditya Jain, 2026-10-14)_
- `406a8a1` feat(pipeline): flag drafts that introduce unverified links, accounts or phone numbers _(Aditya Jain, 2026-10-14)_
- `d3baa8b` feat(pipeline): deterministic injection scan sets the suspicious flag _(Aditya Jain, 2026-10-14)_
- `38a44dc` feat(owner-qa): scope-limited answers (owner_qa/v2), input screening, limit reply _(Aditya Jain, 2026-10-14)_
- `c98c7f9` feat(pipeline): leave messages pending and alert once a day when the LLM budget is spent _(Aditya Jain, 2026-10-14)_
- `8526ad1` feat(llm): per-company budget and call caps checked in run_agent (disabled by default) _(Aditya Jain, 2026-10-14)_
- `a3b559c` docs(plan): close unterminated code fence in task 1 _(Aditya Jain, 2026-10-14)_
- `2106dc6` docs(plan): agent guardrails implementation plan _(Aditya Jain, 2026-10-12)_
- `b5771be` docs(spec): agent guardrails design (scope, cost, injection) _(Aditya Jain, 2026-10-12)_
- `6fdb0ff` fix(digest): include spam and non-reply messages in ignored count and dispatch when filtered items exist _(Aditya Jain, 2026-10-09)_
- `03d5bd4` test(chat): verify cardsV2 payload is delivered directly without text stringification _(Aditya Jain, 2026-10-09)_
- `469d44e` fix(digest): ensure exact case drafts are created and linked in Gmail threads _(Aditya Jain, 2026-10-09)_
- `858fe71` fix(sender): instantiate GoogleChatClient when google_chat_provider is google _(Aditya Jain, 2026-10-09)_
- `248f23a` feat(chat): support Google Chat cardsV2 digest and webhook delivery _(Aditya Jain, 2026-10-09)_
- `0df0948` fix(digest): redesign morning email for executive readability, KPI bar, and collapsible drafts _(Aditya Jain, 2026-10-09)_
- `0a90b48` feat(owner): morning email digest and Google Chat bot alongside WhatsApp _(Aditya Jain, 2026-10-09)_

## Inferred recent decisions

- `60e2afb` fix(docs): guardrail limit notes, plan deviation, progress status
- `8e227d6` fix(pipeline): dotted times in output guard, budget-blocked messages and documents wait instead of being dropped, scanner escapes and false positive
- `57ae115` fix(pipeline): do not treat numeric dates as phone numbers in the draft guard
- `406a8a1` feat(pipeline): flag drafts that introduce unverified links, accounts or phone numbers
- `d3baa8b` feat(pipeline): deterministic injection scan sets the suspicious flag
- `38a44dc` feat(owner-qa): scope-limited answers (owner_qa/v2), input screening, limit reply
- `c98c7f9` feat(pipeline): leave messages pending and alert once a day when the LLM budget is spent
- `8526ad1` feat(llm): per-company budget and call caps checked in run_agent (disabled by default)
- `6fdb0ff` fix(digest): include spam and non-reply messages in ignored count and dispatch when filtered items exist
- `469d44e` fix(digest): ensure exact case drafts are created and linked in Gmail threads
- `858fe71` fix(sender): instantiate GoogleChatClient when google_chat_provider is google
- `248f23a` feat(chat): support Google Chat cardsV2 digest and webhook delivery
- `0df0948` fix(digest): redesign morning email for executive readability, KPI bar, and collapsible drafts
- `0a90b48` feat(owner): morning email digest and Google Chat bot alongside WhatsApp

## Hotspots

- 27x — `docs/PROGRESS.md`
- 17x — `pyproject.toml`
- 13x — `app/workflows/runtime.py`
- 12x — `app/core/settings.py`
- 12x — `Makefile`
- 11x — `.env.example`
- 11x — `tests/integration/conftest.py`
- 10x — `app/pipeline/understand.py`
- 10x — `app/llm/fakes.py`
- 9x — `tests/integration/test_pipeline_understand.py`

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
.hypothesis/constants/10071e043e03df79
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
.hypothesis/constants/1698903551872c03
.hypothesis/constants/169bc0d237350095
.hypothesis/constants/169e9c7b4e354eb3
.hypothesis/constants/16d1427514f4f582
.hypothesis/constants/18ac05979d68b886
.hypothesis/constants/18cbaebcf558e677
.hypothesis/constants/18e8e4f038c394a2
.hypothesis/constants/19a164300f00d55a
.hypothesis/constants/1a8ea749b1a2d2be
.hypothesis/constants/1ad6c6e183522539
.hypothesis/constants/1b8f41e38f01284b
.hypothesis/constants/1be411ee2443de67
.hypothesis/constants/1c196534129813c5
.hypothesis/constants/1c72227e927f1610
.hypothesis/constants/1ca62d6cef2fe2d1
.hypothesis/constants/1dc1ab6c5c65cc09
.hypothesis/constants/1e2dfba909fef86b
.hypothesis/constants/1e566dbb32834f38
.hypothesis/constants/1e5d0a2f24149f22
.hypothesis/constants/1f1e7e2e14fc52a5
.hypothesis/constants/1f8e5d0de39657df
.hypothesis/constants/1fbff929102c20ef
.hypothesis/constants/1fc5bf9ad31f56a9
.hypothesis/constants/20827ccd9750d3d3
.hypothesis/constants/20e0467fb85d3346
.hypothesis/constants/2118d12bbacf255c
.hypothesis/constants/2142174f111588ae
.hypothesis/constants/2259aef991d03b0b
.hypothesis/constants/227369e31e6d5520
.hypothesis/constants/2449b03f5e30d950
.hypothesis/constants/24fc6d42a8d0ae99
.hypothesis/constants/2565d3ad32c02882
.hypothesis/constants/256dc7b3680fbc52
.hypothesis/constants/25f5116d3990976a
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
.hypothesis/constants/2de7f021151d81a2
.hypothesis/constants/2e1a5d6cb47b7b0d
.hypothesis/constants/30828794d1b5b326
.hypothesis/constants/30a2c2f0b812185b
.hypothesis/constants/30f0df4c8e4ac9b7
.hypothesis/constants/316f8965a07ce7a7
.hypothesis/constants/31d86fe1ccb0bf54
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
.hypothesis/constants/369e69e84b56d853
.hypothesis/constants/371ba148863ae86c
.hypothesis/constants/3760c1493ed2ad17
.hypothesis/constants/38539e4c250205c3
.hypothesis/constants/387647b2c16939c9
.hypothesis/constants/38fd7109a7f04c74
.hypothesis/constants/39190734e43752be
.hypothesis/constants/39f2cead6d3e8c8a
.hypothesis/constants/39fd3165f506a35f
.hypothesis/constants/3a89b708b9e9eca9
.hypothesis/constants/3afd2908bf8e528c
.hypothesis/constants/3b03fc9925e00a3b
.hypothesis/constants/3b459f5069ce7e07
.hypothesis/constants/3b45b580f92c2113
.hypothesis/constants/3c65ec9dbb23823e
.hypothesis/constants/3cbff9b7334d2c2f
.hypothesis/constants/3d5a941ad5e31542
.hypothesis/constants/3dac131e55975f7b
.hypothesis/constants/3f17d84de0526a5c
.hypothesis/constants/3f1c2a137853b24a
.hypothesis/constants/3fb0d15bbf84f55e
.hypothesis/constants/3fc370c37685a4a1
.hypothesis/constants/3ff3ab4b0eb9f7dd
.hypothesis/constants/4043691dede377e6
.hypothesis/constants/40cff6d3e2abb94f
.hypothesis/constants/4108ca7672165946
.hypothesis/constants/42702cec73c800b8
.hypothesis/constants/43eeae193eccbf10
.hypothesis/constants/455dbd92e746d450
.hypothesis/constants/45bb751a6e99f27f
.hypothesis/constants/460c09199eeca90e
.hypothesis/constants/466260addd5e64e2
.hypothesis/constants/46b274c825592c24
.hypothesis/constants/46e70417a00f1c79
.hypothesis/constants/47c1fc7ba7a99ebc
.hypothesis/constants/48387fed914b1176
.hypothesis/constants/484cb543d173ff60
.hypothesis/constants/48b4f5c686850b10
.hypothesis/constants/48f56763c748c24a
.hypothesis/constants/496653ba641686f1
.hypothesis/constants/49bcd9e6008de088
.hypothesis/constants/4a2b7272e71e06fc
.hypothesis/constants/4b239c936942f6ea
.hypothesis/constants/4d90c52c5544cc57
.hypothesis/constants/4e33c63462822c11
.hypothesis/constants/4e50f1bf4b81f01b
.hypothesis/constants/4eeb2e2f9a3bc02e
.hypothesis/constants/4f4afa560a4db830
.hypothesis/constants/4f7d55c959d4da6e
.hypothesis/constants/4fb5c4122eaea8c0
.hypothesis/constants/50f9f0b170c78cfd
.hypothesis/constants/519981ca86aa2bdb
.hypothesis/constants/5204b68f1a7b17fd
.hypothesis/constants/5216dda74d56d897
.hypothesis/constants/536c9680579b3988
.hypothesis/constants/54c475215b319d99
.hypothesis/constants/559cb233a21d422c
.hypothesis/constants/56f456e675932dd6
.hypothesis/constants/58141bff2f379eac
.hypothesis/constants/585065cb3b391e00
.hypothesis/constants/5881dbda61a7858c
.hypothesis/constants/590f74b838c1fb58
.hypothesis/constants/5a28f170ae8910b6
```
