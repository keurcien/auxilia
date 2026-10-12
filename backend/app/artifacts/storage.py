"""Private object storage; deliberately use only S3's common PUT/GET surface.

GCS XML/HMAC, MinIO and AWS all support this subset. Bytes are proxied through
Auxilia so the bucket need not be browser-accessible or configured for CORS.
"""

from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

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
        self.bucket = settings.s3_bucket
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
