"""Case lifecycle state machine."""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from app.core.errors import IllegalTransitionError


class CaseState(StrEnum):
    open = "open"
    waiting_on_owner = "waiting_on_owner"
    waiting_on_third_party = "waiting_on_third_party"
    resolved = "resolved"
    closed = "closed"


_S = CaseState
ALLOWED: Mapping[CaseState, frozenset[CaseState]] = MappingProxyType(
    {
        _S.open: frozenset({_S.waiting_on_owner, _S.waiting_on_third_party, _S.resolved, _S.closed}),
        _S.waiting_on_owner: frozenset({_S.open, _S.resolved, _S.closed}),
        _S.waiting_on_third_party: frozenset({_S.open, _S.resolved, _S.closed}),
        _S.resolved: frozenset({_S.open, _S.closed}),
        _S.closed: frozenset(),
    }
)


def can_transition(current: CaseState, new: CaseState) -> bool:
    return new in ALLOWED[current]


def assert_transition(current: CaseState, new: CaseState) -> None:
    if not can_transition(current, new):
        raise IllegalTransitionError(f"case cannot move from {current} to {new}")
