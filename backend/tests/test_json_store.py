from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.store.json_store import JSONStore, RevisionConflict
from backend.app.store.models import Author, Collection, CollectionPatch, Image, Stats


def test_json_store_crud_and_persistence(tmp_path: Path):
    path = tmp_path / "collections.json"
    store = JSONStore(path)

    initial = store.snapshot()
    assert initial.revision == 0
    assert initial.collections == []

    imported, updated, snapshot = store.import_collections([collection("note-1")])
    assert imported == 1
    assert updated == 0
    assert snapshot.revision == 1
    assert len(snapshot.collections) == 1

    patched, snapshot = store.patch(
        "note-1",
        CollectionPatch(title="编辑后的标题", content="编辑后的正文", tags=["美食", "#美食", "后端"]),
    )
    assert snapshot.revision == 2
    assert patched.title == "编辑后的标题"
    assert patched.content == "编辑后的正文"
    assert patched.tags == ["美食", "后端"]

    deleted, snapshot = store.delete("note-1")
    assert deleted.id == "note-1"
    assert snapshot.revision == 3
    assert snapshot.collections == []

    _, _, snapshot = store.import_collections([collection("note-2"), collection("note-3")])
    assert snapshot.revision == 4
    assert len(snapshot.collections) == 2

    previous, snapshot = store.clear()
    assert len(previous) == 2
    assert snapshot.revision == 5
    assert snapshot.collections == []

    reloaded = JSONStore(path)
    persisted = reloaded.snapshot()
    assert persisted.revision == 5
    assert persisted.collections == []


def test_json_store_dedupes_by_source_url(tmp_path: Path):
    store = JSONStore(tmp_path / "collections.json")
    first = collection("note-1")
    second = collection("note-2")
    second.source_url = first.source_url
    second.title = "覆盖后的标题"

    imported, updated, snapshot = store.import_collections([first, second])

    assert imported == 1
    assert updated == 1
    assert len(snapshot.collections) == 1
    assert snapshot.collections[0].title == "覆盖后的标题"


def test_add_front_duplicate_does_not_write_or_overwrite_existing(tmp_path: Path):
    store = JSONStore(tmp_path / "collections.json")
    first = collection("note-1")
    first.title = "用户保留标题"
    second = collection("note-2")
    second.id = ""
    second.source_id = ""
    second.source_url = "https://www.xiaohongshu.com/explore/note-1?xsec_token=changed&extra=1"
    second.title = "不应覆盖"

    first_result = store.add_front(first)
    second_result = store.add_front(second)
    snapshot = store.snapshot()

    assert first_result.duplicated is False
    assert first_result.snapshot.revision == 1
    assert second_result.duplicated is True
    assert second_result.snapshot.revision == 1
    assert second_result.collection.title == "用户保留标题"
    assert snapshot.revision == 1
    assert len(snapshot.collections) == 1
    assert snapshot.collections[0].title == "用户保留标题"


def test_refresh_preserves_user_modified_fields_and_records_success(tmp_path: Path):
    store = JSONStore(tmp_path / "collections.json")
    store.import_collections([collection("note-1")])
    store.patch("note-1", CollectionPatch(title="用户标题", tags=["用户标签"]))

    refreshed = collection("note-1")
    refreshed.title = "平台新标题"
    refreshed.content = "平台新正文"
    refreshed.tags = ["平台标签"]
    refreshed.stats.likes = "99"

    saved, snapshot = store.refresh("note-1", refreshed)

    assert snapshot.revision == 3
    assert saved.title == "用户标题"
    assert saved.content == "平台新正文"
    assert saved.tags == ["用户标签"]
    assert saved.stats.likes == "99"
    assert saved.fetch.last_status == "success"
    assert saved.fetch.last_error_reason == ""


def test_record_fetch_failure_keeps_existing_collection(tmp_path: Path):
    store = JSONStore(tmp_path / "collections.json")
    store.import_collections([collection("note-1")])

    saved, snapshot = store.record_fetch_failure("note-1", "PLATFORM_BLOCKED", "rednote限制了本次访问")

    assert snapshot.revision == 2
    assert saved.title == "测试笔记 note-1"
    assert saved.fetch.last_status == "failed"
    assert saved.fetch.last_error_reason == "PLATFORM_BLOCKED"
    assert saved.fetch.last_error_message == "rednote限制了本次访问"


def test_json_store_rejects_stale_base_revision_for_writes(tmp_path: Path):
    store = JSONStore(tmp_path / "collections.json")
    _, _, snapshot = store.import_collections([collection("note-1")])
    stale_revision = snapshot.revision
    store.patch("note-1", CollectionPatch(title="当前标题"), base_revision=stale_revision)
    current_revision = store.snapshot().revision

    write_attempts = [
        lambda: store.assert_base_revision(stale_revision),
        lambda: store.add_front(collection("note-2"), base_revision=stale_revision),
        lambda: store.import_collections([collection("note-2")], base_revision=stale_revision),
        lambda: store.patch("note-1", CollectionPatch(title="旧页面标题"), base_revision=stale_revision),
        lambda: store.delete("note-1", base_revision=stale_revision),
        lambda: store.clear(base_revision=stale_revision),
        lambda: store.refresh("note-1", collection("note-1"), base_revision=stale_revision),
        lambda: store.record_fetch_failure("note-1", "NETWORK_FAILED", "网络异常", base_revision=stale_revision),
    ]

    for attempt in write_attempts:
        with pytest.raises(RevisionConflict) as exc_info:
            attempt()
        assert exc_info.value.current_revision == current_revision

    snapshot = store.snapshot()
    assert snapshot.revision == current_revision
    assert [item.id for item in snapshot.collections] == ["note-1"]
    assert snapshot.collections[0].title == "当前标题"


def collection(collection_id: str) -> Collection:
    return Collection(
        id=collection_id,
        platform="xiaohongshu",
        sourceId=collection_id,
        sourceUrl=f"https://www.xiaohongshu.com/explore/{collection_id}",
        type="normal",
        title=f"测试笔记 {collection_id}",
        content="正文",
        author=Author(name="作者"),
        images=[Image(url=f"https://sns-webpic-qc.xhscdn.com/{collection_id}.jpg")],
        tags=["测试"],
        stats=Stats(likes="1"),
    )
