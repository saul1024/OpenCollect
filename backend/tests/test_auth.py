from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import AuthManager, hash_password
from backend.app.core.config import AuthSettings, Settings, SettingsError
from backend.app.main import create_app


AUTH_SECRET = "test-session-secret-minimum-32-chars"


def test_auth_protects_app_and_api_when_enabled(tmp_path: Path):
    settings = auth_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"].startswith("/login")

        response = client.get("/index.html", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"].startswith("/login")

        protected_requests = [
            lambda: client.get("/api/collections"),
            lambda: client.get("/api/collections/export"),
            lambda: client.post("/api/collect", json={"input": "https://xhslink.com/a"}),
            lambda: client.post("/api/collections/import-local", json={"collections": []}),
            lambda: client.post("/api/collections/import-json", json={"schemaVersion": 1, "collections": []}),
            lambda: client.patch("/api/collections/note-1", json={"title": "x"}),
            lambda: client.delete("/api/collections/note-1"),
            lambda: client.delete("/api/collections"),
            lambda: client.post("/api/collections/note-1/refresh", json={}),
            lambda: client.post("/api/sync/push"),
            lambda: client.post("/api/sync/pull"),
            lambda: client.get("/api/image?url=https%3A%2F%2Fsns-img-qc.xhscdn.com%2Fa.jpg"),
            lambda: client.get("/api/media?url=https%3A%2F%2Fsns-video-bd.xhscdn.com%2Fa.mp4"),
        ]
        for protected_request in protected_requests:
            response = protected_request()
            assert response.status_code == 401
            assert response.json() == {"error": "UNAUTHORIZED", "message": "请先登录"}

        response = client.post("/api/auth/login", json={"password": "wrong"})
        assert response.status_code == 401
        assert settings.auth.cookie_name not in response.cookies

        response = client.post("/api/auth/login", json={"password": "secret"})
        assert response.status_code == 200
        assert response.json()["authenticated"] is True
        set_cookie = response.headers["set-cookie"]
        assert settings.auth.cookie_name in set_cookie
        assert settings.auth.csrf_cookie_name in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie
        csrf_token = client.cookies.get(settings.auth.csrf_cookie_name)
        assert csrf_token

        response = client.get("/api/auth/session")
        assert response.status_code == 200
        assert response.json() == {"authenticated": True, "authEnabled": True, "user": "owner"}

        response = client.get("/api/collections")
        assert response.status_code == 200
        assert response.json()["collections"] == []

        response = client.get("/")
        assert response.status_code == 200
        assert "OpenCollect" in response.text

        response = client.post("/api/auth/logout")
        assert response.status_code == 403

        response = client.post("/api/auth/logout", headers=csrf_headers(client, settings))
        assert response.status_code == 200
        assert "Max-Age=0" in response.headers["set-cookie"]

        response = client.get("/api/collections")
        assert response.status_code == 401


def test_tampered_and_expired_sessions_are_rejected(tmp_path: Path):
    settings = auth_settings(tmp_path)
    manager = AuthManager(settings)
    with TestClient(create_app(settings)) as client:
        token = manager.create_session_token()
        client.cookies.set(settings.auth.cookie_name, f"{token}tampered")
        response = client.get("/api/collections")
        assert response.status_code == 401

        expired = manager.create_session_token(now=1000, ttl_seconds=-1)
        client.cookies.set(settings.auth.cookie_name, expired)
        response = client.get("/api/collections")
        assert response.status_code == 401


def test_auth_disabled_allows_development_access(tmp_path: Path):
    settings = Settings(port="0", data_dir=tmp_path / "data", public_dir=public_dir(tmp_path), auth=AuthSettings(enabled=False))
    with TestClient(create_app(settings)) as client:
        response = client.get("/")
        assert response.status_code == 200
        response = client.get("/api/collections")
        assert response.status_code == 200
        response = client.get("/api/auth/session")
        assert response.json() == {"authenticated": True, "authEnabled": False, "user": "owner"}


def test_authenticated_write_apis_require_csrf(tmp_path: Path):
    settings = auth_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        login(client)

        response = client.post("/api/collections/import-local", json={"collections": []})
        assert response.status_code == 403
        assert response.json()["error"] == "FORBIDDEN"

        response = client.post("/api/collections/import-local", json={"collections": []}, headers={"X-CSRF-Token": "bad"})
        assert response.status_code == 403
        assert response.json()["error"] == "FORBIDDEN"

        response = client.post("/api/collections/import-local", json={"collections": []}, headers=csrf_headers(client, settings))
        assert response.status_code == 200

        response = client.get("/api/collections")
        assert response.status_code == 200


def test_login_failures_trigger_cooldown_before_password_check(tmp_path: Path):
    settings = auth_settings(tmp_path)
    app = create_app(settings)
    app.state.rate_limiter.login_failure_limit = 2
    app.state.rate_limiter.login_cooldown_seconds = 120

    with TestClient(app) as client:
        response = client.post("/api/auth/login", json={"password": "wrong"})
        assert response.status_code == 401

        response = client.post("/api/auth/login", json={"password": "wrong"})
        assert response.status_code == 429
        assert response.json()["error"] == "RATE_LIMITED"

        response = client.post("/api/auth/login", json={"password": "secret"})
        assert response.status_code == 429
        assert response.json()["error"] == "RATE_LIMITED"


def test_public_endpoints_have_light_rate_limit(tmp_path: Path):
    settings = auth_settings(tmp_path)
    app = create_app(settings)
    app.state.rate_limiter.set_rule("public_light", limit=1, window_seconds=60)

    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200

        response = client.get("/api/health")
        assert response.status_code == 429
        assert response.json()["error"] == "RATE_LIMITED"


def test_business_api_rate_limit_uses_authenticated_session(tmp_path: Path):
    settings = auth_settings(tmp_path)
    app = create_app(settings)
    app.state.rate_limiter.set_rule("import_json", limit=1, window_seconds=60)

    with TestClient(app) as client:
        login(client)
        payload = {"schemaVersion": 1, "revision": 0, "updatedAt": "", "collections": []}

        response = client.post("/api/collections/import-json", json=payload, headers=csrf_headers(client, settings))
        assert response.status_code == 200

        response = client.post("/api/collections/import-json", json=payload, headers=csrf_headers(client, settings))
        assert response.status_code == 429
        assert response.json()["error"] == "RATE_LIMITED"


def test_production_requires_auth_configuration(tmp_path: Path):
    with pytest.raises(SettingsError, match="AUTH_ENABLED"):
        create_app(
            Settings(
                port="0",
                data_dir=tmp_path / "data-a",
                public_dir=public_dir(tmp_path / "a"),
                app_env="production",
                auth=AuthSettings(enabled=False),
            )
        )

    with pytest.raises(SettingsError, match="AUTH_PASSWORD_HASH"):
        create_app(
            Settings(
                port="0",
                data_dir=tmp_path / "data-b",
                public_dir=public_dir(tmp_path / "b"),
                app_env="production",
                auth=AuthSettings(enabled=True, session_secret=AUTH_SECRET),
            )
        )

    with pytest.raises(SettingsError, match="AUTH_SESSION_SECRET"):
        create_app(
            Settings(
                port="0",
                data_dir=tmp_path / "data-c",
                public_dir=public_dir(tmp_path / "c"),
                app_env="production",
                auth=AuthSettings(enabled=True, password_hash=hash_password("secret"), session_secret="short"),
            )
        )


def test_production_login_cookie_is_secure(tmp_path: Path):
    settings = auth_settings(tmp_path, app_env="production")
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/auth/login", json={"password": "secret"})

    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie


def auth_settings(tmp_path: Path, app_env: str = "development") -> Settings:
    return Settings(
        port="0",
        data_dir=tmp_path / "data",
        public_dir=public_dir(tmp_path),
        app_env=app_env,
        auth=AuthSettings(
            enabled=True,
            password_hash=hash_password("secret", salt="test-salt", iterations=1000),
            session_secret=AUTH_SECRET,
            session_ttl_seconds=3600,
        ),
    )


def login(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"password": "secret"})
    assert response.status_code == 200


def csrf_headers(client: TestClient, settings: Settings) -> dict[str, str]:
    csrf_token = client.cookies.get(settings.auth.csrf_cookie_name)
    assert csrf_token
    return {"X-CSRF-Token": csrf_token}


def public_dir(tmp_path: Path) -> Path:
    path = tmp_path / "public"
    path.mkdir(parents=True, exist_ok=True)
    (path / "index.html").write_text("<!doctype html><title>OpenCollect</title>", encoding="utf-8")
    (path / "login.html").write_text("<!doctype html><title>Login</title>", encoding="utf-8")
    return path
