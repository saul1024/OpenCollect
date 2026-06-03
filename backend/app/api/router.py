from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.app.auth import AuthManager, session_payload
from backend.app.media.proxy import MediaProxy, MediaProxyError
from backend.app.rate_limit import RateLimitExceeded, RateLimiter
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


class ImportJsonRequest(DataFile):
    base_revision: int | None = Field(None, alias="baseRevision")


class RevisionRequest(BaseModel):
    base_revision: int | None = Field(None, alias="baseRevision")


class SyncPushRequest(BaseModel):
    force: bool = False


class LoginRequest(BaseModel):
    password: str = ""


def create_api_router(
    store: JSONStore,
    parser: XHSParser,
    media_proxy: MediaProxy,
    sync_manager: SyncManager | None = None,
    auth_manager: AuthManager | None = None,
    rate_limiter: RateLimiter | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/auth/login")
    async def auth_login(login: LoginRequest, request: Request):
        if auth_manager is None or not auth_manager.enabled:
            return {"authenticated": True, "authEnabled": False, "user": "owner"}
        client_key = rate_limiter.client_key(request) if rate_limiter is not None else ""
        if rate_limiter is not None:
            try:
                rate_limiter.check("auth_login", client_key)
                rate_limiter.check_login_allowed(client_key)
            except RateLimitExceeded as exc:
                return rate_limit_response(exc.retry_after)
        if not auth_manager.verify_password(login.password):
            if rate_limiter is not None:
                try:
                    rate_limiter.record_login_failure(client_key)
                except RateLimitExceeded as exc:
                    return rate_limit_response(exc.retry_after)
            return error_response(401, "AUTH_FAILED", "口令错误")
        if rate_limiter is not None:
            rate_limiter.record_login_success(client_key)
        token = auth_manager.create_session_token()
        csrf_token = auth_manager.create_csrf_token(token)
        response = JSONResponse(content={"authenticated": True, "authEnabled": True, "user": "owner"})
        response.set_cookie(
            auth_manager.cookie_name,
            token,
            max_age=auth_manager.auth.session_ttl_seconds,
            httponly=True,
            secure=auth_manager.cookie_secure,
            samesite="lax",
            path="/",
        )
        response.set_cookie(
            auth_manager.csrf_cookie_name,
            csrf_token,
            max_age=auth_manager.auth.session_ttl_seconds,
            httponly=False,
            secure=auth_manager.cookie_secure,
            samesite="lax",
            path="/",
        )
        return response

    @router.post("/auth/logout")
    async def auth_logout():
        response = JSONResponse(content={"authenticated": False, "authEnabled": bool(auth_manager and auth_manager.enabled), "user": ""})
        if auth_manager is not None:
            response.delete_cookie(auth_manager.cookie_name, path="/", secure=auth_manager.cookie_secure, samesite="lax")
            response.delete_cookie(auth_manager.csrf_cookie_name, path="/", secure=auth_manager.cookie_secure, samesite="lax")
        return response

    @router.get("/auth/session")
    async def auth_session(request: Request):
        if auth_manager is None:
            return {"authenticated": True, "authEnabled": False, "user": "owner"}
        return session_payload(auth_manager, request.cookies.get(auth_manager.cookie_name, ""))

    @router.get("/health")
    async def health():
        return health_payload(store, auth_manager, sync_manager)

    @router.get("/collections")
    async def list_collections():
        snapshot = store.snapshot()
        return snapshot_payload(snapshot)

    @router.get("/collections/export")
    async def export_collections():
        return data_file_payload(store.snapshot())

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

    @router.post("/collections/import-json")
    async def import_json_collections(request: ImportJsonRequest):
        if request.schema_version != 1:
            return error_response(422, "IMPORT_FAILED", "不支持的导入文件", reason="UNSUPPORTED_SCHEMA")
        try:
            imported, updated, snapshot = store.import_collections(request.collections, base_revision=request.base_revision)
        except StoreError as exc:
            return store_error_response(exc)
        return {
            **data_file_payload(snapshot),
            "imported": imported,
            "updated": updated,
            "skipped": 0,
        }

    @router.get("/collections/{collection_id}")
    async def get_collection(collection_id: str):
        collection = store.get(collection_id)
        if collection is None:
            return error_response(404, "NOT_FOUND", "收藏不存在")
        return {"collection": model_to_api(collection)}

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
    async def image():
        return error_response(403, "FORBIDDEN", "媒体代理不接受任意 URL")

    @router.get("/media")
    async def media():
        return error_response(403, "FORBIDDEN", "媒体代理不接受任意 URL")

    @router.get("/media/collections/{collection_id}/items/{media_index}")
    async def collection_media_item(request: Request, collection_id: str, media_index: int, type: str = "image"):
        collection = store.get(collection_id)
        if collection is None:
            return error_response(404, "NOT_FOUND", "收藏不存在")
        try:
            resource = collection_media_url(collection, media_index, type)
            if resource.kind == "video":
                return await media_proxy.video(request, resource.url)
            return await media_proxy.image(resource.url)
        except MediaProxyError as exc:
            return error_response(422, "MEDIA_FAILED", str(exc))

    @router.get("/media/collections/{collection_id}/avatar")
    async def collection_author_avatar(collection_id: str):
        collection = store.get(collection_id)
        if collection is None:
            return error_response(404, "NOT_FOUND", "收藏不存在")
        try:
            return await media_proxy.image(collection_author_avatar_url(collection))
        except MediaProxyError as exc:
            return error_response(422, "MEDIA_FAILED", str(exc))

    @router.get("/media/collections/{collection_id}/poster")
    async def collection_video_poster(collection_id: str):
        collection = store.get(collection_id)
        if collection is None:
            return error_response(404, "NOT_FOUND", "收藏不存在")
        try:
            return await media_proxy.image(collection_video_poster_url(collection))
        except MediaProxyError as exc:
            return error_response(422, "MEDIA_FAILED", str(exc))

    return router


def snapshot_payload(snapshot: DataFile) -> dict:
    return {
        "collections": [model_to_api(collection) for collection in snapshot.collections],
        "revision": snapshot.revision,
        "updatedAt": snapshot.updated_at,
    }


def data_file_payload(snapshot: DataFile) -> dict:
    return model_to_api(snapshot)


class MediaResource(BaseModel):
    kind: str
    url: str


def collection_media_url(collection: Collection, media_index: int, media_type: str) -> MediaResource:
    kind = (media_type or "image").strip().lower()
    if media_index < 0:
        raise MediaProxyError("媒体不存在")
    if kind == "image":
        if media_index >= len(collection.images):
            raise MediaProxyError("媒体不存在")
        url = collection.images[media_index].url
        if not url:
            raise MediaProxyError("媒体不存在")
        return MediaResource(kind="image", url=url)
    if kind == "video":
        urls = video_urls(collection)
        if media_index >= len(urls):
            raise MediaProxyError("媒体不存在")
        return MediaResource(kind="video", url=urls[media_index])
    raise MediaProxyError("不支持的媒体类型")


def collection_author_avatar_url(collection: Collection) -> str:
    url = collection.author.avatar
    if not url:
        raise MediaProxyError("媒体不存在")
    return url


def collection_video_poster_url(collection: Collection) -> str:
    if collection.video and collection.video.poster:
        return collection.video.poster
    if collection.images:
        return collection.images[0].url
    raise MediaProxyError("媒体不存在")


def video_urls(collection: Collection) -> list[str]:
    if collection.video is None:
        return []
    urls: list[str] = []
    if collection.video.url:
        urls.append(collection.video.url)
    for stream in collection.video.streams:
        if stream.url:
            urls.append(stream.url)
        urls.extend(url for url in stream.backup_urls if url)
    return unique_values(urls)


def unique_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def health_payload(store: JSONStore, auth_manager: AuthManager | None, sync_manager: SyncManager | None) -> dict:
    data_file_readable = store.path.is_file() and os.access(store.path, os.R_OK)
    data_file_writable = os.access(store.path, os.W_OK) if store.path.exists() else os.access(store.path.parent, os.W_OK)
    if sync_manager is None:
        sync_provider = "none"
        sync_enabled = False
    else:
        sync_status = sync_manager.status_payload()
        sync_provider = sync_status.get("provider", "none")
        sync_enabled = bool(sync_status.get("enabled", False))
    return {
        "status": "ok",
        "authEnabled": bool(auth_manager and auth_manager.enabled),
        "sync": {
            "provider": sync_provider,
            "enabled": sync_enabled,
        },
        "dataFile": {
            "readable": data_file_readable,
            "writable": data_file_writable,
        },
    }


def error_response(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message, **extra})


def rate_limit_response(retry_after: int) -> JSONResponse:
    response = error_response(429, "RATE_LIMITED", "请求过于频繁，请稍后重试", retryAfter=retry_after)
    response.headers["Retry-After"] = str(retry_after)
    return response


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
