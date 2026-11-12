# Project context (auto)

Generated: 2026-11-12T18:54:08.029Z

## Detected stack

- Python
- GitHub Actions

## Git

- Branch: `m-client-ready-sweep`
- HEAD: `1ff2574`

## Recent commits

- `1ff2574` chore(merge): origin/main (superagent UI, unified composer) into m-client-ready-sweep _(Aditya Jain, 2026-11-13)_
- `6aed10b` fix(maintenance): persist owner ticket edits, surface API outages, verify dev DB _(Aditya Jain, 2026-11-13)_
- `d3f15a7` feat(frontend,agent,inbox): mobile/desktop UI cleanup, unified inbox composer, full AI drafts & Schibsted Grotesk mobile font _(Suryansh Tyagi, 2026-11-12)_
- `31fac13` feat(i18n): dynamic bidirectional chat translation, shared STT hook, BRIXX live check _(Aditya Jain, 2026-11-12)_
- `8b61a5d` feat(superagent,frontend): clean executive answers and structured cards _(Suryansh Tyagi, 2026-11-11)_
- `a0b4cd6` fix(frontend): add rentStatus to ContactItem and remove duplicate keys in LanguageContext _(Suryansh Tyagi, 2026-11-11)_
- `1685f04` fix(pipeline): make Action case_id optional in tool schema so LLM proposal validation succeeds _(Suryansh Tyagi, 2026-11-11)_
- `28e7c38` feat(dashboard,sim): round dashboard filter bar and execute live tenant scenario simulation _(Suryansh Tyagi, 2026-11-11)_
- `489c7d7` feat(drafts,tenants): connect real AI proposer agent and add tenants directory fallback _(Suryansh Tyagi, 2026-11-11)_
- `e953952` feat(money): add Monthly vs Yearly time horizon and collapsible chart toggle _(Suryansh Tyagi, 2026-11-11)_
- `10fa6a6` fix(money,tenants): cap occupancy to 100% and wire live rent status for overdue tenants _(Suryansh Tyagi, 2026-11-11)_
- `5510270` fix(ui): replace unicode flag emojis with crisp SVG flags for cross-platform Windows support _(Suryansh Tyagi, 2026-11-11)_
- `e588cc0` fix(auth): restore X-Session-Token header support and prioritize real owner company in dev _(Suryansh Tyagi, 2026-11-11)_
- `2f33052` fix(frontend): restore API proxy rewrite in next.config.ts _(Suryansh Tyagi, 2026-11-11)_
- `845ed8c` chore(merge): merge origin/main into experiment-superagent-ui _(Suryansh Tyagi, 2026-11-11)_
- `120325e` fix(pipeline): truncate massive email bodies for understanding and suppress fallback cases for unlinked senders _(Suryansh Tyagi, 2026-11-11)_
- `f83e293` chore(deps): google-genai 3.1.0 in the lock, and the merge notes _(Aditya Jain, 2026-11-11)_
- `01adfe0` chore(merge): dependabot dependency-review-action 5.0.0 _(Aditya Jain, 2026-11-11)_
- `142eed5` chore(merge): dependabot docker astral-sh/uv 0.13.7 _(Aditya Jain, 2026-11-11)_
- `3f490d8` chore(merge): wip/brixx-uncommitted-snapshot (archived patch under docs/wip) _(Aditya Jain, 2026-11-11)_

## Inferred recent decisions

- `6aed10b` fix(maintenance): persist owner ticket edits, surface API outages, verify dev DB
- `d3f15a7` feat(frontend,agent,inbox): mobile/desktop UI cleanup, unified inbox composer, full AI drafts & Schibsted Grotesk mobile font
- `31fac13` feat(i18n): dynamic bidirectional chat translation, shared STT hook, BRIXX live check
- `8b61a5d` feat(superagent,frontend): clean executive answers and structured cards
- `a0b4cd6` fix(frontend): add rentStatus to ContactItem and remove duplicate keys in LanguageContext
- `1685f04` fix(pipeline): make Action case_id optional in tool schema so LLM proposal validation succeeds
- `28e7c38` feat(dashboard,sim): round dashboard filter bar and execute live tenant scenario simulation
- `489c7d7` feat(drafts,tenants): connect real AI proposer agent and add tenants directory fallback
- `e953952` feat(money): add Monthly vs Yearly time horizon and collapsible chart toggle
- `10fa6a6` fix(money,tenants): cap occupancy to 100% and wire live rent status for overdue tenants
- `5510270` fix(ui): replace unicode flag emojis with crisp SVG flags for cross-platform Windows support
- `e588cc0` fix(auth): restore X-Session-Token header support and prioritize real owner company in dev
- `2f33052` fix(frontend): restore API proxy rewrite in next.config.ts
- `120325e` fix(pipeline): truncate massive email bodies for understanding and suppress fallback cases for unlinked senders

## Hotspots

- 64x — `docs/PROGRESS.md`
- 48x — `app/api/agent/routes.py`
- 41x — `frontend/src/components/assistant/AskEstateOSPanel.tsx`
- 35x — `app/api/inbox/routes.py`
- 35x — `pyproject.toml`
- 34x — `app/core/settings.py`
- 30x — `docs/dashboard-api.md`
- 28x — `frontend/src/lib/api.ts`
- 27x — `.env.example`
- 27x — `tests/unit/api/__snapshots__/test_openapi_snapshot.ambr`

## Top-level tree

```
.DS_Store
.claude/
.claude/.cache/
.claude/.cache/req.txt
.claude/.cache/stop_gate_green
.claude/agents/
.claude/agents/builder.md
.claude/agents/estateos-implementer.md
.claude/agents/estateos-reviewer.md
.claude/agents/estateos-security.md
.claude/agents/reviewer.md
.claude/agents/test-runner.md
.claude/commands/
.claude/commands/audit.md
.claude/commands/autoship.md
.claude/commands/build.md
.claude/commands/release.md
.claude/commands/sync.md
.claude/commands/verify.md
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
.claude/skills/retro/
.claude/skills/ship/
.claude/worktrees/
.claude/worktrees/m-bugfix-sweep/
.claude/worktrees/m-founderos-lessons/
.coverage
.data/
.data/models/
.data/models/opus-mt-en-nl/
.data/models/opus-mt-nl-en/
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
.hypothesis/constants/011f8c7d7f68d607
.hypothesis/constants/018e5e84e3516ec0
.hypothesis/constants/01b8e3c637b8109e
.hypothesis/constants/020b42d5c9ec5bd3
.hypothesis/constants/02162a9809ed17e0
.hypothesis/constants/021cab0b131c3d27
.hypothesis/constants/02341df55f048e14
.hypothesis/constants/025364ce523ac2e3
.hypothesis/constants/0299ab0ecd7b9af7
.hypothesis/constants/02af8e2877328043
.hypothesis/constants/02b19c2985618352
.hypothesis/constants/031c4c1df766fd0b
.hypothesis/constants/031df9505c37006c
.hypothesis/constants/033bd937e52698ec
.hypothesis/constants/03485f319bd03ffa
.hypothesis/constants/03efb4450d257e29
.hypothesis/constants/047dddab7d1e2042
.hypothesis/constants/0489319aba8b4266
.hypothesis/constants/04db34449aed6317
.hypothesis/constants/05a0fc6ca21bad0d
.hypothesis/constants/05b7f95645c62968
.hypothesis/constants/05d7646eba8ddcea
.hypothesis/constants/05f6f9f5ce335b00
.hypothesis/constants/0663b6384f92d284
.hypothesis/constants/066dcc2451d28d3d
.hypothesis/constants/06b16bf0adda75ba
.hypothesis/constants/06fc84a8ded75372
.hypothesis/constants/071c066c9f36a75d
.hypothesis/constants/0741646aec08f0a4
.hypothesis/constants/074d319453979af0
.hypothesis/constants/07549a6ed9b93e40
.hypothesis/constants/076fe3d8ce5b8034
.hypothesis/constants/078fe14cfbe68ec5
.hypothesis/constants/079c977bde882be8
.hypothesis/constants/07a463fdfd5276cc
.hypothesis/constants/07bc5cdea903258b
.hypothesis/constants/07c5d8e751b4052c
.hypothesis/constants/08399c98e11d72f3
.hypothesis/constants/08678ced6d7ac7a0
.hypothesis/constants/0874b1af030e7f6e
.hypothesis/constants/0878fa11a1d66210
.hypothesis/constants/08dd16c58dfc12eb
.hypothesis/constants/09635c7c9cfb7bf5
.hypothesis/constants/0967d8a1deb2d71d
.hypothesis/constants/0986b816d012b7e1
.hypothesis/constants/098e7a69d0ca8370
.hypothesis/constants/09c642a734fa75e8
.hypothesis/constants/09d81387d4e3d455
.hypothesis/constants/0a0d80a90f43c58e
.hypothesis/constants/0a239b20ff8f1406
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
.hypothesis/constants/0c65a791a749a664
.hypothesis/constants/0d3b005c663d8b0f
.hypothesis/constants/0d47a69ff78e53a7
.hypothesis/constants/0d9c54784e959eed
.hypothesis/constants/0e11ab0b8c66a34c
.hypothesis/constants/0e28cd3493a35c4f
.hypothesis/constants/0e47127688c846e4
.hypothesis/constants/0e7e7a4a326b1a27
.hypothesis/constants/0e836acda2f4484e
.hypothesis/constants/0e9ce59b2a34bfd1
.hypothesis/constants/0f39e532d13c7352
.hypothesis/constants/0f653f19c429ef93
.hypothesis/constants/0fc1c72bcd463bdf
.hypothesis/constants/0fd3f300291e5a79
.hypothesis/constants/10071e043e03df79
.hypothesis/constants/10123237489c0b01
.hypothesis/constants/101fbfc29d2d4be9
.hypothesis/constants/108dc265a25d671a
.hypothesis/constants/109a31233581e910
.hypothesis/constants/1127bbba5fd1bc74
.hypothesis/constants/115bff4f5140daeb
.hypothesis/constants/115dd987f7a9d815
.hypothesis/constants/117e2fa864c19620
.hypothesis/constants/118f6336530076ef
.hypothesis/constants/11b9c5c92cd45506
.hypothesis/constants/11ce61e7d98bef38
.hypothesis/constants/11ed984919a4c108
.hypothesis/constants/1214fb91a3ec0ce5
.hypothesis/constants/123e9576de3051b0
.hypothesis/constants/12af14c4068abbfb
.hypothesis/constants/12ca5a8a7e159b1d
.hypothesis/constants/12fc7ebb940e41f5
.hypothesis/constants/1309a78a70d3b814
.hypothesis/constants/136b95391794680f
.hypothesis/constants/1372f01307654ad7
.hypothesis/constants/13a9da2a7533455a
.hypothesis/constants/13d9faa1eb1264e1
.hypothesis/constants/140a243e4455782f
.hypothesis/constants/140e1721e6d8af11
.hypothesis/constants/147a7b9b926e2e2f
.hypothesis/constants/1491ca36ea85f0f9
.hypothesis/constants/14ce81f75dc62efe
.hypothesis/constants/14d78eaa2dda9f79
.hypothesis/constants/14e86ed128eb8aa4
.hypothesis/constants/14f3396259e2be74
.hypothesis/constants/1540ebb0e0e9cbbf
.hypothesis/constants/15a811b8fb9f1fce
.hypothesis/constants/15b46810e63c7047
.hypothesis/constants/15fcf20b59788cb1
.hypothesis/constants/1669c3aca74e6e47
.hypothesis/constants/1698903551872c03
.hypothesis/constants/169bc0d237350095
.hypothesis/constants/169e9c7b4e354eb3
.hypothesis/constants/16aced8b0b6b7be8
.hypothesis/constants/16d1144fb472dc7a
.hypothesis/constants/16d1427514f4f582
.hypothesis/constants/174c60c25c0a411c
.hypothesis/constants/1766fd75ec487ac8
.hypothesis/constants/17def00619196439
.hypothesis/constants/17eecd6d28d38311
.hypothesis/constants/183c619edd3f2c89
.hypothesis/constants/18ac05979d68b886
.hypothesis/constants/18b75e180da594de
.hypothesis/constants/18cbaebcf558e677
.hypothesis/constants/18dac4c9f22a7e70
.hypothesis/constants/18e8e4f038c394a2
.hypothesis/constants/192242756f9e15d5
.hypothesis/constants/195d9679adab69f3
.hypothesis/constants/196704790a8481a7
.hypothesis/constants/1984e5dce037d7af
.hypothesis/constants/199e3430959bbbba
.hypothesis/constants/199f724890b76d48
.hypothesis/constants/19a111c3ccc893e4
.hypothesis/constants/19a164300f00d55a
.hypothesis/constants/1a44f4f101c24bed
.hypothesis/constants/1a67cf06e4a6c2cf
.hypothesis/constants/1a8ea749b1a2d2be
.hypothesis/constants/1aa9ce6d02dd58a7
.hypothesis/constants/1aba4137143afa91
.hypothesis/constants/1ad6c6e183522539
.hypothesis/constants/1b2996e00f048f45
.hypothesis/constants/1b81d4d985941a69
.hypothesis/constants/1b8f41e38f01284b
.hypothesis/constants/1bdadf4880ad507f
```
