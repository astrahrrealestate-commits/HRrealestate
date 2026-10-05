"""Domain error hierarchy. Everything EstateOS raises on purpose subclasses EstateOSError."""


class EstateOSError(Exception):
    """Base for all deliberate EstateOS errors."""


class IllegalTransitionError(EstateOSError):
    """A case state change not allowed by the state machine."""


class InvalidButtonIdError(EstateOSError, ValueError):
    """A WhatsApp reply-button id that does not match `apr:<uuid>:<choice>`."""


class PromptNotFoundError(EstateOSError):
    """No prompt file exists for the requested name/version."""


class NotFoundError(EstateOSError):
    """A requested row does not exist (within the caller's company)."""


class TenantMismatchError(EstateOSError):
    """A row belongs to a different company than the caller."""
