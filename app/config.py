"""Load and validate configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


DEFAULT_ARK_MODEL: str = "doubao-seedream-4-0-250828"


@dataclass(frozen=True)
class Config:
    """Runtime configuration for the bot."""

    dingtalk_app_key: str
    dingtalk_app_secret: str
    dingtalk_robot_code: str
    ark_api_key: str
    ark_model: str
    log_level: str
    health_port: int
    work_dir: str
    convert_timeout_s: int
    max_workers: int

    @classmethod
    def from_env(cls) -> "Config":
        """Build a Config from environment variables.

        Required: DINGTALK_APP_KEY, DINGTALK_APP_SECRET, ARK_API_KEY.
        Optional (with defaults): DINGTALK_ROBOT_CODE, LOG_LEVEL, HEALTH_PORT,
        WORK_DIR, CONVERT_TIMEOUT_S, MAX_WORKERS, ARK_MODEL.
        """
        app_key = os.environ.get("DINGTALK_APP_KEY", "").strip()
        app_secret = os.environ.get("DINGTALK_APP_SECRET", "").strip()
        robot_code = os.environ.get("DINGTALK_ROBOT_CODE", "").strip()
        ark_api_key = os.environ.get("ARK_API_KEY", "").strip()

        if not app_key:
            raise ConfigError("DINGTALK_APP_KEY is required")
        if not app_secret:
            raise ConfigError("DINGTALK_APP_SECRET is required")
        if not robot_code:
            robot_code = app_key
        if not ark_api_key:
            raise ConfigError("ARK_API_KEY is required")

        return cls(
            dingtalk_app_key=app_key,
            dingtalk_app_secret=app_secret,
            dingtalk_robot_code=robot_code,
            ark_api_key=ark_api_key,
            ark_model=os.environ.get("ARK_MODEL", DEFAULT_ARK_MODEL),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            health_port=int(os.environ.get("HEALTH_PORT", "8080")),
            work_dir=os.environ.get("WORK_DIR", "/tmp/laser-bot"),
            convert_timeout_s=int(os.environ.get("CONVERT_TIMEOUT_S", "60")),
            max_workers=int(os.environ.get("MAX_WORKERS", "3")),
        )
