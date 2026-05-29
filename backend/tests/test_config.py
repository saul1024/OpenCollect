from __future__ import annotations

import backend.app.core.config as config


def test_cos_provider_defaults_to_virtual_hosted_style(monkeypatch):
    monkeypatch.setenv("SYNC_PROVIDER", "cos")
    monkeypatch.setenv("COS_ENDPOINT", "https://cos.ap-guangzhou.myqcloud.com")
    monkeypatch.setenv("COS_REGION", "ap-guangzhou")
    monkeypatch.setenv("COS_BUCKET", "opencollect-1250000000")
    monkeypatch.setenv("COS_SECRET_ID", "secret-id")
    monkeypatch.setenv("COS_SECRET_KEY", "secret-key")

    settings = config.load_settings()

    assert settings.sync.provider == "cos"
    assert settings.sync.force_path_style is False
    assert settings.sync.access_key_id == "secret-id"


def test_s3_provider_defaults_to_path_style(monkeypatch):
    monkeypatch.setenv("SYNC_PROVIDER", "s3")
    monkeypatch.setenv("S3_ENDPOINT", "http://127.0.0.1:9000")
    monkeypatch.setenv("S3_REGION", "auto")
    monkeypatch.setenv("S3_BUCKET", "opencollect")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "access-key")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret-key")

    settings = config.load_settings()

    assert settings.sync.provider == "s3"
    assert settings.sync.force_path_style is True
    assert settings.sync.access_key_id == "access-key"


def test_load_settings_reads_dotenv_without_shell_source(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SYNC_PROVIDER", raising=False)
    monkeypatch.delenv("COS_ENDPOINT", raising=False)
    monkeypatch.delenv("COS_REGION", raising=False)
    monkeypatch.delenv("COS_BUCKET", raising=False)
    monkeypatch.delenv("COS_SECRET_ID", raising=False)
    monkeypatch.delenv("COS_SECRET_KEY", raising=False)
    monkeypatch.setattr(config, "DOTENV_LOADED", False)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "SYNC_PROVIDER=cos",
                "COS_ENDPOINT = https://cos.ap-guangzhou.myqcloud.com",
                "COS_REGION=ap-guangzhou",
                "COS_BUCKET='opencollect-1250000000'",
                'COS_SECRET_ID="secret-id"',
                "COS_SECRET_KEY=secret-key",
            ]
        ),
        encoding="utf-8",
    )

    settings = config.load_settings()

    assert settings.sync.provider == "cos"
    assert settings.sync.endpoint == "https://cos.ap-guangzhou.myqcloud.com"
    assert settings.sync.bucket == "opencollect-1250000000"
    assert settings.sync.access_key_id == "secret-id"
