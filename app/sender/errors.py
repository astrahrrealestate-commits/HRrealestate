"""Sender errors, in their own module so recipient and targets can share them without importing each other."""

from app.core.errors import EstateOSError


class SendBlockedError(EstateOSError):
    """The action cannot be delivered within the Phase 1 rules (no thread, no owner number, not allowed)."""
