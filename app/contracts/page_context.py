"""What the dashboard page the Super Agent was opened on shows (spec amendment 2026-10-16). Request-side only.

The structured ids are validated here for shape and later resolved company-scoped into server facts. `snapshot` and
`filters` are client-supplied display text: UNVERIFIED, so they only ever reach a model inside an escaped data block
and are never an id source, a recipient or a permission (CLAUDE.md invariant 6). Over-limit input is rejected (422),
never truncated into a different meaning.
"""

import re
import unicodedata
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, Field, field_validator

from app.contracts.common import Contract
from app.contracts.thread_key import BadThreadKeyError, decode_thread_key

MAX_SNAPSHOT = 6000  # characters after whitespace is collapsed
MAX_RAW_SNAPSHOT = 4 * MAX_SNAPSHOT  # bounds the work before collapsing
MAX_FILTERS = 10
MAX_FILTER_KEY = 40
MAX_FILTER_VALUE = 120
MAX_VISIBLE = 50
MAX_VISIBLE_ID = 120
MAX_THREAD_KEY = 400  # base64 of `{channel}:{ref}` with a 255-char ref
TASK_REF = re.compile(r"#?[0-9a-fA-F]{6,8}")
_THREAD_KEY = re.compile(r"[A-Za-z0-9_-]+")
_BLANK_RUN = re.compile(r"[ \t]+")


class PageView(StrEnum):
    inbox = "inbox"
    thread = "thread"
    case = "case"
    approvals = "approvals"
    tasks = "tasks"
    waiting = "waiting"
    documents = "documents"
    briefing = "briefing"
    other = "other"


class VisibleKind(StrEnum):
    uuid = "uuid"
    task_ref = "task_ref"
    thread_key = "thread_key"


def _is_control(ch: str) -> bool:
    return unicodedata.category(ch) == "Cc"


def visible_kind(value: str) -> VisibleKind | None:
    """What a visible row id looks like: a UUID, a 6-8 hex task ref, or a decodable thread key; None otherwise."""
    if TASK_REF.fullmatch(value):
        return VisibleKind.task_ref
    try:
        UUID(value)
        return VisibleKind.uuid
    except ValueError:
        pass
    if not _THREAD_KEY.fullmatch(value):
        return None
    try:
        decode_thread_key(value)
    except BadThreadKeyError:
        return None
    return VisibleKind.thread_key


def _task_ref(value: str) -> str:
    if not TASK_REF.fullmatch(value):
        raise ValueError("task_ref must be 6-8 hex characters")
    return value.lstrip("#").lower()


def _thread_key(value: str) -> str:
    if len(value) > MAX_THREAD_KEY or not _THREAD_KEY.fullmatch(value):
        raise ValueError("invalid thread key")
    try:
        decode_thread_key(value)
    except BadThreadKeyError:
        raise ValueError("invalid thread key") from None
    return value


def _visible_id(value: str) -> str:
    if len(value) > MAX_VISIBLE_ID or visible_kind(value) is None:
        raise ValueError("visible ids must be UUIDs, thread keys or task refs of at most 120 characters")
    kind = visible_kind(value)
    if kind is VisibleKind.task_ref:
        return value.lstrip("#").lower()
    return str(UUID(value)) if kind is VisibleKind.uuid else value


def collapse(text: str) -> str:
    """Runs of spaces/tabs become one space, each line is trimmed and blank lines are dropped (single newlines)."""
    lines = (_BLANK_RUN.sub(" ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


class PageContext(Contract):
    """The open entity ids (trusted only after server-side, company-scoped resolution) and the page's unverified
    display text (`snapshot`, `filters`): never an id source, a recipient or a permission."""

    view: PageView
    case_id: UUID | None = None
    thread_key: Annotated[str, AfterValidator(_thread_key)] | None = None
    approval_id: UUID | None = None
    task_ref: Annotated[str, AfterValidator(_task_ref)] | None = None
    attachment_id: UUID | None = None
    filters: dict[str, str] = Field(default_factory=dict)
    visible_ids: list[Annotated[str, AfterValidator(_visible_id)]] = Field(default_factory=list, max_length=MAX_VISIBLE)
    snapshot: str = Field(default="", json_schema_extra={"maxLength": MAX_SNAPSHOT})

    @field_validator("filters")
    @classmethod
    def _check_filters(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > MAX_FILTERS:
            raise ValueError(f"at most {MAX_FILTERS} filters")
        for key, item in value.items():
            if not key.strip() or len(key) > MAX_FILTER_KEY or len(item) > MAX_FILTER_VALUE:
                raise ValueError(f"filter keys must be 1-{MAX_FILTER_KEY} and values at most {MAX_FILTER_VALUE} chars")
            if any(_is_control(ch) for ch in key + item):
                raise ValueError("filters must not contain control characters")
        return value

    @field_validator("snapshot")
    @classmethod
    def _check_snapshot(cls, value: str) -> str:
        if len(value) > MAX_RAW_SNAPSHOT:
            raise ValueError(f"snapshot must be at most {MAX_SNAPSHOT} characters")
        if any(_is_control(ch) and ch not in "\n\t" for ch in value):
            raise ValueError("snapshot must not contain control characters other than newline and tab")
        collapsed = collapse(value)
        if len(collapsed) > MAX_SNAPSHOT:
            raise ValueError(f"snapshot must be at most {MAX_SNAPSHOT} characters after collapsing whitespace")
        return collapsed
