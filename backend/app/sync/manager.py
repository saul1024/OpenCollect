from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from backend.app.core.config import Settings, SyncSettings
from backend.app.store.json_store import SCHEMA_VERSION, canonical_source_url, normalize_collection, write_json_atomic
from backend.app.store.models import Collection, DataFile, model_to_api
from backend.app.sync.s3_client import S3Client, S3Config, S3Error


logger = logging.getLogger(__name__)


class Syncer(Protocol):
    def pull(self) -> bytes | None: ...

    def push(self, data: bytes) -> None: ...

    def backup(self, data: bytes, revision: int) -> str: ...


class NoopSyncer:
    def pull(self) -> bytes | None:
        return None

    def push(self, data: bytes) -> None:
        return None

    def backup(self, data: bytes, revision: int) -> str:
        return ""


class UnavailableSyncer:
    def __init__(self, message: str):
        self.message = message

    def pull(self) -> bytes | None:
        raise S3Error(self.message)

    def push(self, data: bytes) -> None:
        raise S3Error(self.message)

    def backup(self, data: bytes, revision: int) -> str:
        raise S3Error(self.message)


class S3Syncer:
    def __init__(self, settings: SyncSettings):
        self.settings = settings
        self.client = S3Client(
            S3Config(
                endpoint=settings.endpoint,
                region=settings.region,
                bucket=settings.bucket,
                access_key_id=settings.access_key_id,
                secret_access_key=settings.secret_access_key,
                session_token=settings.session_token,
                force_path_style=settings.force_path_style,
                timeout_seconds=settings.timeout_seconds,
            )
        )

    def pull(self) -> bytes | None:
        return self.client.get_object(self.settings.object_key)

    def push(self, data: bytes) -> None:
        self.client.put_object(self.settings.object_key, data)

    def backup(self, data: bytes, revision: int) -> str:
        prefix = self.settings.backup_prefix.strip("/")
        if not prefix:
            return ""
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_key = f"{prefix}/collections-{timestamp}-rev{revision}.json"
        self.client.put_object(backup_key, data)
        return backup_key


@dataclass
class SyncState:
    provider: str = "none"
    enabled: bool = False
    status: str = "disabled"
    dirty: bool = False
    object_key: str = ""
    backup_prefix: str = ""
    last_pull_at: str = ""
    last_push_at: str = ""
    last_backup_at: str = ""
    last_local_change_at: str = ""
    last_success_at: str = ""
    last_error_at: str = ""
    last_error: str = ""
    last_pushed_revision: int = 0
    pending_revision: int = 0
    last_backup_key: str = ""
    base_remote_revision: int = 0
    remote_revision: int = 0
    local_revision: int = 0
    conflict_type: str = ""
    local_backup_path: str = ""
    updated_at: str = ""
    extra: dict[str, str] = field(default_factory=dict)


class SyncManager:
    def __init__(self, settings: Settings, syncer: Syncer | None = None):
        self.settings = settings
        self.sync_settings = settings.sync
        self.state_path = settings.sync_state_path
        self.base_path = settings.sync_base_path
        self.local_backup_dir = settings.sync_local_backup_dir
        self._lock = threading.RLock()
        self._syncer = syncer if syncer is not None else create_syncer(self.sync_settings)
        self._state = self._load_state()
        self._persist_state()

    @property
    def enabled(self) -> bool:
        return self.sync_settings.enabled

    def bootstrap_local_file(self, collections_path: Path) -> None:
        if not self.enabled:
            return

        try:
            remote_bytes = self._syncer.pull()
        except Exception as exc:
            self._record_error("pull_failed", exc)
            logger.warning("cloud sync pull failed: %s", exc)
            return

        now = now_utc()
        if remote_bytes is None:
            self._write_base_data(empty_data_file())
            self._update_state(
                status="remote_missing",
                last_pull_at=now,
                last_error="",
                last_error_at="",
                base_remote_revision=0,
            )
            return

        try:
            remote_data = parse_data_file(remote_bytes)
        except Exception as exc:
            self._record_error("pull_invalid", exc)
            logger.warning("cloud sync pull returned invalid data: %s", exc)
            return

        local_data = self._read_local_data_file(collections_path)
        if local_data is not None and local_data.revision > remote_data.revision:
            self._write_base_data(remote_data)
            self._update_state(
                status="local_newer",
                dirty=True,
                last_pull_at=now,
                last_success_at=now,
                last_pushed_revision=remote_data.revision,
                pending_revision=local_data.revision,
                last_local_change_at=local_data.updated_at or now,
                last_error="",
                last_error_at="",
                base_remote_revision=remote_data.revision,
                remote_revision=remote_data.revision,
                local_revision=local_data.revision,
            )
            return

        try:
            write_json_atomic(collections_path, remote_data)
            self._write_base_data(remote_data)
        except Exception as exc:
            self._record_error("pull_write_failed", exc)
            logger.warning("cloud sync could not write pulled data: %s", exc)
            return

        self._update_state(
            status="synced",
            dirty=False,
            last_pull_at=now,
            last_success_at=now,
            last_pushed_revision=remote_data.revision,
            pending_revision=0,
            base_remote_revision=remote_data.revision,
            remote_revision=remote_data.revision,
            local_revision=remote_data.revision,
            last_error="",
            last_error_at="",
            conflict_type="",
        )

    def initialize_local_snapshot(self, snapshot: DataFile) -> None:
        if not self.enabled:
            return

        with self._lock:
            state = SyncState(**asdict(self._state))

        if snapshot.revision > state.last_pushed_revision:
            status = "local_only" if state.last_pushed_revision == 0 else "local_dirty"
            if state.status in {"pull_failed", "pull_invalid", "pull_write_failed"}:
                status = state.status
            self._update_state(
                status=status,
                dirty=True,
                pending_revision=snapshot.revision,
                last_local_change_at=snapshot.updated_at or now_utc(),
            )
            return

        self._update_state(dirty=False, pending_revision=0)

    def after_local_write(self, collections_path: Path, snapshot: DataFile) -> None:
        if not self.enabled:
            return

        self._update_state(
            status="local_dirty",
            dirty=True,
            pending_revision=snapshot.revision,
            last_local_change_at=snapshot.updated_at or now_utc(),
            last_error="",
            last_error_at="",
            local_revision=snapshot.revision,
            conflict_type="",
        )

    def push_now(self, collections_path: Path, snapshot: DataFile, force: bool = False) -> SyncState:
        if not self.enabled:
            return self.status()

        with self._lock:
            state = SyncState(**asdict(self._state))

        if not state.dirty and snapshot.revision <= state.last_pushed_revision:
            self._update_state(status="synced", dirty=False, pending_revision=0, last_error="", last_error_at="")
            return self.status()

        try:
            local_data = parse_data_file(collections_path.read_bytes())
            base_data = self._read_base_data() or empty_data_file(state.base_remote_revision or state.last_pushed_revision)
            remote_bytes = self._syncer.pull()
            remote_data = parse_data_file(remote_bytes) if remote_bytes is not None else None
            remote_revision = remote_data.revision if remote_data is not None else 0
            base_revision = base_data.revision

            if remote_revision != base_revision and not force:
                if remote_data is not None:
                    merged = merge_only_additions(base_data, local_data, remote_data)
                    if merged is not None:
                        write_json_atomic(collections_path, merged)
                        local_data = merged
                    else:
                        self._record_remote_conflict(local_data, remote_data, base_revision, "manual_required")
                        return self.status()
                else:
                    self._record_remote_conflict(local_data, None, base_revision, "manual_required")
                    return self.status()

            data = collections_path.read_bytes()
            backup_key = ""
            backup_error = ""
            if force and remote_data is not None and remote_revision != base_revision:
                try:
                    backup_key = self._syncer.backup(model_to_bytes(remote_data), remote_data.revision)
                except Exception as exc:
                    backup_error = str(exc)
                    logger.warning("cloud sync remote backup failed before overwrite: %s", exc)
            try:
                local_backup_key = self._syncer.backup(data, local_data.revision)
                backup_key = local_backup_key or backup_key
            except Exception as exc:
                backup_error = str(exc)
                logger.warning("cloud sync backup failed: %s", exc)

            self._syncer.push(data)
            self._write_base_data(local_data)
            now = now_utc()
            state_update = {
                "status": merged_status(force, remote_revision != base_revision, backup_error),
                "dirty": False,
                "last_push_at": now,
                "last_success_at": now,
                "last_pushed_revision": local_data.revision,
                "pending_revision": 0,
                "last_error": backup_error,
                "last_error_at": now if backup_error else "",
                "base_remote_revision": local_data.revision,
                "remote_revision": local_data.revision,
                "local_revision": local_data.revision,
                "conflict_type": "",
            }
            if backup_key:
                state_update.update({"last_backup_at": now, "last_backup_key": backup_key})
            self._update_state(**state_update)
        except Exception as exc:
            self._record_error("push_failed", exc, pending_revision=snapshot.revision, dirty=True)
            logger.warning("cloud sync push failed: %s", exc)
        return self.status()

    def retry_push(self, collections_path: Path, snapshot: DataFile) -> SyncState:
        return self.push_now(collections_path, snapshot)

    def pull_now(self, collections_path: Path) -> SyncState:
        if not self.enabled:
            return self.status()

        try:
            remote_bytes = self._syncer.pull()
            if remote_bytes is None:
                raise S3Error("云端数据不存在")
            remote_data = parse_data_file(remote_bytes)
            local_backup_path = ""
            local_data = self._read_local_data_file(collections_path)
            if local_data is not None:
                local_backup_path = self._backup_local_file(local_data)
            write_json_atomic(collections_path, remote_data)
            self._write_base_data(remote_data)
            now = now_utc()
            self._update_state(
                status="synced",
                dirty=False,
                last_pull_at=now,
                last_success_at=now,
                last_pushed_revision=remote_data.revision,
                pending_revision=0,
                base_remote_revision=remote_data.revision,
                remote_revision=remote_data.revision,
                local_revision=remote_data.revision,
                conflict_type="",
                local_backup_path=local_backup_path,
                last_error="",
                last_error_at="",
            )
        except Exception as exc:
            self._record_error("pull_failed", exc, pending_revision=self.status().pending_revision, dirty=self.status().dirty)
            logger.warning("cloud sync pull failed: %s", exc)
        return self.status()

    def status(self) -> SyncState:
        with self._lock:
            return SyncState(**asdict(self._state))

    def status_payload(self) -> dict:
        with self._lock:
            return asdict(self._state)

    def _record_error(self, status: str, exc: Exception, pending_revision: int = 0, dirty: bool | None = None) -> None:
        changes = {
            "status": status,
            "last_error": str(exc),
            "last_error_at": now_utc(),
            "pending_revision": pending_revision,
        }
        if dirty is not None:
            changes["dirty"] = dirty
        self._update_state(
            **changes,
        )

    def _load_state(self) -> SyncState:
        base = SyncState(
            provider=self.sync_settings.provider,
            enabled=self.sync_settings.enabled,
            status="idle" if self.sync_settings.enabled else "disabled",
            object_key=self.sync_settings.object_key if self.sync_settings.enabled else "",
            backup_prefix=self.sync_settings.backup_prefix if self.sync_settings.enabled else "",
        )

        if not self.state_path.exists():
            return base

        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            existing = SyncState(**raw)
        except Exception:
            return base

        existing.provider = self.sync_settings.provider
        existing.enabled = self.sync_settings.enabled
        existing.object_key = self.sync_settings.object_key if self.sync_settings.enabled else ""
        existing.backup_prefix = self.sync_settings.backup_prefix if self.sync_settings.enabled else ""
        if not self.sync_settings.enabled:
            existing.status = "disabled"
            existing.dirty = False
            existing.pending_revision = 0
        return existing

    def _read_local_data_file(self, collections_path: Path) -> DataFile | None:
        if not collections_path.exists():
            return None
        try:
            return parse_data_file(collections_path.read_bytes())
        except Exception as exc:
            logger.warning("local collections json is invalid during sync bootstrap: %s", exc)
            return None

    def _read_base_data(self) -> DataFile | None:
        if not self.base_path.exists():
            return None
        try:
            return parse_data_file(self.base_path.read_bytes())
        except Exception as exc:
            logger.warning("sync base json is invalid: %s", exc)
            return None

    def _write_base_data(self, data: DataFile) -> None:
        write_json_atomic(self.base_path, data)

    def _backup_local_file(self, data: DataFile) -> str:
        self.local_backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_path = self.local_backup_dir / f"collections-local-{timestamp}-rev{data.revision}.json"
        write_json_atomic(backup_path, data)
        return str(backup_path)

    def _record_remote_conflict(self, local_data: DataFile, remote_data: DataFile | None, base_revision: int, conflict_type: str) -> None:
        remote_revision = remote_data.revision if remote_data is not None else 0
        self._update_state(
            status="remote_conflict",
            dirty=True,
            pending_revision=local_data.revision,
            last_error="云端已有新版本",
            last_error_at=now_utc(),
            base_remote_revision=base_revision,
            remote_revision=remote_revision,
            local_revision=local_data.revision,
            conflict_type=conflict_type,
        )

    def _update_state(self, **changes) -> None:
        with self._lock:
            data = asdict(self._state)
            data.update(changes)
            data["updated_at"] = now_utc()
            self._state = SyncState(**data)
            self._persist_state_locked()

    def _persist_state(self) -> None:
        with self._lock:
            self._state.updated_at = now_utc()
            self._persist_state_locked()

    def _persist_state_locked(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        write_json_dict_atomic(self.state_path, asdict(self._state))


def create_sync_manager(settings: Settings) -> SyncManager:
    return SyncManager(settings)


def create_syncer(settings: SyncSettings) -> Syncer:
    if not settings.enabled:
        return NoopSyncer()
    try:
        return S3Syncer(settings)
    except S3Error as exc:
        return UnavailableSyncer(str(exc))


def parse_data_file(data: bytes) -> DataFile:
    try:
        raw = json.loads(data.decode("utf-8"))
        parsed = DataFile.model_validate(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise S3Error(f"collections json is invalid: {exc}") from exc

    if parsed.schema_version == 0:
        parsed.schema_version = SCHEMA_VERSION
    if parsed.schema_version != SCHEMA_VERSION:
        raise S3Error(f"unsupported schema version: {parsed.schema_version}")
    return parsed


def model_to_bytes(data: DataFile) -> bytes:
    return (json.dumps(model_to_api(data), ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def empty_data_file(revision: int = 0) -> DataFile:
    return DataFile(schemaVersion=SCHEMA_VERSION, revision=revision, updatedAt="", collections=[])


def merge_only_additions(base: DataFile, local: DataFile, remote: DataFile) -> DataFile | None:
    base_map = collection_map(base.collections)
    local_map = collection_map(local.collections)
    remote_map = collection_map(remote.collections)
    if len(base_map) != len(base.collections) or len(local_map) != len(local.collections) or len(remote_map) != len(remote.collections):
        return None

    for key, base_collection in base_map.items():
        local_collection = local_map.get(key)
        remote_collection = remote_map.get(key)
        if local_collection is None or remote_collection is None:
            return None
        if not same_collection_payload(local_collection, base_collection):
            return None
        if not same_collection_payload(remote_collection, base_collection):
            return None

    local_new_keys = set(local_map) - set(base_map)
    remote_new_keys = set(remote_map) - set(base_map)
    for key in local_new_keys & remote_new_keys:
        if not same_collection_payload(local_map[key], remote_map[key]):
            return None

    merged_collections = [Collection.model_validate(model_to_api(collection)) for collection in local.collections]
    local_keys = set(local_map)
    for collection in remote.collections:
        key = collection_key(collection)
        if key not in local_keys:
            merged_collections.append(Collection.model_validate(model_to_api(collection)))

    return DataFile(
        schemaVersion=SCHEMA_VERSION,
        revision=max(local.revision, remote.revision) + 1,
        updatedAt=now_utc(),
        collections=merged_collections,
    )


def collection_map(collections: list[Collection]) -> dict[str, Collection]:
    result: dict[str, Collection] = {}
    for collection in collections:
        key = collection_key(collection)
        if not key or key in result:
            return {}
        result[key] = collection
    return result


def collection_key(collection: Collection) -> str:
    platform = collection.platform or "unknown"
    if collection.source_id:
        return f"{platform}:source:{collection.source_id}"
    if collection.canonical_url:
        return f"{platform}:url:{collection.canonical_url}"
    if collection.source_url:
        return f"{platform}:url:{collection.source_url}"
    if collection.id:
        return f"{platform}:id:{collection.id}"
    return ""


def same_collection_payload(left: Collection, right: Collection) -> bool:
    return comparable_collection_payload(left) == comparable_collection_payload(right)


def comparable_collection_payload(collection: Collection) -> dict:
    normalized = normalize_collection(Collection.model_validate(model_to_api(collection)), "")
    payload = model_to_api(normalized)
    source_url = payload.get("sourceUrl") or ""
    platform = payload.get("platform") or ""
    payload["canonicalUrl"] = canonical_source_url(payload.get("canonicalUrl") or source_url, platform)
    payload.pop("updatedAt", None)
    return payload


def merged_status(force: bool, remote_changed: bool, backup_error: str) -> str:
    if backup_error:
        return "synced_with_backup_error"
    if force and remote_changed:
        return "synced_overwrote_remote"
    if remote_changed:
        return "synced_auto_merged"
    return "synced"


def write_json_dict_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
