from __future__ import annotations

from pathlib import Path

from backend.app.store.json_store import JSONStore
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
