from __future__ import annotations

from backend.app.sync.s3_client import S3Client, S3Config


def test_s3_client_uses_bucket_endpoint_without_duplicate_bucket():
    client = S3Client(
        S3Config(
            endpoint="https://opencollect-1256544987.cos.ap-shanghai.myqcloud.com",
            region="ap-shanghai",
            bucket="opencollect-1256544987",
            access_key_id="secret-id",
            secret_access_key="secret-key",
            force_path_style=False,
        )
    )

    url, host, canonical_uri = client._object_url("opencollect/collections.json")

    assert host == "opencollect-1256544987.cos.ap-shanghai.myqcloud.com"
    assert url == "https://opencollect-1256544987.cos.ap-shanghai.myqcloud.com/opencollect/collections.json"
    assert canonical_uri == "/opencollect/collections.json"


def test_s3_client_builds_virtual_host_from_region_endpoint():
    client = S3Client(
        S3Config(
            endpoint="https://cos.ap-shanghai.myqcloud.com",
            region="ap-shanghai",
            bucket="opencollect-1256544987",
            access_key_id="secret-id",
            secret_access_key="secret-key",
            force_path_style=False,
        )
    )

    url, host, canonical_uri = client._object_url("opencollect/collections.json")

    assert host == "opencollect-1256544987.cos.ap-shanghai.myqcloud.com"
    assert url == "https://opencollect-1256544987.cos.ap-shanghai.myqcloud.com/opencollect/collections.json"
    assert canonical_uri == "/opencollect/collections.json"
