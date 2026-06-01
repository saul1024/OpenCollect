from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from backend.app.media.video_urls import normalize_xhs_video_url
from backend.app.store.models import Collection, CollectionPatch, DataFile, FetchState, model_to_api


SCHEMA_VERSION = 1
logger = logging.getLogger(__name__)


class StoreError(Exception):
    pass


class CollectionNotFound(StoreError):
    pass


class CollectionConflict(StoreError):
    pass


@dataclass(frozen=True)
class SaveFrontResult:
    collection: Collection
    snapshot: DataFile
    duplicated: bool = False


class JSONStore:
    def __init__(self, path: Path | str, on_write=None):
        self.path = Path(path)
        self._on_write = on_write
        self._lock = threading.RLock()
        self._data = self._load()

    def snapshot(self) -> DataFile:
        with self._lock:
            return self._clone_data(self._data)

    def list(self) -> list[Collection]:
        with self._lock:
            return [self._clone_collection(item) for item in self._data.collections]

    def get(self, collection_id: str) -> Collection | None:
        with self._lock:
            for collection in self._data.collections:
                if collection.id == collection_id:
                    return self._clone_collection(collection)
        return None

    def add_front(self, collection: Collection) -> SaveFrontResult:
        saved: Collection | None = None
        duplicated = False
        snapshot_for_hook: DataFile | None = None

        with self._lock:
            now = now_utc()
            next_data = self._clone_data(self._data)
            normalized = normalize_collection(collection, now)
            if not normalized.collected_at:
                normalized.collected_at = now
            mark_fetch_success(normalized, now)

            for index, existing in enumerate(next_data.collections):
                if same_collection(existing, normalized):
                    saved = self._clone_collection(existing)
                    duplicated = True
                    snapshot = self._clone_data(self._data)
                    break
            else:
                next_data.collections.insert(0, normalized)
                saved = normalized
                snapshot = self._commit_locked(next_data)
                snapshot_for_hook = snapshot

        if saved is None:
            raise StoreError("收藏保存失败")
        if snapshot_for_hook is not None:
            self._run_on_write(snapshot_for_hook)
        return SaveFrontResult(self._clone_collection(saved), snapshot, duplicated)

    def upsert_front(self, collection: Collection) -> tuple[Collection, DataFile]:
        saved: Collection | None = None

        def mutate(next_data: DataFile) -> None:
            nonlocal saved
            now = now_utc()
            normalized = normalize_collection(collection, now)
            if not normalized.collected_at:
                normalized.collected_at = now
            mark_fetch_success(normalized, now)

            for index, existing in enumerate(next_data.collections):
                if same_collection(existing, normalized):
                    normalized.collected_at = existing.collected_at or now
                    normalized.user_modified_fields = existing.user_modified_fields
                    preserve_user_modified_fields(normalized, existing)
                    next_data.collections[index] = normalized
                    saved = normalized
                    return

            next_data.collections.insert(0, normalized)
            saved = normalized

        snapshot = self._update(mutate)
        if saved is None:
            raise StoreError("收藏保存失败")
        return self._clone_collection(saved), snapshot

    def import_collections(self, collections: list[Collection]) -> tuple[int, int, DataFile]:
        imported = 0
        updated = 0

        def mutate(next_data: DataFile) -> None:
            nonlocal imported, updated
            now = now_utc()
            for collection in collections:
                normalized = normalize_collection(collection, now)
                if not normalized.collected_at:
                    normalized.collected_at = now

                for index, existing in enumerate(next_data.collections):
                    if same_collection(existing, normalized):
                        if not normalized.collected_at:
                            normalized.collected_at = existing.collected_at or now
                        next_data.collections[index] = normalized
                        updated += 1
                        break
                else:
                    next_data.collections.append(normalized)
                    imported += 1

        snapshot = self._update(mutate)
        return imported, updated, snapshot

    def patch(self, collection_id: str, patch: CollectionPatch) -> tuple[Collection, DataFile]:
        saved: Collection | None = None

        def mutate(next_data: DataFile) -> None:
            nonlocal saved
            now = now_utc()
            for index, collection in enumerate(next_data.collections):
                if collection.id != collection_id:
                    continue
                if patch.title is not None:
                    collection.title = patch.title.strip()
                if patch.content is not None:
                    collection.content = patch.content.strip()
                if patch.tags is not None:
                    collection.tags = sanitize_tags(patch.tags)
                    mark_user_modified(collection, "tags")
                if patch.source_url is not None and patch.source_url.strip():
                    collection.source_url = patch.source_url.strip()
                    collection.canonical_url = canonical_source_url(collection.source_url, collection.platform)
                    mark_user_modified(collection, "sourceUrl")
                if patch.title is not None:
                    mark_user_modified(collection, "title")
                if patch.content is not None:
                    mark_user_modified(collection, "content")
                next_data.collections[index] = normalize_collection(collection, now)
                saved = next_data.collections[index]
                return
            raise CollectionNotFound("收藏不存在")

        snapshot = self._update(mutate)
        if saved is None:
            raise CollectionNotFound("收藏不存在")
        return self._clone_collection(saved), snapshot

    def delete(self, collection_id: str) -> tuple[Collection, DataFile]:
        deleted: Collection | None = None

        def mutate(next_data: DataFile) -> None:
            nonlocal deleted
            for index, collection in enumerate(next_data.collections):
                if collection.id == collection_id:
                    deleted = collection
                    del next_data.collections[index]
                    return
            raise CollectionNotFound("收藏不存在")

        snapshot = self._update(mutate)
        if deleted is None:
            raise CollectionNotFound("收藏不存在")
        return self._clone_collection(deleted), snapshot

    def clear(self) -> tuple[list[Collection], DataFile]:
        previous: list[Collection] = []

        def mutate(next_data: DataFile) -> None:
            nonlocal previous
            previous = [self._clone_collection(item) for item in next_data.collections]
            next_data.collections = []

        snapshot = self._update(mutate)
        return previous, snapshot

    def refresh(self, collection_id: str, refreshed: Collection) -> tuple[Collection, DataFile]:
        saved: Collection | None = None

        def mutate(next_data: DataFile) -> None:
            nonlocal saved
            now = now_utc()
            target_index = -1
            existing: Collection | None = None
            for index, collection in enumerate(next_data.collections):
                if collection.id == collection_id:
                    target_index = index
                    existing = collection
                    break
            if existing is None:
                raise CollectionNotFound("收藏不存在")

            normalized = normalize_collection(refreshed, now)
            for index, other in enumerate(next_data.collections):
                if index != target_index and same_collection(other, normalized):
                    raise CollectionConflict("刷新结果与已有收藏重复")

            merged = merge_refreshed_collection(existing, normalized, now)
            next_data.collections[target_index] = normalize_collection(merged, now)
            saved = next_data.collections[target_index]

        snapshot = self._update(mutate)
        if saved is None:
            raise CollectionNotFound("收藏不存在")
        return self._clone_collection(saved), snapshot

    def record_fetch_failure(self, collection_id: str, reason: str, message: str) -> tuple[Collection, DataFile]:
        saved: Collection | None = None

        def mutate(next_data: DataFile) -> None:
            nonlocal saved
            now = now_utc()
            for index, collection in enumerate(next_data.collections):
                if collection.id != collection_id:
                    continue
                collection.fetch.last_attempt_at = now
                collection.fetch.last_status = "failed"
                collection.fetch.last_error_reason = reason
                collection.fetch.last_error_message = message
                next_data.collections[index] = normalize_collection(collection, now)
                saved = next_data.collections[index]
                return
            raise CollectionNotFound("收藏不存在")

        snapshot = self._update(mutate)
        if saved is None:
            raise CollectionNotFound("收藏不存在")
        return self._clone_collection(saved), snapshot

    def _load(self) -> DataFile:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            data = DataFile(schemaVersion=SCHEMA_VERSION, revision=0, updatedAt="", collections=[])
            write_json_atomic(self.path, data)
            return data

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StoreError(f"collections json is invalid: {exc}") from exc

        data = DataFile.model_validate(raw)
        if data.schema_version == 0:
            data.schema_version = SCHEMA_VERSION
        if data.schema_version != SCHEMA_VERSION:
            raise StoreError(f"unsupported schema version: {data.schema_version}")

        needs_migration = needs_data_migration(raw)
        now = now_utc()
        data.collections = [normalize_collection(collection, now) for collection in data.collections]
        if needs_migration:
            data.revision += 1
            data.updated_at = now
            write_json_atomic(self.path, data)
        return data

    def _update(self, mutator) -> DataFile:
        with self._lock:
            next_data = self._clone_data(self._data)
            mutator(next_data)
            snapshot = self._commit_locked(next_data)
        self._run_on_write(snapshot)
        return snapshot

    def _commit_locked(self, next_data: DataFile) -> DataFile:
        next_data.schema_version = SCHEMA_VERSION
        next_data.revision += 1
        next_data.updated_at = now_utc()
        if next_data.collections is None:
            next_data.collections = []
        write_json_atomic(self.path, next_data)
        self._data = next_data
        return self._clone_data(next_data)

    def _run_on_write(self, snapshot: DataFile) -> None:
        if self._on_write is None:
            return
        try:
            self._on_write(self.path, snapshot)
        except Exception as exc:
            logger.warning("post-write hook failed: %s", exc)

    @staticmethod
    def _clone_data(data: DataFile) -> DataFile:
        return DataFile.model_validate(copy.deepcopy(model_to_api(data)))

    @staticmethod
    def _clone_collection(collection: Collection) -> Collection:
        return Collection.model_validate(copy.deepcopy(model_to_api(collection)))


def write_json_atomic(path: Path, data: DataFile) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(model_to_api(data), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def normalize_collection(collection: Collection, now: str) -> Collection:
    collection = Collection.model_validate(model_to_api(collection))
    collection.id = collection.id.strip()
    collection.source_id = collection.source_id.strip()
    collection.source_url = collection.source_url.strip()
    collection.canonical_url = collection.canonical_url.strip()
    collection.platform = normalize_platform(collection.platform, collection.source_url)
    collection.canonical_url = canonical_source_url(collection.canonical_url or collection.source_url, collection.platform)
    collection.type = collection.type.strip() or "normal"
    collection.title = collection.title.strip() or "无标题笔记"
    collection.author.name = collection.author.name.strip() or "未知作者"
    collection.tags = sanitize_tags(collection.tags)
    collection.images = collection.images or []
    collection.user_modified_fields = sanitize_user_modified_fields(collection.user_modified_fields)
    normalize_collection_video(collection)

    if not collection.stats.likes:
        collection.stats.likes = "0"
    if not collection.stats.collects:
        collection.stats.collects = "0"
    if not collection.stats.comments:
        collection.stats.comments = "0"
    if not collection.stats.shares:
        collection.stats.shares = "0"
    if not collection.source_id:
        collection.source_id = collection.id
    if not collection.id:
        collection.id = collection.source_id
    if not collection.id:
        collection.id = generated_id(collection)
    if not collection.updated_at:
        collection.updated_at = now
    return collection


def normalize_collection_video(collection: Collection) -> None:
    if collection.video is None:
        return
    collection.video.url = normalize_xhs_video_url(collection.video.url)
    for stream in collection.video.streams:
        stream.url = normalize_xhs_video_url(stream.url)
        stream.backup_urls = [normalize_xhs_video_url(url) for url in stream.backup_urls if url]


def needs_data_migration(raw: object) -> bool:
    if not isinstance(raw, dict):
        return False
    collections = raw.get("collections")
    if not isinstance(collections, list):
        return False
    return any(needs_collection_migration(collection) for collection in collections)


def needs_collection_migration(raw: object) -> bool:
    if not isinstance(raw, dict):
        return False
    video = raw.get("video")
    if not isinstance(video, dict):
        return False
    if "rawUrl" in video or "fallbackUrls" in video:
        return True
    url = video.get("url")
    return isinstance(url, str) and bool(url) and normalize_xhs_video_url(url) != url


def same_collection(left: Collection, right: Collection) -> bool:
    if left.id and right.id and left.id == right.id:
        return True
    if left.source_id and right.source_id and left.platform == right.platform and left.source_id == right.source_id:
        return True
    left_key = left.canonical_url or canonical_source_url(left.source_url, left.platform)
    right_key = right.canonical_url or canonical_source_url(right.source_url, right.platform)
    return bool(left_key and right_key and left_key == right_key)


def merge_refreshed_collection(existing: Collection, refreshed: Collection, now: str) -> Collection:
    merged = Collection.model_validate(model_to_api(refreshed))
    merged.id = existing.id
    merged.collected_at = existing.collected_at or now
    merged.user_modified_fields = sanitize_user_modified_fields(existing.user_modified_fields)
    preserve_user_modified_fields(merged, existing)
    mark_fetch_success(merged, now)
    return merged


def preserve_user_modified_fields(target: Collection, existing: Collection) -> None:
    fields = set(existing.user_modified_fields)
    if "title" in fields:
        target.title = existing.title
    if "content" in fields:
        target.content = existing.content
    if "tags" in fields:
        target.tags = existing.tags
    if "sourceUrl" in fields:
        target.source_url = existing.source_url
        target.canonical_url = existing.canonical_url


def mark_fetch_success(collection: Collection, now: str) -> None:
    collection.fetch = FetchState(
        lastSuccessAt=now,
        lastAttemptAt=now,
        lastStatus="success",
        lastErrorReason="",
        lastErrorMessage="",
    )


def mark_user_modified(collection: Collection, field: str) -> None:
    fields = sanitize_user_modified_fields(collection.user_modified_fields)
    if field not in fields:
        fields.append(field)
    collection.user_modified_fields = fields


def sanitize_user_modified_fields(fields: list[str]) -> list[str]:
    allowed = {"title", "content", "tags", "sourceUrl"}
    result: list[str] = []
    for field in fields:
        if field in allowed and field not in result:
            result.append(field)
    return result


def canonical_source_url(raw_url: str, platform: str = "") -> str:
    if not raw_url:
        return ""
    parsed = urlparse(raw_url.strip())
    if not parsed.scheme or not parsed.netloc:
        return raw_url.strip()
    host = (parsed.hostname or "").lower()
    normalized_platform = platform or infer_platform(raw_url)
    if normalized_platform == "xiaohongshu" or "xiaohongshu.com" in host:
        note_id = extract_xhs_note_id(parsed.path)
        if note_id:
            return f"https://www.xiaohongshu.com/explore/{note_id}"
    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    path = parsed.path.rstrip("/") or "/"
    return parsed._replace(scheme=parsed.scheme.lower(), netloc=netloc, path=path, fragment="").geturl()


def extract_xhs_note_id(path: str) -> str:
    parts = [part for part in path.strip("/").split("/") if part]
    for index, part in enumerate(parts):
        if part in {"explore", "item"} and index + 1 < len(parts):
            return parts[index + 1]
    if len(parts) >= 3 and parts[0] == "discovery" and parts[1] == "item":
        return parts[2]
    return ""


def generated_id(collection: Collection) -> str:
    key = f"{collection.platform}|{collection.source_url}|{collection.title}"
    return "oc_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def normalize_platform(platform: str, source_url: str) -> str:
    value = platform.strip().lower()
    if value in {"xiaohongshu", "xhs", "red", "小红书"}:
        return "xiaohongshu"
    if value in {"douyin", "抖音"}:
        return "douyin"
    if value in {"bilibili", "b站", "哔哩哔哩"}:
        return "bilibili"
    if value in {"youtube", "yt"}:
        return "youtube"
    if value in {"instagram", "ig"}:
        return "instagram"
    if value == "tiktok":
        return "tiktok"
    if value in {"wechat", "weixin", "微信"}:
        return "wechat"
    inferred = infer_platform(source_url)
    if inferred:
        return inferred
    return value or "xiaohongshu"


def infer_platform(raw_url: str) -> str:
    host = urlparse(raw_url).hostname or ""
    host = host.lower()
    if "xiaohongshu.com" in host or "xhslink.com" in host:
        return "xiaohongshu"
    if "douyin.com" in host:
        return "douyin"
    if "bilibili.com" in host or "b23.tv" in host:
        return "bilibili"
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "instagram.com" in host:
        return "instagram"
    if "tiktok.com" in host:
        return "tiktok"
    if "weixin.qq.com" in host or "mp.weixin.qq.com" in host:
        return "wechat"
    return ""


def sanitize_tags(tags: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        value = tag.strip().removeprefix("#").removesuffix("#").removesuffix("[话题]").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
