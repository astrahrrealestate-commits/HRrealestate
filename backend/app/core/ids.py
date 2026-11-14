"""Identifier generation. UUIDv7: time-ordered, so primary-key indexes stay append-friendly."""

import uuid

from uuid_utils.compat import uuid7


def new_id() -> uuid.UUID:
    return uuid7()


CASE_REF_LEN = 6


def case_ref(case_id: uuid.UUID | str) -> str:
    """The short ticket reference shown to people: the random tail of the UUIDv7 (the head is a timestamp, so
    cases created together share it). Text ids may carry a `case-` prefix; anything that is not an id keeps its
    first characters."""
    raw = str(case_id)
    try:
        return uuid.UUID(raw.removeprefix("case-")).hex[-CASE_REF_LEN:]
    except ValueError:
        return raw[:CASE_REF_LEN]
