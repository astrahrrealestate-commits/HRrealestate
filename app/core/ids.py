"""Identifier generation. UUIDv7: time-ordered, so primary-key indexes stay append-friendly."""

import uuid

from uuid_utils.compat import uuid7


def new_id() -> uuid.UUID:
    return uuid7()
