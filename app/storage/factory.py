"""Build the configured ObjectStorage adapter."""

import boto3

from app.core.errors import UnsafeConfigurationError
from app.core.settings import Settings
from app.storage.local import LocalStorage
from app.storage.memory import MemoryStorage
from app.storage.ports import ObjectStorage
from app.storage.s3 import S3Storage

S3_REGION = "eu-central-1"


def build_storage(settings: Settings) -> ObjectStorage:
    if settings.storage_backend == "memory":
        return MemoryStorage()
    if settings.storage_backend == "local":
        return LocalStorage(settings.storage_local_dir)
    if not settings.s3_bucket:
        raise UnsafeConfigurationError("storage_backend 's3' needs s3_bucket")
    client = boto3.client(
        "s3",
        region_name=S3_REGION,
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key.get_secret_value()
        if settings.s3_secret_access_key
        else None,
    )
    return S3Storage(client=client, bucket=settings.s3_bucket)
