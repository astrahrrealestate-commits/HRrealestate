"""PageContext: the page the Super Agent was opened on. Limits are rejected, never silently truncated."""

import base64
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts import Channel, PageContext, PageView
from app.contracts.page_context import MAX_SNAPSHOT, MAX_VISIBLE_ID, VisibleKind, collapse, visible_kind
from app.contracts.thread_key import MAX_REF_LEN, MAX_THREAD_KEY, encode_thread_key

KEY = encode_thread_key(Channel.gmail, "<abc@mail.test>")


def _page(**kw: object) -> PageContext:
    return PageContext.model_validate({"view": "case", **kw})


def test_minimal_page_has_no_entity_and_no_snapshot() -> None:
    page = PageContext.model_validate({"view": "inbox"})
    assert page.view is PageView.inbox
    assert (page.case_id, page.thread_key, page.approval_id, page.task_ref, page.attachment_id) == (None,) * 5
    assert (page.filters, page.visible_ids, page.snapshot) == ({}, [], "")


def test_entity_ids_are_accepted_and_task_ref_normalised() -> None:
    cid, aid = uuid4(), uuid4()
    page = _page(case_id=str(cid), thread_key=KEY, approval_id=str(aid), task_ref="#A1B2C3", attachment_id=str(aid))
    assert (page.case_id, page.thread_key, page.approval_id, page.task_ref) == (cid, KEY, aid, "a1b2c3")


@pytest.mark.parametrize(
    "field",
    [
        {"view": "nope"},
        {"thread_key": "not a key!"},
        {"thread_key": "Zm9v"},  # decodes to "foo": no channel separator
        {"thread_key": encode_thread_key(Channel.gmail, "x").replace("Z", "*")},
        {"task_ref": "a1b2c"},
        {"task_ref": "a1b2c3d4e"},
        {"task_ref": "%%%%%%"},
        {"case_id": "a1b2c3"},
        {"unknown": "x"},
    ],
)
def test_invalid_fields_are_rejected(field: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _page(**field)


def test_invalid_thread_key_with_a_bad_channel_is_rejected() -> None:
    bad = base64.urlsafe_b64encode(b"fax:123").decode().rstrip("=")
    with pytest.raises(ValidationError):
        _page(thread_key=bad)


def test_filters_limits() -> None:
    assert _page(filters={"status": "pending"}).filters == {"status": "pending"}
    with pytest.raises(ValidationError):
        _page(filters={f"k{i}": "v" for i in range(11)})
    with pytest.raises(ValidationError):
        _page(filters={"k" * 41: "v"})
    with pytest.raises(ValidationError):
        _page(filters={"k": "v" * 121})
    with pytest.raises(ValidationError):
        _page(filters={"k": "a\nb"})
    with pytest.raises(ValidationError):
        _page(filters={" ": "v"})


def test_visible_ids_accept_uuids_keys_and_refs_up_to_fifty() -> None:
    ids = [str(uuid4()) for _ in range(48)] + [KEY, "#ABCDEF"]
    page = _page(visible_ids=ids)
    assert len(page.visible_ids) == 50
    assert page.visible_ids[-1] == "abcdef"


@pytest.mark.parametrize("n", [51, 1000])
def test_too_many_visible_ids_is_rejected_not_truncated(n: int) -> None:
    with pytest.raises(ValidationError):
        _page(visible_ids=[str(uuid4()) for _ in range(n)])


@pytest.mark.parametrize("value", ["hello world", "x" * 121, "<script>", "approve all", "", "A" * (MAX_THREAD_KEY + 1)])
def test_visible_ids_must_be_id_shaped(value: str) -> None:
    with pytest.raises(ValidationError):
        _page(visible_ids=[value])


def test_a_long_gmail_message_id_thread_key_is_a_valid_visible_id() -> None:
    ref = "<CAF" + "x" * 230 + "@mail.gmail.com>"
    key = encode_thread_key(Channel.gmail, ref[:MAX_REF_LEN])
    assert MAX_VISIBLE_ID < len(key) <= MAX_THREAD_KEY
    assert _page(visible_ids=[key], thread_key=key).visible_ids == [key]


def test_the_thread_key_limit_covers_the_longest_ref() -> None:
    assert len(encode_thread_key(Channel.whatsapp, "x" * MAX_REF_LEN)) <= MAX_THREAD_KEY


def test_visible_kind() -> None:
    assert visible_kind(str(uuid4())) is VisibleKind.uuid
    assert visible_kind("a1b2c3") is VisibleKind.task_ref
    assert visible_kind(KEY) is VisibleKind.thread_key
    assert visible_kind("nope nope") is None


def test_snapshot_whitespace_is_collapsed() -> None:
    page = _page(snapshot="  Case  Sanne\t\t·  leak \n\n\n   Status:   open  \n\t\n")
    assert page.snapshot == "Case Sanne · leak\nStatus: open"
    assert collapse("a\n\n b ") == "a\nb"


def test_blank_snapshot_means_no_snapshot() -> None:
    assert _page(snapshot=" \n\t \n").snapshot == ""


def test_snapshot_at_the_limit_is_kept_and_one_more_is_rejected() -> None:
    assert len(_page(snapshot="x" * MAX_SNAPSHOT).snapshot) == MAX_SNAPSHOT
    with pytest.raises(ValidationError):
        _page(snapshot="x" * (MAX_SNAPSHOT + 1))


def test_snapshot_that_fits_only_after_collapsing_is_accepted() -> None:
    page = _page(snapshot="ab" + " " * 7000 + "cd")
    assert page.snapshot == "ab cd"


def test_huge_raw_snapshot_is_rejected_before_collapsing() -> None:
    with pytest.raises(ValidationError):
        _page(snapshot=" " * 30_000)


@pytest.mark.parametrize("ch", ["\x00", "\x07", "\x0b", "\x0c", "\x1b", "\x7f", "\x85"])
def test_snapshot_control_characters_are_rejected(ch: str) -> None:
    with pytest.raises(ValidationError):
        _page(snapshot=f"before{ch}after")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("before\r\nafter", "before\nafter"),
        ("before\rafter", "before\nafter"),
        ("a\r\n\r\nb\rc\n", "a\nb\nc"),
        ("Case \r\n  Status:\topen\r", "Case\nStatus: open"),
    ],
)
def test_snapshot_line_breaks_are_normalised_to_lf(raw: str, expected: str) -> None:
    assert _page(snapshot=raw).snapshot == expected


def test_dump_round_trips_for_storage() -> None:
    page = _page(case_id=str(uuid4()), visible_ids=[KEY], snapshot="a  b", filters={"s": "x"})
    assert PageContext.model_validate(page.model_dump(mode="json")) == page
