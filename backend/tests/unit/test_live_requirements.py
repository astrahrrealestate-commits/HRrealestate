from pydantic import SecretStr
from pydantic_settings import BaseSettings

from tests.live.requirements import configured_from, live_requirements, missing


class Fake(BaseSettings):
    whatsapp_provider: str = "fake"
    s3_bucket: str | None = None
    gmail_credentials_file: str | None = None
    gmail_reply_send_credentials_file: str | None = None
    whatsapp_media_tokens: dict[str, SecretStr] = {}
    price_search_provider: str = "none"


def test_missing_lists_unset_names_sorted_once() -> None:
    configured = configured_from({"LIVE_GMAIL_MAILBOX": "x@example.test"}, Fake(s3_bucket="b"))
    required = ["S3_BUCKET", "GMAIL_CREDENTIALS_FILE", "LIVE_GMAIL_MAILBOX", "WHATSAPP_MEDIA_TOKENS", "S3_BUCKET"]
    assert missing(required, configured) == ["GMAIL_CREDENTIALS_FILE", "WHATSAPP_MEDIA_TOKENS"]


def test_blank_values_count_as_missing() -> None:
    configured = configured_from({"LIVE_WHATSAPP_OWNER": "  "}, Fake(s3_bucket=""))
    assert missing(["LIVE_WHATSAPP_OWNER", "S3_BUCKET"], configured) == ["LIVE_WHATSAPP_OWNER", "S3_BUCKET"]


def test_real_settings_are_judged_by_parsed_value_not_raw_environment() -> None:
    configured = configured_from({"WHATSAPP_MEDIA_TOKENS": "{}", "S3_BUCKET": "from-shell"}, Fake())
    assert missing(["WHATSAPP_MEDIA_TOKENS", "S3_BUCKET"], configured) == ["S3_BUCKET", "WHATSAPP_MEDIA_TOKENS"]


def test_settings_values_count_even_without_environment() -> None:
    """Settings may come from .env, which never reaches os.environ."""
    configured = configured_from({}, Fake(whatsapp_media_tokens={"1": SecretStr("t")}))
    assert missing(["WHATSAPP_MEDIA_TOKENS"], configured) == []


def test_provider_left_on_fake_is_missing() -> None:
    assert missing(["WHATSAPP_PROVIDER"], configured_from({}, Fake())) == ["WHATSAPP_PROVIDER"]
    assert missing(["WHATSAPP_PROVIDER"], configured_from({}, Fake(whatsapp_provider="360dialog"))) == []


def test_search_provider_left_on_none_or_fake_is_missing() -> None:
    for unset in ("none", "fake"):
        got = missing(["PRICE_SEARCH_PROVIDER"], configured_from({}, Fake(price_search_provider=unset)))
        assert got == ["PRICE_SEARCH_PROVIDER"]
    assert missing(["PRICE_SEARCH_PROVIDER"], configured_from({}, Fake(price_search_provider="tavily"))) == []


def test_outbound_lists_the_reply_send_token_and_mailbox_when_missing() -> None:
    required = live_requirements("outbound")
    assert missing(required, configured_from({}, Fake())) == [
        "GMAIL_CREDENTIALS_FILE",
        "GMAIL_REPLY_SEND_CREDENTIALS_FILE",
        "LIVE_GMAIL_MAILBOX",
    ]
    configured = configured_from(
        {"LIVE_GMAIL_MAILBOX": "me@example.test"},
        Fake(gmail_credentials_file="read.json", gmail_reply_send_credentials_file="send.json"),
    )
    assert missing(required, configured) == []


def test_outbound_never_asks_for_the_compose_token() -> None:
    assert "GMAIL_SEND_CREDENTIALS_FILE" not in live_requirements("outbound")
