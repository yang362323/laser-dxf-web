"""Tests for app.config."""

from __future__ import annotations

import pytest

from app.config import Config, ConfigError


def test_load_from_env_with_required_vars(monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test_id")
    monkeypatch.setenv("FEISHU_APP_SECRET", "test_secret_xyz")
    monkeypatch.setenv("ARK_API_KEY", "ark-test-key")
    cfg = Config.from_env()
    assert cfg.app_id == "cli_test_id"
    assert cfg.app_secret == "test_secret_xyz"
    assert cfg.log_level == "INFO"
    assert cfg.health_port == 8080
    assert cfg.work_dir == "/tmp/laser-bot"
    assert cfg.convert_timeout_s == 60
    assert cfg.max_workers == 3


def test_load_overrides_via_env(monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test_id")
    monkeypatch.setenv("FEISHU_APP_SECRET", "test_secret_xyz")
    monkeypatch.setenv("ARK_API_KEY", "ark-test-key")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("HEALTH_PORT", "9999")
    monkeypatch.setenv("WORK_DIR", "/var/laser")
    monkeypatch.setenv("CONVERT_TIMEOUT_S", "120")
    monkeypatch.setenv("MAX_WORKERS", "8")
    cfg = Config.from_env()
    assert cfg.log_level == "DEBUG"
    assert cfg.health_port == 9999
    assert cfg.work_dir == "/var/laser"
    assert cfg.convert_timeout_s == 120
    assert cfg.max_workers == 8


def test_missing_app_id_raises(monkeypatch):
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.setenv("FEISHU_APP_SECRET", "x")
    with pytest.raises(ConfigError) as exc:
        Config.from_env()
    assert "FEISHU_APP_ID" in str(exc.value)


def test_missing_app_secret_raises(monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    with pytest.raises(ConfigError) as exc:
        Config.from_env()
    assert "FEISHU_APP_SECRET" in str(exc.value)


def test_config_requires_ark_api_key(monkeypatch):
    """Missing ARK_API_KEY should raise ConfigError."""
    from app.config import Config, ConfigError

    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        Config.from_env()


def test_config_loads_ark_api_key(monkeypatch):
    from app.config import Config

    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("ARK_API_KEY", "ark-test-key")
    monkeypatch.delenv("ARK_MODEL", raising=False)
    cfg = Config.from_env()
    assert cfg.ark_api_key == "ark-test-key"


def test_config_ark_model_default(monkeypatch):
    from app.config import Config

    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("ARK_API_KEY", "ark-test-key")
    monkeypatch.delenv("ARK_MODEL", raising=False)
    cfg = Config.from_env()
    assert cfg.ark_model == "doubao-seedream-5-0-2 60128"


def test_config_ark_model_override(monkeypatch):
    from app.config import Config

    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("ARK_API_KEY", "ark-test-key")
    monkeypatch.setenv("ARK_MODEL", "doubao-seedream-5-0-2 60128-prod")
    cfg = Config.from_env()
    assert cfg.ark_model == "doubao-seedream-5-0-2 60128-prod"