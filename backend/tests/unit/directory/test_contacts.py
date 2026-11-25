"""Contact input rules that need no database: categories, trades and email/phone normalisation."""

import pytest

from app.contracts import Channel
from app.db.enums import PersonKind
from app.directory.contacts import InvalidContactError, _clean_name, _identity, _trade, category_of


@pytest.mark.parametrize(
    ("kind", "trade", "expected"),
    [
        (PersonKind.tenant, None, "tenant"),
        (PersonKind.contractor, "plumber", "contractor"),
        (PersonKind.owner, None, "owner"),
        (PersonKind.other, None, "other"),
        (PersonKind.other, "notary", "other"),
        (PersonKind.other, "legal", "legal"),
        (PersonKind.other, "vve", "vve"),
        (PersonKind.other, "business", "business"),
        (PersonKind.other, "Utility", "utility"),
        (PersonKind.other, "municipal", "municipal"),
        (PersonKind.contractor, "utility", "contractor"),
    ],
)
def test_category_of(kind: PersonKind, trade: str | None, expected: str) -> None:
    assert category_of(kind, trade) == expected


def test_utility_and_municipal_ignore_a_typed_trade() -> None:
    assert _trade("utility", "plumber") == "utility"
    assert _trade("municipal", None) == "municipal"
    assert _trade("legal", "anything") == "legal"
    assert _trade("vve", None) == "vve"
    assert _trade("business", "bank") == "business"


def test_trade_is_trimmed_and_blank_means_none() -> None:
    assert _trade("contractor", "  roof   leaks ") == "roof leaks"
    assert _trade("contractor", "   ") is None
    assert _trade("tenant", None) is None


def test_unknown_category_is_refused() -> None:
    with pytest.raises(InvalidContactError):
        _trade("landlord", None)


def test_name_is_collapsed_and_required() -> None:
    assert _clean_name("  Jan   de  Vries ") == "Jan de Vries"
    with pytest.raises(InvalidContactError):
        _clean_name("  \n ")


@pytest.mark.parametrize(
    ("channel", "raw", "expected"),
    [
        (Channel.gmail, " Jan@Example.TEST ", "jan@example.test"),
        (Channel.whatsapp, "06 12345678", "+31612345678"),
        (Channel.whatsapp, "+49 151 23456789", "+4915123456789"),
        (Channel.gmail, "", None),
        (Channel.whatsapp, None, None),
        (Channel.whatsapp, "   ", None),
    ],
)
def test_identity_normalisation(channel: Channel, raw: str | None, expected: str | None) -> None:
    assert _identity(channel, raw) == expected


@pytest.mark.parametrize(
    ("channel", "raw"),
    [
        (Channel.gmail, "nope"),
        (Channel.gmail, "+31612345678"),
        (Channel.whatsapp, "jan@example.test"),
        (Channel.whatsapp, "12"),
    ],
)
def test_identity_rejects_the_wrong_kind_or_garbage(channel: Channel, raw: str) -> None:
    with pytest.raises(InvalidContactError):
        _identity(channel, raw)
