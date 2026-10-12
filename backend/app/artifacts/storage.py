"""Private object storage: native GCS (keyless, ADC) or S3's common PUT/GET surface.

The S3 subset works with AWS, MinIO and GCS XML/HMAC. Bytes are proxied through
Auxilia so the bucket need not be browser-accessible or configured for CORS.
"""

from functools import lru_cache
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from google.api_core.exceptions import NotFound, RequestRangeNotSatisfiable
from google.cloud import storage
from google.cloud.storage.retry import DEFAULT_RETRY

from app.artifacts.settings import ArtifactSettings


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, mime_type: str) -> None: ...
    def get(self, key: str, limit: int) -> bytes: ...
    def delete(self, key: str) -> None: ...


class ObjectMissingError(Exception):
    pass


class ObjectTooLargeError(Exception):
    pass


class S3ObjectStore:
    def __init__(self, settings: ArtifactSettings):
        self.bucket = settings.bucket_name
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key.get_secret_value()
            if settings.s3_secret_access_key
            else None,
            aws_session_token=settings.s3_session_token.get_secret_value()
            if settings.s3_session_token
            else None,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": settings.s3_addressing_style},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                connect_timeout=10,
                read_timeout=30,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )

    def put(self, key: str, data: bytes, mime_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=mime_type
        )

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def get(self, key: str, limit: int) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"NoSuchKey", "NotFound", "404"}:
                raise ObjectMissingError from exc
            raise
        body = response["Body"]
        try:
            # Some providers omit Content-Length; the bounded read still caps it.
            if response.get("ContentLength", 0) > limit:
                raise ObjectTooLargeError(key)
            data = body.read(limit + 1)
            if len(data) > limit:
                raise ObjectTooLargeError(key)
            return data
        finally:
            body.close()


# Parity with S3ObjectStore: 10s connect / 30s read, retries capped well below the 120s default.
GCS_TIMEOUT = (10, 30)
GCS_RETRY = DEFAULT_RETRY.with_timeout(60)


@lru_cache(maxsize=1)
def _gcs_client() -> storage.Client:
    # ADC: the Cloud Run/GKE service account, or `gcloud auth application-default login`.
    return storage.Client()


class GCSObjectStore:
    def __init__(self, settings: ArtifactSettings):
        self.bucket = _gcs_client().bucket(settings.bucket_name)

    def put(self, key: str, data: bytes, mime_type: str) -> None:
        self.bucket.blob(key).upload_from_string(
            data, content_type=mime_type, timeout=GCS_TIMEOUT
        )

    def delete(self, key: str) -> None:
        self.bucket.blob(key).delete(timeout=GCS_TIMEOUT, retry=GCS_RETRY)

    def get(self, key: str, limit: int) -> bytes:
        try:
            # `end` is inclusive: one extra byte tells an oversize object apart.
            data = self.bucket.blob(key).download_as_bytes(
                start=0, end=limit, timeout=GCS_TIMEOUT, retry=GCS_RETRY
            )
        except NotFound as exc:
            raise ObjectMissingError from exc
        except RequestRangeNotSatisfiable:
            return b""  # a byte range over a zero-byte object
        if len(data) > limit:
            raise ObjectTooLargeError(key)
        return data


def build_store(settings: ArtifactSettings) -> ObjectStore:
    if settings.provider == "gcs":
        return GCSObjectStore(settings)
    return S3ObjectStore(settings)
