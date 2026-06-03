from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DOTENV_LOADED = False


def load_dotenv(path: Path = Path(".env")) -> None:
    global DOTENV_LOADED
    if DOTENV_LOADED or not path.is_file():
        return

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)

    DOTENV_LOADED = True


def env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return value
    return default


def env_bool(*names: str, default: bool = False) -> bool:
    raw = env_first(*names, default=str(default).lower())
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(*names: str, default: int) -> int:
    raw = env_first(*names, default=str(default))
    try:
        return int(raw)
    except ValueError:
        return default


class SettingsError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthSettings:
    enabled: bool = False
    password_hash: str = ""
    session_secret: str = ""
    session_ttl_seconds: int = 604800
    cookie_name: str = "opencollect_session"
    csrf_cookie_name: str = "opencollect_csrf"


@dataclass(frozen=True)
class SyncSettings:
    provider: str = "none"
    endpoint: str = ""
    region: str = "auto"
    bucket: str = ""
    access_key_id: str = ""
    secret_access_key: str = ""
    session_token: str = ""
    object_key: str = "opencollect/collections.json"
    backup_prefix: str = "opencollect/backups/"
    force_path_style: bool = True
    timeout_seconds: float = 15.0

    @property
    def enabled(self) -> bool:
        return self.provider in {"s3", "cos"}


@dataclass(frozen=True)
class Settings:
    port: str
    data_dir: Path
    public_dir: Path
    app_env: str = "development"
    auth: AuthSettings = AuthSettings()
    sync: SyncSettings = SyncSettings()

    @property
    def collections_path(self) -> Path:
        return self.data_dir / "collections.json"

    @property
    def sync_state_path(self) -> Path:
        return self.data_dir / "sync-state.json"

    @property
    def sync_base_path(self) -> Path:
        return self.data_dir / "sync-base.json"

    @property
    def sync_local_backup_dir(self) -> Path:
        return self.data_dir / "local-backups"


def load_settings() -> Settings:
    load_dotenv()
    app_env = env_first("APP_ENV", default="development").strip().lower() or "development"
    auth_enabled = env_bool("AUTH_ENABLED", default=app_env == "production")
    provider = env_first("SYNC_PROVIDER", default="none").strip().lower()
    if provider in {"", "off", "false", "disabled"}:
        provider = "none"
    default_force_path_style = provider != "cos"
    first = ("COS", "S3") if provider == "cos" else ("S3", "COS")

    def sync_env(name: str, default: str = "") -> str:
        return env_first(*(f"{prefix}_{name}" for prefix in first), default=default)

    settings = Settings(
        port=os.getenv("PORT", "3000"),
        data_dir=Path(os.getenv("DATA_DIR", "./data")),
        public_dir=Path(os.getenv("PUBLIC_DIR", "./public")),
        app_env=app_env,
        auth=AuthSettings(
            enabled=auth_enabled,
            password_hash=env_first("AUTH_PASSWORD_HASH"),
            session_secret=env_first("AUTH_SESSION_SECRET"),
            session_ttl_seconds=env_int("AUTH_SESSION_TTL_SECONDS", default=604800),
        ),
        sync=SyncSettings(
            provider=provider,
            endpoint=sync_env("ENDPOINT"),
            region=sync_env("REGION", default="auto"),
            bucket=sync_env("BUCKET"),
            access_key_id=env_first(
                *(f"{prefix}_{name}" for prefix in first for name in ["SECRET_ID", "ACCESS_KEY_ID"]),
            ),
            secret_access_key=env_first(
                *(f"{prefix}_{name}" for prefix in first for name in ["SECRET_KEY", "SECRET_ACCESS_KEY"]),
            ),
            session_token=sync_env("SESSION_TOKEN"),
            object_key=sync_env("OBJECT_KEY", default="opencollect/collections.json"),
            backup_prefix=sync_env("BACKUP_PREFIX", default="opencollect/backups/"),
            force_path_style=env_bool("COS_FORCE_PATH_STYLE", "S3_FORCE_PATH_STYLE", default=default_force_path_style),
            timeout_seconds=float(env_first("SYNC_TIMEOUT_SECONDS", default="15")),
        ),
    )
    validate_settings(settings)
    return settings


def validate_settings(settings: Settings) -> None:
    if settings.app_env == "production" and not settings.auth.enabled:
        raise SettingsError("AUTH_ENABLED=true is required in production")
    if settings.app_env != "production" and not settings.auth.enabled:
        return
    if not settings.auth.password_hash:
        raise SettingsError("AUTH_PASSWORD_HASH is required when auth is enabled")
    if len(settings.auth.session_secret) < 32:
        raise SettingsError("AUTH_SESSION_SECRET must be at least 32 characters when auth is enabled")
