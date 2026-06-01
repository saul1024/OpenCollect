from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.router import create_api_router
from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.store.json_store import JSONStore
from backend.app.store.models import Author, Collection, Image, Stats
from backend.app.xhs.parser import ParserError


def test_collections_api_matches_frontend_contract(tmp_path: Path):
    public_dir = tmp_path / "public"
    public_dir.mkdir()
    (public_dir / "index.html").write_text("<!doctype html><title>OpenCollect</title>", encoding="utf-8")

    settings = Settings(port="0", data_dir=tmp_path / "data", public_dir=public_dir)
    with TestClient(create_app(settings)) as client:
        response = client.get("/")
        assert response.status_code == 200

        response = client.get("/api/collections")
        assert response.status_code == 200
        assert response.json() == {"collections": [], "revision": 0, "updatedAt": ""}

        response = client.get("/api/sync/status")
        assert response.status_code == 200
        assert response.json()["status"] == "disabled"

        response = client.post("/api/sync/push")
        assert response.status_code == 200
        assert response.json()["status"] == "disabled"

        response = client.post("/api/sync/retry")
        assert response.status_code == 200
        assert response.json()["status"] == "disabled"

        fixture = {
            "id": "api-note-1",
            "platform": "xiaohongshu",
            "sourceId": "api-note-1",
            "sourceUrl": "https://www.xiaohongshu.com/explore/api-note-1",
            "type": "normal",
            "title": "迁移笔记",
            "content": "迁移正文",
            "author": {"name": "作者"},
            "images": [{"url": "https://sns-webpic-qc.xhscdn.com/api-note-1.jpg"}],
            "tags": ["迁移"],
            "stats": {"likes": "1"},
        }

        response = client.post("/api/collections/import-local", json={"collections": [fixture]})
        assert response.status_code == 200
        payload = response.json()
        assert payload["imported"] == 1
        assert payload["updated"] == 0
        assert payload["revision"] == 1
        assert payload["collections"][0]["sourceId"] == "api-note-1"

        response = client.patch(
            "/api/collections/api-note-1",
            json={"title": "编辑后", "content": "编辑正文", "tags": ["后端", "#后端"]},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["collection"]["title"] == "编辑后"
        assert payload["collection"]["tags"] == ["后端"]

        response = client.delete("/api/collections/api-note-1")
        assert response.status_code == 200
        assert response.json()["collections"] == []

        client.post("/api/collections/import-local", json={"collections": [fixture]})
        response = client.delete("/api/collections")
        assert response.status_code == 200
        payload = response.json()
        assert payload["collections"] == []
        assert len(payload["previous"]) == 1


def test_collect_duplicate_returns_existing_without_overwrite(tmp_path: Path):
    parser = QueueParser(
        parsed_result(api_collection("note-1", title="平台标题")),
        parsed_result(api_collection("note-1", title="平台新标题")),
    )
    with TestClient(api_app(tmp_path, parser)) as client:
        response = client.post("/api/collect", json={"input": "https://xhslink.com/a"})
        assert response.status_code == 200
        assert response.json()["duplicated"] is False

        response = client.patch("/api/collections/note-1", json={"title": "用户标题", "tags": ["用户"]})
        assert response.status_code == 200

        response = client.post("/api/collect", json={"input": "https://www.xiaohongshu.com/explore/note-1"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["duplicated"] is True
        assert payload["existingId"] == "note-1"
        assert payload["note"]["title"] == "用户标题"
        assert payload["revision"] == 2

        response = client.get("/api/collections")
        payload = response.json()
        assert payload["revision"] == 2
        assert len(payload["collections"]) == 1
        assert payload["collections"][0]["title"] == "用户标题"


def test_collect_parse_error_exposes_reason(tmp_path: Path):
    parser = QueueParser(ParserError("小红书限制了本次访问，请稍后重试", "PLATFORM_BLOCKED"))
    with TestClient(api_app(tmp_path, parser)) as client:
        response = client.post("/api/collect", json={"input": "https://www.xiaohongshu.com/explore/note-1"})

    assert response.status_code == 422
    assert response.json() == {
        "error": "PARSE_FAILED",
        "message": "小红书限制了本次访问，请稍后重试",
        "reason": "PLATFORM_BLOCKED",
    }


def test_refresh_success_preserves_user_fields_and_updates_platform_fields(tmp_path: Path):
    parser = QueueParser(parsed_result(api_collection("note-1", title="平台刷新标题", content="平台刷新正文", likes="88")))
    with TestClient(api_app(tmp_path, parser)) as client:
        client.post("/api/collections/import-local", json={"collections": [api_collection("note-1", title="原标题").model_dump(by_alias=True)]})
        client.patch("/api/collections/note-1", json={"title": "用户标题", "tags": ["用户标签"]})

        response = client.post("/api/collections/note-1/refresh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["refreshed"] is True
    assert payload["collection"]["title"] == "用户标题"
    assert payload["collection"]["content"] == "平台刷新正文"
    assert payload["collection"]["tags"] == ["用户标签"]
    assert payload["collection"]["stats"]["likes"] == "88"
    assert payload["collection"]["fetch"]["lastStatus"] == "success"


def test_refresh_failure_keeps_collection_and_records_reason(tmp_path: Path):
    parser = QueueParser(ParserError("网络异常，请重试", "NETWORK_FAILED"))
    with TestClient(api_app(tmp_path, parser)) as client:
        client.post("/api/collections/import-local", json={"collections": [api_collection("note-1", title="旧标题").model_dump(by_alias=True)]})

        response = client.post("/api/collections/note-1/refresh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["refreshed"] is False
    assert payload["reason"] == "NETWORK_FAILED"
    assert payload["collection"]["title"] == "旧标题"
    assert payload["collection"]["fetch"]["lastStatus"] == "failed"
    assert payload["collection"]["fetch"]["lastErrorReason"] == "NETWORK_FAILED"


def test_refresh_conflict_returns_409(tmp_path: Path):
    parser = QueueParser(parsed_result(api_collection("note-2", title="另一条")))
    with TestClient(api_app(tmp_path, parser)) as client:
        client.post(
            "/api/collections/import-local",
            json={
                "collections": [
                    api_collection("note-1").model_dump(by_alias=True),
                    api_collection("note-2").model_dump(by_alias=True),
                ]
            },
        )

        response = client.post("/api/collections/note-1/refresh")

    assert response.status_code == 409
    assert response.json()["error"] == "CONFLICT"


def api_app(tmp_path: Path, parser) -> FastAPI:
    app = FastAPI()
    store = JSONStore(tmp_path / "collections.json")
    app.include_router(create_api_router(store, parser, DummyMediaProxy()))
    return app


class DummyMediaProxy:
    pass


class QueueParser:
    def __init__(self, *items):
        self.items = list(items)

    async def collect(self, input_text: str):
        if not self.items:
            raise AssertionError(f"unexpected parser call: {input_text}")
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def parsed_result(collection: Collection) -> dict:
    return {
        "source": {
            "input": collection.source_url,
            "extractedUrl": collection.source_url,
            "finalUrl": collection.source_url,
        },
        "note": collection,
    }


def api_collection(collection_id: str, title: str | None = None, content: str = "正文", likes: str = "1") -> Collection:
    return Collection(
        id=collection_id,
        platform="xiaohongshu",
        sourceId=collection_id,
        sourceUrl=f"https://www.xiaohongshu.com/explore/{collection_id}?xsec_token=test",
        type="normal",
        title=title or f"测试笔记 {collection_id}",
        content=content,
        author=Author(name="作者"),
        images=[Image(url=f"https://sns-webpic-qc.xhscdn.com/{collection_id}.jpg")],
        tags=["平台标签"],
        stats=Stats(likes=likes),
    )
