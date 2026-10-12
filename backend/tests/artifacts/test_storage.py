import io
import os
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from botocore.stub import Stubber

from app.artifacts.settings import ArtifactSettings
from app.artifacts.storage import (
    ObjectMissingError,
    ObjectTooLargeError,
    S3ObjectStore,
)


@pytest.mark.parametrize(
    "endpoint,region,style",
    [
        (None, "eu-west-1", "virtual"),
        ("http://localhost:9000", "us-east-1", "path"),
        ("https://storage.googleapis.com", "auto", "path"),
    ],
)
def test_portable_s3_operations(endpoint, region, style):
    store = S3ObjectStore(
        ArtifactSettings(
            _env_file=None,
            s3_bucket="private",
            s3_endpoint_url=endpoint,
            s3_region=region,
            s3_addressing_style=style,
            s3_access_key_id="test",
            s3_secret_access_key="test",
        )
    )
    with Stubber(store.client) as stub:
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": "private",
                "Key": "file",
                "Body": b"data",
                "ContentType": "text/plain",
            },
        )
        store.put("file", b"data", "text/plain")
        stub.add_response(
            "get_object",
            {"ContentLength": 4, "Body": StreamingBody(io.BytesIO(b"data"), 4)},
            {"Bucket": "private", "Key": "file"},
        )
        assert store.get("file", 4) == b"data"
        stub.add_client_error(
            "get_object", service_error_code="NoSuchKey", http_status_code=404
        )
        with pytest.raises(ObjectMissingError):
            store.get("file", 4)
        stub.add_client_error(
            "get_object", service_error_code="AccessDenied", http_status_code=403
        )
        with pytest.raises(ClientError):
            store.get("file", 4)


def stub_store():
    return S3ObjectStore(
        ArtifactSettings(
            _env_file=None,
            s3_bucket="private",
            s3_access_key_id="test",
            s3_secret_access_key="test",
        )
    )


def test_oversize_object_is_typed_and_missing_length_is_bounded():
    store = stub_store()
    with Stubber(store.client) as stub:
        stub.add_response(
            "get_object",
            {"ContentLength": 10, "Body": StreamingBody(io.BytesIO(b"0123456789"), 10)},
            {"Bucket": "private", "Key": "big"},
        )
        with pytest.raises(ObjectTooLargeError):
            store.get("big", 4)
        # No Content-Length header: the bounded read still enforces the limit.
        stub.add_response(
            "get_object",
            {"Body": StreamingBody(io.BytesIO(b"0123456789"), 10)},
            {"Bucket": "private", "Key": "big"},
        )
        with pytest.raises(ObjectTooLargeError):
            store.get("big", 4)


def test_session_token_requires_static_credentials():
    with pytest.raises(ValueError, match="session token"):
        ArtifactSettings(_env_file=None, s3_session_token="token")


@pytest.mark.skipif(
    not os.environ.get("ARTIFACT_TEST_S3_ENDPOINT"),
    reason="Opt-in MinIO integration test",
)
def test_minio_roundtrip():
    store = S3ObjectStore(
        ArtifactSettings(
            _env_file=None,
            s3_bucket="auxilia-artifacts",
            s3_endpoint_url=os.environ["ARTIFACT_TEST_S3_ENDPOINT"],
            s3_addressing_style="path",
            s3_access_key_id="auxilia-local",
            s3_secret_access_key="auxilia-local-development-only",
        )
    )
    key = f"integration/{uuid4()}/binary.pptx"
    data = bytes(range(256)) * 100
    try:
        store.put(key, data, "application/octet-stream")
        assert store.get(key, len(data)) == data
        with pytest.raises(ObjectTooLargeError):
            store.get(key, len(data) - 1)
    finally:
        store.client.delete_object(Bucket=store.bucket, Key=key)
