"""In-process storage for tests."""

from app.core.errors import NotFoundError
from app.storage.ports import StoredObject, clamp_ttl, describe, validate_key


class MemoryStorage:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        self._objects[validate_key(key)] = data
        return describe(key, data, content_type)

    def get(self, key: str) -> bytes:
        try:
            return self._objects[validate_key(key)]
        except KeyError as exc:
            raise NotFoundError(key) from exc

    def exists(self, key: str) -> bool:
        return validate_key(key) in self._objects

    def presigned_url(self, key: str, ttl_seconds: int) -> str:
        return f"memory://{validate_key(key)}?expires_in={clamp_ttl(ttl_seconds)}"
