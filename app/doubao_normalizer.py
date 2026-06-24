"""Per-request image -> Doubao-normalized image.

Wraps the OpenAI Python SDK pointed at Volcengine Ark. Byte-in / bytes-out
plus an on-disk path so the caller can decide what to do with the result
(e.g. upload to Feishu, hand to the existing DXF converter).

Has no knowledge of Feishu. The retry policy lives here, not in handlers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


class DoubaoAPIError(Exception):
    """Terminal failure from Doubao. Carries a user-facing Chinese message
    distinct from the internal one (which may include raw SDK details)."""

    def __init__(self, user_msg: str, internal_msg: str) -> None:
        super().__init__(internal_msg)
        self.user_msg = user_msg
        self.internal_msg = internal_msg


@dataclass(frozen=True)
class NormalizedImage:
    """Result of a successful normalization call."""

    cleaned_bytes: bytes
    cleaned_path: Path
