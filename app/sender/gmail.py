"""Gmail drafts adapter construction — compose-scoped credentials live only here."""

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.channels.gmail.drafts import COMPOSE_SCOPES, FakeDrafts, GmailDrafts, GoogleDrafts
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
