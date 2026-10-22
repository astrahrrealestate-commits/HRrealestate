"""Single-call answers (concierge/v3, spec amendment 2026-10-22): the planner's own `reply`, screened.

The reply is untrusted model text (the model read tenant messages and the browser snapshot). Harjot sees it only
- for an in-scope plan: scope is decided by the plan; an out-of-scope plan keeps no reply and runs nothing;
- through an `answer` step (a plan with a usable reply but no `answer` step gets one appended when there is room);
- after `screen_reply`: control/format characters out, whitespace collapsed per line, at most `MAX_REPLY_LINES` lines,
  links, emails, phone numbers, IBANs and amounts redacted (`concierge_sanitize.redact`), capped at `MAX_REPLY`.
Ids are never read from the reply (case refs are not taken from model text). A blank or missing reply means the
`answer` step asks owner_qa as before (a second model call). Pure: no I/O.
"""

from app.contracts import ConciergePlan, Intent, PlanStep
from app.contracts.concierge import MAX_PLAN_STEPS, MAX_REPLY
from app.pipeline.concierge_sanitize import plain_line, redact

MAX_REPLY_LINES = 20
ANSWER_STEP = PlanStep(intent=Intent.answer, case_id=None, task_ref=None, text=None, view=None)


def screen_reply(text: str | None) -> str | None:
    """The reply as Harjot may see it, or None when nothing usable is left. Idempotent."""
    if not text:
        return None
    lines = [line for line in (plain_line(raw) for raw in text.splitlines()) if line][:MAX_REPLY_LINES]
    screened = redact("\n".join(lines))[:MAX_REPLY].strip()
    return screened or None


def prepare_plan(plan: ConciergePlan) -> ConciergePlan:
    """The plan as stored and run: the reply screened (dropped when out of scope), and an `answer` step appended when
    a usable reply has none, so the reply is shown. Other steps keep their deterministic summaries."""
    if not plan.in_scope:
        return plan.model_copy(update={"reply": None})
    reply = screen_reply(plan.reply)
    steps = list(plan.steps)
    if reply and Intent.answer not in {s.intent for s in steps} and len(steps) < MAX_PLAN_STEPS:
        steps.append(ANSWER_STEP)
    return plan.model_copy(update={"reply": reply, "steps": steps})


def stored_plan(raw: dict[str, object]) -> ConciergePlan:
    """A plan stored by an earlier attempt; plans stored before concierge/v3 have no `reply` key."""
    return ConciergePlan.model_validate({"reply": None, **raw})
