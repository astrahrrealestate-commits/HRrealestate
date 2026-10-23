"""Rules engine: every rule × outcome. Phase 1: everything external needs approval."""

from uuid import UUID, uuid4

import pytest

from app.contracts import Action, ActionType
from app.pipeline.rules import RuleContext, Verdict, apply_rules

CASE = uuid4()
CONTRACTOR = uuid4()


def _action(kind: ActionType, **payload: object) -> Action:
    defaults: dict[ActionType, dict[str, object]] = {
        ActionType.reply_draft: {"channel": "whatsapp", "subject": None, "body_variants": ["A", "B"]},
        ActionType.notify_owner: {"text": "Info"},
        ActionType.create_reminder: {"due_at": "2026-10-09T08:00:00+00:00", "note": "Bel"},
        ActionType.update_case_state: {"new_state": "waiting_on_third_party"},
        ActionType.request_contractor: {"contractor_person_id": str(CONTRACTOR), "body_variants": ["A", "B"]},
        ActionType.escalate: {"reason": "Urgent"},
    }
    body = {"kind": kind.value, **defaults[kind], **payload}
    return Action.model_validate(
        {"type": kind, "case_id": CASE, "payload": body, "rationale": "r", "context_ref": [], "draft_version": 1}
    )


def _ctx(**kw: object) -> RuleContext:
    base: dict[str, object] = {"paused": False, "suspicious": False, "contractor_ids": frozenset({CONTRACTOR})}
    return RuleContext(**{**base, **kw})  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", list(ActionType))
def test_every_action_type_needs_approval_by_default(kind: ActionType) -> None:
    [d] = apply_rules([_action(kind)], _ctx())
    assert d.verdict is Verdict.pending_approval


@pytest.mark.parametrize("kind", list(ActionType))
def test_paused_company_pauses_everything(kind: ActionType) -> None:
    [d] = apply_rules([_action(kind)], _ctx(paused=True, suspicious=True))
    assert (d.verdict, d.reason) == (Verdict.paused, "company paused")


@pytest.mark.parametrize("kind", list(ActionType))
def test_suspicious_message_turns_everything_into_an_exception(kind: ActionType) -> None:
    [d] = apply_rules([_action(kind)], _ctx(suspicious=True))
    assert (d.verdict, d.reason) == (Verdict.exception, "suspicious message")


def test_unknown_contractor_is_an_exception() -> None:
    [d] = apply_rules([_action(ActionType.request_contractor, contractor_person_id=str(uuid4()))], _ctx())
    assert (d.verdict, d.reason) == (Verdict.exception, "contractor is not on file")


def test_only_the_first_state_update_and_first_reply_per_channel_survive() -> None:
    actions = [
        _action(ActionType.update_case_state),
        _action(ActionType.update_case_state, new_state="resolved"),
        _action(ActionType.reply_draft),
        _action(ActionType.reply_draft),
        _action(ActionType.reply_draft, channel="gmail"),
    ]
    verdicts = [d.verdict for d in apply_rules(actions, _ctx())]
    assert verdicts == [
        Verdict.pending_approval,
        Verdict.drop,
        Verdict.pending_approval,
        Verdict.drop,
        Verdict.pending_approval,
    ]


def test_decisions_keep_input_order_and_actions() -> None:
    actions = [_action(ActionType.notify_owner), _action(ActionType.escalate)]
    assert [d.action for d in apply_rules(actions, _ctx())] == actions


def test_empty_input() -> None:
    assert apply_rules([], _ctx()) == []


def test_contractor_ids_are_uuids() -> None:
    assert all(isinstance(c, UUID) for c in _ctx().contractor_ids)


def test_reply_with_an_invented_link_becomes_an_exception() -> None:
    draft = _action(
        ActionType.reply_draft,
        body_variants=["Betaal hier: https://evil.example.com/pay", "Zie https://evil.example.com"],
    )
    [d] = apply_rules([draft], _ctx(source_text="Wanneer komt de loodgieter?"))
    assert (d.verdict, d.reason) == (Verdict.exception, "draft contains an unverified link, account or phone number")


def test_reply_quoting_the_senders_own_link_is_fine() -> None:
    draft = _action(
        ActionType.reply_draft,
        body_variants=["Foto ontvangen: https://x.example.com/a", "Dank voor https://x.example.com/a"],
    )
    [d] = apply_rules([draft], _ctx(source_text="Kijk https://x.example.com/a"))
    assert d.verdict is Verdict.pending_approval
