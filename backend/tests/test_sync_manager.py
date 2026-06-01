from __future__ import annotations

import json
from pathlib import Path

from backend.app.core.config import Settings, SyncSettings
from backend.app.store.json_store import JSONStore
from backend.app.store.models import CollectionPatch, DataFile, model_to_api
from backend.app.sync.manager import SyncManager
from backend.tests.test_json_store import collection


class FakeSyncer:
    def __init__(self, remote: bytes | None = None, push_error: Exception | None = None):
        self.remote = remote
        self.push_error = push_error
        self.pulls = 0
        self.pushes: list[bytes] = []
        self.backups: list[tuple[bytes, int]] = []

    def pull(self) -> bytes | None:
        self.pulls += 1
        return self.remote

    def push(self, data: bytes) -> None:
        if self.push_error is not None:
            raise self.push_error
        self.pushes.append(data)
        self.remote = data

    def backup(self, data: bytes, revision: int) -> str:
        self.backups.append((data, revision))
        return f"opencollect/backups/rev-{revision}.json"


def test_sync_manager_pulls_remote_file_before_store_load(tmp_path: Path):
    remote = DataFile(
        schemaVersion=1,
        revision=7,
        updatedAt="2026-05-27T00:00:00Z",
        collections=[collection("remote-note")],
    )
    syncer = FakeSyncer(remote=json.dumps(model_to_api(remote)).encode())
    settings = sync_settings(tmp_path)
    manager = SyncManager(settings, syncer=syncer)

    manager.bootstrap_local_file(settings.collections_path)
    store = JSONStore(settings.collections_path, on_write=manager.after_local_write)
    snapshot = store.snapshot()

    assert syncer.pulls == 1
    assert snapshot.revision == 7
    assert snapshot.collections[0].id == "remote-note"
    state = manager.status_payload()
    assert state["status"] == "synced"
    assert state["dirty"] is False
    assert state["last_pushed_revision"] == 7


def test_sync_manager_marks_dirty_after_local_write_without_upload(tmp_path: Path):
    syncer = FakeSyncer(remote=None)
    settings = sync_settings(tmp_path)
    manager = SyncManager(settings, syncer=syncer)
    store = JSONStore(settings.collections_path, on_write=manager.after_local_write)

    _, _, snapshot = store.import_collections([collection("note-1")])
    state = manager.status_payload()

    assert snapshot.revision == 1
    assert syncer.backups == []
    assert syncer.pushes == []
    assert state["status"] == "local_dirty"
    assert state["dirty"] is True
    assert state["last_pushed_revision"] == 0
    assert state["pending_revision"] == 1


def test_sync_manager_push_now_uploads_and_clears_dirty(tmp_path: Path):
    syncer = FakeSyncer(remote=None)
    settings = sync_settings(tmp_path)
    manager = SyncManager(settings, syncer=syncer)
    store = JSONStore(settings.collections_path, on_write=manager.after_local_write)

    _, _, snapshot = store.import_collections([collection("note-1")])
    state = manager.push_now(settings.collections_path, snapshot)

    assert len(syncer.backups) == 1
    assert syncer.backups[0][1] == 1
    assert len(syncer.pushes) == 1
    assert json.loads(syncer.pushes[0].decode())["revision"] == 1
    assert state.status == "synced"
    assert state.dirty is False
    assert state.last_pushed_revision == 1
    assert state.pending_revision == 0


def test_sync_manager_push_failure_does_not_fail_local_write(tmp_path: Path):
    syncer = FakeSyncer(remote=None, push_error=RuntimeError("cos unavailable"))
    settings = sync_settings(tmp_path)
    manager = SyncManager(settings, syncer=syncer)
    store = JSONStore(settings.collections_path, on_write=manager.after_local_write)

    _, _, snapshot = store.import_collections([collection("note-1")])
    manager.push_now(settings.collections_path, snapshot)
    state = manager.status_payload()

    assert snapshot.revision == 1
    assert store.snapshot().collections[0].id == "note-1"
    assert state["status"] == "push_failed"
    assert state["dirty"] is True
    assert state["pending_revision"] == 1
    assert "cos unavailable" in state["last_error"]


def test_sync_manager_keeps_local_file_when_local_revision_is_newer(tmp_path: Path):
    settings = sync_settings(tmp_path)
    local_store = JSONStore(settings.collections_path)
    local_store.import_collections([collection("local-note-1")])
    local_store.import_collections([collection("local-note-2")])
    remote = DataFile(
        schemaVersion=1,
        revision=1,
        updatedAt="2026-05-27T00:00:00Z",
        collections=[collection("remote-note")],
    )
    syncer = FakeSyncer(remote=json.dumps(model_to_api(remote)).encode())
    manager = SyncManager(settings, syncer=syncer)

    manager.bootstrap_local_file(settings.collections_path)
    store = JSONStore(settings.collections_path, on_write=manager.after_local_write)
    manager.initialize_local_snapshot(store.snapshot())
    snapshot = store.snapshot()
    state = manager.status_payload()

    assert snapshot.revision == 2
    assert [item.id for item in snapshot.collections] == ["local-note-1", "local-note-2"]
    assert state["status"] == "local_dirty"
    assert state["dirty"] is True
    assert state["last_pushed_revision"] == 1
    assert state["pending_revision"] == 2


def test_sync_status_does_not_expose_cloud_secrets(tmp_path: Path):
    syncer = FakeSyncer(remote=None)
    settings = sync_settings(tmp_path)
    manager = SyncManager(settings, syncer=syncer)

    state = manager.status_payload()
    raw_state = json.dumps(state)

    assert "access_key_id" not in state
    assert "secret_access_key" not in state
    assert settings.sync.access_key_id not in raw_state
    assert settings.sync.secret_access_key not in raw_state


def test_sync_manager_auto_merges_remote_and_local_additions(tmp_path: Path):
    base = DataFile(
        schemaVersion=1,
        revision=1,
        updatedAt="2026-05-27T00:00:00Z",
        collections=[collection("base-note")],
    )
    syncer = FakeSyncer(remote=json.dumps(model_to_api(base)).encode())
    settings = sync_settings(tmp_path)
    manager = SyncManager(settings, syncer=syncer)
    manager.bootstrap_local_file(settings.collections_path)
    store = JSONStore(settings.collections_path, on_write=manager.after_local_write)

    _, _, local_snapshot = store.import_collections([collection("local-note")])
    remote = DataFile(
        schemaVersion=1,
        revision=2,
        updatedAt="2026-05-28T00:00:00Z",
        collections=[collection("base-note"), collection("remote-note")],
    )
    syncer.remote = json.dumps(model_to_api(remote)).encode()

    state = manager.push_now(settings.collections_path, local_snapshot)
    pushed = json.loads(syncer.pushes[-1].decode())

    assert state.status == "synced_auto_merged"
    assert state.dirty is False
    assert state.last_pushed_revision == 3
    assert pushed["revision"] == 3
    assert {item["id"] for item in pushed["collections"]} == {"base-note", "local-note", "remote-note"}
    assert JSONStore(settings.collections_path).snapshot().revision == 3


def test_sync_manager_remote_edit_requires_manual_conflict(tmp_path: Path):
    base = DataFile(
        schemaVersion=1,
        revision=1,
        updatedAt="2026-05-27T00:00:00Z",
        collections=[collection("base-note")],
    )
    syncer = FakeSyncer(remote=json.dumps(model_to_api(base)).encode())
    settings = sync_settings(tmp_path)
    manager = SyncManager(settings, syncer=syncer)
    manager.bootstrap_local_file(settings.collections_path)
    store = JSONStore(settings.collections_path, on_write=manager.after_local_write)

    edited = collection("base-note")
    edited.title = "云端编辑"
    remote = DataFile(schemaVersion=1, revision=2, updatedAt="2026-05-28T00:00:00Z", collections=[edited])
    syncer.remote = json.dumps(model_to_api(remote)).encode()
    patched, local_snapshot = store.patch("base-note", CollectionPatch(title="本地编辑"))

    state = manager.push_now(settings.collections_path, local_snapshot)

    assert patched.title == "本地编辑"
    assert state.status == "remote_conflict"
    assert state.dirty is True
    assert state.pending_revision == local_snapshot.revision
    assert state.remote_revision == 2
    assert state.conflict_type == "manual_required"
    assert syncer.pushes == []


def test_sync_manager_force_push_overwrites_remote_conflict(tmp_path: Path):
    base = DataFile(schemaVersion=1, revision=1, collections=[collection("base-note")])
    syncer = FakeSyncer(remote=json.dumps(model_to_api(base)).encode())
    settings = sync_settings(tmp_path)
    manager = SyncManager(settings, syncer=syncer)
    manager.bootstrap_local_file(settings.collections_path)
    store = JSONStore(settings.collections_path, on_write=manager.after_local_write)

    edited = collection("base-note")
    edited.title = "云端编辑"
    remote = DataFile(schemaVersion=1, revision=2, collections=[edited])
    syncer.remote = json.dumps(model_to_api(remote)).encode()
    _, local_snapshot = store.patch("base-note", CollectionPatch(title="本地编辑"))

    state = manager.push_now(settings.collections_path, local_snapshot, force=True)
    pushed = json.loads(syncer.pushes[-1].decode())

    assert state.status == "synced_overwrote_remote"
    assert state.dirty is False
    assert pushed["collections"][0]["title"] == "本地编辑"
    assert len(syncer.backups) >= 2


def test_sync_manager_pull_now_backs_up_dirty_local_and_replaces_file(tmp_path: Path):
    base = DataFile(schemaVersion=1, revision=1, collections=[collection("base-note")])
    syncer = FakeSyncer(remote=json.dumps(model_to_api(base)).encode())
    settings = sync_settings(tmp_path)
    manager = SyncManager(settings, syncer=syncer)
    manager.bootstrap_local_file(settings.collections_path)
    store = JSONStore(settings.collections_path, on_write=manager.after_local_write)
    store.import_collections([collection("local-note")])

    remote = DataFile(schemaVersion=1, revision=2, collections=[collection("base-note"), collection("remote-note")])
    syncer.remote = json.dumps(model_to_api(remote)).encode()

    state = manager.pull_now(settings.collections_path)
    snapshot = JSONStore(settings.collections_path).snapshot()

    assert state.status == "synced"
    assert state.dirty is False
    assert Path(state.local_backup_path).is_file()
    assert snapshot.revision == 2
    assert {item.id for item in snapshot.collections} == {"base-note", "remote-note"}


def sync_settings(tmp_path: Path) -> Settings:
    return Settings(
        port="0",
        data_dir=tmp_path / "data",
        public_dir=tmp_path / "public",
        sync=SyncSettings(
            provider="cos",
            endpoint="https://cos.ap-guangzhou.myqcloud.com",
            region="ap-guangzhou",
            bucket="opencollect-1250000000",
            access_key_id="secret-id",
            secret_access_key="secret-key",
        ),
    )
