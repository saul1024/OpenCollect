from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from backend.app.auth import AuthError, AuthManager
from backend.app.api.router import create_api_router, error_response, rate_limit_response
from backend.app.core.config import Settings, load_settings, validate_settings
from backend.app.media.proxy import MediaProxy
from backend.app.rate_limit import RateLimitExceeded, RateLimiter
from backend.app.store.json_store import JSONStore
from backend.app.sync import create_sync_manager
from backend.app.xhs.parser import XHSParser


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    validate_settings(settings)
    sync_manager = create_sync_manager(settings)
    sync_manager.bootstrap_local_file(settings.collections_path)
    store = JSONStore(settings.collections_path, on_write=sync_manager.after_local_write)
    sync_manager.initialize_local_snapshot(store.snapshot())
    parser = XHSParser()
    media_proxy = MediaProxy()
    auth_manager = AuthManager(settings)
    rate_limiter = RateLimiter()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.store = store
        app.state.parser = parser
        app.state.sync_manager = sync_manager
        app.state.auth_manager = auth_manager
        app.state.rate_limiter = rate_limiter
        yield
        await parser.close()

    app = FastAPI(title="OpenCollect", lifespan=lifespan)
    app.state.rate_limiter = rate_limiter
    app.middleware("http")(security_middleware(auth_manager, rate_limiter))
    app.include_router(create_api_router(store, parser, media_proxy, sync_manager, auth_manager, rate_limiter))

    @app.get("/")
    async def index():
        return static_file(settings.public_dir, "index.html")

    @app.get("/login")
    async def login():
        return static_file(settings.public_dir, "login.html")

    @app.get("/{asset_path:path}")
    async def static(asset_path: str, request: Request):
        if request.url.path.startswith("/api/"):
            return error_response(404, "NOT_FOUND", "接口不存在")
        return static_file(settings.public_dir, asset_path)

    return app


def security_middleware(auth_manager: AuthManager, rate_limiter: RateLimiter):
    async def middleware(request: Request, call_next):
        path = request.url.path
        if is_light_public_request(request):
            try:
                rate_limiter.check("public_light", rate_limiter.client_key(request))
            except RateLimitExceeded as exc:
                return rate_limit_response(exc.retry_after)

        if path == "/api/auth/logout":
            if auth_manager.enabled:
                try:
                    session = auth_manager.read_session(request.cookies)
                    request.state.user = session.user
                except AuthError:
                    pass
                else:
                    if is_write_request(request):
                        try:
                            validate_csrf(auth_manager, request)
                        except AuthError:
                            return error_response(403, "FORBIDDEN", "请求来源校验失败")
            return await call_next(request)

        if not auth_manager.enabled or is_public_request(request):
            return await call_next(request)

        try:
            session = auth_manager.read_session(request.cookies)
            request.state.user = session.user
        except AuthError:
            if request.url.path.startswith("/api/"):
                return error_response(401, "UNAUTHORIZED", "请先登录")
            target = request.url.path or "/"
            if request.url.query:
                target = f"{target}?{request.url.query}"
            next_path = quote(target, safe="/")
            return RedirectResponse(url=f"/login?next={next_path}", status_code=302)

        if rule_name := protected_rate_limit_rule(request):
            try:
                rate_limiter.check(rule_name, rate_limiter.session_key(request))
            except RateLimitExceeded as exc:
                return rate_limit_response(exc.retry_after)

        if is_write_request(request):
            try:
                validate_csrf(auth_manager, request)
            except AuthError:
                return error_response(403, "FORBIDDEN", "请求来源校验失败")
        return await call_next(request)

    return middleware


def validate_csrf(auth_manager: AuthManager, request: Request) -> None:
    session_token = request.cookies.get(auth_manager.cookie_name, "")
    csrf_cookie = request.cookies.get(auth_manager.csrf_cookie_name, "")
    csrf_header = request.headers.get("x-csrf-token", "")
    if not csrf_cookie or csrf_cookie != csrf_header:
        raise AuthError("csrf token mismatch")
    auth_manager.verify_csrf_token(session_token, csrf_header)


def is_public_request(request: Request) -> bool:
    path = request.url.path
    if path in {"/login", "/api/auth/login", "/api/auth/logout", "/api/auth/session", "/api/health"}:
        return True
    return False


def is_light_public_request(request: Request) -> bool:
    return request.url.path in {"/login", "/api/auth/session", "/api/health"}


def is_write_request(request: Request) -> bool:
    return request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}


def protected_rate_limit_rule(request: Request) -> str:
    path = request.url.path
    if path == "/api/collect":
        return "collect"
    if path == "/api/collections/import-json":
        return "import_json"
    if path.startswith("/api/media") or path == "/api/image":
        return "media"
    return ""


def static_file(public_dir: Path, asset_path: str):
    clean = Path(asset_path or "index.html")
    if clean.is_absolute() or ".." in clean.parts or any(part.startswith(".") for part in clean.parts):
        return JSONResponse(status_code=404, content={"error": "NOT_FOUND", "message": "页面不存在"})

    public_abs = public_dir.resolve()
    file_path = (public_abs / clean).resolve()
    if public_abs != file_path and public_abs not in file_path.parents:
        return JSONResponse(status_code=404, content={"error": "NOT_FOUND", "message": "页面不存在"})
    if not file_path.is_file():
        return JSONResponse(status_code=404, content={"error": "NOT_FOUND", "message": "页面不存在"})
    headers = {}
    if file_path.suffix in {".html", ".css", ".js"}:
        headers["cache-control"] = "no-cache"
    return FileResponse(file_path, headers=headers)


app = create_app()
