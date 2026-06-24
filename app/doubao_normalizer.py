"""Per-request image -> Doubao-normalized image.

Wraps the OpenAI Python SDK pointed at Volcengine Ark. Byte-in / bytes-out
plus an on-disk path so the caller can decide what to do with the result
(e.g. upload to Feishu, hand to the existing DXF converter).

Has no knowledge of Feishu. The retry policy lives here, not in handlers.
"""

from __future__ import annotations

import base64
import io
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    OpenAI,
)
from PIL import Image

log = logging.getLogger(__name__)


#: Long-edge cap for images sent to Ark. Conservative default that keeps
#: cost low and stays well under the documented per-image size limit.
MAX_LONG_EDGE = 2048


def _resize_if_needed(image_bytes: bytes) -> bytes:
    """If the image's long edge exceeds MAX_LONG_EDGE, downscale and re-encode
    as PNG. Otherwise return the bytes unchanged.

    Always returns valid PNG bytes; never returns the original format
    untouched when resizing happened.
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        if max(img.size) <= MAX_LONG_EDGE:
            return image_bytes
        img = img.copy()
        img.thumbnail((MAX_LONG_EDGE, MAX_LONG_EDGE), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class DoubaoAPIError(RuntimeError):
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


@dataclass(frozen=True)
class _RetryDecision:
    """Internal: tells run() whether to retry and what to say to the user
    if we give up."""

    retry: bool
    user_msg: str


def _classify_error(exc: BaseException) -> _RetryDecision:
    """Map a single SDK exception to a retry decision + Chinese user message.

    No side effects; no logging. Called inside run() once per failed call.
    """
    if isinstance(exc, APIConnectionError):
        return _RetryDecision(retry=True, user_msg="网络问题")
    if isinstance(exc, APIStatusError):
        status = getattr(exc, "status_code", None)
        code = getattr(exc, "code", None)
        if code == "AuditReject":
            return _RetryDecision(retry=False, user_msg="图片内容被 AI 拒绝")
        if code == "Arrearage":
            return _RetryDecision(retry=False, user_msg="账户欠费")
        if status in (401, 403):
            return _RetryDecision(retry=False, user_msg="鉴权失败")
        if status is not None and 500 <= status < 600:
            return _RetryDecision(retry=True, user_msg="服务暂时不可用")
        # Any other 4xx (400, 404, 422, ...)
        return _RetryDecision(retry=False, user_msg="请求被拒绝")
    # Unknown error type — treat as terminal but generic.
    return _RetryDecision(retry=False, user_msg="请求被拒绝")
