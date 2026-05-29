from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.app.media.proxy import MediaProxy, MediaProxyError
from backend.app.store.json_store import CollectionNotFound, JSONStore, StoreError
from backend.app.store.models import Collection, CollectionPatch, DataFile, model_to_api
from backend.app.sync import SyncManager
from backend.app.xhs.parser import ParserError, XHSParser


class CollectRequest(BaseModel):
    input: str = ""


class ImportLocalRequest(BaseModel):
    collections: list[Collection] = []


def create_api_router(
    store: JSONStore,
    parser: XHSParser,
    media_proxy: MediaProxy,
    sync_manager: SyncManager | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/collections")
    async def list_collections():
        snapshot = store.snapshot()
        return snapshot_payload(snapshot)

    @router.get("/collections/{collection_id}")
    async def get_collection(collection_id: str):
        collection = store.get(collection_id)
        if collection is None:
            return error_response(404, "NOT_FOUND", "收藏不存在")
        return {"collection": model_to_api(collection)}

    @router.post("/collections/import-local")
    async def import_local_collections(request: ImportLocalRequest):
        try:
            imported, updated, snapshot = store.import_collections(request.collections)
        except StoreError as exc:
            return store_error_response(exc)
        return {
            **snapshot_payload(snapshot),
            "imported": imported,
            "updated": updated,
        }

    @router.patch("/collections/{collection_id}")
    async def patch_collection(collection_id: str, patch: CollectionPatch):
        try:
            collection, snapshot = store.patch(collection_id, patch)
        except StoreError as exc:
            return store_error_response(exc)
        return {
            "collection": model_to_api(collection),
            "revision": snapshot.revision,
            "updatedAt": snapshot.updated_at,
        }

    @router.delete("/collections/{collection_id}")
    async def delete_collection(collection_id: str):
        try:
            deleted, snapshot = store.delete(collection_id)
        except StoreError as exc:
            return store_error_response(exc)
        return {
            "collection": model_to_api(deleted),
            **snapshot_payload(snapshot),
        }

    @router.delete("/collections")
    async def clear_collections():
        try:
            previous, snapshot = store.clear()
        except StoreError as exc:
            return store_error_response(exc)
        return {
            **snapshot_payload(snapshot),
            "previous": [model_to_api(collection) for collection in previous],
        }

    @router.post("/collect")
    async def collect(request: CollectRequest):
        input_text = request.input.strip()
        if not input_text:
            return error_response(400, "EMPTY_INPUT", "请粘贴小红书分享文本或链接")
        try:
            result = await parser.collect(input_text)
            note, _ = store.upsert_front(result["note"])
        except ParserError as exc:
            return error_response(422, "PARSE_FAILED", str(exc))
        except StoreError as exc:
            return store_error_response(exc)
        result["note"] = model_to_api(note)
        return result

    @router.get("/sample")
    async def sample():
        try:
            return await parser.sample()
        except ParserError as exc:
            return error_response(422, "SAMPLE_FAILED", str(exc))

    @router.get("/sample-video")
    async def sample_video():
        try:
            return await parser.sample_video()
        except ParserError as exc:
            return error_response(422, "SAMPLE_VIDEO_FAILED", str(exc))

    @router.get("/sync/status")
    async def sync_status():
        if sync_manager is None:
            return {"provider": "none", "enabled": False, "status": "disabled"}
        return sync_manager.status_payload()

    @router.post("/sync/retry")
    async def sync_retry():
        return await sync_push()

    @router.post("/sync/push")
    async def sync_push():
        if sync_manager is None or not sync_manager.enabled:
            return {"provider": "none", "enabled": False, "status": "disabled"}
        snapshot = store.snapshot()
        sync_manager.push_now(store.path, snapshot)
        return {"sync": sync_manager.status_payload()}

    @router.get("/image")
    async def image(url: str = ""):
        try:
            return await media_proxy.image(url)
        except MediaProxyError as exc:
            return error_response(422, "MEDIA_FAILED", str(exc))

    @router.get("/media")
    async def media(request: Request, url: str = ""):
        try:
            return await media_proxy.video(request, url)
        except MediaProxyError as exc:
            return error_response(422, "MEDIA_FAILED", str(exc))

    return router


def snapshot_payload(snapshot: DataFile) -> dict:
    return {
        "collections": [model_to_api(collection) for collection in snapshot.collections],
        "revision": snapshot.revision,
        "updatedAt": snapshot.updated_at,
    }


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


def store_error_response(exc: StoreError) -> JSONResponse:
    if isinstance(exc, CollectionNotFound):
        return error_response(404, "NOT_FOUND", "收藏不存在")
    return error_response(500, "STORE_ERROR", str(exc))
