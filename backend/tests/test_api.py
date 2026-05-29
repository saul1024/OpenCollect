from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app


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
