# Feishu Laser DXF Bot — Doubao Image Normalization

**Date:** 2026-06-24
**Status:** Draft, awaiting user approval
**Target repo:** `~/projects/feishu-laser-dxf-bot/`
**Depends on:**
- `~/projects/feishu-laser-dxf-bot/` (this project, MIT)
- `~/image-to-laser-dxf` (local Python package, MIT)
- Volcengine Ark Images API (`https://ark.cn-beijing.volces.com/api/v3`), OpenAI-compatible
- Model: `doubao-seedream-5-0-2 60128`

## 1. Purpose & Scope

Insert an AI-driven image normalization step into the existing
`feishu-laser-dxf-bot` `/dxf` pipeline. Before the image is handed to
`image_to_dxf.convert`, the bot sends it to Volcengine Ark's Doubao image
generation model with a **fixed Chinese prompt** that asks the model to:

1. 提高图片清晰度
2. 把图片的 logo 摆正
3. 把图片中的 logo 改为纯黑色
4. 把背景改成纯白

The cleaned image is then used as the input to the existing DXF pipeline. The
cleaned image is also uploaded to Feishu and shown in the reply message so the
user can verify the AI did not mangle the input.

**Use case:** the same small lab team (2–5 users) on the same single cloud
server. No public exposure, no new permissions, no new secret storage path.

**Out of scope (v1):**
- User-selectable normalization prompt (the prompt is fixed by spec)
- Per-user opt-in/out toggle (normalization is automatic on every `/dxf`)
- Fallback to the original image when Doubao fails (the spec is: retry once,
  then return an error)
- Multi-image or batch processing
- Cost accounting or rate limiting beyond Ark's own quotas
- Caching of normalized images

## 2. Requirements

### Functional

| ID | Requirement |
|----|-------------|
| F1 | Every `/dxf` request automatically runs the input image through Doubao normalization before `image_to_dxf.convert`. |
| F2 | The Doubao prompt is a single module-level constant `DEFAULT_PROMPT` containing exactly the four-step Chinese instructions listed above. |
| F3 | The cleaned image is uploaded to Feishu and included as the first image in the reply post message, before the DXF preview. |
| F4 | The reply post message order is: text summary, cleaned image, DXF preview image, DXF file. |
| F5 | On Doubao call failure, the bot retries exactly once internally; on the second failure it replies with a short Chinese error message and does not produce a DXF. |
| F6 | The bot updates the "正在处理..." reply to "正在清理图片..." while Doubao is running, and to "正在转换 DXF..." once the cleaned image is in hand. |
| F7 | If Doubao completes in under ~3 s, the second progress reply is skipped to avoid message spam. |
| F8 | The fixed prompt is never interpolated with user content. |
| F9 | All previously existing `/dxf` requirements (F1–F8 of the 2026-06-23 spec) remain satisfied. |

### Non-functional

| ID | Requirement |
|----|-------------|
| N1 | API key and model id are read from environment variables `ARK_API_KEY` and `ARK_MODEL`. No new secret file. |
| N2 | `ARK_MODEL` defaults to `doubao-seedream-5-0-2 60128` if not set. |
| N3 | `openai` Python SDK is added to `dependencies` (not just dev). |
| N4 | HTTP timeouts: connect 10 s, read 60 s. |
| N5 | Images whose long edge exceeds 2048 px are resized with Pillow before upload to Ark (Ark accepts up to 4096 px on the long edge, but 2048 is a safer / cheaper default for the laser workflow). |
| N6 | The normalization module is byte-in / bytes-out and has no knowledge of Feishu. |
| N7 | All existing non-functional requirements of the 2026-06-23 spec (N1–N7) remain satisfied. |
| N8 | The per-request work directory cleanup contract is unchanged: `handlers.handle_dxf_request` still removes the directory in `finally`. The cleaned PNG lives inside that directory. |

## 3. Architecture

### 3.1 Topology

```
┌──────────────────────────────────────────────────────────────────────┐
│  Docker container                                                    │
│                                                                     │
│  Feishu WebSocket  ──►  handlers.handle_dxf_request                  │
│                              │                                      │
│                              ├─► feishu.download_image               │
│                              │                                      │
│                              ├─► doubao_normalizer.run  ◄── NEW      │
│                              │       │                              │
│                              │       ├─ resize if long edge > 2048  │
│                              │       ├─ openai SDK → Ark API         │
│                              │       ├─ internal retry-once          │
│                              │       └─ write normalized.png        │
│                              │                                      │
│                              ├─► feishu.upload_image_bytes  ◄── NEW  │
│                              │                                      │
│                              ├─► converter.run                       │
│                              │                                      │
│                              ├─► preview.render                      │
│                              │                                      │
│                              └─► feishu.send_post_message            │
│                                      (cleaned + preview + dxf)       │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 Data flow (single `/dxf` request)

```
t=0       Feishu event arrives
t≈0.3s    feishu.reply_text("正在处理...")
t≈1–3s    feishu.download_image → image_bytes
t≈3s      feishu.reply_text("正在清理图片...")        (skipped if <3s elapsed)
t≈3–18s   doubao_normalizer.run:
              - Pillow resize if long edge > 2048
              - openai SDK call to Ark
              - on 4xx: raise DoubaoAPIError (no retry)
              - on 5xx/connect: sleep 1s, retry once
              - decode b64 → write work_dir/normalized.png
              - return NormalizedImage(cleaned_bytes, path)
t≈18s     feishu.reply_text("正在转换 DXF...")
t≈18–22s  converter.run(cleaned_bytes, ".png", ...)
t≈22s     feishu.send_post_message(
              text="转换成功 (N 个轮廓)",
              image_keys=[cleaned_key, preview_key],   # NEW: list, cleaned first
              file_key=dxf_key)
t≈22s     finally: shutil.rmtree(work_dir)             # unchanged
```

## 4. Module design

### 4.1 `app/doubao_prompt.py` (NEW)

Single module-level constant. No logic.

```python
DEFAULT_PROMPT: str = (
    "先提高图片清晰度，把图片的logo摆正，"
    "图片中的logo改为纯黑色，然后背景改成纯白。"
)
```

### 4.2 `app/doubao_normalizer.py` (NEW)

```python
from dataclasses import dataclass
from pathlib import Path

class DoubaoAPIError(Exception):
    def __init__(self, user_msg: str, internal_msg: str):
        super().__init__(internal_msg)
        self.user_msg = user_msg
        self.internal_msg = internal_msg

@dataclass(frozen=True)
class NormalizedImage:
    cleaned_bytes: bytes
    cleaned_path: Path

def run(
    *,
    image_bytes: bytes,
    prompt: str,
    work_dir: Path,
    api_key: str,
    model: str,
) -> NormalizedImage:
    """Resize if needed, call Ark, return cleaned image bytes + on-disk path.
    Retries once on 5xx and connection errors. Raises DoubaoAPIError on
    terminal failure. The caller (handlers) is responsible for retry policy
    and for translating the user_msg to a Feishu reply.
    """
```

Internal helpers (private):

- `_resize_if_needed(image_bytes) -> bytes` — uses Pillow, returns
  unchanged bytes when long edge ≤ 2048. Encodes back as PNG.
- `_call_once(client, model, prompt, image_bytes) -> bytes` — single SDK call,
  returns the decoded cleaned bytes or raises.
- `_classify_error(exc) -> RetryDecision` — returns one of
  `RETRY`, `NO_RETRY`, with a `user_msg` string for the terminal case.

### 4.3 `app/feishu_client.py` (modified)

Two small additions:

```python
def upload_image_bytes(self, data: bytes, suffix: str) -> str:
    """Upload raw image bytes to Feishu, return image_key. Used for the
    cleaned PNG that came from Doubao and is not yet on disk as a path."""

def send_post_message(
    self,
    *,
    receive_id: str,
    receive_id_type: str,
    text: str,
    image_keys: list[str] | None = None,   # CHANGED: was single image_key
    file_key: str | None = None,
) -> None:
    """Send a post message with up to two images (cleaned + preview) plus an
    optional file attachment."""
```

### 4.4 `app/config.py` (modified)

```python
class Settings(BaseSettings):
    # ... existing fields ...
    ark_api_key: str                                # ARK_API_KEY, required
    ark_model: str = "doubao-seedream-5-0-2 60128"  # ARK_MODEL
```

`ark_api_key` is **required** — application fails to start without it, with
a clear error.

### 4.5 `app/handlers.py` (modified)

```python
from . import converter, doubao_normalizer, doubao_prompt, preview
from .doubao_normalizer import DoubaoAPIError

# inside handle_dxf_request, between download and converter:

# progress: "正在清理图片..."
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
    feishu.reply_text(parsed.message_id, f"AI 标准化失败: {e.user_msg}，请重试")
    return

# progress: "正在转换 DXF..."
feishu.reply_text(parsed.message_id, "正在转换 DXF...")

# upload cleaned PNG (NEW)
try:
    cleaned_key = feishu.upload_image_bytes(
        normalized.cleaned_bytes, ".png"
    )
except FeishuAPIError:
    feishu.reply_text(parsed.message_id, "清理后图片上传失败,请重试")
    return

# converter.run receives normalized.cleaned_bytes (it writes its own
# input.png inside work_dir; the pre-existing normalized.png remains
# alongside for the duration of the request and is removed by the
# existing shutil.rmtree in finally).

# at the end, send_post_message gets image_keys=[cleaned_key, preview_key]
```

The `try/finally` cleanup contract is **unchanged**: `work_dir` still contains
the cleaned PNG when removed, which is fine because it was inside the per-
request scratch dir.

### 4.6 `pyproject.toml` (modified)

Add `openai` to `dependencies`:

```toml
dependencies = [
    "fastapi",
    "lark-oapi",
    "uvicorn",
    "pydantic-settings",
    "image-to-laser-dxf",
    "openai",          # NEW
    "Pillow",          # NEW (transitively available, but pinning for clarity)
]
```

`Pillow` is already a transitive dep of `image-to-laser-dxf`, so this is a
documentation pin rather than a new install. If `image-to-laser-dxf` ever
drops Pillow, this keeps us honest.

## 5. Error handling

The internal classifier:

| Trigger | `user_msg` | Retry? |
|---|---|---|
| `openai.APIConnectionError` (timeout, DNS, refused) | "网络问题" | yes, 1× |
| `openai.APIStatusError` 4xx, code=AuditReject | "图片内容被 AI 拒绝" | no |
| `openai.APIStatusError` 4xx, code=Arrearage | "账户欠费" | no |
| `openai.APIStatusError` 4xx, other | "请求被拒绝" | no |
| `openai.APIStatusError` 5xx | "服务暂时不可用" | yes, 1× |
| `openai.APIStatusError` 401/403 | "鉴权失败" | no |
| No `b64_json` and no `url` in response | "返回数据异常" | no |
| `base64.b64decode` raises | "返回数据异常" | no |
| Decoded bytes fail Pillow PNG verification | "返回数据异常" | no |

Retry backoff: 1.0 s sleep. No jitter for v1 (single retry).

Logging: each call emits one JSON line with `request_id`, `image_bytes_size`,
`duration_ms`, `http_status`, `result: ok | retry | failed`.

## 6. Configuration

`docker-compose.yml` env-file additions:

```yaml
environment:
  ARK_API_KEY: ${ARK_API_KEY:?ARK_API_KEY is required}
  ARK_MODEL: ${ARK_MODEL:-doubao-seedream-5-0-2 60128}
```

`.env.example` gains:

```
ARK_API_KEY=ark-your-key-here
# ARK_MODEL=doubao-seedream-5-0-2 60128
```

`README.md` "Feishu console setup" section gains a one-paragraph note pointing
to https://console.volcengine.com/ark for obtaining an API key.

## 7. Testing

### 7.1 `tests/test_doubao_prompt.py`

- `DEFAULT_PROMPT` is a `str`
- Non-empty
- Contains "提高图片清晰度", "logo 摆正", "纯黑色", "纯白"

### 7.2 `tests/test_doubao_normalizer.py`

SDK is monkey-patched via a fake client. Coverage:

| Case | Mock | Expectation |
|---|---|---|
| Happy path | Returns `Mock(b64_json=...)`, decodes to valid PNG | `NormalizedImage` returned, file written |
| Network error, recovers on retry | 1st call `APIConnectionError`, 2nd call OK | 2 SDK calls, success |
| Network error, two strikes | Both calls `APIConnectionError` | `DoubaoAPIError`, `user_msg` contains "网络问题" |
| 4xx, no retry | 1 call `APIStatusError(400)` | 1 SDK call, `DoubaoAPIError`, `user_msg` contains "请求被拒绝" |
| 4xx AuditReject | `APIStatusError(400, code=AuditReject)` | no retry, "图片内容被 AI 拒绝" |
| 4xx Arrearage | `APIStatusError(401, code=Arrearage)` | no retry, "账户欠费" |
| 5xx, recovers | 1st `APIStatusError(500)`, 2nd OK | 2 calls, success |
| 5xx, two strikes | Both `APIStatusError(500)` | `DoubaoAPIError`, "服务暂时不可用" |
| 401/403, no retry | `APIStatusError(401)` | no retry, "鉴权失败" |
| No b64, no url | Returns `Mock(b64_json=None, url=None)` | `DoubaoAPIError`, "返回数据异常" |
| b64 decodes to non-image | Garbage bytes | `DoubaoAPIError`, "返回数据异常" |
| Resize needed | Image 5000×5000 | Pillow resize called, SDK receives ≤ 2048 long edge |
| Resize not needed | Image 1000×1000 | Pillow resize **not** called, bytes unchanged |

### 7.3 `tests/test_handlers_doubao_integration.py`

`feishu`, `doubao_normalizer.run`, `converter.run`, `preview.render` all
monkey-patched. Asserts the call order and the final `send_post_message`
arguments.

| Case | Expectation |
|---|---|
| Happy path | Call order ends with `send_post_message(image_keys=[cleaned_key, preview_key], file_key=...)` |
| Cleaned key reaches post | `image_keys[0]` equals the key returned by `upload_image_bytes` |
| Doubao final failure | `reply_text(AI 标准化失败...)` called; `converter.run` and `send_post_message` **not** called |
| Doubao success + converter fails | Original converter error branch ("无法读取图片...") triggers |
| Doubao success + upload_image_bytes fails | `reply_text(清理后图片上传失败...)` called; `converter.run` and `send_post_message` not called |

### 7.4 Manual checklist additions

Append to README:

- [ ] Send `/dxf` + clear logo → receive [cleaned, preview, DXF]
- [ ] Send `/dxf` + blurry tilted logo → cleaned shows straightened black-on-white logo
- [ ] Send `/dxf` + already-clean B/W logo → cleaned is essentially identical
- [ ] Disable network → user message "AI 标准化失败: 网络问题，请重试", no DXF produced
- [ ] Set `ARK_MODEL=does-not-exist` → user message mentions model error
- [ ] Set `ARK_API_KEY=invalid` → user message "鉴权失败"
- [ ] `pytest -v` is fully green

## 8. Risk & rollback

- **Risk:** Doubao changes the image in a way that breaks downstream
  binarization (e.g. adds shading). *Mitigation:* the cleaned image is shown
  to the user, who can re-send with /dxf in a way that... well, can't, since
  normalization is automatic. *Acceptable for v1; user can revert this PR.*
- **Risk:** Doubao rejects the image for content safety. *Mitigation:* the
  classifier maps this to a clear Chinese message; user can crop the image
  and retry.
- **Risk:** Doubao is slow / down for an extended period. *Mitigation:*
  retry is bounded (1 attempt); failure path is clean. If the team decides
  later, a feature flag can disable normalization.
- **Rollback:** revert this PR. No database, no schema, no breaking change to
  the existing `/dxf` message format that external systems depend on (the
  reply post is still `text + image(s) + file`).

## 9. Open questions

None at design time. All design decisions resolved during brainstorming.
