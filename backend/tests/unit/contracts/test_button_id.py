import contextlib
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.contracts import MAX_BUTTON_ID_LEN, ButtonChoice, ButtonId
from app.core.errors import InvalidButtonIdError


def test_round_trip_all_choices() -> None:
    for c in ButtonChoice:
        b = ButtonId(approval_id=uuid4(), choice=c)
        raw = b.render()
        assert len(raw) <= MAX_BUTTON_ID_LEN
        assert ButtonId.parse(raw) == b


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "apr:x:ok",
        "apr:{u}:OK",
        "apr:{u}:ok:extra",
        " apr:{u}:ok",
        "apr:{u}:ok ",
        "rej:{u}:ok",
        "apr:{u}:",
        "apr::ok",
    ],
)
def test_malformed(raw: str) -> None:
    with pytest.raises(InvalidButtonIdError):
        ButtonId.parse(raw.format(u=uuid4()))


@given(st.text(max_size=300))
def test_fuzz_only_invalid_button_id(raw: str) -> None:
    with contextlib.suppress(InvalidButtonIdError):
        ButtonId.parse(raw)


@pytest.mark.parametrize("raw", [None, 123, b"apr:x:ok", ["apr"]])
def test_non_string_input(raw: object) -> None:
    with pytest.raises(InvalidButtonIdError):
        ButtonId.parse(raw)


def _mutations(valid: str) -> st.SearchStrategy[str]:
    idx = st.integers(min_value=0, max_value=len(valid) - 1)
    return st.one_of(
        idx.map(lambda i: valid[:i] + valid[i].swapcase() + valid[i + 1 :]).filter(lambda s: s != valid),
        idx.map(lambda i: valid[:i] + valid[i + 1 :]),
        st.sampled_from([" ", "\n", "\t", ":", "x"]).flatmap(lambda c: st.sampled_from([c + valid, valid + c])),
        st.just(valid.replace("-", "")),
    )


_VALID = ButtonId(approval_id=uuid4(), choice=ButtonChoice.ok).render()


@given(_mutations(_VALID))
def test_near_miss_ids_rejected(raw: str) -> None:
    with pytest.raises(InvalidButtonIdError):
        ButtonId.parse(raw)
