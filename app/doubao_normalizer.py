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

    Always returns valid PNG bytes when resizing happened.

    If the bytes are not a recognisable image (Pillow raises
    UnidentifiedImageError or OSError for truncated data), return them
    unchanged — let the downstream SDK decide what to do with them. (Callers
    may forward arbitrary bytes; we shouldn't reject here.)
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            if max(img.size) <= MAX_LONG_EDGE:
                return image_bytes
            img = img.copy()
            img.thumbnail((MAX_LONG_EDGE, MAX_LONG_EDGE), Image.LANCZOS)
    except (Image.UnidentifiedImageError, OSError, ValueError):
        return image_bytes
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


def _build_client(api_key: str) -> OpenAI:
    """Construct a real OpenAI client pointed at Volcengine Ark.

    Centralised so tests can pass a MagicMock instead and so the timeouts
    are set in exactly one place.
    """
    return OpenAI(
        api_key=api_key,
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        timeout=httpx.Timeout(10.0, read=60.0),
    )


def _call_once(
    *,
    client: OpenAI,
    model: str,
    prompt: str,
    image_bytes: bytes,
) -> bytes:
    """One SDK call. Returns the cleaned image re-encoded as PNG.

    Raises DoubaoAPIError (terminal) for malformed responses. Propagates
    openai.* exceptions untouched so the caller (run) can classify and
    decide whether to retry.

    Notes on the Ark API:
    - openai >= 2.0's typed `images.generate` does not accept `image` as
      a kwarg (it is text-to-image only). To call Ark's image-to-image
      endpoint we pass `image` through `extra_body` so the SDK forwards
      it verbatim in the JSON request body.
    - Ark rejects `size="auto"`. Accepted values are `'1k' | '2k' | '4k'`
      or `'WIDTHxHEIGHT'`. We default to `'2k'`.
    - Ark returns the image in JPEG (not PNG). We re-encode as PNG to
      keep a single byte format downstream.
    """
    b64 = base64.b64encode(image_bytes).decode()
    data_url = f"data:image/png;base64,{b64}"
    resp = client.images.generate(
        model=model,
        prompt=prompt,
        size="2k",
        response_format="b64_json",
        extra_body={"image": [data_url]},
    )
    item = resp.data[0]
    out_b64 = getattr(item, "b64_json", None)
    if not out_b64:
        raise DoubaoAPIError(
            user_msg="返回数据异常",
            internal_msg="doubao response had no b64_json",
        )
    decoded = base64.b64decode(out_b64)
    # Re-encode as PNG so callers (Feishu upload, on-disk .png, DXF
    # converter) see one consistent format. Pillow is the cheapest way
    # to validate that the bytes are a real image.
    try:
        with Image.open(io.BytesIO(decoded)) as img:
            img.load()
            img = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
    except (Image.UnidentifiedImageError, OSError, ValueError) as e:
        raise DoubaoAPIError(
            user_msg="返回数据异常",
            internal_msg=f"doubao response is not a valid image: {e}",
        )
    return decoded


def run(
    *,
    image_bytes: bytes,
    prompt: str,
    work_dir: Path,
    api_key: str,
    model: str,
    client: Optional[OpenAI] = None,
) -> NormalizedImage:
    """Resize if needed, call Ark (with one retry on 5xx/connect), return
    the cleaned image. Raises DoubaoAPIError on terminal failure.

    The caller (handlers) treats DoubaoAPIError as a user-facing error and
    does NOT retry. All retry policy lives in this function.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    if client is None:
        client = _build_client(api_key)

    resized = _resize_if_needed(image_bytes)
    last_exc: BaseException | None = None
    decision: _RetryDecision | None = None

    for attempt in (1, 2):
        start = time.monotonic()
        status = "ok"
        try:
            cleaned = _call_once(
                client=client,
                model=model,
                prompt=prompt,
                image_bytes=resized,
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            log.info(
                "doubao call ok attempt=%d duration_ms=%d bytes_in=%d bytes_out=%d",
                attempt, duration_ms, len(image_bytes), len(cleaned),
            )
            cleaned_path = work_dir / "normalized.png"
            cleaned_path.write_bytes(cleaned)
            return NormalizedImage(cleaned_bytes=cleaned, cleaned_path=cleaned_path)
        except DoubaoAPIError:
            # Malformed response — _call_once already classified; no retry
            raise
        except (APIConnectionError, APIStatusError) as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            decision = _classify_error(e)
            last_exc = e
            status = "retry" if decision.retry else "failed"
            log.warning(
                "doubao call %s attempt=%d duration_ms=%d err=%s",
                status, attempt, duration_ms, e,
            )
            if not decision.retry:
                break
            if attempt == 1:
                time.sleep(1.0)

    # Exhausted retries or terminal error
    assert decision is not None and last_exc is not None
    raise DoubaoAPIError(
        user_msg=decision.user_msg,
        internal_msg=f"doubao call failed: {last_exc}",
    )
