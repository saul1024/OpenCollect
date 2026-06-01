from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.app.media.proxy import MediaProxy, MediaProxyError
from backend.app.store.json_store import CollectionConflict, CollectionNotFound, JSONStore, RevisionConflict, StoreError
from backend.app.store.models import Collection, CollectionPatch, DataFile, model_to_api
from backend.app.sync import SyncManager
from backend.app.xhs.parser import ParserError, XHSParser


class CollectRequest(BaseModel):
    input: str = ""
    base_revision: int | None = Field(None, alias="baseRevision")


class ImportLocalRequest(BaseModel):
    collections: list[Collection] = []
    base_revision: int | None = Field(None, alias="baseRevision")


class RevisionRequest(BaseModel):
    base_revision: int | None = Field(None, alias="baseRevision")


class SyncPushRequest(BaseModel):
    force: bool = False


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
            imported, updated, snapshot = store.import_collections(request.collections, base_revision=request.base_revision)
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
            collection, snapshot = store.patch(collection_id, patch, base_revision=patch.base_revision)
        except StoreError as exc:
            return store_error_response(exc)
        return {
            "collection": model_to_api(collection),
            "revision": snapshot.revision,
            "updatedAt": snapshot.updated_at,
        }

    @router.delete("/collections/{collection_id}")
    async def delete_collection(collection_id: str, baseRevision: int | None = None):
        try:
            deleted, snapshot = store.delete(collection_id, base_revision=baseRevision)
        except StoreError as exc:
            return store_error_response(exc)
        return {
            "collection": model_to_api(deleted),
            **snapshot_payload(snapshot),
        }

    @router.delete("/collections")
    async def clear_collections(baseRevision: int | None = None):
        try:
            previous, snapshot = store.clear(base_revision=baseRevision)
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
            return error_response(400, "EMPTY_INPUT", "请粘贴rednote分享文本或链接")
        try:
            store.assert_base_revision(request.base_revision)
        except StoreError as exc:
            return store_error_response(exc)
        try:
            result = await parser.collect(input_text)
            save_result = store.add_front(result["note"], base_revision=request.base_revision)
        except ParserError as exc:
            return parser_error_response(exc)
        except StoreError as exc:
            return store_error_response(exc)
        result["note"] = model_to_api(save_result.collection)
        result["duplicated"] = save_result.duplicated
        result["existingId"] = save_result.collection.id if save_result.duplicated else ""
        result["revision"] = save_result.snapshot.revision
        result["updatedAt"] = save_result.snapshot.updated_at
        return result

    @router.post("/collections/{collection_id}/refresh")
    async def refresh_collection(collection_id: str, request: RevisionRequest = RevisionRequest()):
        try:
            store.assert_base_revision(request.base_revision)
        except StoreError as exc:
            return store_error_response(exc)
        existing = store.get(collection_id)
        if existing is None:
            return error_response(404, "NOT_FOUND", "收藏不存在")
        source_url = existing.source_url or existing.canonical_url
        if not source_url:
            return error_response(422, "REFRESH_FAILED", "收藏缺少原文链接", reason="INVALID_LINK")
        try:
            result = await parser.collect(source_url)
            refreshed, snapshot = store.refresh(collection_id, result["note"], base_revision=request.base_revision)
        except ParserError as exc:
            try:
                failed, snapshot = store.record_fetch_failure(collection_id, exc.reason, exc.message, base_revision=request.base_revision)
            except StoreError as store_exc:
                return store_error_response(store_exc)
            return {
                "refreshed": False,
                "collection": model_to_api(failed),
                "reason": exc.reason,
                "message": exc.message,
                "revision": snapshot.revision,
                "updatedAt": snapshot.updated_at,
            }
        except StoreError as exc:
            return store_error_response(exc)
        return {
            "refreshed": True,
            "collection": model_to_api(refreshed),
            "reason": "",
            "message": "",
            "revision": snapshot.revision,
            "updatedAt": snapshot.updated_at,
        }

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
        return await sync_push(SyncPushRequest())

    @router.post("/sync/push")
    async def sync_push(request: SyncPushRequest = SyncPushRequest()):
        if sync_manager is None or not sync_manager.enabled:
            return {"provider": "none", "enabled": False, "status": "disabled"}
        snapshot = store.snapshot()
        sync_manager.push_now(store.path, snapshot, force=request.force)
        if sync_manager.status().status in {"synced_auto_merged", "synced_overwrote_remote", "synced"}:
            store.reload_from_disk()
        return {"sync": sync_manager.status_payload()}

    @router.post("/sync/pull")
    async def sync_pull():
        if sync_manager is None or not sync_manager.enabled:
            return {"provider": "none", "enabled": False, "status": "disabled"}
        sync_manager.pull_now(store.path)
        if sync_manager.status().status == "synced":
            store.reload_from_disk()
        return {
            "sync": sync_manager.status_payload(),
            **snapshot_payload(store.snapshot()),
        }

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


def error_response(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message, **extra})


def parser_error_response(exc: ParserError) -> JSONResponse:
    return error_response(422, "PARSE_FAILED", exc.message, reason=exc.reason)


def store_error_response(exc: StoreError) -> JSONResponse:
    if isinstance(exc, CollectionNotFound):
        return error_response(404, "NOT_FOUND", "收藏不存在")
    if isinstance(exc, CollectionConflict):
        return error_response(409, "CONFLICT", "刷新结果与已有收藏重复")
    if isinstance(exc, RevisionConflict):
        return error_response(409, "CONFLICT", "数据已在其他页面更新", currentRevision=exc.current_revision)
    return error_response(500, "STORE_ERROR", str(exc))
