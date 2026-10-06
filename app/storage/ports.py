"""Object storage port: media, attachments, imports. Keys are validated relative paths."""

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    sha256: str
    content_type: str


class ObjectStorage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> StoredObject: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...


def validate_key(key: str) -> str:
    """Relative, normalised, no traversal: every adapter (fs or s3) stores exactly what it was given."""
    if not key or key.startswith("/") or "\\" in key or key.endswith("/"):
        raise ValueError(f"invalid storage key: {key!r}")
    if any(part in ("", ".", "..") for part in key.split("/")):
        raise ValueError(f"invalid storage key: {key!r}")
    return key


def content_key(company_id: UUID, sha256: str, prefix: str = "media") -> str:
    if not _SHA256.fullmatch(sha256):
        raise ValueError("sha256 must be 64 lowercase hex characters")
    return validate_key(f"{prefix}/{company_id}/{sha256[:2]}/{sha256}")


def describe(key: str, data: bytes, content_type: str) -> StoredObject:
    return StoredObject(key=key, size=len(data), sha256=hashlib.sha256(data).hexdigest(), content_type=content_type)
