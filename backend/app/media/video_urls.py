from __future__ import annotations

from urllib.parse import urlparse


XHS_VIDEO_PLAYBACK_HOSTS = ("sns-video-bd.xhscdn.com", "sns-video-hw.xhscdn.com")


def normalize_xhs_video_url(raw_url: str) -> str:
    raw_url = normalize_url_scheme(raw_url)
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    if not is_xhs_video_host(host):
        return raw_url
    if "/stream/" not in parsed.path or not parsed.path.lower().endswith(".mp4"):
        return raw_url

    playback_host = host if host in XHS_VIDEO_PLAYBACK_HOSTS else XHS_VIDEO_PLAYBACK_HOSTS[0]
    return replace_url_host_without_query(parsed, playback_host)


def normalize_url_scheme(value: str) -> str:
    if not value:
        return ""
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("http://"):
        return "https://" + value.removeprefix("http://")
    return value


def replace_url_host_without_query(parsed, host: str) -> str:
    return parsed._replace(scheme="https", netloc=host, query="", fragment="").geturl()


def is_xhs_video_host(host: str) -> bool:
    return host.startswith("sns-video-") and host.endswith(".xhscdn.com")
