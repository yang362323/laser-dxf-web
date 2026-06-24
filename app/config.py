"""Load and validate configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    """Runtime configuration for the bot."""

    app_id: str
    app_secret: str
    log_level: str
    health_port: int
    work_dir: str
    convert_timeout_s: int
    max_workers: int

    @classmethod
    def from_env(cls) -> "Config":
        """Build a Config from environment variables.

        Required: FEISHU_APP_ID, FEISHU_APP_SECRET.
        Optional (with defaults): LOG_LEVEL, HEALTH_PORT, WORK_DIR,
        CONVERT_TIMEOUT_S, MAX_WORKERS.
        """
        app_id = os.environ.get("FEISHU_APP_ID", "").strip()
        app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
        if not app_id:
            raise ConfigError("FEISHU_APP_ID is required")
        if not app_secret:
            raise ConfigError("FEISHU_APP_SECRET is required")
        return cls(
            app_id=app_id,
            app_secret=app_secret,
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            health_port=int(os.environ.get("HEALTH_PORT", "8080")),
            work_dir=os.environ.get("WORK_DIR", "/tmp/laser-bot"),
            convert_timeout_s=int(os.environ.get("CONVERT_TIMEOUT_S", "60")),
            max_workers=int(os.environ.get("MAX_WORKERS", "3")),
        )
