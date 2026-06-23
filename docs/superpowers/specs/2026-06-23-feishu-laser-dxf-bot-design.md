# Feishu Laser DXF Bot — Design Spec

**Date:** 2026-06-23
**Status:** Draft, awaiting user approval
**Target repo:** `~/projects/feishu-laser-dxf-bot/`
**Depends on:** `~/image-to-laser-dxf` (local Python package, MIT)

## 1. Purpose & Scope

Build a Feishu (Lark) chatbot that bridges the existing
[`image-to-laser-dxf`](https://github.com/yang362323/image-to-laser-dxf)
package to a chat interface. A user in Feishu invokes the `/dxf` slash command
with an attached image; the bot downloads the image, runs the local conversion
pipeline to produce a laser-ready DXF, then sends the DXF plus a preview image
back to the same chat.

**Use case:** small lab team (2–5 users) sharing one bot on a single cloud
server. Not a public service.

**Out of scope (v1):**
- Custom conversion parameters via chat (all defaults are used)
- Persistent user history or settings
- Horizontal scaling beyond one container
- Serverless / multi-tenant deployment

## 2. Requirements

### Functional

| ID | Requirement |
|----|-------------|
| F1 | User types `/dxf` in a Feishu chat (1-on-1 or group) and attaches an image. |
| F2 | Bot replies "正在处理..." immediately upon receiving the event. |
| F3 | Bot downloads the attached image, converts it with `image_to_dxf.convert`, and produces a DXF. |
| F4 | Bot renders a PNG preview of the DXF for at-a-glance inspection. |
| F5 | Bot sends a single reply containing: a one-line summary (image pixel size + polyline count), the preview PNG, and the DXF file. |
| F6 | If the message has no image, bot replies with a usage hint. |
| F7 | If any step fails, bot replies with a short, user-facing error message and logs the underlying exception. |
| F8 | `/dxf` works in both private chat and group chat. |

### Non-functional

| ID | Requirement |
|----|-------------|
| N1 | All conversion parameters use `image_to_dxf` defaults (`px_to_mm=0.05`, `blur=5`, `morph=3`, `close_iters=2`, `open_iters=1`, `min_area_frac=1e-5`, `epsilon_frac=8e-4`). |
| N2 | End-to-end latency for a 3265×1280 image: ≤ 30 s typical. |
| N3 | Single Docker container, single process. |
| N4 | Survives container restart by reconnecting to Feishu automatically. |
| N5 | No public HTTPS endpoint required (uses outbound WebSocket). |
| N6 | App credentials read from environment, never written to code or git. |
| N7 | Up to 3 concurrent conversion requests without blocking each other. |

## 3. Architecture

### 3.1 Topology

```
┌──────────────────────────────────────────────────────┐
│  Docker container                                    │
│                                                      │
│  ┌───────────────────────────────────────────────┐   │
│  │  FastAPI app (single process)                 │   │
│  │                                               │   │
│  │  • WebSocket client  ──> lark-oapi → Feishu   │   │
│  │  • HTTP /healthz     ──> :8080                │   │
│  │  • ThreadPoolExecutor(max_workers=3)          │   │
│  │    for conversion requests                    │   │
│  │                                               │   │
│  │  Temp dir: /tmp/laser-bot/{uuid}/             │   │
│  └───────────────────────────────────────────────┘   │
│                                                      │
│  image_to_dxf (installed via pip install -e)        │
└──────────────────────────────────────────────────────┘
        │                                       ▲
        ▼ (outbound WebSocket)                  │ (outbound HTTPS)
   Feishu servers  ◀────── events + files ──────┘
```

The bot initiates an outbound WebSocket connection to Feishu via
`lark-oapi`. No inbound traffic, no HTTPS certificate, no DNS record.

### 3.2 File Layout

```
feishu-laser-dxf-bot/
├── app/
│   ├── __init__.py
│   ├── main.py             # entry: assemble lark client, start uvicorn
│   ├── config.py           # load APP_ID, APP_SECRET, LOG_LEVEL from env
│   ├── handlers.py         # /dxf slash command event handler
│   ├── feishu_client.py    # download image / upload file / send message
│   ├── converter.py        # wrapper around image_to_dxf.convert + temp dir
│   └── preview.py          # DXF -> PNG via ezdxf + matplotlib
├── tests/
│   ├── test_converter.py
│   ├── test_preview.py
│   ├── test_handlers.py
│   └── fixtures/sample.jpg
├── docs/
│   └── superpowers/specs/2026-06-23-feishu-laser-dxf-bot-design.md
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

### 3.3 Module Responsibilities

| Module | Owns | Depends on |
|--------|------|------------|
| `app.main` | Process lifecycle: build config, lark client, register handlers, run uvicorn for `/healthz` | config, handlers |
| `app.config` | Env loading + validation | — |
| `app.handlers` | Slash command dispatch: parse event, call converter, send reply | feishu_client, converter, preview |
| `app.feishu_client` | Thin wrapper over `lark_oapi` SDK calls: download image bytes, upload DXF, upload PNG, send interactive message | lark_oapi |
| `app.converter` | Per-request temp dir creation, call `image_to_dxf.convert`, cleanup | image_to_dxf |
| `app.preview` | Render a DXF to a PNG using `ezdxf.addons.matplotlib` | ezdxf, matplotlib |

Each module has a single responsibility and can be unit-tested with a mocked
collaborator.

## 4. Data Flow

User action: in Feishu, type `/dxf`, pick the menu entry, attach an image, hit
send.

| # | Actor | Action |
|---|-------|--------|
| 1 | User | Sends `/dxf` + image |
| 2 | Feishu | Pushes slash-command event over WebSocket |
| 3 | Bot (handler) | Receives event; extracts `image_key`, `message_id`, `chat_id`, `sender_id` |
| 4 | Bot | Sends a text reply to the original message via `POST /im/v1/messages/{message_id}/reply` with `msg_type=text` and `content={"text": "正在处理..."}`. |
| 5 | Bot | Downloads image bytes via `im/v1/images/{image_key}` |
| 6 | Bot | Writes image to `/tmp/laser-bot/{uuid}/input.{ext}` |
| 7 | Bot | Calls `image_to_dxf.convert(input, dxf)` → produces `output.dxf` |
| 8 | Bot | Calls `preview.render(dxf, png)` → produces `preview.png` |
| 9 | Bot | Uploads `output.dxf` → gets `file_key` |
| 10 | Bot | Uploads `preview.png` → gets `image_key` |
| 11 | Bot | Sends a single `post` (rich text) message to the chat containing: a summary line, an inline image reference (preview `image_key`), and an inline file reference (DXF `file_key`). |
| 12 | Bot | Cleans up temp dir (finally block) |

Notes:
- Steps 5–11 run in a `ThreadPoolExecutor` worker; the WebSocket thread is not blocked.
- If step 8 (preview render) fails, the bot still sends step 11 with only the DXF file and a "预览生成失败" note — graceful degradation.
- If step 9 or 10 fails, the bot replies with an error message; nothing is partially sent.

## 5. Error Handling

| Failure | User-facing reply | Internal action |
|---------|-------------------|-----------------|
| Event has no image attachment | "请在 `/dxf` 后面附上一张图片再发送" | Log info; return |
| Image download returns 404 | "图片下载失败(可能已过期),请重发" | Log warning; cleanup |
| Image download returns non-2xx | "图片下载失败,请重试" | Log warning; cleanup |
| `image_to_dxf.convert` raises `FileNotFoundError` | "无法读取图片,可能格式损坏" | Log error; cleanup |
| Conversion exceeds 60 s | "处理超时,请尝试较小的图" | Cancel future; log warning; cleanup |
| DXF upload fails | "DXF 上传失败,稍后再试" | Log error; copy DXF to `/tmp/laser-bot/failed/{uuid}.dxf` for manual recovery |
| Preview render fails | (skip preview; still send DXF) | Log warning; continue |
| Final send-message fails | (no retry; user sees nothing) | Log error |

### Resource Isolation

- Every request gets its own UUID-suffixed subdir under `/tmp/laser-bot/`.
- Cleanup is in a `try/finally`.
- On container start, `app.main` does `shutil.rmtree("/tmp/laser-bot", ignore_errors=True)` to clear stale state.
- `ThreadPoolExecutor(max_workers=3)` — enough for 2–5 concurrent users; avoids thrashing on the CPU-bound OpenCV step.

### Per-request Timeout

Only the conversion step is wrapped in a future with `wait(timeout=60)`. The
Feishu API calls rely on `lark-oapi`'s built-in HTTP timeouts.

## 6. Configuration

Environment variables (loaded in `app.config`):

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `FEISHU_APP_ID` | yes | — | App ID from Feishu developer console |
| `FEISHU_APP_SECRET` | yes | — | App Secret from Feishu developer console |
| `LOG_LEVEL` | no | `INFO` | Standard Python logging level |
| `HEALTH_PORT` | no | `8080` | Port for `/healthz` HTTP endpoint |
| `WORK_DIR` | no | `/tmp/laser-bot` | Base directory for per-request temp dirs |
| `CONVERT_TIMEOUT_S` | no | `60` | Per-request conversion timeout in seconds |
| `MAX_WORKERS` | no | `3` | ThreadPoolExecutor size |

`.env.example` ships a template; `.env` is in `.gitignore`. Docker reads it
via `env_file: .env` in `docker-compose.yml`.

## 7. Testing Strategy

### Unit tests

- `test_converter.py`: feed a known JPG fixture, assert `output.dxf` exists and contains ≥ 1 LWPOLYLINE.
- `test_preview.py`: feed a fixed DXF, assert `preview.png` exists and is non-empty (PIL `Image.open(...).size`).
- `test_handlers.py`: mock `FeishuClient` and `Converter`, feed a fake event dict, assert the call sequence (download → convert → upload DXF → upload preview → send message).

### Manual test checklist (in README)

- [ ] Private chat: send `/dxf` + simple JPG → receive DXF + preview
- [ ] Group chat: `@bot /dxf` + image → receive DXF + preview
- [ ] `/dxf` with no image → see usage hint
- [ ] `/dxf` with corrupt file → see error message
- [ ] Two users in parallel → both get results
- [ ] `docker restart` the container → bot reconnects automatically

### Out of scope for v1

- Full Feishu sandbox integration test (too heavy for the value)
- Load testing beyond 3 concurrent requests
- Fuzz testing of malformed events

## 8. Deployment

### Dockerfile (overview)

- Base: `python:3.11-slim`
- System deps: `libgl1` (matplotlib backend)
- Python deps: `lark-oapi`, `fastapi`, `uvicorn[standard]`, `matplotlib`, `image_to_dxf` (installed via `pip install -e /deps/image-to-laser-dxf`)
- Build context includes `image-to-laser-dxf/` as a subdirectory or sibling mount
- Entrypoint: `python -m app.main`
- Exposes `8080` for `/healthz`

### docker-compose.yml

- Single `bot` service
- `env_file: .env`
- `restart: unless-stopped`
- `ports: ["8080:8080"]` (health check only)
- `healthcheck` via `curl localhost:8080/healthz`

### Operational notes

- Container only needs outbound 443 — works on any cloud.
- Logs go to stdout; `docker logs` collects them.
- No persistent volumes needed in v1; failed uploads land in `/tmp/laser-bot/failed/` and survive until container restart.

## 9. Feishu Console Setup (one-time, manual)

These steps live in `README.md`:

1. Open https://open.feishu.cn/ → create a custom enterprise app.
2. Add the "Bot" capability.
3. Permissions: enable `im:message`, `im:message:send_as_bot`, `im:resource`, `im:message.group_at_msg`, `im:message.p2p_msg`, `im:message:receive_as_bot`.
4. Event subscription: add a slash command `/dxf` of type **Menu** with no extra parameters. The lark-oapi WebSocket client receives these events automatically once the app is published.
5. Copy `App ID` and `App Secret` into `.env`.
6. In Feishu, search the bot's name, open a chat, send `/dxf`.

## 10. Out-of-Scope / Future Work

- Custom conversion parameters exposed in the slash command (would need command parameters and CLI flag mapping)
- Per-user configurable output scale (`px_to_mm`)
- Async queue (Celery / RQ) if usage grows beyond a single container
- Persistent storage of past conversions
- Other IM platforms (WeCom, DingTalk, Slack) — the `image_to_dxf` call is platform-agnostic; only `feishu_client` would be replaced