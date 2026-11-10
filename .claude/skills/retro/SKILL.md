---
name: retro
description: Run the EstateOS self-improvement loop after a slice, milestone, release or incident. Writes reports/<date>-<slug>.md and turns each lesson into a concrete artifact (a rule in docs/dev-pipeline.md or docs/standards, a skill, a hook, an ADR, a test). Use when the user says "retro", "what slowed us down", "lessons learned", "self-improve", or when closing a milestone or slice.
---

# /retro

Goal: every finished piece of work leaves the system better at building the next one.

1. **Gather evidence, do not recall.** `git log --oneline <base>..HEAD`, the gate result lines from this session, every
   gate or hook failure, every test that had to be fixed for a reason other than the feature, and every correction the
   user gave. Quote result lines.
2. **Ask four questions.** What slowed us down? What knowledge was missing, and where should it live? What repeated
   activity should become a skill (the **third** occurrence makes it one)? What should become a hook, a test or a gate?
3. **Turn each lesson into an artifact in this same change**, not a note to self:
   - a rule for how we write or test code -> `docs/dev-pipeline.md` or `docs/standards/*`
   - a security rule or known gap -> `docs/standards/security.md`
   - a repeatable procedure -> a skill under `.claude/skills/`; an edit to an existing skill's checklist
   - a mechanical check that was missed -> a hook, a lint rule, a CI step or a regression test
   - a significant design choice -> an ADR in `docs/adr/`
   A lesson with no artifact is a follow-up with an owner or an issue link, never silently dropped.
4. **Write `reports/<YYYY-MM-DD>-<slug>.md`** (see `reports/README.md`): What happened · What slowed us down ·
   Knowledge captured (link the artifact) · Follow-ups. Honest about failures; no praise.
5. Commit the report together with the artifacts it created (`docs(retro): ...` or the artifact's own type).

Never: rewrite an older report, record a lesson without evidence, or claim a gate passed without its result line.
