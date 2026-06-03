from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import Request
from fastapi.responses import Response, StreamingResponse

from backend.app.xhs.parser import BROWSER_UA


class MediaProxyError(Exception):
    pass


class MediaProxy:
    max_image_bytes = 25 * 1024 * 1024
    max_video_bytes = 256 * 1024 * 1024
    max_redirects = 3

    async def image(self, raw_url: str) -> Response:
        target = validate_asset_url(raw_url)
        headers = {
            "user-agent": BROWSER_UA,
            "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "referer": "https://www.xiaohongshu.com/",
        }
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await get_with_safe_redirects(client, target, headers)
        except httpx.HTTPError as exc:
            raise MediaProxyError("图片加载失败") from exc

        if response.status_code < 200 or response.status_code >= 300:
            raise MediaProxyError("图片加载失败")

        content_type = response.headers.get("content-type") or "image/jpeg"
        if not is_allowed_image_content_type(content_type):
            raise MediaProxyError("不支持的图片类型")
        if response_too_large(response, self.max_image_bytes):
            raise MediaProxyError("图片过大")
        if len(response.content) > self.max_image_bytes:
            raise MediaProxyError("图片过大")
        return Response(
            content=response.content,
            media_type=content_type,
            headers={"cache-control": "public, max-age=3600"},
        )

    async def video(self, request: Request, raw_url: str) -> StreamingResponse:
        target = validate_asset_url(raw_url)
        headers = {
            "user-agent": BROWSER_UA,
            "accept": "video/mp4,video/*,*/*;q=0.8",
            "referer": "https://www.xiaohongshu.com/",
        }
        if range_header := request.headers.get("range"):
            headers["range"] = range_header

        response, client = await open_stream(target, headers)
        if (response.status_code < 200 or response.status_code >= 300) and response.status_code != 206:
            await response.aclose()
            await client.aclose()
            raise MediaProxyError("媒体加载失败")
        content_type = response.headers.get("content-type") or "video/mp4"
        if not is_allowed_video_content_type(content_type):
            await response.aclose()
            await client.aclose()
            raise MediaProxyError("不支持的媒体类型")
        if response_too_large(response, self.max_video_bytes):
            await response.aclose()
            await client.aclose()
            raise MediaProxyError("媒体过大")
        return stream_response(response, client, response.status_code, ("content-type", "content-length", "content-range", "accept-ranges"), "video/mp4")


async def open_stream(raw_url: str, headers: dict[str, str]) -> tuple[httpx.Response, httpx.AsyncClient]:
    client = httpx.AsyncClient(timeout=30, follow_redirects=False)
    current_url = validate_asset_url(raw_url)
    for _ in range(MediaProxy.max_redirects + 1):
        request = client.build_request("GET", current_url, headers=headers)
        response = await client.send(request, stream=True)
        if not is_redirect(response):
            return response, client
        location = response.headers.get("location", "")
        await response.aclose()
        current_url = validate_asset_url(urljoin(current_url, location))
    await client.aclose()
    raise MediaProxyError("媒体重定向异常")


async def get_with_safe_redirects(client: httpx.AsyncClient, raw_url: str, headers: dict[str, str]) -> httpx.Response:
    current_url = validate_asset_url(raw_url)
    for _ in range(MediaProxy.max_redirects + 1):
        response = await client.get(current_url, headers=headers)
        if not is_redirect(response):
            return response
        current_url = validate_asset_url(urljoin(current_url, response.headers.get("location", "")))
    raise MediaProxyError("图片重定向异常")


def stream_response(
    response: httpx.Response,
    client: httpx.AsyncClient,
    status_code: int,
    copied_headers: tuple[str, ...],
    default_content_type: str,
) -> StreamingResponse:
    headers: dict[str, str] = {}
    for key in copied_headers:
        if value := response.headers.get(key):
            headers[key] = value
    if default_content_type and "content-type" not in headers:
        headers["content-type"] = default_content_type
    if "accept-ranges" not in headers and "content-range" in copied_headers:
        headers["accept-ranges"] = "bytes"
    headers["cache-control"] = "public, max-age=3600"

    async def body():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(body(), status_code=status_code, headers=headers)


def validate_asset_url(raw_url: str) -> str:
    if not raw_url:
        raise MediaProxyError("缺少媒体地址")
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"}:
        raise MediaProxyError("不支持的媒体地址")
    host = (parsed.hostname or "").lower()
    if not host or is_blocked_host(host):
        raise MediaProxyError("不支持的媒体地址")
    return raw_url


def is_redirect(response: httpx.Response) -> bool:
    return response.status_code in {301, 302, 303, 307, 308} and bool(response.headers.get("location"))


def is_blocked_host(host: str) -> bool:
    clean_host = host.strip().strip("[]").rstrip(".").lower()
    if clean_host in {"localhost", "metadata.google.internal"} or clean_host.endswith(".localhost"):
        return True
    try:
        return is_blocked_ip(ipaddress.ip_address(clean_host))
    except ValueError:
        pass

    try:
        addresses = socket.getaddrinfo(clean_host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address[4][0])
        except ValueError:
            return True
        if is_blocked_ip(ip):
            return True
    return False


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    return str(ip) == "169.254.169.254"


def is_allowed_image_content_type(content_type: str) -> bool:
    return content_type.split(";", 1)[0].strip().lower().startswith("image/")


def is_allowed_video_content_type(content_type: str) -> bool:
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type.startswith("video/") or media_type == "application/octet-stream"


def response_too_large(response: httpx.Response, max_bytes: int) -> bool:
    try:
        return int(response.headers.get("content-length") or "0") > max_bytes
    except ValueError:
        return True
