"""Object storage shared by services and agents (ADR-011): S3 on AWS, SeaweedFS locally.

Keys are always `tenants/{tenant_id}/{area}/{name}`, and the tenant comes from the open
transaction's app.tenant_id (the same value RLS uses), never from a caller's argument.
`python -m secondchance.storage` creates the local bucket; on AWS Terraform owns it.
"""

import os
import re
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

AREAS = ("artifacts", "documents", "attachments")
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")


def client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("SECONDCHANCE_S3_ENDPOINT"),
        region_name=os.environ.get("AWS_REGION", "eu-central-1"),
        config=Config(retries={"mode": "standard", "max_attempts": 6}),
    )


def bucket() -> str:
    return os.environ.get("SECONDCHANCE_S3_BUCKET", "secondchance-local")


def object_key(session: Session, area: str, name: str) -> str:
    if area not in AREAS:
        raise ValueError(f"unknown area {area!r}")
    if not _SAFE_NAME.fullmatch(name):
        raise ValueError("object names are letters, digits, dot, dash and underscore")
    tenant = session.execute(text("SELECT current_tenant_id()")).scalar_one_or_none()
    if tenant is None:
        raise PermissionError("no tenant in this transaction")
    return f"tenants/{uuid.UUID(str(tenant))}/{area}/{name}"


def put(session: Session, area: str, name: str, data: bytes, content_type: str, s3=None) -> str:
    key = object_key(session, area, name)
    (s3 or client()).put_object(Bucket=bucket(), Key=key, Body=data, ContentType=content_type)
    return key


def get(session: Session, area: str, name: str, s3=None) -> bytes:
    key = object_key(session, area, name)
    return (s3 or client()).get_object(Bucket=bucket(), Key=key)["Body"].read()


def read_key(session: Session, key: str, s3=None) -> bytes:
    """Reads a stored key, refusing any key outside the transaction's tenant prefix."""
    prefix = object_key(session, "artifacts", "x").removesuffix("artifacts/x")
    if not key.startswith(prefix) or ".." in key:
        raise PermissionError("object key outside this tenant")
    return (s3 or client()).get_object(Bucket=bucket(), Key=key)["Body"].read()


SCAN_TAG = "GuardDutyMalwareScanStatus"


def scan_status(key: str, s3=None) -> str | None:
    """GuardDuty Malware Protection's verdict on an object (ADR-022); None while the scan runs."""
    tags = (s3 or client()).get_object_tagging(Bucket=bucket(), Key=key)["TagSet"]
    return next((tag["Value"] for tag in tags if tag["Key"] == SCAN_TAG), None)


def ensure_bucket(s3=None) -> None:
    from botocore.exceptions import ClientError

    s3 = s3 or client()
    try:
        s3.head_bucket(Bucket=bucket())
    except ClientError as error:
        if error.response["Error"]["Code"] not in ("404", "NoSuchBucket", "NotFound"):
            raise
        try:
            s3.create_bucket(Bucket=bucket())
        except s3.exceptions.BucketAlreadyOwnedByYou:
            pass  # created concurrently by another run


if __name__ == "__main__":
    import time

    from botocore.exceptions import EndpointConnectionError

    for _ in range(30):  # SeaweedFS needs a few seconds after the container starts
        try:
            ensure_bucket()
            break
        except EndpointConnectionError:
            time.sleep(1)
    else:
        raise SystemExit("object storage not reachable")
    print(f"bucket ready: {bucket()}")
