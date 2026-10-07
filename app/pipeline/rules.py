"""Rules engine: pure policy functions over contracts. No I/O imports (import-linter contract).

Phase 1 policy, first match wins: company paused → `paused`; suspicious message → `exception` (Harjot reviews it by
hand); `request_contractor` for someone not on file → `exception`; a second state update or a second reply draft on
the same channel → `drop`; everything else → `pending_approval` (nothing external happens without Harjot).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.contracts import Action, ActionType, ReplyDraftPayload, RequestContractorPayload


class Verdict(StrEnum):
    pending_approval = "pending_approval"
    exception = "exception"
    paused = "paused"
    drop = "drop"


@dataclass(frozen=True)
class RuleContext:
    paused: bool
    suspicious: bool
    contractor_ids: frozenset[UUID]


@dataclass(frozen=True)
class RuleDecision:
    action: Action
    verdict: Verdict
    reason: str | None = None


def _duplicate_key(action: Action) -> str | None:
    if action.type is ActionType.update_case_state:
        return "state"
    if isinstance(action.payload, ReplyDraftPayload):
        return f"reply:{action.payload.channel.value}"
    return None


def _decide(action: Action, ctx: RuleContext, seen: set[str]) -> RuleDecision:
    if ctx.paused:
        return RuleDecision(action, Verdict.paused, "company paused")
    if ctx.suspicious:
        return RuleDecision(action, Verdict.exception, "suspicious message")
    payload = action.payload
    if isinstance(payload, RequestContractorPayload) and payload.contractor_person_id not in ctx.contractor_ids:
        return RuleDecision(action, Verdict.exception, "contractor is not on file")
    key = _duplicate_key(action)
    if key is not None and key in seen:
        return RuleDecision(action, Verdict.drop, "duplicate")
    if key is not None:
        seen.add(key)
    return RuleDecision(action, Verdict.pending_approval)


def apply_rules(actions: Sequence[Action], ctx: RuleContext) -> list[RuleDecision]:
    seen: set[str] = set()
    return [_decide(action, ctx, seen) for action in actions]
