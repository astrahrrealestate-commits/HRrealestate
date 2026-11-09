"""Identifier generation. UUIDv7: time-ordered, so primary-key indexes stay append-friendly."""

import uuid

from uuid_utils.compat import uuid7


def new_id() -> uuid.UUID:
    return uuid7()


CASE_REF_LEN = 6


def case_ref(case_id: uuid.UUID) -> str:
    """The short ticket reference shown to people: the random tail of the UUIDv7 (the head is a timestamp, so
    cases created together share it)."""
    return case_id.hex[-CASE_REF_LEN:]
