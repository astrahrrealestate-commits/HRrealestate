"""Build inbound-side channel adapters from settings (fakes by default). Outbound adapters are built in app.sender."""

import json
import re
import threading
from collections.abc import Sequence
from functools import lru_cache
from uuid import UUID

from googleapiclient.discovery import build
from sqlalchemy import Engine

from app.channels import google_store
from app.channels.brixx.fake import FakeBrixxApi
from app.channels.brixx.http import HttpBrixxApi
from app.channels.brixx.ports import BrixxApi
from app.channels.gmail.fake import DirMailboxStore, FakeMailbox
from app.channels.gmail.google import READ_SCOPES, GoogleMailbox
from app.channels.gmail.ports import GmailMailbox
from app.channels.gmail.push import (
    DEV_AUDIENCE,
    DEV_SERVICE_ACCOUNT,
    PushVerifier,
    google_push_verifier,
    local_push_verifier,
)
from app.channels.google_chat.verifier import ChatVerifier
from app.channels.prices.gemini_search import GeminiSearchClient
from app.channels.prices.search import FakeSearchClient, SearchClient, UnconfiguredSearchClient
from app.channels.whatsapp.fake_media import DirWhatsAppMedia
from app.channels.whatsapp.media import HttpWhatsAppMedia, WhatsAppMedia
from app.channels.whatsapp.media_settings import WhatsAppMediaSettings
from app.core.errors import GmailNotConnectedError, UnsafeConfigurationError
from app.core.settings import Settings, get_settings


@lru_cache(maxsize=1)
def _media_credentials() -> WhatsAppMediaSettings:
    """Read once per process (not per download)."""

    return WhatsAppMediaSettings()


def whatsapp_media(
    settings: Settings,
    phone_number_id: str,
    *,
    media_settings: WhatsAppMediaSettings | None = None,
) -> WhatsAppMedia:
    """Media adapter for the number that received the message (360dialog keys are per number)."""

    if settings.whatsapp_provider == "fake":
        return fake_whatsapp_media(settings)

    tokens = (media_settings or _media_credentials()).whatsapp_media_tokens

    if not settings.whatsapp_api_base_url or phone_number_id not in tokens:
        raise UnsafeConfigurationError(f"no WhatsApp media credentials for phone_number_id {phone_number_id}")

    token = tokens[phone_number_id].get_secret_value()

    if settings.whatsapp_provider == "360dialog":
        return HttpWhatsAppMedia.dialog360(settings.whatsapp_api_base_url, token)

    return HttpWhatsAppMedia.cloud_api(settings.whatsapp_api_base_url, token)


def fake_whatsapp_media(settings: Settings) -> DirWhatsAppMedia:
    """Shared on-disk fake media (simulator puts, worker downloads)."""

    return DirWhatsAppMedia(settings.storage_local_dir / "fake_whatsapp_media")


def channel_problems(settings: Settings, media_settings: WhatsAppMediaSettings | None = None) -> list[str]:
    """Channel readiness for real providers (complements core.startup's checks)."""

    if settings.whatsapp_provider == "fake":
        return []

    tokens = (media_settings or _media_credentials()).whatsapp_media_tokens

    return [] if tokens else ["WHATSAPP_MEDIA_TOKENS is empty (needed for inbound media download)"]


def assert_channels_ready(settings: Settings, media_settings: WhatsAppMediaSettings | None = None) -> None:
    problems = channel_problems(settings, media_settings)

    if problems and settings.env == "prod":
        raise UnsafeConfigurationError("refusing to start in prod: " + "; ".join(problems))


_MAILBOX = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")


def _mailbox_address(address: str) -> str:
    normalised = address.strip().lower()

    if not _MAILBOX.fullmatch(normalised) or ".." in normalised:
        raise UnsafeConfigurationError(f"invalid mailbox address {address[:80]!r}")

    return normalised


def fake_gmail_mailbox(settings: Settings, address: str) -> FakeMailbox:
    """Shared on-disk fake mailbox (simulator writes, api/worker read); the address is validated before it becomes

    a directory name."""

    address = _mailbox_address(address)

    return FakeMailbox(address, DirMailboxStore(settings.storage_local_dir / "fake_gmail" / address))


_local_mailboxes = threading.local()


OWNER_LOGIN_FILE = google_store.LOCAL_FILE


def owner_login_email(settings: Settings | None = None) -> str | None:
    """The address the dashboard's Google login was granted for, if someone connected one (in any process: the
    connect callback runs in the API, the Gmail poll in the worker)."""
    path = google_store.refresh(settings or get_settings())
    if not path.exists():
        return None
    return str(json.loads(path.read_text()).get("email") or "").lower() or None


def gmail_mailbox(settings: Settings, address: str) -> GmailMailbox:
    owner_email = owner_login_email(settings)
    if owner_email and settings.gmail_provider == "fake" and _mailbox_address(address) != owner_email:
        return fake_gmail_mailbox(settings, address)  # the login covers its own mailbox only; dev mailboxes stay fake
    cred_file = OWNER_LOGIN_FILE if owner_email else settings.gmail_credentials_file
    if settings.gmail_provider == "fake" and not (cred_file and cred_file.exists()):
        return fake_gmail_mailbox(settings, address)
    if not cred_file or not cred_file.exists():
        raise GmailNotConnectedError("gmail_provider 'google' has no connected Google account or credentials file")

    addr = _mailbox_address(address)

    cache: dict[tuple[str, str, int], GmailMailbox] | None = getattr(_local_mailboxes, "cache", None)

    if cache is None:
        cache = {}

        _local_mailboxes.cache = cache

    key = (str(cred_file), addr, cred_file.stat().st_mtime_ns)  # a reconnect (new tokens) builds a new mailbox

    if key in cache:
        return cache[key]

    from google.oauth2.credentials import Credentials

    # The login file keeps the scopes it was granted (gmail.modify covers reading); refreshing with another scope fails.
    creds = Credentials.from_authorized_user_file(str(cred_file), None if owner_email else READ_SCOPES)

    mailbox = GoogleMailbox(build("gmail", "v1", credentials=creds, cache_discovery=False), addr)

    mailbox.verify_address()  # never read another account's mail under this company

    cache[key] = mailbox

    return mailbox


def gmail_push_verifier(settings: Settings) -> PushVerifier:
    if settings.gmail_provider == "fake":
        audience = settings.gmail_pubsub_audience or DEV_AUDIENCE

        account = settings.gmail_pubsub_service_account or DEV_SERVICE_ACCOUNT

        return local_push_verifier(settings.dev_signing_dir, audience, account)

    if not settings.gmail_pubsub_audience or not settings.gmail_pubsub_service_account:
        if settings.env == "prod":
            raise UnsafeConfigurationError("google push verification needs GMAIL_PUBSUB_AUDIENCE and _SERVICE_ACCOUNT")

        # Local testing with a real mailbox and no Pub/Sub yet (`make gmail-pull`): the API still boots, and every

        # push is answered 401 because no signing key can ever match.

        return PushVerifier("pull-only", "pull-only@invalid", lambda _force_refresh: {})

    return google_push_verifier(settings.gmail_pubsub_audience, settings.gmail_pubsub_service_account)


def google_chat_verifier(settings: Settings) -> ChatVerifier:
    return ChatVerifier(
        project_number=settings.google_chat_project_number,
        provider=settings.google_chat_provider,
    )


def brixx_api(settings: Settings) -> BrixxApi:
    """BRIXX read API: in-process fake by default; the HTTP adapter needs a token (never logged)."""

    if settings.brixx_provider == "fake":
        return FakeBrixxApi({})

    if settings.brixx_token is None:
        raise UnsafeConfigurationError("brixx_provider 'api' needs brixx_token")

    return HttpBrixxApi(
        settings.brixx_base_url,
        settings.brixx_environment,
        settings.brixx_token,
        settings.brixx_auth_scheme,
        settings.brixx_timeout_sec,
    )


def search_client(
    settings: Settings,
    engine: Engine | None = None,
    company_id: UUID | None = None,
    allowed_domains: Sequence[str] = (),
) -> SearchClient:
    """The web-search adapter for `price_search_provider`. With `engine` and `company_id` a Gemini search is recorded
    in `model_calls` and counts against the budget; `allowed_domains` limits the pages it may return."""
    if settings.price_search_provider == "fake":
        return FakeSearchClient()
    if settings.price_search_provider == "gemini":
        return GeminiSearchClient(settings, engine=engine, company_id=company_id, allowed_domains=allowed_domains)
    return UnconfiguredSearchClient()
