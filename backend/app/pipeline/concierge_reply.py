"""Single-call answers (concierge/v3, spec amendment 2026-10-22): the planner's own `reply`, screened.

The reply is untrusted model text (the model read tenant messages and the browser snapshot). Harjot sees it only
- for an in-scope plan: scope is decided by the plan; an out-of-scope plan keeps no reply and runs nothing;
- only beside read steps: every step is `answer` or `open_view` (`READ_STEPS`); a plan with any other step (a draft,
  a chase, a task change) keeps no reply, so model text can never sit next to a real action's summary;
- through an `answer` step (a plan of read steps with a usable reply but no `answer` step gets one appended when
  there is room; with no room the reply is dropped, so the stored plan never holds an unshown reply);
- after `screen_reply`: control/format characters out, whitespace collapsed per line, at most `MAX_REPLY_LINES` lines,
  links, emails, phone numbers and IBANs redacted (`concierge_sanitize.redact_contact`; amounts are kept, prompt
  concierge/v5+ allows only those in the server data), capped at `MAX_REPLY`.
Ids are never read from the reply (case refs are not taken from model text). A blank or missing reply means the
`answer` step asks owner_qa as before (a second model call). Pure: no I/O.
"""

from app.contracts import ConciergePlan, Intent, PlanStep
from app.contracts.concierge import MAX_PLAN_STEPS, MAX_REPLY
from app.pipeline.concierge_sanitize import plain_line, redact_contact

MAX_REPLY_LINES = 20
ANSWER_STEP = PlanStep(intent=Intent.answer, case_id=None, task_ref=None, text=None, view=None)
READ_STEPS = frozenset({Intent.answer, Intent.open_view})


def screen_reply(text: str | None) -> str | None:
    """The reply as Harjot may see it, or None when nothing usable is left. Idempotent."""
    if not text:
        return None
    lines = [line for line in (plain_line(raw) for raw in text.splitlines()) if line][:MAX_REPLY_LINES]
    screened = redact_contact("\n".join(lines))[:MAX_REPLY].strip()
    return screened or None


def reply_allowed(plan: ConciergePlan) -> bool:
    """An in-scope plan whose steps are all read steps (none at all counts): the only plans that may show a reply."""
    return plan.in_scope and all(s.intent in READ_STEPS for s in plan.steps)


def prepare_plan(plan: ConciergePlan) -> ConciergePlan:
    """The plan as stored and run: the reply screened, kept only beside read steps and only when an `answer` step
    shows it (appended when missing and there is room); otherwise the stored reply is null. The same holds for
    `needs_research` (concierge/v7), which a usable reply makes redundant: it stays only for a read-only plan without
    a reply, and an `answer` step is appended for it too."""
    allowed = reply_allowed(plan)
    reply = screen_reply(plan.reply) if allowed else None
    research = allowed and reply is None and plan.needs_research
    steps = list(plan.steps)
    if (reply or research) and Intent.answer not in {s.intent for s in steps}:
        if len(steps) >= MAX_PLAN_STEPS:
            return plan.model_copy(update={"reply": None, "needs_research": False})
        steps.append(ANSWER_STEP)
    return plan.model_copy(update={"reply": reply, "steps": steps, "needs_research": research})


def stored_plan(raw: dict[str, object]) -> ConciergePlan:
    """A plan stored by an earlier attempt; plans stored before concierge/v3 have no `reply` key."""
    return ConciergePlan.model_validate({"reply": None, **raw})
