# Project context (auto)

Generated: 2026-10-15T17:46:10.286Z

## Detected stack

- Python
- GitHub Actions

## Git

- Branch: `d-dashboard`
- HEAD: `769a32e`

## Recent commits

- `769a32e` docs(dashboard): record the stuck-send gap that blocks send mode _(Aditya Jain, 2026-10-15)_
- `9fdb959` docs(dashboard): final review wave: same-origin/CORS, sweep, sends, owner switch _(Aditya Jain, 2026-10-15)_
- `fa4dfa6` feat(api): cors allowlist, session recheck, api import contract, settings wiring _(Aditya Jain, 2026-10-15)_
- `7fdcd03` feat(workflows): commit-then-crash sweeper for approved actions and turns _(Aditya Jain, 2026-10-15)_
- `7f88818` fix(sender): dashboard owner delivery, in-flight resume and stuck sends _(Aditya Jain, 2026-10-15)_
- `f7a561e` fix(dashboard): document review feed kind and task refs in the planner brief _(Aditya Jain, 2026-10-15)_
- `76e4003` fix(dev): reject the public dev session secret in prod, demo guards _(Aditya Jain, 2026-10-15)_
- `8d90981` fix(dev): dashboard demo env, provider guard, state restore; limiter and docs follow-ups _(Aditya Jain, 2026-10-15)_
- `51296b3` docs(dashboard): API guide, ADR accepted, progress and deviations _(Aditya Jain, 2026-10-15)_
- `d906862` feat(api): rate limits, dashboard simulator scenario _(Aditya Jain, 2026-10-15)_
- `db24230` fix(evals): ignore ids in the injection walk _(Aditya Jain, 2026-10-15)_
- `f9eb588` fix(evals): fake-runnable safety cases, hostile-plan injection test, results cap _(Aditya Jain, 2026-10-15)_
- `29c283d` test(evals): concierge golden set and injection suite _(Aditya Jain, 2026-10-15)_
- `d698b38` fix(agent): persist plan before executing, enqueue failure, input validation _(Aditya Jain, 2026-10-15)_
- `bb62d70` feat(agent): super agent workflow, chat endpoints, turn events _(Aditya Jain, 2026-10-15)_
- `27a8169` fix(pipeline): concierge sanitiser urls, chase dedupe, honest results _(Aditya Jain, 2026-10-15)_
- `c008476` feat(pipeline): concierge plan validation and dispatch _(Aditya Jain, 2026-10-15)_
- `7735524` feat(llm): concierge plan contract, prompt v1, fake model _(Aditya Jain, 2026-10-15)_
- `ff2fa0d` feat(live): outbound live check, reply-send consent, go-live notes _(Aditya Jain, 2026-10-15)_
- `d492af4` fix(sender): tenant subject from thread, stuck/exhausted send telling, replay order _(Aditya Jain, 2026-10-15)_

## Inferred recent decisions

- `fa4dfa6` feat(api): cors allowlist, session recheck, api import contract, settings wiring
- `7fdcd03` feat(workflows): commit-then-crash sweeper for approved actions and turns
- `7f88818` fix(sender): dashboard owner delivery, in-flight resume and stuck sends
- `f7a561e` fix(dashboard): document review feed kind and task refs in the planner brief
- `76e4003` fix(dev): reject the public dev session secret in prod, demo guards
- `8d90981` fix(dev): dashboard demo env, provider guard, state restore; limiter and docs follow-ups
- `51296b3` docs(dashboard): API guide, ADR accepted, progress and deviations
- `d906862` feat(api): rate limits, dashboard simulator scenario
- `db24230` fix(evals): ignore ids in the injection walk
- `f9eb588` fix(evals): fake-runnable safety cases, hostile-plan injection test, results cap
- `d698b38` fix(agent): persist plan before executing, enqueue failure, input validation
- `bb62d70` feat(agent): super agent workflow, chat endpoints, turn events
- `27a8169` fix(pipeline): concierge sanitiser urls, chase dedupe, honest results
- `c008476` feat(pipeline): concierge plan validation and dispatch
- `7735524` feat(llm): concierge plan contract, prompt v1, fake model
- `ff2fa0d` feat(live): outbound live check, reply-send consent, go-live notes
- `d492af4` fix(sender): tenant subject from thread, stuck/exhausted send telling, replay order

## Hotspots

- 34x — `docs/PROGRESS.md`
- 19x — `pyproject.toml`
- 17x — `app/core/settings.py`
- 16x — `Makefile`
- 15x — `.env.example`
- 15x — `app/workflows/runtime.py`
- 12x — `docs/go-live-channels.md`
- 11x — `app/llm/fakes.py`
- 11x — `tests/integration/conftest.py`
- 10x — `app/main.py`

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
.env.example.bak
.hypothesis/
.hypothesis/constants/
.hypothesis/constants/0018aac87bd74f1f
.hypothesis/constants/00c306c2503e3401
.hypothesis/constants/020b42d5c9ec5bd3
.hypothesis/constants/025364ce523ac2e3
.hypothesis/constants/0299ab0ecd7b9af7
.hypothesis/constants/02af8e2877328043
.hypothesis/constants/02b19c2985618352
.hypothesis/constants/031c4c1df766fd0b
.hypothesis/constants/033bd937e52698ec
.hypothesis/constants/03485f319bd03ffa
.hypothesis/constants/047dddab7d1e2042
.hypothesis/constants/0489319aba8b4266
.hypothesis/constants/05b7f95645c62968
.hypothesis/constants/05f6f9f5ce335b00
.hypothesis/constants/0663b6384f92d284
.hypothesis/constants/066dcc2451d28d3d
.hypothesis/constants/0741646aec08f0a4
.hypothesis/constants/079c977bde882be8
.hypothesis/constants/07a463fdfd5276cc
.hypothesis/constants/07bc5cdea903258b
.hypothesis/constants/08678ced6d7ac7a0
.hypothesis/constants/08dd16c58dfc12eb
.hypothesis/constants/098e7a69d0ca8370
.hypothesis/constants/09c642a734fa75e8
.hypothesis/constants/0a6570335408273a
.hypothesis/constants/0b6a7a1a0067f347
.hypothesis/constants/0b6f853c4e8f892a
.hypothesis/constants/0c2fc8cfd5a20235
.hypothesis/constants/0c3d979d908ea376
.hypothesis/constants/0c4de379d7ee3d14
.hypothesis/constants/0d9c54784e959eed
.hypothesis/constants/0e7e7a4a326b1a27
.hypothesis/constants/0f39e532d13c7352
.hypothesis/constants/0f653f19c429ef93
.hypothesis/constants/0fc1c72bcd463bdf
.hypothesis/constants/10071e043e03df79
.hypothesis/constants/10123237489c0b01
.hypothesis/constants/101fbfc29d2d4be9
.hypothesis/constants/1127bbba5fd1bc74
.hypothesis/constants/118f6336530076ef
.hypothesis/constants/11ce61e7d98bef38
.hypothesis/constants/12af14c4068abbfb
.hypothesis/constants/12ca5a8a7e159b1d
.hypothesis/constants/12fc7ebb940e41f5
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
.hypothesis/constants/16d1427514f4f582
.hypothesis/constants/17def00619196439
.hypothesis/constants/17eecd6d28d38311
.hypothesis/constants/18ac05979d68b886
.hypothesis/constants/18cbaebcf558e677
.hypothesis/constants/18e8e4f038c394a2
.hypothesis/constants/19a164300f00d55a
.hypothesis/constants/1a44f4f101c24bed
.hypothesis/constants/1a8ea749b1a2d2be
.hypothesis/constants/1ad6c6e183522539
.hypothesis/constants/1b2996e00f048f45
.hypothesis/constants/1b8f41e38f01284b
.hypothesis/constants/1bdadf4880ad507f
.hypothesis/constants/1be411ee2443de67
.hypothesis/constants/1c196534129813c5
.hypothesis/constants/1c72227e927f1610
.hypothesis/constants/1ca62d6cef2fe2d1
.hypothesis/constants/1dc1ab6c5c65cc09
.hypothesis/constants/1e2dfba909fef86b
.hypothesis/constants/1e566dbb32834f38
.hypothesis/constants/1e5d0a2f24149f22
.hypothesis/constants/1ec744f92449aa78
.hypothesis/constants/1ef1c521932952b7
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
.hypothesis/constants/23165cbdf7509af2
.hypothesis/constants/2449b03f5e30d950
.hypothesis/constants/24fc6d42a8d0ae99
.hypothesis/constants/2565d3ad32c02882
.hypothesis/constants/256dc7b3680fbc52
.hypothesis/constants/25f5116d3990976a
.hypothesis/constants/26041bf34cd84b95
.hypothesis/constants/2658074c65cb1cf7
.hypothesis/constants/27b37a1c3daeaa48
.hypothesis/constants/286cac3bd81b2e4b
.hypothesis/constants/2914df98f5205757
.hypothesis/constants/2931cb21b8d99daa
.hypothesis/constants/2a0499fe63fb96e2
.hypothesis/constants/2a3271688d9dd912
.hypothesis/constants/2aa0c7182029e0cd
.hypothesis/constants/2b1db47352a9982b
.hypothesis/constants/2b2386e15fdf8e34
.hypothesis/constants/2b4540f778e84b31
.hypothesis/constants/2b47d0f4908b47a6
.hypothesis/constants/2b5ffcccc0c1791f
.hypothesis/constants/2bc4cf0d30b947d6
.hypothesis/constants/2c11dd4943563191
.hypothesis/constants/2cfb7ca432f35516
.hypothesis/constants/2d9cb9574e671cf2
.hypothesis/constants/2de7f021151d81a2
.hypothesis/constants/2e1a5d6cb47b7b0d
.hypothesis/constants/306f1403e79ae2e7
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
.hypothesis/constants/33fe1c152eb88c27
.hypothesis/constants/343a4272d58087d1
.hypothesis/constants/346fa2abedd0898e
.hypothesis/constants/34af8208fdfe2c92
.hypothesis/constants/353b8d87598fb3ca
.hypothesis/constants/35b815d7b2761471
.hypothesis/constants/35beee241fbcc05f
.hypothesis/constants/368d6942fda097cd
.hypothesis/constants/369e69e84b56d853
.hypothesis/constants/371ba148863ae86c
.hypothesis/constants/374e4426df8244d8
.hypothesis/constants/3760c1493ed2ad17
.hypothesis/constants/38539e4c250205c3
.hypothesis/constants/387647b2c16939c9
.hypothesis/constants/38f49994b8e47e4a
.hypothesis/constants/38fd7109a7f04c74
.hypothesis/constants/39190734e43752be
.hypothesis/constants/39c1ff8f7ba285e3
.hypothesis/constants/39ea3c779b308b3c
.hypothesis/constants/39f2cead6d3e8c8a
.hypothesis/constants/39fd3165f506a35f
.hypothesis/constants/3a89b708b9e9eca9
.hypothesis/constants/3afd2908bf8e528c
.hypothesis/constants/3b03fc9925e00a3b
.hypothesis/constants/3b459f5069ce7e07
.hypothesis/constants/3b45b580f92c2113
.hypothesis/constants/3c65ec9dbb23823e
.hypothesis/constants/3c73be4d58c149b0
.hypothesis/constants/3cbff9b7334d2c2f
.hypothesis/constants/3d4ed9194708572b
.hypothesis/constants/3d5a941ad5e31542
.hypothesis/constants/3dac131e55975f7b
.hypothesis/constants/3dbae7bf2392a3a0
.hypothesis/constants/3e294546b462faca
.hypothesis/constants/3eb1d14a6b5ae636
.hypothesis/constants/3f17d84de0526a5c
.hypothesis/constants/3f1c2a137853b24a
.hypothesis/constants/3f33bc585a403aad
```
