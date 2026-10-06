"""S3-compatible storage (EU bucket) for production."""

from typing import Any

from botocore.exceptions import ClientError

from app.core.errors import NotFoundError
from app.storage.ports import StoredObject, describe, validate_key


class S3Storage:
    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        obj = describe(validate_key(key), data, content_type)
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=data, ContentType=content_type, Metadata={"sha256": obj.sha256}
        )
        return obj

    def get(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=validate_key(key))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                raise NotFoundError(key) from exc
            raise
        body: bytes = response["Body"].read()
        return body

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=validate_key(key))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                return False
            raise
        return True
