"""Gmail adapter construction — compose- and send-scoped credentials live only here, in separate token files.

`gmail.compose` can technically call `messages.send` as well, so the OAuth scope alone does not stop the drafts
token from sending. The separation is enforced in code: `assert_allowed` limits `send_message` to the owner's own
email addresses, and tenant replies only ever use `build_gmail_sender` (GMAIL_REPLY_SEND_CREDENTIALS_FILE).
"""

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.channels.gmail.drafts import COMPOSE_SCOPES, SEND_SCOPES, FakeDrafts, GmailDrafts, GoogleDrafts
from app.channels.gmail.fake import FakeMailbox
from app.core.errors import UnsafeConfigurationError
from app.core.settings import Settings
from app.sender.settings import SenderSettings


def build_gmail_drafts(
    settings: Settings, sender: SenderSettings, address: str, fake_mailbox: FakeMailbox | None = None
) -> GmailDrafts:
    if settings.gmail_provider == "fake":
        if fake_mailbox is None:
            raise UnsafeConfigurationError("fake gmail drafts need the fake mailbox they write into")
        return FakeDrafts(fake_mailbox)
    if not sender.gmail_send_credentials_file:
        raise UnsafeConfigurationError("gmail drafts need GMAIL_SEND_CREDENTIALS_FILE (gmail.compose scope)")
    creds = Credentials.from_authorized_user_file(str(sender.gmail_send_credentials_file), COMPOSE_SCOPES)
    return GoogleDrafts(build("gmail", "v1", credentials=creds, cache_discovery=False), address)


def gmail_send_configured(settings: Settings, sender: SenderSettings) -> bool:
    """Tenant Gmail replies need their own `gmail.send` token; the drafts token is never used to send to tenants."""
    return settings.gmail_provider == "fake" or sender.gmail_reply_send_credentials_file is not None


def build_gmail_sender(
    settings: Settings, sender: SenderSettings, address: str, fake_mailbox: FakeMailbox | None = None
) -> GmailDrafts:
    """The adapter used only for `send_reply` (send mode), built from GMAIL_REPLY_SEND_CREDENTIALS_FILE."""
    if settings.gmail_provider == "fake":
        if fake_mailbox is None:
            raise UnsafeConfigurationError("fake gmail sending needs the fake mailbox it writes into")
        return FakeDrafts(fake_mailbox)
    if not sender.gmail_reply_send_credentials_file:
        raise UnsafeConfigurationError("tenant replies need GMAIL_REPLY_SEND_CREDENTIALS_FILE (gmail.send scope)")
    creds = Credentials.from_authorized_user_file(str(sender.gmail_reply_send_credentials_file), SEND_SCOPES)
    return GoogleDrafts(build("gmail", "v1", credentials=creds, cache_discovery=False), address)
