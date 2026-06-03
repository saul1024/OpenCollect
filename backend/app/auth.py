from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from backend.app.core.config import AuthSettings, Settings


SESSION_USER = "owner"
PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 240000


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class Session:
    authenticated: bool
    user: str = ""


class AuthManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.auth = settings.auth

    @property
    def enabled(self) -> bool:
        return self.auth.enabled

    @property
    def cookie_name(self) -> str:
        return self.auth.cookie_name

    @property
    def csrf_cookie_name(self) -> str:
        return self.auth.csrf_cookie_name

    @property
    def cookie_secure(self) -> bool:
        return self.settings.app_env == "production"

    def verify_password(self, password: str) -> bool:
        if not self.enabled:
            return True
        return verify_password_hash(password, self.auth.password_hash)

    def create_session_token(self, now: int | None = None, ttl_seconds: int | None = None) -> str:
        issued_at = int(now if now is not None else time.time())
        ttl = self.auth.session_ttl_seconds if ttl_seconds is None else ttl_seconds
        payload = {
            "sub": SESSION_USER,
            "iat": issued_at,
            "exp": issued_at + int(ttl),
        }
        encoded_payload = base64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        signature = self._sign(encoded_payload.encode("ascii"))
        return f"{encoded_payload}.{signature}"

    def create_csrf_token(self, session_token: str) -> str:
        nonce = secrets.token_urlsafe(24)
        signature = self._sign_csrf(session_token, nonce)
        return f"{nonce}.{signature}"

    def verify_csrf_token(self, session_token: str, csrf_token: str) -> None:
        if not self.enabled:
            return
        if not session_token or not csrf_token or "." not in csrf_token:
            raise AuthError("missing csrf token")
        nonce, signature = csrf_token.split(".", 1)
        if not nonce or not signature:
            raise AuthError("invalid csrf token")
        expected = self._sign_csrf(session_token, nonce)
        if not hmac.compare_digest(signature, expected):
            raise AuthError("invalid csrf signature")

    def verify_session_token(self, token: str, now: int | None = None) -> Session:
        if not self.enabled:
            return Session(authenticated=True, user=SESSION_USER)
        if not token or "." not in token:
            raise AuthError("missing session")
        encoded_payload, encoded_signature = token.split(".", 1)
        expected_signature = self._sign(encoded_payload.encode("ascii"))
        if not hmac.compare_digest(encoded_signature, expected_signature):
            raise AuthError("invalid session signature")
        try:
            payload = json.loads(base64url_decode(encoded_payload))
        except (ValueError, json.JSONDecodeError) as exc:
            raise AuthError("invalid session payload") from exc
        user = str(payload.get("sub") or "")
        expires_at = int(payload.get("exp") or 0)
        current_time = int(now if now is not None else time.time())
        if user != SESSION_USER:
            raise AuthError("invalid session user")
        if expires_at <= current_time:
            raise AuthError("session expired")
        return Session(authenticated=True, user=user)

    def read_session(self, cookies: dict[str, str], now: int | None = None) -> Session:
        if not self.enabled:
            return Session(authenticated=True, user=SESSION_USER)
        return self.verify_session_token(cookies.get(self.cookie_name, ""), now=now)

    def _sign(self, value: bytes) -> str:
        digest = hmac.new(self.auth.session_secret.encode("utf-8"), value, hashlib.sha256).digest()
        return base64url_encode(digest)

    def _sign_csrf(self, session_token: str, nonce: str) -> str:
        return self._sign(f"csrf:{session_token}:{nonce}".encode("utf-8"))


def hash_password(password: str, salt: str | None = None, iterations: int = PASSWORD_ITERATIONS) -> str:
    raw_salt = salt or secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), raw_salt.encode("utf-8"), iterations)
    return f"{PASSWORD_ALGORITHM}${iterations}${raw_salt}${base64url_encode(digest)}"


def verify_password_hash(password: str, password_hash: str) -> bool:
    try:
        algorithm, raw_iterations, salt, expected = password_hash.split("$", 3)
        iterations = int(raw_iterations)
    except ValueError:
        return False
    if algorithm != PASSWORD_ALGORITHM or iterations <= 0 or not salt or not expected:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return hmac.compare_digest(base64url_encode(digest), expected)


def session_payload(auth_manager: AuthManager, token: str) -> dict[str, Any]:
    if not auth_manager.enabled:
        return {"authenticated": True, "authEnabled": False, "user": SESSION_USER}
    try:
        session = auth_manager.verify_session_token(token)
    except AuthError:
        return {"authenticated": False, "authEnabled": True, "user": ""}
    return {"authenticated": session.authenticated, "authEnabled": True, "user": session.user}


def base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def base64url_decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}").decode("utf-8")
