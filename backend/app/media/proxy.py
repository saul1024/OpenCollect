from __future__ import annotations

from urllib.parse import urlparse

import httpx
from fastapi import Request
from fastapi.responses import Response, StreamingResponse

from backend.app.xhs.parser import BROWSER_UA


class MediaProxyError(Exception):
    pass


class MediaProxy:
    async def image(self, raw_url: str) -> Response:
        target = validate_asset_url(raw_url)
        headers = {
            "user-agent": BROWSER_UA,
            "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "referer": "https://www.xiaohongshu.com/",
        }
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(target, headers=headers)
        except httpx.HTTPError as exc:
            raise MediaProxyError("图片加载失败") from exc

        if response.status_code < 200 or response.status_code >= 300:
            raise MediaProxyError("图片加载失败")

        content_type = response.headers.get("content-type") or "image/jpeg"
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
        return stream_response(response, client, response.status_code, ("content-type", "content-length", "content-range", "accept-ranges"), "video/mp4")


async def open_stream(raw_url: str, headers: dict[str, str]) -> tuple[httpx.Response, httpx.AsyncClient]:
    client = httpx.AsyncClient(timeout=30, follow_redirects=True)
    request = client.build_request("GET", raw_url, headers=headers)
    response = await client.send(request, stream=True)
    return response, client


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
    if not is_xhs_asset_host(host):
        raise MediaProxyError("不支持的媒体域名")
    return raw_url


def is_xhs_asset_host(host: str) -> bool:
    return (
        host == "xhscdn.com"
        or host.endswith(".xhscdn.com")
        or host == "xiaohongshu.com"
        or host.endswith(".xiaohongshu.com")
    )
