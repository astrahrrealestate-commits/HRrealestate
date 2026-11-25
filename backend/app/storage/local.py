"""Filesystem storage for dev/compose (shared volume between api and worker). Never used in prod."""

import os
import tempfile
from pathlib import Path
from urllib.parse import urlencode

from app.core.errors import NotFoundError
from app.storage.ports import StoredObject, clamp_ttl, describe, response_overrides, validate_key


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _path(self, key: str) -> Path:
        return self._root / validate_key(key)

    def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent)  # atomic replace: readers never see a partial file
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            Path(tmp).replace(path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return describe(key, data, content_type)

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except (FileNotFoundError, IsADirectoryError) as exc:
            raise NotFoundError(key) from exc

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def presigned_url(
        self, key: str, ttl_seconds: int, *, content_type: str | None = None, disposition: str | None = None
    ) -> str:
        """Dev only: an opaque relative URL with an advisory `expires_in`; nothing serves it, so no real expiry."""
        query = {"expires_in": str(clamp_ttl(ttl_seconds)), **response_overrides(content_type, disposition)}
        return f"/dev-storage/{validate_key(key)}?{urlencode(query)}"
