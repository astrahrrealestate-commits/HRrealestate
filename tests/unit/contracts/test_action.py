from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts import Action, ActionType, CaseState, Channel


def _reply(**kw: Any) -> dict[str, Any]:
    return {
        "kind": "reply_draft",
        "channel": Channel.gmail,
        "subject": "Re: Heizung",
        "body_variants": ["a", "b"],
        **kw,
    }


def _action(**kw: Any) -> Action:
    base: dict[str, Any] = {
        "type": ActionType.reply_draft,
        "case_id": uuid4(),
        "payload": _reply(),
        "rationale": "tenant asked",
        "context_ref": [uuid4()],
        "draft_version": 1,
    }
    return Action(**{**base, **kw})


def test_valid_reply_draft_round_trip() -> None:
    a = _action()
    assert Action.model_validate_json(a.model_dump_json()) == a


def test_every_type_has_matching_payload() -> None:
    payloads: dict[ActionType, dict[str, Any]] = {
        ActionType.reply_draft: _reply(),
        ActionType.notify_owner: {"kind": "notify_owner", "text": "Heizung Whg 3"},
        ActionType.create_reminder: {"kind": "create_reminder", "due_at": "2026-01-02T08:00:00+01:00", "note": "x"},
        ActionType.update_case_state: {"kind": "update_case_state", "new_state": CaseState.resolved},
        ActionType.request_contractor: {
            "kind": "request_contractor",
            "contractor_person_id": str(uuid4()),
            "body_variants": ["a", "b"],
        },
        ActionType.escalate: {"kind": "escalate", "reason": "legal threat"},
        ActionType.calendar_event: {
            "kind": "calendar_event",
            "title": "Loodgieter Keizersgracht 42-A",
            "start_time": "2026-01-02T11:30:00+01:00",
            "end_time": "2026-01-02T12:30:00+01:00",
            "location": None,
            "contractor_name": None,
            "lockbox_code": None,
            "notes": None,
        },
    }
    assert set(payloads) == set(ActionType)
    for t, p in payloads.items():
        a = _action(type=t, payload=p)
        assert a.payload.kind == t.value
        assert Action.model_validate_json(a.model_dump_json()) == a


def test_type_payload_mismatch_rejected() -> None:
    with pytest.raises(ValidationError):
        _action(type=ActionType.escalate)


@pytest.mark.parametrize("variants", [["only one"], ["a", "b", "c", "d"], ["a", ""], ["a", "   "]])
def test_variant_rules(variants: list[str]) -> None:
    with pytest.raises(ValidationError):
        _action(payload=_reply(body_variants=variants))


def test_naive_reminder_rejected() -> None:
    with pytest.raises(ValidationError):
        _action(
            type=ActionType.create_reminder,
            payload={"kind": "create_reminder", "due_at": "2026-01-02T08:00:00", "note": "x"},
        )


@pytest.mark.parametrize("kw", [{"draft_version": 0}, {"rationale": ""}, {"rationale": "  "}])
def test_bounds(kw: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _action(**kw)


def test_payload_has_no_recipient_field() -> None:
    with pytest.raises(ValidationError):
        _action(payload=_reply(to="anyone@example.de"))


def test_mismatch_reports_single_clear_error() -> None:
    with pytest.raises(ValidationError) as exc:
        _action(type=ActionType.escalate)
    assert exc.value.error_count() == 1
    assert "does not match action type" in str(exc.value)
