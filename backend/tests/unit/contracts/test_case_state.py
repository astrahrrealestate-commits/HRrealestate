import itertools

import pytest

from app.contracts import CaseState as S
from app.contracts import assert_transition, can_transition
from app.core.errors import IllegalTransitionError

LEGAL = {
    (S.open, S.waiting_on_owner),
    (S.open, S.waiting_on_third_party),
    (S.open, S.resolved),
    (S.open, S.closed),
    (S.waiting_on_owner, S.open),
    (S.waiting_on_owner, S.resolved),
    (S.waiting_on_owner, S.closed),
    (S.waiting_on_third_party, S.open),
    (S.waiting_on_third_party, S.resolved),
    (S.waiting_on_third_party, S.closed),
    (S.resolved, S.open),
    (S.resolved, S.closed),
}


@pytest.mark.parametrize(("a", "b"), list(itertools.product(S, S)))
def test_full_matrix(a: S, b: S) -> None:
    assert can_transition(a, b) is ((a, b) in LEGAL)
    if (a, b) in LEGAL:
        assert_transition(a, b)
    else:
        with pytest.raises(IllegalTransitionError):
            assert_transition(a, b)


def test_allowed_table_is_read_only() -> None:
    from app.contracts import ALLOWED

    with pytest.raises(TypeError):
        ALLOWED[S.closed] = frozenset({S.open})  # type: ignore[index]
