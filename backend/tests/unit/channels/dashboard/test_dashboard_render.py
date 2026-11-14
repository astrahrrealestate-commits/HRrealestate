from uuid import UUID, uuid4

import pytest
from syrupy.assertion import SnapshotAssertion

from app.channels.dashboard.feed import kind_for_key, ref_for_key, stored_key
from app.channels.dashboard.render import to_payload
from app.contracts import OwnerChoice, OwnerMessage
from app.db.enums import FeedKind
from app.owner.cards import document_choice_id, document_review_key

APPROVAL = "11111111-1111-4111-8111-111111111111"


def test_three_choice_card_payload(snapshot: SnapshotAssertion) -> None:
    msg = OwnerMessage(
        text="Choose a draft, edit or reject.",
        header="Reply: Sanne · maintenance",
        choices=(
            OwnerChoice(f"apr:{APPROVAL}:d1", "Send draft 1", "Dag Sanne, de monteur komt morgen"),
            OwnerChoice(f"apr:{APPROVAL}:edit", "Edit"),
            OwnerChoice(f"apr:{APPROVAL}:rej", "Reject"),
        ),
        menu_title="Options",
    )
    assert to_payload(msg) == snapshot


def test_plain_message_has_empty_choices() -> None:
    assert to_payload(OwnerMessage(text="hi")) == {"text": "hi", "header": None, "choices": [], "menu_title": None}


@pytest.mark.parametrize(
    ("key", "kind"),
    [
        (f"approval:{APPROVAL}:0", FeedKind.approval),
        (f"apr:{APPROVAL}:d1", FeedKind.approval),
        (document_review_key(UUID(APPROVAL)), FeedKind.document_review),  # the key documents.review_card_step uses
        (document_choice_id(UUID(APPROVAL), "lease"), FeedKind.alert),  # a button id, never a feed key
        (f"memreview:{APPROVAL}", FeedKind.memory_review),
        ("briefing:abc", FeedKind.briefing),
        ("weekly:abc", FeedKind.briefing),
        ("blocked:x", FeedKind.alert),
        ("nudge:x", FeedKind.alert),
        ("alert:x", FeedKind.alert),
        ("exception:x", FeedKind.alert),
        ("drift:c:2026-10-15", FeedKind.alert),
        ("owner_reply:1:0", FeedKind.alert),
    ],
)
def test_kind_from_key_prefix(key: str, kind: FeedKind) -> None:
    assert kind_for_key(key) is kind


def test_ref_id_only_for_approval_and_document_keys() -> None:
    assert ref_for_key(f"approval:{APPROVAL}:0", FeedKind.approval) == UUID(APPROVAL)
    review = document_review_key(APPROVAL)
    assert ref_for_key(review, kind_for_key(review)) == UUID(APPROVAL)
    assert ref_for_key(f"memreview:{APPROVAL}", FeedKind.memory_review) == UUID(APPROVAL)
    assert ref_for_key(f"briefing:{uuid4()}", FeedKind.briefing) is None
    assert ref_for_key("approval:a:0", FeedKind.approval) is None  # not a UUID: no ref, no crash


def test_stored_key_is_namespaced_by_company_and_fits_the_column() -> None:
    a, b = uuid4(), uuid4()
    assert stored_key(a, "k") == f"{a}:k"
    assert stored_key(a, "k") != stored_key(b, "k")
    long = stored_key(a, "x" * 400)
    assert len(long) == 255
    assert long.startswith(f"{a}:")
