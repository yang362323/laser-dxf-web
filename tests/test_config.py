"""Tests for app.config."""

from __future__ import annotations

import pytest

from app.config import Config, ConfigError


def test_load_from_env_with_required_vars(monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test_id")
    monkeypatch.setenv("FEISHU_APP_SECRET", "test_secret_xyz")
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