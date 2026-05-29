from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, AsyncIterator
from urllib.parse import quote, urlparse

import httpx

from backend.app.media.video_urls import normalize_xhs_video_url
from backend.app.store.models import Author, Collection, Image, Stats, Video
from backend.app.store.json_store import now_utc


SAMPLE_MIN_IMAGES = 3
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
XHS_IMAGE_STYLE_SUFFIX = "!nd_dft_wlteh_webp_3"

URL_RE = re.compile(r"https?://[^\s\"'<>）)]+")
INITIAL_STATE_RE = re.compile(r"<script>window\.__INITIAL_STATE__=(.*?)</script>", re.S)
HASH_TAG_RE = re.compile(r"#([^#\[\]\s]+)(?:\[话题\])?#")


class ParserError(Exception):
    pass


class XHSParser:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=20, follow_redirects=True)

    async def close(self) -> None:
        await self.client.aclose()

    async def collect(self, input_text: str) -> dict[str, Any]:
        extracted_url = extract_first_url(input_text)
        if not extracted_url:
            raise ParserError("没有识别到链接，请粘贴小红书分享文本或 URL")

        final_url = await self.resolve_share_url(extracted_url)
        parsed = urlparse(final_url)
        if not is_xhs_host(parsed.hostname or ""):
            raise ParserError("当前 PoC 仅支持小红书链接")

        note_id = extract_note_id(final_url)
        if not note_id:
            raise ParserError("没有识别到小红书笔记 ID")

        html = await self.fetch_text(final_url)
        state = extract_initial_state(html)
        detail = find_note_detail(state, note_id)
        if detail is None:
            if "xsec_token=" in parsed.query:
                raise ParserError("页面没有返回完整笔记数据，可能已失效、需登录或被平台限制访问")
            raise ParserError("链接缺少 xsec_token，裸笔记链接通常拿不到完整内容。请使用小红书 App 分享出来的完整链接或短链")

        note_map = get_map(detail, "note")
        if not note_map:
            raise ParserError("页面没有返回完整笔记数据，可能已失效、需登录或被平台限制访问")

        return {
            "source": {
                "input": input_text,
                "extractedUrl": extracted_url,
                "finalUrl": final_url,
            },
            "note": normalize_note(note_map, final_url),
        }

    async def sample(self) -> dict[str, Any]:
        fallback: dict[str, Any] | None = None
        async for note_url, result in self.iter_explore_feed_results():
            try:
                note: Collection = result["note"]
            except (KeyError, TypeError):
                continue
            sample = {
                "input": note_url,
                "title": note.title,
                "imageCount": len(note.images),
                "preferred": "fallback",
            }
            if sample["imageCount"] >= SAMPLE_MIN_IMAGES:
                sample["preferred"] = "multi-image"
                return sample
            if fallback is None or sample["imageCount"] > fallback["imageCount"]:
                fallback = sample

        if fallback is not None:
            return fallback
        raise ParserError("暂时没有拿到公开示例")

    async def sample_video(self) -> dict[str, Any]:
        async for note_url, result in self.iter_explore_feed_results():
            try:
                note: Collection = result["note"]
            except (KeyError, TypeError):
                continue
            if note.video and note.video.url:
                return {
                    "input": note_url,
                    "title": note.title,
                    "video": True,
                    "preferred": "video",
                }
        raise ParserError("暂时没有拿到公开视频示例")

    async def iter_explore_feed_results(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        html = await self.fetch_text("https://www.xiaohongshu.com/explore")
        state = extract_initial_state(html)
        feeds = get_array(get_map(get_map(state, "feed"), "feedsHolder"), "feeds")
        if not feeds:
            feeds = get_array(get_map(state, "feed"), "feeds")
        if not feeds:
            raise ParserError("暂时没有拿到公开示例")

        for raw_feed in feeds:
            if not isinstance(raw_feed, dict):
                continue
            note_id = get_string(raw_feed, "id")
            xsec_token = get_string(raw_feed, "xsecToken") or get_string(raw_feed, "xsec_token")
            if not note_id or not xsec_token:
                continue
            note_url = build_feed_note_url(note_id, xsec_token)
            try:
                yield note_url, await self.collect(note_url)
            except ParserError:
                continue

    async def resolve_share_url(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        host = parsed.hostname or ""
        if not is_xhs_host(host) and not is_xhslink_host(host):
            return raw_url
        response = await self.client.get(raw_url, headers=browser_headers())
        return str(response.url)

    async def fetch_text(self, raw_url: str) -> str:
        response = await self.client.get(raw_url, headers=browser_headers())
        text = response.text
        if "window.__INITIAL_STATE__" not in text and response.status_code >= 400:
            raise ParserError(f"小红书页面请求失败：{response.status_code}")
        return text


def browser_headers() -> dict[str, str]:
    return {
        "user-agent": BROWSER_UA,
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "referer": "https://www.xiaohongshu.com/explore",
    }


def extract_first_url(input_text: str) -> str:
    match = URL_RE.search(input_text)
    if not match:
        return ""
    return match.group(0).rstrip("，。,.")


def extract_note_id(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    for index, part in enumerate(parts):
        if part in {"explore", "item"} and index + 1 < len(parts):
            return parts[index + 1]
    if len(parts) >= 3 and parts[0] == "discovery" and parts[1] == "item":
        return parts[2]
    return ""


def extract_initial_state(html: str) -> dict[str, Any]:
    match = INITIAL_STATE_RE.search(html)
    if not match:
        raise ParserError("页面中没有找到 SSR 数据")
    raw = match.group(1).strip().rstrip(";").replace(":undefined", ":null")
    try:
        state = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ParserError(f"页面 SSR 数据无法解析：{exc}") from exc
    if not isinstance(state, dict):
        raise ParserError("页面 SSR 数据无法解析")
    return state


def find_note_detail(state: dict[str, Any], note_id: str) -> dict[str, Any] | None:
    detail_map = get_map(get_map(state, "note"), "noteDetailMap")
    direct = get_map(detail_map, note_id)
    if get_map(direct, "note"):
        return direct
    for value in detail_map.values():
        if not isinstance(value, dict):
            continue
        note = get_map(value, "note")
        if (
            get_string(note, "noteId") == note_id
            or get_string(note, "id") == note_id
            or get_string(note, "title")
            or get_string(note, "desc")
        ):
            return value
    return None


def normalize_note(note: dict[str, Any], source_url: str) -> Collection:
    images = normalize_images(get_array(note, "imageList"))
    video = normalize_video(get_map(note, "video"), images)
    note_id = get_string(note, "noteId") or extract_note_id(source_url)
    created_at = xhs_time(get_any(note, "time"))
    updated_at = xhs_time(get_any(note, "lastUpdateTime"))

    return Collection(
        id=note_id,
        platform="xiaohongshu",
        sourceId=note_id,
        sourceUrl=source_url,
        canonicalUrl=source_url,
        type=default_string(get_string(note, "type"), "normal"),
        title=default_string(get_string(note, "title"), "未命名笔记"),
        content=get_string(note, "desc"),
        author=normalize_author(get_map(note, "user")),
        images=images,
        video=video,
        tags=normalize_tags(note),
        stats=normalize_stats(get_map(note, "interactInfo")),
        sourceCreatedAt=created_at,
        sourceUpdatedAt=updated_at,
        createdAt=created_at,
        updatedAt=updated_at,
        collectedAt=now_utc(),
    )


def normalize_images(raw_images: list[Any]) -> list[Image]:
    images: list[Image] = []
    for raw in raw_images:
        if not isinstance(raw, dict):
            continue
        image_url = first_string(
            get_string(raw, "urlDefault"),
            get_string(raw, "urlPre"),
            get_string(raw, "url"),
            find_info_list_url(get_array(raw, "infoList")),
        )
        image_url = normalize_asset_url(image_url)
        if not image_url:
            continue
        images.append(
            Image(
                url=image_url,
                width=get_int(raw, "width"),
                height=get_int(raw, "height"),
                livePhoto=get_bool(raw, "livePhoto"),
            )
        )
    return images


def normalize_author(user: dict[str, Any]) -> Author:
    return Author(
        id=get_string(user, "userId"),
        name=default_string(first_string(get_string(user, "nickname"), get_string(user, "nickName")), "小红书用户"),
        avatar=normalize_asset_url(get_string(user, "avatar")),
    )


def normalize_tags(note: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for raw in get_array(note, "tagList"):
        if isinstance(raw, dict):
            name = get_string(raw, "name").strip()
            if name:
                tags.append(name)
    if tags:
        return tags
    return [match.group(1) for match in HASH_TAG_RE.finditer(get_string(note, "desc"))]


def normalize_stats(info: dict[str, Any]) -> Stats:
    return Stats(
        likes=default_string(get_count_string(info, "likedCount"), "0"),
        collects=default_string(get_count_string(info, "collectedCount"), "0"),
        comments=default_string(get_count_string(info, "commentCount"), "0"),
        shares=default_string(get_count_string(info, "shareCount"), "0"),
    )


def normalize_video(raw_video: dict[str, Any], images: list[Image]) -> Video | None:
    if not raw_video:
        return None
    media_v2 = parse_json_string(get_string(raw_video, "mediaV2"))
    streams: list[dict[str, Any]] = []
    streams.extend(extract_streams(get_map(get_map(raw_video, "media"), "stream")))
    streams.extend(extract_streams(get_map(media_v2, "stream")))
    if not streams:
        return None

    selected = streams[0]
    for stream in streams:
        if get_bool(stream, "defaultStream") or get_bool(stream, "default_stream"):
            selected = stream
            break
        if get_video_url(stream):
            selected = stream

    video_url = normalize_xhs_video_url(get_video_url(selected))
    if not video_url:
        return None

    poster = images[0].url if images else ""
    duration = first_int(
        get_int(selected, "duration"),
        get_int(selected, "videoDuration"),
        get_int(selected, "video_duration"),
        get_int(get_map(get_map(raw_video, "media"), "video"), "duration"),
        get_int(get_map(media_v2, "video"), "duration"),
        get_int(get_map(raw_video, "capa"), "duration"),
    )
    if duration > 1000:
        duration //= 1000

    return Video(
        url=video_url,
        poster=poster,
        width=first_int(get_int(selected, "width"), get_int(get_map(media_v2, "video"), "width")),
        height=first_int(get_int(selected, "height"), get_int(get_map(media_v2, "video"), "height")),
        duration=duration,
        format=default_string(get_string(selected, "format"), "mp4"),
        codec=default_string(first_string(get_string(selected, "videoCodec"), get_string(selected, "video_codec")), "h264"),
    )


def extract_streams(stream_map: dict[str, Any]) -> list[dict[str, Any]]:
    streams: list[dict[str, Any]] = []
    for codec in ("h264", "h265", "h266", "av1"):
        for raw in get_array(stream_map, codec):
            if isinstance(raw, dict):
                streams.append(raw)
    return streams


def get_video_url(stream: dict[str, Any]) -> str:
    for key in ("masterUrl", "master_url", "url"):
        value = get_string(stream, key)
        if value:
            return value
    for key in ("backupUrls", "backup_urls"):
        urls = get_array(stream, key)
        if urls and isinstance(urls[0], str):
            return urls[0]
    return ""


def build_feed_note_url(note_id: str, xsec_token: str) -> str:
    return f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={quote(xsec_token)}&xsec_source=pc_feed"


def find_info_list_url(info_list: list[Any]) -> str:
    for raw in info_list:
        if isinstance(raw, dict):
            value = get_string(raw, "url")
            if value:
                return value
    return ""


def normalize_asset_url(value: str) -> str:
    if not value:
        return ""
    if value.startswith("//"):
        value = "https:" + value
    if value.startswith("http://"):
        value = "https://" + value.removeprefix("http://")
    return normalize_xhs_image_url(value)


def normalize_xhs_image_url(value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if not host.endswith(".xhscdn.com"):
        return value

    resource_id = extract_xhs_image_resource_id(parsed.path)
    if not resource_id:
        return value

    path_prefix = "spectrum/" if has_xhs_spectrum_path(parsed.path) else ""

    if host.startswith("sns-webpic-"):
        image_host = host.replace("sns-webpic-", "sns-img-", 1)
        return f"https://{image_host}/{path_prefix}{resource_id}{XHS_IMAGE_STYLE_SUFFIX}"

    if host.startswith("sns-img-") and "!" not in parsed.path:
        return f"https://{host}/{path_prefix}{resource_id}{XHS_IMAGE_STYLE_SUFFIX}"

    return value


def has_xhs_spectrum_path(path: str) -> bool:
    return any(part == "spectrum" for part in path.split("/"))


def extract_xhs_image_resource_id(path: str) -> str:
    filename = path.rsplit("/", 1)[-1]
    if not filename:
        return ""
    return filename.split("!", 1)[0].split("?", 1)[0]


def is_xhs_host(host: str) -> bool:
    return host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com")


def is_xhslink_host(host: str) -> bool:
    return host == "xhslink.com" or host.endswith(".xhslink.com")


def parse_json_string(value: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def get_map(data: dict[str, Any], key: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def get_array(data: dict[str, Any], key: str) -> list[Any]:
    if not isinstance(data, dict):
        return []
    value = data.get(key)
    return value if isinstance(value, list) else []


def get_any(data: dict[str, Any], key: str) -> Any:
    if not isinstance(data, dict):
        return None
    return data.get(key)


def get_string(data: dict[str, Any], key: str) -> str:
    value = get_any(data, key)
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, int | float):
        return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
    return ""


def get_count_string(data: dict[str, Any], key: str) -> str:
    value = get_any(data, key)
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, int | float):
        return str(int(value))
    return ""


def get_int(data: dict[str, Any], key: str) -> int:
    value = get_any(data, key)
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def get_bool(data: dict[str, Any], key: str) -> bool:
    return bool(get_any(data, key) is True)


def xhs_time(value: Any) -> str:
    millis = 0
    if isinstance(value, int | float):
        millis = int(value)
    elif isinstance(value, str):
        try:
            millis = int(value)
        except ValueError:
            millis = 0
    if millis <= 0:
        return ""
    if millis < 1_000_000_000_000:
        dt = datetime.fromtimestamp(millis, UTC)
    else:
        dt = datetime.fromtimestamp(millis / 1000, UTC)
    return dt.isoformat().replace("+00:00", "Z")


def first_string(*values: str) -> str:
    return next((value for value in values if value), "")


def first_int(*values: int) -> int:
    return next((value for value in values if value), 0)


def default_string(value: str, fallback: str) -> str:
    return value if value.strip() else fallback
