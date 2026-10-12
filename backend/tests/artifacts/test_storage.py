import io
import os
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from botocore.stub import Stubber
from google.api_core.exceptions import NotFound, RequestRangeNotSatisfiable

from app.artifacts.settings import ArtifactSettings
from app.artifacts.storage import (
    GCS_RETRY,
    GCS_TIMEOUT,
    GCSObjectStore,
    ObjectMissingError,
    ObjectTooLargeError,
    S3ObjectStore,
    build_store,
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
            bucket="private",
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
            bucket="private",
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


@pytest.mark.parametrize(
    "bucket,provider,name",
    [
        ("", None, ""),
        ("private", "s3", "private"),
        ("s3://private", "s3", "private"),
        ("gs://private", "gcs", "private"),
    ],
)
def test_provider_is_inferred_from_bucket(bucket, provider, name):
    cfg = ArtifactSettings(_env_file=None, bucket=bucket)
    assert (cfg.provider, cfg.bucket_name) == (provider, name)


@pytest.mark.parametrize(
    "extra",
    [
        {"s3_endpoint_url": "https://storage.googleapis.com"},
        {"s3_access_key_id": "id", "s3_secret_access_key": "secret"},
    ],
)
def test_gcs_bucket_rejects_s3_settings(extra):
    with pytest.raises(ValueError, match="ADC"):
        ArtifactSettings(_env_file=None, bucket="gs://private", **extra)


def test_gcs_store(monkeypatch):
    bucket = MagicMock()
    client = MagicMock()
    client.bucket.return_value = bucket
    monkeypatch.setattr("app.artifacts.storage._gcs_client", lambda: client)
    store = build_store(ArtifactSettings(_env_file=None, bucket="gs://private"))
    assert isinstance(store, GCSObjectStore)
    client.bucket.assert_called_once_with("private")
    blob = bucket.blob.return_value
    store.put("file", b"data", "text/plain")
    blob.upload_from_string.assert_called_once_with(
        b"data", content_type="text/plain", timeout=GCS_TIMEOUT
    )
    blob.download_as_bytes.return_value = b"data"
    assert store.get("file", 4) == b"data"
    blob.download_as_bytes.assert_called_once_with(
        start=0, end=4, timeout=GCS_TIMEOUT, retry=GCS_RETRY
    )
    blob.download_as_bytes.return_value = b"01234"
    with pytest.raises(ObjectTooLargeError):
        store.get("file", 4)
    blob.download_as_bytes.side_effect = NotFound("gone")
    with pytest.raises(ObjectMissingError):
        store.get("file", 4)
    blob.download_as_bytes.side_effect = RequestRangeNotSatisfiable("empty")
    assert store.get("file", 4) == b""


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
            bucket="auxilia-artifacts",
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
