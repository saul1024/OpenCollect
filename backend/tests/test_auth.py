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
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie

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


def public_dir(tmp_path: Path) -> Path:
    path = tmp_path / "public"
    path.mkdir(parents=True, exist_ok=True)
    (path / "index.html").write_text("<!doctype html><title>OpenCollect</title>", encoding="utf-8")
    (path / "login.html").write_text("<!doctype html><title>Login</title>", encoding="utf-8")
    return path
