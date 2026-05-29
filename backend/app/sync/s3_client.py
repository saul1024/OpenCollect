from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote, urlparse

import httpx


class S3Error(Exception):
    pass


@dataclass(frozen=True)
class S3Config:
    endpoint: str
    region: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    session_token: str = ""
    force_path_style: bool = True
    timeout_seconds: float = 15.0


class S3Client:
    def __init__(self, config: S3Config):
        self.config = config
        self._validate_config()
        self._endpoint = config.endpoint.rstrip("/")
        self._parsed_endpoint = urlparse(self._endpoint)
        if self._parsed_endpoint.scheme not in {"http", "https"} or not self._parsed_endpoint.netloc:
            raise S3Error("S3_ENDPOINT/COS_ENDPOINT 必须是完整 http(s) 地址")

    def get_object(self, key: str) -> bytes | None:
        response = self._request("GET", key)
        if response.status_code == 404:
            return None
        self._raise_for_status(response)
        return response.content

    def put_object(self, key: str, data: bytes, content_type: str = "application/json; charset=utf-8") -> None:
        response = self._request(
            "PUT",
            key,
            body=data,
            extra_headers={"content-type": content_type},
        )
        self._raise_for_status(response)

    def _request(
        self,
        method: str,
        key: str,
        body: bytes = b"",
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        url, host, canonical_uri = self._object_url(key)
        payload_hash = hashlib.sha256(body).hexdigest()
        request_time = datetime.now(UTC)
        amz_date = request_time.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = request_time.strftime("%Y%m%d")

        headers = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if self.config.session_token:
            headers["x-amz-security-token"] = self.config.session_token
        if extra_headers:
            headers.update({key.lower(): value for key, value in extra_headers.items()})

        authorization = self._authorization(
            method=method,
            canonical_uri=canonical_uri,
            canonical_querystring="",
            headers=headers,
            payload_hash=payload_hash,
            date_stamp=date_stamp,
            amz_date=amz_date,
        )
        headers["authorization"] = authorization

        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            return client.request(method, url, content=body, headers=headers)

    def _raise_for_status(self, response: httpx.Response) -> None:
        if 200 <= response.status_code < 300:
            return
        detail = response.text.strip().replace("\n", " ")[:500]
        message = f"COS/S3 request failed: {response.status_code}"
        if response.reason_phrase:
            message += f" {response.reason_phrase}"
        if detail:
            message += f" - {detail}"
        raise S3Error(message)

    def _authorization(
        self,
        method: str,
        canonical_uri: str,
        canonical_querystring: str,
        headers: dict[str, str],
        payload_hash: str,
        date_stamp: str,
        amz_date: str,
    ) -> str:
        canonical_headers, signed_headers = canonicalize_headers(headers)
        canonical_request = "\n".join(
            [
                method,
                canonical_uri,
                canonical_querystring,
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        credential_scope = f"{date_stamp}/{self.config.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        signing_key = signature_key(self.config.secret_access_key, date_stamp, self.config.region, "s3")
        signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        return (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.config.access_key_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )

    def _object_url(self, key: str) -> tuple[str, str, str]:
        encoded_key = encode_key(key)
        path_prefix = self._parsed_endpoint.path.rstrip("/")
        if self.config.force_path_style:
            canonical_uri = f"{path_prefix}/{encode_segment(self.config.bucket)}/{encoded_key}".replace("//", "/")
            url = f"{self._parsed_endpoint.scheme}://{self._parsed_endpoint.netloc}{canonical_uri}"
            return url, self._parsed_endpoint.netloc, canonical_uri

        host = self._parsed_endpoint.netloc
        if not host.startswith(f"{self.config.bucket}."):
            host = f"{self.config.bucket}.{host}"
        canonical_uri = f"{path_prefix}/{encoded_key}".replace("//", "/")
        url = f"{self._parsed_endpoint.scheme}://{host}{canonical_uri}"
        return url, host, canonical_uri

    def _validate_config(self) -> None:
        missing = []
        for field in ["endpoint", "region", "bucket", "access_key_id", "secret_access_key"]:
            value = getattr(self.config, field)
            if not value:
                missing.append(field)
            elif "<" in value or ">" in value:
                raise S3Error(f"云同步配置 {field} 仍包含占位符，请替换为真实值")
        if missing:
            raise S3Error("缺少云同步配置：" + ", ".join(missing))


def canonicalize_headers(headers: dict[str, str]) -> tuple[str, str]:
    normalized = {name.lower().strip(): " ".join(str(value).strip().split()) for name, value in headers.items()}
    names = sorted(normalized)
    canonical_headers = "".join(f"{name}:{normalized[name]}\n" for name in names)
    signed_headers = ";".join(names)
    return canonical_headers, signed_headers


def signature_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    key_date = sign(("AWS4" + secret_key).encode(), date_stamp)
    key_region = sign(key_date, region)
    key_service = sign(key_region, service)
    return sign(key_service, "aws4_request")


def sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def encode_key(key: str) -> str:
    return "/".join(encode_segment(part) for part in key.strip("/").split("/"))


def encode_segment(value: str) -> str:
    return quote(value, safe="-_.~")
