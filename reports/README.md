# reports/ — retros and run reports

Durable, dated history of what the work taught us. Distinct from `docs/PROGRESS.md` (live status) and `docs/adr/`
(decisions): a report records **what happened and what we changed because of it**.

- Naming: `<YYYY-MM-DD>-<slug>.md`. One file per slice, milestone, release or incident. Never rewrite an old report;
  add a new dated one.
- Sections: What happened · What slowed us down · Knowledge captured (each item points at the artifact that now holds
  it) · Follow-ups (with an owner or an issue link).
- State facts and failures honestly, with result lines. A retro with no friction in it was not written honestly.
- Written with `/retro` at the end of every slice or milestone, before `/milestone close`.
