"""Domain error hierarchy. Everything EstateOS raises on purpose subclasses EstateOSError."""


class EstateOSError(Exception):
    """Base for all deliberate EstateOS errors."""


class IllegalTransitionError(EstateOSError):
    """A case state change not allowed by the state machine."""


class InvalidButtonIdError(EstateOSError, ValueError):
    """A WhatsApp reply-button id that does not match `apr:<uuid>:<choice>`."""


class PromptNotFoundError(EstateOSError):
    """No prompt file exists for the requested name/version."""


class AgentFailedError(EstateOSError):
    """An LLM agent call failed (validation or model error)."""


class BudgetExceededError(AgentFailedError):
    """A company LLM budget or call cap is spent.

    Subclasses AgentFailedError so every call site's existing graceful fallback applies; callers that must wait
    instead of degrading (the understand step) catch it first.
    """

    def __init__(self, scope: str) -> None:
        super().__init__(f"llm limit reached: {scope}")
        self.scope = scope


class NotFoundError(EstateOSError):
    """A requested row does not exist (within the caller's company)."""


class PersonalDocumentError(EstateOSError):
    """A person's own document (linked to them, their lease, unit or case, or an ID) asked to join the reference
    library, which every dossier reads."""


class DiligenceRequestError(EstateOSError):
    """A due diligence request the caller must fix (no documents, too many, review not restartable)."""


class TenantMismatchError(EstateOSError):
    """A row belongs to a different company than the caller."""


class PriceSourceNotConfiguredError(EstateOSError):
    """The configured market price source has no adapter wired up."""


class SnapshotNotApplicableError(EstateOSError):
    """A decision-day price snapshot was asked for an action that is not a request_contractor with a contractor."""


class UnsafeConfigurationError(EstateOSError):
    """Settings that must never reach production (fake providers, local storage, missing webhook secrets)."""


class GmailNotConnectedError(UnsafeConfigurationError):
    """A Gmail mailbox with no Google account connected yet: a state the owner ends in the Connections modal."""


class WebhookRejectedError(EstateOSError):
    """An inbound provider request failed verification (signature, token, OIDC). Nothing may be written."""


class UnroutableMessageError(EstateOSError):
    """A provider message whose sender cannot be identified (no usable phone/email). Stored, never retried."""


class WebhookTooLargeError(WebhookRejectedError):
    """Body above the accepted maximum. Routes answer 413 before verification; parsing raises, never drops silently."""


class IgnoredMessageError(EstateOSError):
    """A provider item that is deliberately not a conversation message (Gmail DRAFT/SPAM/TRASH/CHAT).

    Stored as a raw event, never processed further.
    """


class PushRejectedError(WebhookRejectedError):
    """A Pub/Sub push that failed OIDC verification or carried a malformed envelope."""


class BrixxError(EstateOSError):
    """A BRIXX API call failed or returned something unusable (transport, status, malformed body)."""


class BrixxAuthError(BrixxError):
    """BRIXX rejected the token (401/403). Retrying cannot help until the token is replaced."""


class BrixxNotFoundError(BrixxError):
    """BRIXX returned 404 for a resource addressed by its own API (a table, data page or document). Retrying
    the identical request cannot change a 404 into something else, whatever the resource turned out to be missing
    or never existing for: seen for a table BRIXX's own listing names but whose describe endpoint refuses it
    (Postgres/SQL-standard system catalog names it lists but does not actually expose)."""


class StaleRunError(BrixxError):
    """A BRIXX table sync step belongs to a run that no longer owns the table's resume point (or skipped a page)."""


class BrixxStoreError(BrixxError):
    """The mirror database rejected a page. The message names only the DB error class, table and page."""


class TranslationUnavailableError(EstateOSError):
    """The local translation model is not installed (or could not be loaded), so nothing can be translated."""
