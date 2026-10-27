"""Object storage shared by services and agents (ADR-011): S3 on AWS, Blob Storage on Azure, SeaweedFS locally.

Keys are always `tenants/{tenant_id}/{area}/{name}`, and the tenant comes from the open
transaction's app.tenant_id (the same value RLS uses), never from a caller's argument.
`python -m secondchance.storage` creates the local bucket; on AWS Terraform owns it.
"""

import os
import re
import uuid
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.orm import Session

from secondchance.cloud import azure_credential, is_azure

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


class S3Store:
    """S3 or any S3-compatible service; `s3` is injectable for tests."""

    def __init__(self, s3=None) -> None:
        self._s3 = s3

    @property
    def s3(self):
        if self._s3 is None:
            self._s3 = client()
        return self._s3

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.s3.put_object(Bucket=bucket(), Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        return self.s3.get_object(Bucket=bucket(), Key=key)["Body"].read()

    def tags(self, key: str) -> dict[str, str]:
        return {tag["Key"]: tag["Value"] for tag in self.s3.get_object_tagging(Bucket=bucket(), Key=key)["TagSet"]}

    def ensure(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self.s3.head_bucket(Bucket=bucket())
        except ClientError as error:
            if error.response["Error"]["Code"] not in ("404", "NoSuchBucket", "NotFound"):
                raise
            try:
                self.s3.create_bucket(Bucket=bucket())
            except self.s3.exceptions.BucketAlreadyOwnedByYou:
                pass  # created concurrently by another run


class BlobStore:
    """Azure Blob Storage through the caller's managed identity (shared keys are off on the account)."""

    def __init__(self, container=None) -> None:
        self._container = container

    @property
    def container(self):
        if self._container is None:
            from azure.storage.blob import BlobServiceClient

            service = BlobServiceClient(os.environ["SECONDCHANCE_BLOB_ENDPOINT"], credential=azure_credential())
            self._container = service.get_container_client(os.environ.get("SECONDCHANCE_BLOB_CONTAINER", "objects"))
        return self._container

    def put(self, key: str, data: bytes, content_type: str) -> None:
        from azure.storage.blob import ContentSettings

        self.container.upload_blob(key, data, overwrite=True, content_settings=ContentSettings(content_type=content_type))

    def get(self, key: str) -> bytes:
        return self.container.download_blob(key).readall()

    def tags(self, key: str) -> dict[str, str]:
        return dict(self.container.get_blob_client(key).get_blob_tags())

    def ensure(self) -> None:
        pass  # Terraform owns the container; the application identity cannot create one


@lru_cache
def _blob_store() -> BlobStore:
    return BlobStore()


def store(s3=None) -> S3Store | BlobStore:
    if s3 is None and is_azure():
        return _blob_store()
    return S3Store(s3)


def put(session: Session, area: str, name: str, data: bytes, content_type: str, s3=None) -> str:
    key = object_key(session, area, name)
    store(s3).put(key, data, content_type)
    return key


def get(session: Session, area: str, name: str, s3=None) -> bytes:
    return store(s3).get(object_key(session, area, name))


def read_key(session: Session, key: str, s3=None) -> bytes:
    """Reads a stored key, refusing any key outside the transaction's tenant prefix."""
    prefix = object_key(session, "artifacts", "x").removesuffix("artifacts/x")
    if not key.startswith(prefix) or ".." in key:
        raise PermissionError("object key outside this tenant")
    return store(s3).get(key)


SCAN_TAG = "GuardDutyMalwareScanStatus"
# Microsoft Defender for Storage writes its verdict to this blob index tag (on-upload malware scanning).
AZURE_SCAN_TAG = "Malware Scanning scan result"
# Everything that is not an explicit clean verdict fails closed, whatever the scanner calls it.
_AZURE_VERDICTS = {"no threats found": "NO_THREATS_FOUND", "malicious": "THREATS_FOUND", "not scanned": "UNSUPPORTED"}


def scan_status(key: str, s3=None) -> str | None:
    """The malware scanner's verdict on an object (ADR-022), in GuardDuty's vocabulary; None while it runs."""
    tags = store(s3).tags(key)
    if s3 is None and is_azure():
        # Defender writes "Malware Scanning scan result" next to "Malware Scanning scan time UTC" (Microsoft's own
        # scripts use these keys); matching on "scan result" also covers the portal's shorter label.
        verdict = next((value for tag, value in tags.items() if "scan result" in tag.lower()), None)
        return None if verdict is None else _AZURE_VERDICTS.get(verdict.strip().lower(), "FAILED")
    return tags.get(SCAN_TAG)


def ensure_bucket(s3=None) -> None:
    store(s3).ensure()


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
