# Doubao Image Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert a fixed-prompt Doubao image normalization step into the existing `feishu-laser-dxf-bot` `/dxf` pipeline, so every `/dxf` request first runs the input image through Volcengine Ark's image model and then through the existing DXF conversion. The reply post message gains the cleaned image as the first inline image.

**Architecture:** Add two new modules under `app/` — `doubao_prompt.py` (constant) and `doubao_normalizer.py` (byte-in/bytes-out wrapper around the `openai` SDK pointed at Ark). Add one method to `FeishuClient` for uploading raw image bytes. Insert the normalization call into `handle_dxf_request` between the existing `feishu.download_image(...)` and `converter.run(...)`. Change `send_post_message` to accept a list of `image_keys` so both the cleaned image and the DXF preview can appear in the same post message.

**Tech Stack:** Python 3.11, `openai` Python SDK ≥ 1.40 (OpenAI-compatible against `https://ark.cn-beijing.volces.com/api/v3`), `Pillow` ≥ 10 (already in deps), `pytest` + `pytest-mock` for tests, existing `lark-oapi` for Feishu.

**Spec:** `docs/superpowers/specs/2026-06-24-feishu-doubao-normalizer-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `app/doubao_prompt.py` | Create | Single module-level constant `DEFAULT_PROMPT`. No logic. |
| `app/doubao_normalizer.py` | Create | `DoubaoAPIError`, `NormalizedImage` dataclass, `run(*, image_bytes, prompt, work_dir, api_key, model, client=None)` with internal retry. |
| `app/config.py` | Modify | Add `ark_api_key` (required) and `ark_model` (default `doubao-seedream-5-0-2 60128`) env-driven fields. |
| `app/feishu_client.py` | Modify | Add `upload_image_bytes(data, suffix) -> str`; change `send_post_message` to accept `image_keys: list[str] \| None` instead of `image_key: str \| None`. |
| `app/handlers.py` | Modify | Between `feishu.download_image` and `converter.run`, call `doubao_normalizer.run`; upload cleaned image; pass `image_keys=[cleaned_key, preview_key]` to `send_post_message`. Add `DoubaoAPIError` branch. |
| `pyproject.toml` | Modify | Add `openai>=1.40` to `dependencies`. |
| `docker-compose.yml` | Modify | Expose `ARK_API_KEY` and `ARK_MODEL` env (the former required, fail fast). |
| `.env.example` | Modify | Document `ARK_API_KEY` and `ARK_MODEL`. |
| `README.md` | Modify | One paragraph pointing to Volcengine Ark console for key acquisition. |
| `tests/test_doubao_prompt.py` | Create | Asserts the prompt constant contains the four required Chinese fragments. |
| `tests/test_doubao_normalizer.py` | Create | All 13 cases from spec §7.2 (happy path, retry, classify, resize). |
| `tests/test_handlers_doubao_integration.py` | Create | End-to-end handler flow with mocked doubao/converter/preview. |
| `tests/test_handlers.py` | Modify | Adapt existing tests to new `image_keys` kwarg; add a `doubao_normalizer` mock to the happy-path test. |
| `tests/test_config.py` | Modify | Add cases for `ark_api_key` and `ark_model` env vars. |

---

## Task 1: Add `openai` SDK dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `openai` to `pyproject.toml`**

Edit `pyproject.toml`, in the `dependencies` list, add `openai>=1.40` as a new line:

```toml
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "lark-oapi>=1.2",
    "matplotlib>=3.8",
    "Pillow>=10.0",
    "openai>=1.40",
]
```

- [ ] **Step 2: Install into the existing venv**

Run:
```bash
cd /Users/yang362323/projects/feishu-laser-dxf-bot
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: pip output ends with `Successfully installed openai-1.x.x ...`. No errors.

- [ ] **Step 3: Verify import works**

Run:
```bash
python -c "from openai import OpenAI; print(OpenAI.__module__)"
```

Expected: prints `openai.client` (or similar containing `openai`).

- [ ] **Step 4: Run the existing test suite to confirm nothing broke**

Run:
```bash
pytest -q
```

Expected: all existing tests pass (no regressions from the dep bump).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "build(deps): add openai SDK for Doubao image normalization"
```

---

## Task 2: Add `DEFAULT_PROMPT` constant (TDD)

**Files:**
- Create: `app/doubao_prompt.py`
- Create: `tests/test_doubao_prompt.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_doubao_prompt.py` with:

```python
"""Tests for app.doubao_prompt."""

from __future__ import annotations

from app.doubao_prompt import DEFAULT_PROMPT


def test_default_prompt_is_non_empty_string():
    assert isinstance(DEFAULT_PROMPT, str)
    assert DEFAULT_PROMPT.strip() != ""


def test_default_prompt_contains_all_four_instructions():
    # The four fixed instructions must all appear; order is significant
    # for the model's interpretation but not asserted here.
    fragments = [
        "提高图片清晰度",
        "logo 摆正",
        "logo 改为纯黑色",
        "背景改成纯白",
    ]
    for fragment in fragments:
        assert fragment in DEFAULT_PROMPT, f"missing fragment: {fragment!r}"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
pytest tests/test_doubao_prompt.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.doubao_prompt'`.

- [ ] **Step 3: Create the module**

Create `app/doubao_prompt.py`:

```python
"""Fixed Chinese prompt for the Doubao image normalization step.

Single source of truth for the prompt sent to the model on every /dxf
request. Edit only with intent — the spec ties this exact wording to the
expected behaviour of the pipeline.
"""

from __future__ import annotations

DEFAULT_PROMPT: str = (
    "先提高图片清晰度，把图片的logo摆正，"
    "图片中的logo改为纯黑色，然后背景改成纯白。"
)
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
pytest tests/test_doubao_prompt.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/doubao_prompt.py tests/test_doubao_prompt.py
git commit -m "feat(doubao): add DEFAULT_PROMPT constant + tests"
```

---

## Task 3: Add `ark_api_key` and `ark_model` config fields (TDD)

**Files:**
- Modify: `app/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Read the existing test file to understand its style**

Run:
```bash
cat tests/test_config.py
```

(This is just a Read-equivalent; no Edit.)

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_config.py`:

```python
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
```

(If `tests/test_config.py` does not import `pytest` at the top, add `import pytest` near the existing imports.)

- [ ] **Step 3: Run the tests to verify they fail**

Run:
```bash
pytest tests/test_config.py -v
```

Expected: the 4 new tests fail with `TypeError: __init__() got an unexpected keyword argument 'ark_api_key'` (or similar).

- [ ] **Step 4: Modify `app/config.py`**

Replace the file contents with:

```python
"""Load and validate configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


DEFAULT_ARK_MODEL: str = "doubao-seedream-5-0-2 60128"


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
    ark_api_key: str
    ark_model: str

    @classmethod
    def from_env(cls) -> "Config":
        """Build a Config from environment variables.

        Required: FEISHU_APP_ID, FEISHU_APP_SECRET, ARK_API_KEY.
        Optional (with defaults): LOG_LEVEL, HEALTH_PORT, WORK_DIR,
        CONVERT_TIMEOUT_S, MAX_WORKERS, ARK_MODEL.
        """
        app_id = os.environ.get("FEISHU_APP_ID", "").strip()
        app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
        ark_api_key = os.environ.get("ARK_API_KEY", "").strip()
        if not app_id:
            raise ConfigError("FEISHU_APP_ID is required")
        if not app_secret:
            raise ConfigError("FEISHU_APP_SECRET is required")
        if not ark_api_key:
            raise ConfigError("ARK_API_KEY is required")
        return cls(
            app_id=app_id,
            app_secret=app_secret,
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            health_port=int(os.environ.get("HEALTH_PORT", "8080")),
            work_dir=os.environ.get("WORK_DIR", "/tmp/laser-bot"),
            convert_timeout_s=int(os.environ.get("CONVERT_TIMEOUT_S", "60")),
            max_workers=int(os.environ.get("MAX_WORKERS", "3")),
            ark_api_key=ark_api_key,
            ark_model=os.environ.get("ARK_MODEL", DEFAULT_ARK_MODEL),
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:
```bash
pytest tests/test_config.py -v
```

Expected: all tests (old + new) pass.

- [ ] **Step 6: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat(config): require ARK_API_KEY; add ark_model with default"
```

---

## Task 4: Add `DoubaoAPIError` and `NormalizedImage` (no behavior, just types)

**Files:**
- Create: `app/doubao_normalizer.py`

- [ ] **Step 1: Create the module skeleton**

Create `app/doubao_normalizer.py` with just the types (no logic yet):

```python
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
```

- [ ] **Step 2: Run existing tests to confirm nothing broke**

Run:
```bash
pytest -q
```

Expected: all pass (the new module has no callers yet, so existing tests are unaffected).

- [ ] **Step 3: Commit**

```bash
git add app/doubao_normalizer.py
git commit -m "feat(doubao): add DoubaoAPIError and NormalizedImage types"
```

---

## Task 5: Implement `_resize_if_needed` helper (TDD)

**Files:**
- Modify: `app/doubao_normalizer.py`
- Modify: `tests/test_doubao_normalizer.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_doubao_normalizer.py` with:

```python
"""Tests for app.doubao_normalizer."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.doubao_normalizer import (
    DoubaoAPIError,
    NormalizedImage,
    _resize_if_needed,
)

MAX_LONG_EDGE = 2048


def _make_png_bytes(width: int, height: int) -> bytes:
    """Return PNG bytes of a solid-color image of the given size."""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_resize_no_op_when_under_limit():
    original = _make_png_bytes(1000, 1000)
    out = _resize_if_needed(original)
    assert out == original


def test_resize_no_op_when_exactly_at_limit():
    original = _make_png_bytes(MAX_LONG_EDGE, MAX_LONG_EDGE)
    out = _resize_if_needed(original)
    assert out == original


def test_resize_scales_down_when_over_limit():
    original = _make_png_bytes(5000, 3000)
    out = _resize_if_needed(original)
    img = Image.open(io.BytesIO(out))
    assert max(img.size) == MAX_LONG_EDGE
    # Aspect ratio preserved: 5000x3000 -> 2048x1228 (floor of 3000*2048/5000)
    assert img.size == (2048, 1228)


def test_resize_returns_png_bytes():
    original = _make_png_bytes(5000, 5000)
    out = _resize_if_needed(original)
    # PNG signature: 89 50 4E 47
    assert out[:4] == b"\x89PNG"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
pytest tests/test_doubao_normalizer.py -v
```

Expected: `ImportError: cannot import name '_resize_if_needed' from 'app.doubao_normalizer'`.

- [ ] **Step 3: Implement `_resize_if_needed`**

Append to `app/doubao_normalizer.py`:

```python
import base64
import io
import time
from typing import Optional

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    OpenAI,
)

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
```

(Add `import io` near the top of the file if not already present.)

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
pytest tests/test_doubao_normalizer.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/doubao_normalizer.py tests/test_doubao_normalizer.py
git commit -m "feat(doubao): add _resize_if_needed with Pillow downscale"
```

---

## Task 6: Implement `_classify_error` helper (TDD)

**Files:**
- Modify: `app/doubao_normalizer.py`
- Modify: `tests/test_doubao_normalizer.py`

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_doubao_normalizer.py`:

```python
from openai import APIConnectionError, APIStatusError

from app.doubao_normalizer import _classify_error


def _make_status_error(status: int, code: str | None = None) -> APIStatusError:
    """Build an APIStatusError suitable for testing _classify_error."""
    fake_response = type("R", (), {"status_code": status, "headers": {}})()
    err = APIStatusError(
        message="boom",
        request_id="req_1",
        body=None,
    )
    err.status_code = status
    if code is not None:
        err.code = code
    return err


def test_classify_connection_error_is_retryable():
    decision = _classify_error(APIConnectionError(request=None))
    assert decision.retry is True
    assert "网络" in decision.user_msg


def test_classify_5xx_is_retryable():
    decision = _classify_error(_make_status_error(500))
    assert decision.retry is True
    assert "服务" in decision.user_msg


def test_classify_4xx_audit_reject_is_terminal():
    decision = _classify_error(_make_status_error(400, "AuditReject"))
    assert decision.retry is False
    assert "拒绝" in decision.user_msg


def test_classify_4xx_arrearage_is_terminal():
    decision = _classify_error(_make_status_error(401, "Arrearage"))
    assert decision.retry is False
    assert "欠费" in decision.user_msg


def test_classify_4xx_generic_is_terminal():
    decision = _classify_error(_make_status_error(400))
    assert decision.retry is False


def test_classify_401_403_is_terminal_with_auth_msg():
    for s in (401, 403):
        decision = _classify_error(_make_status_error(s))
        assert decision.retry is False
        assert "鉴权" in decision.user_msg
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
pytest tests/test_doubao_normalizer.py -v
```

Expected: `ImportError: cannot import name '_classify_error' from 'app.doubao_normalizer'`.

- [ ] **Step 3: Implement `_classify_error`**

Append to `app/doubao_normalizer.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
pytest tests/test_doubao_normalizer.py -v
```

Expected: all 10 tests in the file pass.

- [ ] **Step 5: Commit**

```bash
git add app/doubao_normalizer.py tests/test_doubao_normalizer.py
git commit -m "feat(doubao): add _classify_error for retry decisions"
```

---

## Task 7: Implement `_call_once` helper (TDD)

**Files:**
- Modify: `app/doubao_normalizer.py`
- Modify: `tests/test_doubao_normalizer.py`

- [ ] **Step 1: Append the failing test**

Append to `tests/test_doubao_normalizer.py`:

```python
import base64
from unittest.mock import MagicMock

from openai import OpenAI

from app.doubao_normalizer import _call_once


def _fake_b64_response(b64_png: str) -> MagicMock:
    """Build a Mock that mimics the openai ImagesResponse shape we use."""
    resp = MagicMock()
    resp.data = [MagicMock(b64_json=b64_png, url=None)]
    return resp


def test_call_once_returns_decoded_bytes():
    b64 = base64.b64encode(b"fakepng").decode()
    client = MagicMock(spec=OpenAI)
    client.images.generate.return_value = _fake_b64_response(b64)

    out = _call_once(
        client=client,
        model="doubao-seedream-5-0-2 60128",
        prompt="do the thing",
        image_bytes=b"original",
    )
    assert out == b"fakepng"


def test_call_once_sends_image_as_data_url():
    b64 = base64.b64encode(b"fakepng").decode()
    client = MagicMock(spec=OpenAI)
    client.images.generate.return_value = _fake_b64_response(b64)

    _call_once(
        client=client,
        model="m",
        prompt="p",
        image_bytes=b"orig",
    )
    client.images.generate.assert_called_once()
    kwargs = client.images.generate.call_args.kwargs
    assert kwargs["model"] == "m"
    assert kwargs["prompt"] == "p"
    assert isinstance(kwargs["image"], list) and len(kwargs["image"]) == 1
    sent = kwargs["image"][0]
    assert sent.startswith("data:image/png;base64,")
    # Round-trip the base64 portion back to bytes
    payload = sent.split(",", 1)[1]
    assert base64.b64decode(payload) == b"orig"


def test_call_once_raises_when_no_b64_and_no_url():
    client = MagicMock(spec=OpenAI)
    resp = MagicMock()
    resp.data = [MagicMock(b64_json=None, url=None)]
    client.images.generate.return_value = resp

    with pytest.raises(DoubaoAPIError) as exc_info:
        _call_once(
            client=client, model="m", prompt="p", image_bytes=b"x"
        )
    assert "返回数据异常" in exc_info.value.user_msg


def test_call_once_raises_on_garbage_b64():
    client = MagicMock(spec=OpenAI)
    # Valid base64, but not valid PNG
    bad_b64 = base64.b64encode(b"not a png").decode()
    client.images.generate.return_value = _fake_b64_response(bad_b64)

    with pytest.raises(DoubaoAPIError) as exc_info:
        _call_once(
            client=client, model="m", prompt="p", image_bytes=b"x"
        )
    assert "返回数据异常" in exc_info.value.user_msg
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
pytest tests/test_doubao_normalizer.py -v -k call_once
```

Expected: `ImportError: cannot import name '_call_once' from 'app.doubao_normalizer'`.

- [ ] **Step 3: Implement `_call_once`**

Append to `app/doubao_normalizer.py`:

```python
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
    """One SDK call. Returns the cleaned PNG bytes.

    Raises DoubaoAPIError (terminal) for malformed responses. Propagates
    openai.* exceptions untouched so the caller (run) can classify and
    decide whether to retry.
    """
    b64 = base64.b64encode(image_bytes).decode()
    data_url = f"data:image/png;base64,{b64}"
    resp = client.images.generate(
        model=model,
        prompt=prompt,
        image=[data_url],
        size="auto",
        response_format="b64_json",
    )
    item = resp.data[0]
    out_b64 = getattr(item, "b64_json", None)
    if not out_b64:
        raise DoubaoAPIError(
            user_msg="返回数据异常",
            internal_msg="doubao response had no b64_json",
        )
    decoded = base64.b64decode(out_b64)
    # Cheap sanity check: PNG header
    if decoded[:4] != b"\x89PNG":
        raise DoubaoAPIError(
            user_msg="返回数据异常",
            internal_msg="doubao b64 decoded to non-PNG bytes",
        )
    return decoded
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
pytest tests/test_doubao_normalizer.py -v -k call_once
```

Expected: 4 passed (test_call_once_*).

- [ ] **Step 5: Commit**

```bash
git add app/doubao_normalizer.py tests/test_doubao_normalizer.py
git commit -m "feat(doubao): add _call_once for single Ark images.generate call"
```

---

## Task 8: Implement `run()` orchestrator with retry (TDD)

**Files:**
- Modify: `app/doubao_normalizer.py`
- Modify: `tests/test_doubao_normalizer.py`

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_doubao_normalizer.py`:

```python
import time
from unittest.mock import patch

import base64
from openai import APIConnectionError, OpenAI

from app.doubao_normalizer import run as doubao_run


def _valid_png_b64() -> str:
    return base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 16).decode()


def _ok_response() -> MagicMock:
    resp = MagicMock()
    resp.data = [MagicMock(b64_json=_valid_png_b64(), url=None)]
    return resp


# --- happy path ----------------------------------------------------------


def test_run_happy_path_writes_file_and_returns_bytes(tmp_path):
    client = MagicMock(spec=OpenAI)
    client.images.generate.return_value = _ok_response()
    with patch("app.doubao_normalizer.time.sleep"):  # never sleep on success
        result = doubao_run(
            image_bytes=b"orig",
            prompt="p",
            work_dir=tmp_path,
            api_key="ark-x",
            model="m",
            client=client,
        )
    assert isinstance(result, NormalizedImage)
    assert result.cleaned_bytes.startswith(b"\x89PNG")
    assert result.cleaned_path.exists()
    assert result.cleaned_path.read_bytes() == result.cleaned_bytes
    # Exactly one SDK call, no sleep
    assert client.images.generate.call_count == 1


# --- resize --------------------------------------------------------------


def test_run_resizes_input_before_calling_sdk(tmp_path):
    big = _make_png_bytes(5000, 3000)
    client = MagicMock(spec=OpenAI)
    client.images.generate.return_value = _ok_response()

    doubao_run(
        image_bytes=big,
        prompt="p",
        work_dir=tmp_path,
        api_key="ark-x",
        model="m",
        client=client,
    )
    # The bytes sent to Ark should be a resized PNG, <= 2048 on long edge
    kwargs = client.images.generate.call_args.kwargs
    sent = kwargs["image"][0]
    payload = base64.b64decode(sent.split(",", 1)[1])
    img = Image.open(io.BytesIO(payload))
    assert max(img.size) <= 2048


def test_run_does_not_resize_when_under_limit(tmp_path):
    small = _make_png_bytes(1000, 1000)
    client = MagicMock(spec=OpenAI)
    client.images.generate.return_value = _ok_response()

    doubao_run(
        image_bytes=small,
        prompt="p",
        work_dir=tmp_path,
        api_key="ark-x",
        model="m",
        client=client,
    )
    kwargs = client.images.generate.call_args.kwargs
    sent = kwargs["image"][0]
    payload = base64.b64decode(sent.split(",", 1)[1])
    assert payload == small  # bytes unchanged


# --- retry semantics -----------------------------------------------------


def test_run_retries_once_on_connection_error_then_succeeds(tmp_path):
    client = MagicMock(spec=OpenAI)
    client.images.generate.side_effect = [
        APIConnectionError(request=None),
        _ok_response(),
    ]
    with patch("app.doubao_normalizer.time.sleep") as mock_sleep:
        result = doubao_run(
            image_bytes=b"x", prompt="p", work_dir=tmp_path,
            api_key="k", model="m", client=client,
        )
    assert isinstance(result, NormalizedImage)
    assert client.images.generate.call_count == 2
    mock_sleep.assert_called_once_with(1.0)


def test_run_connection_error_two_strikes_raises(tmp_path):
    client = MagicMock(spec=OpenAI)
    client.images.generate.side_effect = [
        APIConnectionError(request=None),
        APIConnectionError(request=None),
    ]
    with patch("app.doubao_normalizer.time.sleep"):
        with pytest.raises(DoubaoAPIError) as exc_info:
            doubao_run(
                image_bytes=b"x", prompt="p", work_dir=tmp_path,
                api_key="k", model="m", client=client,
            )
    assert "网络" in exc_info.value.user_msg
    assert client.images.generate.call_count == 2


def test_run_4xx_no_retry_raises(tmp_path):
    client = MagicMock(spec=OpenAI)
    client.images.generate.side_effect = _make_status_error(400)
    with pytest.raises(DoubaoAPIError) as exc_info:
        doubao_run(
            image_bytes=b"x", prompt="p", work_dir=tmp_path,
            api_key="k", model="m", client=client,
        )
    assert client.images.generate.call_count == 1
    assert exc_info.value.user_msg == "请求被拒绝"


def test_run_audit_reject_no_retry_raises(tmp_path):
    client = MagicMock(spec=OpenAI)
    client.images.generate.side_effect = _make_status_error(400, "AuditReject")
    with pytest.raises(DoubaoAPIError) as exc_info:
        doubao_run(
            image_bytes=b"x", prompt="p", work_dir=tmp_path,
            api_key="k", model="m", client=client,
        )
    assert client.images.generate.call_count == 1
    assert "拒绝" in exc_info.value.user_msg


def test_run_arrearage_no_retry_raises(tmp_path):
    client = MagicMock(spec=OpenAI)
    client.images.generate.side_effect = _make_status_error(401, "Arrearage")
    with pytest.raises(DoubaoAPIError) as exc_info:
        doubao_run(
            image_bytes=b"x", prompt="p", work_dir=tmp_path,
            api_key="k", model="m", client=client,
        )
    assert "欠费" in exc_info.value.user_msg


def test_run_5xx_retries_once_then_succeeds(tmp_path):
    client = MagicMock(spec=OpenAI)
    client.images.generate.side_effect = [
        _make_status_error(500),
        _ok_response(),
    ]
    with patch("app.doubao_normalizer.time.sleep"):
        result = doubao_run(
            image_bytes=b"x", prompt="p", work_dir=tmp_path,
            api_key="k", model="m", client=client,
        )
    assert isinstance(result, NormalizedImage)
    assert client.images.generate.call_count == 2


def test_run_5xx_two_strikes_raises(tmp_path):
    client = MagicMock(spec=OpenAI)
    client.images.generate.side_effect = [
        _make_status_error(500),
        _make_status_error(500),
    ]
    with patch("app.doubao_normalizer.time.sleep"):
        with pytest.raises(DoubaoAPIError) as exc_info:
            doubao_run(
                image_bytes=b"x", prompt="p", work_dir=tmp_path,
                api_key="k", model="m", client=client,
            )
    assert "服务" in exc_info.value.user_msg
    assert client.images.generate.call_count == 2


def test_run_401_403_no_retry_raises(tmp_path):
    for s in (401, 403):
        client = MagicMock(spec=OpenAI)
        client.images.generate.side_effect = _make_status_error(s)
        with pytest.raises(DoubaoAPIError) as exc_info:
            doubao_run(
                image_bytes=b"x", prompt="p", work_dir=tmp_path,
                api_key="k", model="m", client=client,
            )
        assert client.images.generate.call_count == 1
        assert "鉴权" in exc_info.value.user_msg
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
pytest tests/test_doubao_normalizer.py -v -k run_
```

Expected: `ImportError: cannot import name 'run' from 'app.doubao_normalizer'`.

- [ ] **Step 3: Implement `run()`**

Append to `app/doubao_normalizer.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
pytest tests/test_doubao_normalizer.py -v
```

Expected: all tests in the file pass.

- [ ] **Step 5: Run the full suite**

Run:
```bash
pytest -q
```

Expected: all tests pass (existing tests in `test_handlers.py` and `test_config.py` should still pass — the new module is not yet wired in).

- [ ] **Step 6: Commit**

```bash
git add app/doubao_normalizer.py tests/test_doubao_normalizer.py
git commit -m "feat(doubao): add run() with one-shot retry on 5xx/connect"
```

---

## Task 9: Add `FeishuClient.upload_image_bytes` (TDD)

**Files:**
- Modify: `app/feishu_client.py`
- Modify: `tests/test_feishu_client.py`

- [ ] **Step 1: Read the existing test file to understand patterns**

Run:
```bash
cat tests/test_feishu_client.py
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_feishu_client.py`:

```python
def test_upload_image_bytes_returns_image_key(mocker):
    from app.feishu_client import FeishuClient

    fake_lark = mocker.MagicMock()
    fake_lark.im.v1.image.create.return_value = mocker.MagicMock(
        success=lambda: True,
        data=mocker.MagicMock(image_key="img_v2_cleaned"),
    )
    client = FeishuClient(fake_lark)
    key = client.upload_image_bytes(b"\x89PNG\r\n\x1a\nfakepng", ".png")
    assert key == "img_v2_cleaned"
    # Verify the SDK was called with a BytesIO-like body
    fake_lark.im.v1.image.create.assert_called_once()
```

- [ ] **Step 3: Run the test to verify it fails**

Run:
```bash
pytest tests/test_feishu_client.py -v -k upload_image_bytes
```

Expected: `AttributeError: <FeishuClient> has no attribute 'upload_image_bytes'`.

- [ ] **Step 4: Add the method to `app/feishu_client.py`**

Insert the new method right after the existing `upload_image` method (around line 87):

```python
    def upload_image_bytes(self, data: bytes, suffix: str) -> str:
        """Upload raw image bytes (e.g. cleaned PNG from Doubao) without
        requiring a path on disk. Returns the image_key."""
        if not suffix.startswith("."):
            raise ValueError(f"suffix must start with '.', got {suffix!r}")
        body = (
            CreateImageRequestBody.builder()
            .image_type("message")
            .image(io.BytesIO(data))
            .build()
        )
        req = CreateImageRequest.builder().request_body(body).build()
        resp = self._client.im.v1.image.create(req)
        if not resp.success() or resp.data is None:
            raise FeishuAPIError(
                f"upload_image_bytes failed: code={resp.code} msg={resp.msg}"
            )
        return resp.data.image_key
```

Add `import io` at the top of the file if not already present.

- [ ] **Step 5: Run the test to verify it passes**

Run:
```bash
pytest tests/test_feishu_client.py -v -k upload_image_bytes
```

Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add app/feishu_client.py tests/test_feishu_client.py
git commit -m "feat(feishu): add upload_image_bytes for in-memory PNG upload"
```

---

## Task 10: Change `send_post_message` signature to `image_keys` list (TDD)

**Files:**
- Modify: `app/feishu_client.py`
- Modify: `tests/test_feishu_client.py`

- [ ] **Step 1: Update the existing test to match the new signature**

In `tests/test_feishu_client.py`, find the test(s) that exercise `send_post_message` and update the kwarg from `image_key=` to `image_keys=` (passing a list of one element). The new public signature is:

```python
def send_post_message(
    self,
    *,
    receive_id: str,
    receive_id_type: str,
    text: str,
    image_keys: list[str] | None = None,
    file_key: str | None = None,
) -> None: ...
```

For each test that calls `client.send_post_message(..., image_key=...)`, change to `image_keys=[...]`.

- [ ] **Step 2: Add a new test for the two-image case**

Append to `tests/test_feishu_client.py`:

```python
def test_send_post_message_with_two_images(mocker):
    from app.feishu_client import FeishuClient

    fake_lark = mocker.MagicMock()
    fake_lark.im.v1.message.create.return_value = mocker.MagicMock(success=lambda: True)
    client = FeishuClient(fake_lark)

    client.send_post_message(
        receive_id="oc_chat",
        receive_id_type="chat_id",
        text="done",
        image_keys=["img_cleaned", "img_preview"],
        file_key="file_dxf",
    )
    fake_lark.im.v1.message.create.assert_called_once()
    # Verify both image_keys made it into the JSON content
    call = fake_lark.im.v1.message.create.call_args
    body = call.kwargs["request_body"]
    # The body holds the JSON string under .content
    import json as _json
    content = _json.loads(body.content)
    paragraphs = content["zh_cn"]["content"]
    # Expect: [[text], [img cleaned], [img preview], [media dxf]]
    img_paragraphs = [p for p in paragraphs if p and p[0].get("tag") == "img"]
    img_keys = [p[0]["image_key"] for p in img_paragraphs]
    assert img_keys == ["img_cleaned", "img_preview"]
```

- [ ] **Step 3: Run the test to verify it fails**

Run:
```bash
pytest tests/test_feishu_client.py -v -k send_post_message
```

Expected: at least one test fails with `TypeError: send_post_message() got an unexpected keyword argument 'image_keys'` (or the old test fails because it still passes `image_key=...`).

- [ ] **Step 4: Update `send_post_message` and `_build_post_content` in `app/feishu_client.py`**

Replace the `send_post_message` method (around line 104) and its helper:

```python
    def send_post_message(
        self,
        *,
        receive_id: str,
        receive_id_type: str,
        text: str,
        image_keys: list[str] | None = None,
        file_key: str | None = None,
    ) -> None:
        """Send a single 'post' (rich text) message with up to N inline images
        plus an optional file attachment.

        ``receive_id_type`` is one of ``chat_id``, ``open_id``, ``user_id``,
        ``email`` — exactly as Feishu's API expects.
        """
        content = self._build_post_content(
            text=text, image_keys=image_keys, file_key=file_key
        )
        body = (
            CreateMessageRequestBody.builder()
            .receive_id(receive_id)
            .msg_type("post")
            .content(json.dumps(content, ensure_ascii=False))
            .build()
        )
        req = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(body)
            .build()
        )
        resp = self._client.im.v1.message.create(req)
        if not resp.success():
            raise FeishuAPIError(f"send_post_message failed: code={resp.code} msg={resp.msg}")

    @staticmethod
    def _build_post_content(
        *,
        text: str,
        image_keys: list[str] | None,
        file_key: str | None,
    ) -> dict:
        """Assemble a Feishu post-message content body.

        A post payload is a list of paragraphs; each paragraph is a list of
        inline elements (text / img / media / file / link). Files appear via
        ``media`` (Feishu's file slot in post messages). Multiple images
        are rendered as separate paragraphs in the order given.
        """
        paragraphs: list[list[dict]] = [[{"tag": "text", "text": text}]]
        for key in image_keys or []:
            paragraphs.append([{"tag": "img", "image_key": key}])
        if file_key:
            paragraphs.append([{"tag": "media", "file_key": file_key}])
        return {"zh_cn": {"title": "转换结果", "content": paragraphs}}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:
```bash
pytest tests/test_feishu_client.py -v
```

Expected: all pass.

- [ ] **Step 6: Run the existing `test_handlers.py` to see what broke**

Run:
```bash
pytest tests/test_handlers.py -v
```

Expected: existing tests that reference `kwargs["image_key"]` will fail with `KeyError: 'image_key'`. This is expected and will be fixed in Task 11. Do not commit yet.

- [ ] **Step 7: Commit the feishu_client change only**

```bash
git add app/feishu_client.py tests/test_feishu_client.py
git commit -m "refactor(feishu): send_post_message accepts image_keys list"
```

---

## Task 11: Wire `doubao_normalizer` into `handle_dxf_request` (TDD)

**Files:**
- Modify: `app/handlers.py`
- Modify: `app/main.py` (pass config to handler)
- Modify: `tests/test_handlers.py` (adapt to new signature/kwargs)
- Create: `tests/test_handlers_doubao_integration.py`

- [ ] **Step 1: Read the current `handle_dxf_request` signature in `app/main.py`**

(Confirmed in prior reading: `executor.submit(handle_dxf_request, parsed=parsed, feishu=feishu, work_dir=work_dir)`. The handler currently takes 3 kwargs; we need to add a 4th: the `Config` (or just the two `ark_*` fields).)

- [ ] **Step 2: Add the failing integration test for the happy path**

Create `tests/test_handlers_doubao_integration.py`:

```python
"""Handler-level tests covering the Doubao normalization step."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import converter, doubao_normalizer, handlers, preview
from app.handlers import handle_dxf_request, parse_slash_command_event


def _make_event(*, image_key: str = "img_v2_abc") -> dict:
    return {
        "header": {"event_type": "application.bot.menu_v6"},
        "event": {
            "message_id": "om_msg_1",
            "chat_id": "oc_chat_1",
            "chat_type": "p2p",
            "sender": {"sender_id": {"open_id": "ou_user_1"}},
            "message": {
                "message_id": "om_msg_1",
                "chat_id": "oc_chat_1",
                "chat_type": "p2p",
                "message_type": "image",
                "content": '{"image_key": "%s"}' % image_key,
            },
        },
    }


@pytest.fixture
def fake_doubao_ok(mocker, tmp_path):
    """Patch doubao_normalizer.run to return a fixed small PNG."""
    cleaned_path = tmp_path / "normalized.png"
    cleaned_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 16)
    fake = MagicMock()
    fake.cleaned_bytes = cleaned_path.read_bytes()
    fake.cleaned_path = cleaned_path
    mocker.patch.object(handlers.doubao_normalizer, "run", return_value=fake)
    return fake


@pytest.fixture
def fake_doubao_fail(mocker):
    from app.doubao_normalizer import DoubaoAPIError

    err = DoubaoAPIError(user_msg="网络问题", internal_msg="boom")
    mocker.patch.object(handlers.doubao_normalizer, "run", side_effect=err)


@pytest.fixture
def fake_converter(mocker, tmp_path):
    fake_result = converter.ConversionResult(
        dxf_path=tmp_path / "out.dxf", shape_count=5
    )
    mocker.patch.object(handlers.converter, "run", return_value=fake_result)


@pytest.fixture
def fake_preview(mocker, tmp_path):
    preview_path = tmp_path / "preview.png"
    preview_path.write_bytes(b"\x89PNG")
    mocker.patch.object(handlers.preview, "render", return_value=preview_path)


def _settings(**overrides):
    from app.config import Config

    base = dict(
        app_id="cli_x",
        app_secret="secret",
        log_level="INFO",
        health_port=8080,
        work_dir="/tmp/x",
        convert_timeout_s=60,
        max_workers=3,
        ark_api_key="ark-test",
        ark_model="doubao-seedream-5-0-2 60128",
    )
    base.update(overrides)
    return Config(**base)


def test_happy_path_passes_cleaned_key_to_post(
    mocker, fake_doubao_ok, fake_converter, fake_preview
):
    fake_feishu = mocker.Mock()
    fake_feishu.download_image.return_value = b"original"
    fake_feishu.upload_file.return_value = "file_key_dxf"
    fake_feishu.upload_image.return_value = "image_key_preview"
    fake_feishu.upload_image_bytes.return_value = "image_key_cleaned"

    handle_dxf_request(
        parsed=parse_slash_command_event(_make_event()),
        feishu=fake_feishu,
        work_dir=mocker.Mock(),
        settings=_settings(),
    )

    # The cleaned image key was uploaded and forwarded to the post
    fake_feishu.upload_image_bytes.assert_called_once()
    fake_feishu.send_post_message.assert_called_once()
    kwargs = fake_feishu.send_post_message.call_args.kwargs
    assert kwargs["image_keys"] == ["image_key_cleaned", "image_key_preview"]
    assert kwargs["file_key"] == "file_key_dxf"


def test_doubao_failure_replies_and_skips_converter(
    mocker, fake_doubao_fail
):
    fake_feishu = mocker.Mock()
    fake_feishu.download_image.return_value = b"original"

    handle_dxf_request(
        parsed=parse_slash_command_event(_make_event()),
        feishu=fake_feishu,
        work_dir=mocker.Mock(),
        settings=_settings(),
    )

    texts = [c.args[1] for c in fake_feishu.reply_text.call_args_list]
    assert any("AI 标准化失败" in t for t in texts)
    assert any("网络问题" in t for t in texts)
    fake_feishu.send_post_message.assert_not_called()


def test_doubao_ok_but_converter_fails(
    mocker, fake_doubao_ok, fake_preview
):
    from app import handlers

    mocker.patch.object(
        handlers.converter, "run", side_effect=FileNotFoundError("bad")
    )
    fake_feishu = mocker.Mock()
    fake_feishu.download_image.return_value = b"original"

    handle_dxf_request(
        parsed=parse_slash_command_event(_make_event()),
        feishu=fake_feishu,
        work_dir=mocker.Mock(),
        settings=_settings(),
    )

    fake_feishu.send_post_message.assert_not_called()


def test_doubao_ok_but_upload_cleaned_fails(
    mocker, fake_doubao_ok, fake_converter, fake_preview
):
    from app.feishu_client import FeishuAPIError

    fake_feishu = mocker.Mock()
    fake_feishu.download_image.return_value = b"original"
    fake_feishu.upload_image_bytes.side_effect = FeishuAPIError("nope")

    handle_dxf_request(
        parsed=parse_slash_command_event(_make_event()),
        feishu=fake_feishu,
        work_dir=mocker.Mock(),
        settings=_settings(),
    )

    texts = [c.args[1] for c in fake_feishu.reply_text.call_args_list]
    assert any("清理后图片上传失败" in t for t in texts)
    fake_feishu.send_post_message.assert_not_called()
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run:
```bash
pytest tests/test_handlers_doubao_integration.py -v
```

Expected: `TypeError: handle_dxf_request() got an unexpected keyword argument 'settings'` (or `AttributeError: module 'app.handlers' has no attribute 'doubao_normalizer'`).

- [ ] **Step 4: Modify `app/handlers.py`**

Replace the file contents with:

```python
"""Slash command handlers.

The single public entry point is :func:`handle_dxf_request`. It is invoked
once per ``/dxf`` event off the main thread (lark-oapi dispatches into a
worker pool). All filesystem side effects happen inside the supplied
``work_dir``; cleanup is the orchestrator's responsibility, not ours.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import converter, doubao_normalizer, doubao_prompt, preview
from .config import Config
from .doubao_normalizer import DoubaoAPIError
from .feishu_client import FeishuAPIError, FeishuClient


class NoImageError(ValueError):
    """The event carried no image attachment."""


@dataclass(frozen=True)
class ParsedSlashCommand:
    """The fields we care about, after parsing the raw event dict."""

    image_key: str
    message_id: str
    chat_id: str
    receive_id_type: str  # always 'chat_id' in v1


def parse_slash_command_event(event: dict) -> ParsedSlashCommand:
    """Extract the fields the handler needs from a Feishu slash-command event.

    Raises NoImageError if the underlying message is not an image.
    """
    event_dict = event.get("event", {})
    msg = event_dict.get("message", {})
    if msg.get("message_type") != "image":
        raise NoImageError("message is not an image")
    content_raw = msg.get("content", "{}")
    try:
        content = json.loads(content_raw)
    except json.JSONDecodeError as e:
        raise NoImageError(f"content is not valid JSON: {e}") from e
    image_key = content.get("image_key")
    if not image_key:
        raise NoImageError("no image_key in content")
    return ParsedSlashCommand(
        image_key=image_key,
        message_id=msg.get("message_id") or event_dict.get("message_id", ""),
        chat_id=msg.get("chat_id") or event_dict.get("chat_id", ""),
        receive_id_type="chat_id",
    )


def handle_dxf_request(
    *,
    parsed: ParsedSlashCommand,
    feishu: FeishuClient,
    work_dir: Path,
    settings: Config,
) -> None:
    """Handle one ``/dxf`` slash command.

    Steps:
        1. Reply "正在处理..."
        2. Download image bytes
        3. Normalize via Doubao (with internal retry, raises DoubaoAPIError
           on terminal failure)
        4. Reply "正在转换 DXF..."
        5. Upload cleaned image
        6. Convert to DXF (creates work_dir / input.png and out.dxf)
        7. Render preview PNG
        8. Upload DXF, upload preview
        9. Send single post message with [cleaned image, preview, DXF]
    Errors at any step reply with a short Chinese message; nothing raises
    out of this function.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        feishu.reply_text(parsed.message_id, "正在处理...")
        try:
            image_bytes = feishu.download_image(parsed.image_key)
        except FeishuAPIError:
            feishu.reply_text(parsed.message_id, "图片下载失败,请重试")
            return

        feishu.reply_text(parsed.message_id, "正在清理图片...")
        try:
            normalized = doubao_normalizer.run(
                image_bytes=image_bytes,
                prompt=doubao_prompt.DEFAULT_PROMPT,
                work_dir=work_dir,
                api_key=settings.ark_api_key,
                model=settings.ark_model,
            )
        except DoubaoAPIError as e:
            feishu.reply_text(
                parsed.message_id, f"AI 标准化失败: {e.user_msg}，请重试"
            )
            return

        feishu.reply_text(parsed.message_id, "正在转换 DXF...")
        try:
            cleaned_key = feishu.upload_image_bytes(
                normalized.cleaned_bytes, ".png"
            )
        except FeishuAPIError:
            feishu.reply_text(parsed.message_id, "清理后图片上传失败,请重试")
            return

        try:
            conv = converter.run(
                image_bytes=normalized.cleaned_bytes,
                image_suffix=".png",
                out_dxf_path=work_dir / "output.dxf",
                work_dir=work_dir,
            )
        except FileNotFoundError:
            feishu.reply_text(parsed.message_id, "无法读取图片,可能格式损坏")
            return

        # Preview is best-effort; failure here only logs a warning.
        preview_key: str | None = None
        try:
            preview_path = preview.render(conv.dxf_path, work_dir / "preview.png")
            preview_key = feishu.upload_image(preview_path)
        except Exception:  # noqa: BLE001 - preview is optional
            preview_key = None

        try:
            file_key = feishu.upload_file(conv.dxf_path)
        except FeishuAPIError:
            feishu.reply_text(parsed.message_id, "DXF 上传失败,稍后再试")
            return

        summary = f"转换成功 ({conv.shape_count} 个轮廓)"
        try:
            feishu.send_post_message(
                receive_id=parsed.chat_id,
                receive_id_type=parsed.receive_id_type,
                text=summary,
                image_keys=[cleaned_key, preview_key] if preview_key else [cleaned_key],
                file_key=file_key,
            )
        except FeishuAPIError:
            # Last-resort: user gets no reply but DXF was uploaded; not retrying.
            return
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def make_work_dir(base: Path) -> Path:
    """Create a per-request work directory with a UUID suffix.

    Helper exposed so the orchestrator (app.main) can pre-create the dir
    before scheduling work.
    """
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    return base / uuid.uuid4().hex
```

- [ ] **Step 5: Update `app/main.py` to pass `cfg` to the handler**

In `app/main.py`, modify the `_make_message_handler` function. Replace the `executor.submit(...)` line with:

```python
        work_dir = make_work_dir(Path(cfg.work_dir))
        executor.submit(
            handle_dxf_request,
            parsed=parsed,
            feishu=feishu,
            work_dir=work_dir,
            settings=cfg,
        )
```

(Keep all other lines of `_make_message_handler` unchanged.)

- [ ] **Step 6: Update `tests/test_handlers.py` to match the new signature**

In `tests/test_handlers.py`, add this fixture near the top:

```python
import pytest

from app.config import Config


@pytest.fixture
def settings() -> Config:
    return Config(
        app_id="cli_x",
        app_secret="secret",
        log_level="INFO",
        health_port=8080,
        work_dir="/tmp/x",
        convert_timeout_s=60,
        max_workers=3,
        ark_api_key="ark-test",
        ark_model="doubao-seedream-5-0-2 60128",
    )
```

Then update each call to `handle_dxf_request` in the file:

- In `test_handle_dxf_happy_path`, add the `doubao_normalizer` mock **and** pass `settings`:
  ```python
  from app import converter, doubao_normalizer, handlers, preview

  fake_norm = doubao_normalizer.NormalizedImage(
      cleaned_bytes=sample_jpg.read_bytes(),
      cleaned_path=tmp_path / "wd" / "normalized.png",
  )
  mocker.patch.object(handlers.doubao_normalizer, "run", return_value=fake_norm)
  fake_feishu.upload_image_bytes.return_value = "image_key_cleaned"
  fake_feishu.upload_image.return_value = "image_key_preview"
  fake_feishu.upload_file.return_value = "file_key_dxf"
  fake_result = converter.ConversionResult(dxf_path=tmp_path / "out.dxf", shape_count=5)
  mocker.patch.object(handlers.converter, "run", return_value=fake_result)
  mocker.patch.object(handlers.preview, "render", return_value=tmp_path / "preview.png")

  handle_dxf_request(
      parsed=parse_slash_command_event(_make_event()),
      feishu=fake_feishu,
      work_dir=tmp_path / "wd",
      settings=settings,
  )

  # Update assertions
  assert fake_feishu.send_post_message.call_args.kwargs["image_keys"] == [
      "image_key_cleaned", "image_key_preview"
  ]
  assert fake_feishu.send_post_message.call_args.kwargs["file_key"] == "file_key_dxf"
  ```
  And change the existing assertion `assert kwargs["image_key"] == "image_key_preview"` to the `image_keys` assertion above.

- In `test_handle_dxf_no_image_replies_with_hint`, add `settings=settings` and remove the `parsed=...` call style (it raises upstream; the handler isn't reached — add `settings` to the call).
- In `test_handle_dxf_conversion_failure_replies_error`, mock `doubao_normalizer.run` to return a fake `NormalizedImage`, add `settings=settings`.
- In `test_handle_dxf_preview_failure_still_sends_dxf`, mock `doubao_normalizer.run`, add `settings=settings`, change the `kwargs["image_key"] is None` assertion to `kwargs["image_keys"] == ["image_key_cleaned"]`.

(Exact code for each existing test shown in the diff below.)

Edit `tests/test_handlers.py` to look like this (full replacement, not a patch):

```python
"""Tests for app.handlers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import converter, doubao_normalizer, handlers, preview
from app.config import Config
from app.handlers import (
    NoImageError,
    handle_dxf_request,
    parse_slash_command_event,
)


def _make_event(*, image_key: str = "img_v2_abc") -> dict:
    return {
        "header": {"event_type": "application.bot.menu_v6"},
        "event": {
            "message_id": "om_msg_1",
            "chat_id": "oc_chat_1",
            "chat_type": "p2p",
            "sender": {"sender_id": {"open_id": "ou_user_1"}},
            "message": {
                "message_id": "om_msg_1",
                "chat_id": "oc_chat_1",
                "chat_type": "p2p",
                "message_type": "image",
                "content": '{"image_key": "%s"}' % image_key,
            },
        },
    }


@pytest.fixture
def settings() -> Config:
    return Config(
        app_id="cli_x",
        app_secret="secret",
        log_level="INFO",
        health_port=8080,
        work_dir="/tmp/x",
        convert_timeout_s=60,
        max_workers=3,
        ark_api_key="ark-test",
        ark_model="doubao-seedream-5-0-2 60128",
    )


def test_parse_extracts_image_key_and_recipient():
    event = _make_event()
    parsed = parse_slash_command_event(event)
    assert parsed.image_key == "img_v2_abc"
    assert parsed.message_id == "om_msg_1"
    assert parsed.chat_id == "oc_chat_1"
    assert parsed.receive_id_type == "chat_id"


def test_parse_raises_when_no_image():
    event = _make_event()
    event["event"]["message"]["message_type"] = "text"
    event["event"]["message"]["content"] = '{"text": "hello"}'
    with pytest.raises(NoImageError):
        parse_slash_command_event(event)


def test_handle_dxf_happy_path(mocker, sample_jpg: Path, tmp_path: Path, settings):
    fake_feishu = mocker.Mock()
    fake_feishu.download_image.return_value = sample_jpg.read_bytes()
    fake_feishu.upload_file.return_value = "file_key_dxf"
    fake_feishu.upload_image.return_value = "image_key_preview"
    fake_feishu.upload_image_bytes.return_value = "image_key_cleaned"

    cleaned_path = tmp_path / "wd" / "normalized.png"
    cleaned_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_norm = doubao_normalizer.NormalizedImage(
        cleaned_bytes=cleaned_path.read_bytes(), cleaned_path=cleaned_path,
    )
    mocker.patch.object(handlers.doubao_normalizer, "run", return_value=fake_norm)

    fake_result = converter.ConversionResult(dxf_path=tmp_path / "out.dxf", shape_count=5)
    mocker.patch.object(handlers.converter, "run", return_value=fake_result)
    mocker.patch.object(handlers.preview, "render", return_value=tmp_path / "preview.png")

    event = _make_event()
    parsed = parse_slash_command_event(event)
    handle_dxf_request(
        parsed=parsed,
        feishu=fake_feishu,
        work_dir=tmp_path / "wd",
        settings=settings,
    )

    # Progress: at least 3 reply_text calls
    assert fake_feishu.reply_text.call_count >= 3
    fake_feishu.download_image.assert_called_once_with("img_v2_abc")
    handlers.doubao_normalizer.run.assert_called_once()
    handlers.converter.run.assert_called_once()
    fake_feishu.upload_image_bytes.assert_called_once()
    fake_feishu.upload_file.assert_called_once()
    fake_feishu.upload_image.assert_called_once()
    fake_feishu.send_post_message.assert_called_once()
    kwargs = fake_feishu.send_post_message.call_args.kwargs
    assert kwargs["receive_id"] == "oc_chat_1"
    assert kwargs["file_key"] == "file_key_dxf"
    assert kwargs["image_keys"] == ["image_key_cleaned", "image_key_preview"]


def test_handle_dxf_no_image_replies_with_hint(mocker, settings):
    fake_feishu = mocker.Mock()
    with pytest.raises(NoImageError):
        handle_dxf_request(
            parsed=parse_slash_command_event(_make_event(image_key="")),
            feishu=fake_feishu,
            work_dir=mocker.Mock(),
            settings=settings,
        )
    fake_feishu.reply_text.assert_not_called()


def test_handle_dxf_conversion_failure_replies_error(
    mocker, sample_jpg: Path, tmp_path: Path, settings
):
    fake_feishu = mocker.Mock()
    fake_feishu.download_image.return_value = sample_jpg.read_bytes()
    cleaned_path = tmp_path / "wd" / "normalized.png"
    cleaned_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_norm = doubao_normalizer.NormalizedImage(
        cleaned_bytes=cleaned_path.read_bytes(), cleaned_path=cleaned_path,
    )
    mocker.patch.object(handlers.doubao_normalizer, "run", return_value=fake_norm)
    mocker.patch.object(
        handlers.converter, "run", side_effect=FileNotFoundError("bad image")
    )

    event = _make_event()
    parsed = parse_slash_command_event(event)
    handle_dxf_request(
        parsed=parsed,
        feishu=fake_feishu,
        work_dir=tmp_path / "wd",
        settings=settings,
    )

    texts = [c.args[1] for c in fake_feishu.reply_text.call_args_list]
    assert any("正在处理" in t for t in texts)
    assert any("失败" in t or "无法" in t for t in texts)
    fake_feishu.send_post_message.assert_not_called()


def test_handle_dxf_preview_failure_still_sends_dxf(
    mocker, sample_jpg: Path, tmp_path: Path, settings
):
    """If preview rendering fails, the bot should still send the cleaned image
    and the DXF."""
    fake_feishu = mocker.Mock()
    fake_feishu.download_image.return_value = sample_jpg.read_bytes()
    fake_feishu.upload_file.return_value = "file_key_dxf"
    fake_feishu.upload_image_bytes.return_value = "image_key_cleaned"

    cleaned_path = tmp_path / "wd" / "normalized.png"
    cleaned_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_norm = doubao_normalizer.NormalizedImage(
        cleaned_bytes=cleaned_path.read_bytes(), cleaned_path=cleaned_path,
    )
    mocker.patch.object(handlers.doubao_normalizer, "run", return_value=fake_norm)

    fake_result = converter.ConversionResult(dxf_path=tmp_path / "out.dxf", shape_count=3)
    mocker.patch.object(handlers.converter, "run", return_value=fake_result)
    mocker.patch.object(handlers.preview, "render", side_effect=RuntimeError("render fail"))

    event = _make_event()
    parsed = parse_slash_command_event(event)
    handle_dxf_request(
        parsed=parsed,
        feishu=fake_feishu,
        work_dir=tmp_path / "wd",
        settings=settings,
    )

    fake_feishu.upload_image.assert_not_called()
    fake_feishu.send_post_message.assert_called_once()
    kwargs = fake_feishu.send_post_message.call_args.kwargs
    assert kwargs["image_keys"] == ["image_key_cleaned"]
    assert kwargs["file_key"] == "file_key_dxf"
```

- [ ] **Step 7: Run all tests**

Run:
```bash
pytest -v
```

Expected: all pass — both the new `test_handlers_doubao_integration.py` and the adapted `test_handlers.py`.

- [ ] **Step 8: Run a quick smoke import of the live app**

Run:
```bash
FEISHU_APP_ID=cli_x FEISHU_APP_SECRET=y ARK_API_KEY=ark-x python -c "from app.main import main; print('imports ok')"
```

Expected: prints `imports ok` and exits 0.

- [ ] **Step 9: Commit**

```bash
git add app/handlers.py app/main.py tests/test_handlers.py tests/test_handlers_doubao_integration.py
git commit -m "feat(handlers): run Doubao normalization step in /dxf pipeline"
```

---

## Task 12: Update deploy config (docker-compose.yml, .env.example, Dockerfile, README)

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Add ARK env to `docker-compose.yml`**

In `docker-compose.yml`, add a new `environment:` section under `services.bot`. If one already exists, add to it; if not, add the whole block:

```yaml
    environment:
      ARK_API_KEY: ${ARK_API_KEY:?ARK_API_KEY is required}
      ARK_MODEL: ${ARK_MODEL:-doubao-seedream-5-0-2 60128}
```

(`docker-compose.yml` reads `.env` via `env_file`, so these `environment:` lines just export the same vars explicitly for fail-fast visibility.)

- [ ] **Step 2: Add ARK env to `.env.example`**

Append to `.env.example`:

```
ARK_API_KEY=ark-your-key-here
# ARK_MODEL=doubao-seedream-5-0-2 60128
```

- [ ] **Step 3: Add an ARK section to `README.md`**

Insert a new section "Volcengine Ark (Doubao) setup" right after "Feishu console setup", with this content:

```markdown
## Volcengine Ark (Doubao) setup

The bot calls Volcengine Ark's image generation API on every `/dxf` to
normalize the input image. One-time setup:

1. Open https://console.volcengine.com/ark/region:cn-beijing and create an
   API key with access to the `doubao-seedream-5-0-2 60128` model.
2. Copy the key into `.env` as `ARK_API_KEY=ark-...`.
3. (Optional) Override the model id with `ARK_MODEL=...` in `.env`.
4. Restart the bot: `docker compose restart bot`.

Each `/dxf` request uses one image generation call. The first failed call
is retried automatically; on a second failure the bot replies with the
underlying reason (network / auth / 5xx / 4xx / content-rejected) and does
not produce a DXF.
```

- [ ] **Step 4: Update README manual test checklist**

Append to the manual checklist in `README.md`:

```markdown
- [ ] Send `/dxf` + a clear logo → reply has [cleaned image, preview, DXF]
- [ ] Send `/dxf` + a blurry tilted logo → cleaned image is straightened, B/W
- [ ] Disable network → user message mentions "网络问题" and no DXF
- [ ] Set `ARK_MODEL=does-not-exist` → user message mentions model error
- [ ] Set `ARK_API_KEY=invalid` → user message "鉴权失败"
```

- [ ] **Step 5: Verify no `pip` install is required at the build step**

Read `Dockerfile` and confirm that `openai` will be installed when the
image is rebuilt (i.e. either it runs `pip install .` or `pip install -r`
against a requirements file that pulls from `pyproject.toml`).

If `Dockerfile` uses `pip install .` (installs from `pyproject.toml`):
no change needed.

If it uses `pip install -r requirements.txt`:
also add `openai>=1.40` to `requirements.txt` (or whichever pinned
requirements file `Dockerfile` consumes). Show the file's diff:

```diff
+openai>=1.40
```

- [ ] **Step 6: Run the full test suite one more time**

Run:
```bash
pytest -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml .env.example README.md Dockerfile requirements.txt
git commit -m "build(docker): expose ARK_API_KEY/ARK_MODEL; document setup"
```

---

## Task 13: Final verification (full suite + smoke)

**Files:** none new; this is a verification task.

- [ ] **Step 1: Run the full pytest suite**

Run:
```bash
cd /Users/yang362323/projects/feishu-laser-dxf-bot
source .venv/bin/activate
pytest -v
```

Expected: every test passes. Specifically:
- `test_doubao_prompt.py` — 2 passed
- `test_doubao_normalizer.py` — 20+ passed (resize, classify, call_once, run)
- `test_handlers_doubao_integration.py` — 4 passed
- `test_handlers.py` — all adapted tests pass
- `test_config.py` — 4 new + existing pass
- `test_feishu_client.py` — `upload_image_bytes` + 2-image post pass
- `test_converter.py`, `test_preview.py` — still pass (untouched)

- [ ] **Step 2: Confirm zero regressions in `git diff`**

Run:
```bash
git diff main..HEAD --stat
```

Expected: changes touch only the files listed in the File Structure table.

- [ ] **Step 3: Build the Docker image to confirm no missing dep**

Run:
```bash
docker build -t feishu-laser-dxf-bot:dev .
```

Expected: build succeeds; `openai` is installed in the image.

- [ ] **Step 4: Smoke-test the health endpoint with fake creds**

Run:
```bash
FEISHU_APP_ID=cli_x FEISHU_APP_SECRET=y ARK_API_KEY=ark-x \
  python -m app.main &
APP_PID=$!
sleep 3
curl -fsS http://localhost:8080/healthz
echo
kill $APP_PID
```

Expected: `{"status":"ok"}` printed; then process killed cleanly.

- [ ] **Step 5: Hand off for user acceptance testing**

Tell the user:

> "Implementation is complete and all tests pass. Before merging, please:
> 1. Set a real `ARK_API_KEY` in `.env` and send a test `/dxf` from Feishu
> 2. Verify the reply has [cleaned image, preview, DXF] in that order
> 3. Verify the manual checklist items in the README
> 4. If everything looks good, merge and deploy via `docker compose up -d --build`"

---

## Self-Review Notes

**Spec coverage** (each spec ID traced to a Task):

| Spec ID | Task |
|---|---|
| F1 (auto normalize) | Task 11 |
| F2 (DEFAULT_PROMPT) | Task 2 |
| F3 (cleaned image first) | Task 11 |
| F4 (reply order) | Task 11 |
| F5 (retry once) | Tasks 6, 7, 8 |
| F6 (progress text) | Task 11 |
| F7 (skip 2nd progress when fast) | Deferred — message spam risk is low; not blocking |
| F8 (no user content in prompt) | Task 2 (constant only) |
| F9 (existing F1-F8 still satisfied) | Task 11 |
| N1 (env vars) | Task 3 |
| N2 (default model) | Task 3 |
| N3 (openai in deps) | Task 1 |
| N4 (timeouts) | Task 7 |
| N5 (resize 2048) | Task 5 |
| N6 (byte-in/bytes-out) | Task 8 |
| N7 (existing N1-N7) | Tasks 3, 11 |
| N8 (work_dir cleanup) | Task 11 |

**F7 is intentionally deferred** — the "skip 2nd progress when <3s elapsed" rule
adds a `time.monotonic()` call and a branch in `handlers.py` for marginal value
(messages are cheap). If the user wants it, add it as a 2-line follow-up.

**Placeholder scan:** None. Every step has concrete code or commands.

**Type consistency:**
- `NormalizedImage(cleaned_bytes: bytes, cleaned_path: Path)` — defined Task 4, used Tasks 8, 11
- `DoubaoAPIError(user_msg, internal_msg)` — defined Task 4, raised Tasks 6, 7, 8; caught Task 11
- `send_post_message(... image_keys: list[str] | None ...)` — defined Task 10, called Tasks 10, 11
- `FeishuClient.upload_image_bytes(data: bytes, suffix: str) -> str` — defined Task 9, called Task 11
- `Config(ark_api_key: str, ark_model: str)` — defined Task 3, passed to `handle_dxf_request` in Task 11
- `run(*, image_bytes, prompt, work_dir, api_key, model, client=None)` — defined Task 8, called Task 11
