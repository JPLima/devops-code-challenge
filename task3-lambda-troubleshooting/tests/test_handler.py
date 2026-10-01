"""Handler tests, against moto."""

import json
import os

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

BUCKET = "test-bucket"


@pytest.fixture
def bucket(monkeypatch):
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        monkeypatch.setenv("DATA_BUCKET", BUCKET)
        yield client


def test_roundtrip(bucket, handler_module, context):
    response = handler_module.handler({"source": "test"}, context)

    assert response["statusCode"] == 200

    body = json.loads(response["body"])
    assert body["roundtrip_ok"] is True
    assert body["bytes_written"] == body["bytes_read"]
    assert body["bucket"] == BUCKET

    # The object is really there, not just reported as written.
    stored = bucket.get_object(Bucket=BUCKET, Key=body["key"])["Body"].read()
    assert json.loads(stored)["event"] == {"source": "test"}


def test_key_layout(bucket, handler_module, context):
    response = handler_module.handler({}, context)
    key = json.loads(response["body"])["key"]

    assert key.startswith("invocations/")

    prefix, year, month, day, filename = key.split("/")
    assert len(year) == 4 and year.isdigit()
    assert len(month) == 2 and month.isdigit()
    assert len(day) == 2 and day.isdigit()
    assert filename.endswith(".json")


def test_record_fields(bucket, handler_module, context):
    response = handler_module.handler({"hello": "world"}, context)
    key = json.loads(response["body"])["key"]

    stored = json.loads(bucket.get_object(Bucket=BUCKET, Key=key)["Body"].read())

    assert stored["request_id"] == context.aws_request_id
    assert stored["function_name"] == context.function_name
    assert stored["timestamp"].endswith("+00:00")


def test_unique_keys(bucket, handler_module, context):
    first = json.loads(handler_module.handler({}, context)["body"])["key"]
    second = json.loads(handler_module.handler({}, context)["body"])["key"]

    assert first != second

    listed = bucket.list_objects_v2(Bucket=BUCKET, Prefix="invocations/")
    assert listed["KeyCount"] == 2


def test_missing_env(
    handler_module, context, monkeypatch
):
    monkeypatch.delenv("DATA_BUCKET", raising=False)

    with pytest.raises(RuntimeError, match="DATA_BUCKET"):
        handler_module.handler({}, context)


def test_empty_env(
    handler_module, context, monkeypatch
):
    monkeypatch.setenv("DATA_BUCKET", "")

    with pytest.raises(RuntimeError, match="DATA_BUCKET"):
        handler_module.handler({}, context)


def test_missing_bucket_raises(
    handler_module, context, monkeypatch
):
    with mock_aws():
        monkeypatch.setenv("DATA_BUCKET", "bucket-that-does-not-exist")

        with pytest.raises(ClientError) as raised:
            handler_module.handler({}, context)

        assert raised.value.response["Error"]["Code"] in {
            "NoSuchBucket",
            "404",
        }


def test_client_cached(bucket, handler_module, context):
    assert handler_module._S3 is None

    handler_module.handler({}, context)
    first = handler_module._S3

    handler_module.handler({}, context)

    assert handler_module._S3 is first
