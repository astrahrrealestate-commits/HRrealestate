# Project context (auto)

Generated: 2026-10-23T11:17:59.146Z

## Detected stack

- Python
- GitHub Actions

## Git

- Branch: `main`
- HEAD: `e993ad4`

## Recent commits

- `e993ad4` docs: keep the phase 1 agents implementation plan and refresh the generated project context _(Aditya Jain, 2026-10-23)_
- `af426a5` feat(agent): memory and context layers, turn measurement, steerable-draft and page pre-warm follow-ups _(Aditya Jain, 2026-10-23)_
- `ea9d3c9` chore(merge): origin/main (PR #8) into the development line _(Aditya Jain, 2026-10-23)_
- `5cd860e` fix(tests): settle the five long-standing integration failures _(Aditya Jain, 2026-10-23)_
- `2019cb6` docs: server-side freshness for page pre-warm, deferred ledger minors _(Aditya Jain, 2026-10-23)_
- `8a70dde` fix(agent): server-side freshness for warmed page facts (migration 0016) _(Aditya Jain, 2026-10-23)_
- `0d289fc` docs: page pre-warm _(Aditya Jain, 2026-10-23)_
- `6116fba` feat(agent): page pre-warm endpoint and agent_page_state (migration 0015) _(Aditya Jain, 2026-10-23)_
- `cfd5c56` fix(dashboard): lean turn event reads, documented LLM concurrency ceiling _(Aditya Jain, 2026-10-23)_
- `d0fe7cb` fix(agent): reply only beside read steps, amounts allowed in replies (concierge v5) _(Aditya Jain, 2026-10-23)_
- `bc0c780` fix(repo): untrack the .venv symlink and ignore .venv as a file or a directory _(Aditya Jain, 2026-10-23)_
- `dd4c0f8` chore(merge): d-dashboard into m10 (document intelligence + advanced RAG) _(Aditya Jain, 2026-10-23)_
- `7b62deb` fix(rag): review findings on refs, embedder failures and deadline, fact route, reindex and freshness _(Aditya Jain, 2026-10-23)_
- `ce3d20a` feat(rag): evaluation corpus and quality gate, reranker sees chunk headers, make rag-eval _(Aditya Jain, 2026-10-22)_
- `599af28` docs: fast turns _(Aditya Jain, 2026-10-22)_
- `d56efde` feat(agent): per-turn timings and thread index (migration 0012) _(Aditya Jain, 2026-10-22)_
- `803ceca` feat(rag): hybrid search for the library, cheap hybrid excerpts for reply drafts _(Aditya Jain, 2026-10-22)_
- `db95072` feat(workflows): dedicated concierge queue and faster turn polling _(Aditya Jain, 2026-10-22)_
- `50389fa` feat(rag): query planning with HyDE, fact-first route, listwise rerank with relevance floor and neighbour widening _(Aditya Jain, 2026-10-22)_
- `881e8d7` feat(agent): single-call page answers with concierge v3 _(Aditya Jain, 2026-10-22)_

## Inferred recent decisions

- `af426a5` feat(agent): memory and context layers, turn measurement, steerable-draft and page pre-warm follow-ups
- `5cd860e` fix(tests): settle the five long-standing integration failures
- `8a70dde` fix(agent): server-side freshness for warmed page facts (migration 0016)
- `6116fba` feat(agent): page pre-warm endpoint and agent_page_state (migration 0015)
- `cfd5c56` fix(dashboard): lean turn event reads, documented LLM concurrency ceiling
- `d0fe7cb` fix(agent): reply only beside read steps, amounts allowed in replies (concierge v5)
- `bc0c780` fix(repo): untrack the .venv symlink and ignore .venv as a file or a directory
- `7b62deb` fix(rag): review findings on refs, embedder failures and deadline, fact route, reindex and freshness
- `ce3d20a` feat(rag): evaluation corpus and quality gate, reranker sees chunk headers, make rag-eval
- `d56efde` feat(agent): per-turn timings and thread index (migration 0012)
- `803ceca` feat(rag): hybrid search for the library, cheap hybrid excerpts for reply drafts
- `db95072` feat(workflows): dedicated concierge queue and faster turn polling
- `50389fa` feat(rag): query planning with HyDE, fact-first route, listwise rerank with relevance floor and neighbour widening
- `881e8d7` feat(agent): single-call page answers with concierge v3

## Hotspots

- 53x — `docs/PROGRESS.md`
- 22x — `pyproject.toml`
- 21x — `docs/dashboard-api.md`
- 20x — `app/core/settings.py`
- 19x — `Makefile`
- 18x — `app/llm/fakes.py`
- 18x — `.env.example`
- 18x — `app/workflows/runtime.py`
- 17x — `tests/unit/api/__snapshots__/test_openapi_snapshot.ambr`
- 17x — `docs/superpowers/specs/2026-10-15-dashboard-super-agent-design.md`

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
.claude/worktrees/fix-harness-ci/
.coverage
.dockerignore
.env
.env.example
.env.example.bak
.hypothesis/
.hypothesis/constants/
.hypothesis/constants/00157836c030c52b
.hypothesis/constants/0018aac87bd74f1f
.hypothesis/constants/001a01a891e65c6f
.hypothesis/constants/00c306c2503e3401
.hypothesis/constants/00ec57e8486eaf7c
.hypothesis/constants/018e5e84e3516ec0
.hypothesis/constants/020b42d5c9ec5bd3
.hypothesis/constants/025364ce523ac2e3
.hypothesis/constants/0299ab0ecd7b9af7
.hypothesis/constants/02af8e2877328043
.hypothesis/constants/02b19c2985618352
.hypothesis/constants/031c4c1df766fd0b
.hypothesis/constants/031df9505c37006c
.hypothesis/constants/033bd937e52698ec
.hypothesis/constants/03485f319bd03ffa
.hypothesis/constants/047dddab7d1e2042
.hypothesis/constants/0489319aba8b4266
.hypothesis/constants/05b7f95645c62968
.hypothesis/constants/05f6f9f5ce335b00
.hypothesis/constants/0663b6384f92d284
.hypothesis/constants/066dcc2451d28d3d
.hypothesis/constants/0741646aec08f0a4
.hypothesis/constants/07549a6ed9b93e40
.hypothesis/constants/076fe3d8ce5b8034
.hypothesis/constants/079c977bde882be8
.hypothesis/constants/07a463fdfd5276cc
.hypothesis/constants/07bc5cdea903258b
.hypothesis/constants/08678ced6d7ac7a0
.hypothesis/constants/0874b1af030e7f6e
.hypothesis/constants/08dd16c58dfc12eb
.hypothesis/constants/098e7a69d0ca8370
.hypothesis/constants/09c642a734fa75e8
.hypothesis/constants/0a0d80a90f43c58e
.hypothesis/constants/0a402ed48b0ecc79
.hypothesis/constants/0a6570335408273a
.hypothesis/constants/0af5e4afddd2e894
.hypothesis/constants/0b5ba5353bbc9d66
.hypothesis/constants/0b6a7a1a0067f347
.hypothesis/constants/0b6e81c36228c663
.hypothesis/constants/0b6f853c4e8f892a
.hypothesis/constants/0c2fc8cfd5a20235
.hypothesis/constants/0c3d979d908ea376
.hypothesis/constants/0c4de379d7ee3d14
.hypothesis/constants/0d3b005c663d8b0f
.hypothesis/constants/0d9c54784e959eed
.hypothesis/constants/0e47127688c846e4
.hypothesis/constants/0e7e7a4a326b1a27
.hypothesis/constants/0e9ce59b2a34bfd1
.hypothesis/constants/0f39e532d13c7352
.hypothesis/constants/0f653f19c429ef93
.hypothesis/constants/0fc1c72bcd463bdf
.hypothesis/constants/0fd3f300291e5a79
.hypothesis/constants/10071e043e03df79
.hypothesis/constants/10123237489c0b01
.hypothesis/constants/101fbfc29d2d4be9
.hypothesis/constants/1127bbba5fd1bc74
.hypothesis/constants/115bff4f5140daeb
.hypothesis/constants/118f6336530076ef
.hypothesis/constants/11b9c5c92cd45506
.hypothesis/constants/11ce61e7d98bef38
.hypothesis/constants/12af14c4068abbfb
.hypothesis/constants/12ca5a8a7e159b1d
.hypothesis/constants/12fc7ebb940e41f5
.hypothesis/constants/1372f01307654ad7
.hypothesis/constants/13a9da2a7533455a
.hypothesis/constants/140a243e4455782f
.hypothesis/constants/140e1721e6d8af11
.hypothesis/constants/147a7b9b926e2e2f
.hypothesis/constants/14ce81f75dc62efe
.hypothesis/constants/14e86ed128eb8aa4
.hypothesis/constants/14f3396259e2be74
.hypothesis/constants/1540ebb0e0e9cbbf
.hypothesis/constants/15b46810e63c7047
.hypothesis/constants/1698903551872c03
.hypothesis/constants/169bc0d237350095
.hypothesis/constants/169e9c7b4e354eb3
.hypothesis/constants/16aced8b0b6b7be8
.hypothesis/constants/16d1427514f4f582
.hypothesis/constants/17def00619196439
.hypothesis/constants/17eecd6d28d38311
.hypothesis/constants/18ac05979d68b886
.hypothesis/constants/18b75e180da594de
.hypothesis/constants/18cbaebcf558e677
.hypothesis/constants/18e8e4f038c394a2
.hypothesis/constants/196704790a8481a7
.hypothesis/constants/1984e5dce037d7af
.hypothesis/constants/199f724890b76d48
.hypothesis/constants/19a164300f00d55a
.hypothesis/constants/1a44f4f101c24bed
.hypothesis/constants/1a67cf06e4a6c2cf
.hypothesis/constants/1a8ea749b1a2d2be
.hypothesis/constants/1aa9ce6d02dd58a7
.hypothesis/constants/1ad6c6e183522539
.hypothesis/constants/1b2996e00f048f45
.hypothesis/constants/1b8f41e38f01284b
.hypothesis/constants/1bdadf4880ad507f
.hypothesis/constants/1bdd85f9d037852f
.hypothesis/constants/1be411ee2443de67
.hypothesis/constants/1c196534129813c5
.hypothesis/constants/1c1ae9dd04497256
.hypothesis/constants/1c72227e927f1610
.hypothesis/constants/1ca62d6cef2fe2d1
.hypothesis/constants/1dc1ab6c5c65cc09
.hypothesis/constants/1e2dfba909fef86b
.hypothesis/constants/1e313a366ae620ea
.hypothesis/constants/1e566dbb32834f38
.hypothesis/constants/1e5d0a2f24149f22
.hypothesis/constants/1ec744f92449aa78
.hypothesis/constants/1ef1c521932952b7
.hypothesis/constants/1f1e7e2e14fc52a5
.hypothesis/constants/1f46f94bb0dcb119
.hypothesis/constants/1f8e5d0de39657df
.hypothesis/constants/1fbff929102c20ef
.hypothesis/constants/1fc5bf9ad31f56a9
.hypothesis/constants/1fe0243c3f2203b2
.hypothesis/constants/20827ccd9750d3d3
.hypothesis/constants/20e0467fb85d3346
.hypothesis/constants/2114363dc1d81b6d
.hypothesis/constants/2118d12bbacf255c
.hypothesis/constants/2142174f111588ae
.hypothesis/constants/2246d1f6070b332d
.hypothesis/constants/2259aef991d03b0b
.hypothesis/constants/225da28f3315e017
.hypothesis/constants/227369e31e6d5520
.hypothesis/constants/22f0928fb2bfe018
.hypothesis/constants/23165cbdf7509af2
.hypothesis/constants/2449b03f5e30d950
.hypothesis/constants/24fc6d42a8d0ae99
.hypothesis/constants/2565d3ad32c02882
.hypothesis/constants/256dc7b3680fbc52
.hypothesis/constants/25f5116d3990976a
.hypothesis/constants/26041bf34cd84b95
.hypothesis/constants/2658074c65cb1cf7
.hypothesis/constants/27450bf63144a293
.hypothesis/constants/27b37a1c3daeaa48
.hypothesis/constants/286cac3bd81b2e4b
.hypothesis/constants/2914df98f5205757
.hypothesis/constants/29202e60884813ef
.hypothesis/constants/2931cb21b8d99daa
.hypothesis/constants/293686c39a98a53a
.hypothesis/constants/297c7f49b0a60247
.hypothesis/constants/2a032a30f9d8c16c
.hypothesis/constants/2a0499fe63fb96e2
.hypothesis/constants/2a324ce5a40def1e
.hypothesis/constants/2a3271688d9dd912
.hypothesis/constants/2aa0c7182029e0cd
.hypothesis/constants/2b1db47352a9982b
.hypothesis/constants/2b2386e15fdf8e34
.hypothesis/constants/2b4540f778e84b31
.hypothesis/constants/2b47d0f4908b47a6
.hypothesis/constants/2b5ffcccc0c1791f
.hypothesis/constants/2b6780114f3a4f14
.hypothesis/constants/2bc4cf0d30b947d6
.hypothesis/constants/2c11dd4943563191
.hypothesis/constants/2cc267ef7b5eb478
.hypothesis/constants/2cfb7ca432f35516
.hypothesis/constants/2d05b70cc8618686
.hypothesis/constants/2d9cb9574e671cf2
.hypothesis/constants/2dcaf019f6537ba1
.hypothesis/constants/2de7f021151d81a2
.hypothesis/constants/2e1a5d6cb47b7b0d
.hypothesis/constants/2f471a174830e478
.hypothesis/constants/2f4c226a014c91ec
.hypothesis/constants/3014283d9233d99f
```
