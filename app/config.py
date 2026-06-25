"""Load and validate configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


DEFAULT_ARK_MODEL: str = "doubao-seedream-4-0-250828"


@dataclass(frozen=True)
class Config:
    """Runtime configuration for the web app."""

    ark_api_key: str
    ark_model: str
    log_level: str
    port: int
    work_dir: str
    max_workers: int

    @classmethod
    def from_env(cls) -> "Config":
        ark_api_key = os.environ.get("ARK_API_KEY", "").strip()
        if not ark_api_key:
            raise ConfigError("ARK_API_KEY is required")
        return cls(
            ark_api_key=ark_api_key,
            ark_model=os.environ.get("ARK_MODEL", DEFAULT_ARK_MODEL),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            port=int(os.environ.get("PORT", "8080")),
            work_dir=os.environ.get("WORK_DIR", "/tmp/laser-bot"),
            max_workers=int(os.environ.get("MAX_WORKERS", "3")),
        )
