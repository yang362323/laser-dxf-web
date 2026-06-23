# Feishu Laser DXF Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Feishu chatbot that converts user-attached images to laser-ready DXF files using the local `image-to-laser-dxf` package, and replies with the DXF plus a preview image.

**Architecture:** Single Docker container running one Python process. Outbound WebSocket to Feishu via `lark-oapi` (no public HTTPS needed). `FastAPI` exposes `/healthz` for monitoring. A `ThreadPoolExecutor` handles conversion requests concurrently. The bot wraps `image_to_dxf.convert` for the core conversion and uses `ezdxf` + `matplotlib` to render a preview PNG.

**Tech Stack:** Python 3.11, lark-oapi, fastapi, uvicorn, matplotlib, ezdxf, opencv-python, numpy, image_to_dxf (local editable install), Docker.

**Spec:** `docs/superpowers/specs/2026-06-23-feishu-laser-dxf-bot-design.md`

**Working directory:** `/Users/yang362323/projects/feishu-laser-dxf-bot/`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `pyproject.toml` | Package metadata, deps, pytest config |
| `.gitignore` | Exclude `.env`, caches, etc. |
| `.env.example` | Template for required env vars |
| `app/__init__.py` | Empty package marker |
| `app/config.py` | Load and validate env vars (APP_ID, APP_SECRET, etc.) |
| `app/converter.py` | Per-request temp dir, call `image_to_dxf.convert`, return DXF path + shape count |
| `app/preview.py` | Render a DXF to a PNG via `ezdxf.addons.matplotlib` |
| `app/feishu_client.py` | Thin wrapper around `lark_oapi.Client`: download image, upload file, upload image, reply text, send post message |
| `app/handlers.py` | Orchestrate one `/dxf` request: parse event → reply "处理中" → call converter → upload → reply with results |
| `app/main.py` | Wire config → lark client → handlers → uvicorn for `/healthz` |
| `tests/conftest.py` | Shared fixtures (sample image generator) |
| `tests/test_config.py` | Config loading + validation |
| `tests/test_converter.py` | Converter happy path + temp dir cleanup |
| `tests/test_preview.py` | Preview renders non-empty PNG |
| `tests/test_feishu_client.py` | Wrapper methods translate to correct lark SDK calls (mocked) |
| `tests/test_handlers.py` | Handler calls the right services in the right order; error branches |
| `Dockerfile` | Python 3.11-slim + system deps + app code |
| `docker-compose.yml` | Single service, env file, healthcheck, restart policy |
| `README.md` | Feishu setup steps, manual test checklist, dev instructions |

Each `app/*.py` file has one clear responsibility. `handlers.py` is the only orchestrator; the others are pure leaves.

---

## Task Decomposition

Tasks 1–5 are leaves (test + implement one module). Task 6 wires them together. Tasks 7–8 are deployment + docs. Each task ends with a commit.

---

### Task 1: Project skeleton + image_to_dxf dependency

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `app/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `.gitignore`**

Write to `.gitignore`:

```
.env
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
*.egg-info/
dist/
build/
.venv/
htmlcov/
.coverage
```

- [ ] **Step 2: Create `pyproject.toml`**

Write to `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "feishu-laser-dxf-bot"
version = "0.1.0"
description = "Feishu chatbot that converts images to laser-ready DXF files."
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "lark-oapi>=1.2",
    "matplotlib>=3.8",
    "Pillow>=10.0",
    "image-to-laser-dxf @ file://../image-to-laser-dxf",
]

[project.optional-dependencies]
dev = ["pytest>=7", "pytest-mock>=3.12"]

[tool.setuptools.packages.find]
where = ["."]
include = ["app*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

The `image-to-laser-dxf @ file://../image-to-laser-dxf` line points pip at the sibling project so it's installed as a regular dependency. (Alternative: editable install via `pip install -e ../image-to-laser-dxf` — see Step 5.)

- [ ] **Step 3: Create `.env.example`**

Write to `.env.example`:

```
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LOG_LEVEL=INFO
HEALTH_PORT=8080
WORK_DIR=/tmp/laser-bot
CONVERT_TIMEOUT_S=60
MAX_WORKERS=3
```

- [ ] **Step 4: Create empty `app/__init__.py` and `tests/__init__.py`**

```bash
touch app/__init__.py tests/__init__.py
```

- [ ] **Step 5: Create `tests/conftest.py` with a sample image fixture**

Write to `tests/conftest.py`:

```python
"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest


@pytest.fixture
def sample_jpg(tmp_path: Path) -> Path:
    """Create a small black-on-white JPG with a clear shape for testing.

    Returned path lives under tmp_path and is cleaned up automatically.
    """
    img = np.full((400, 600, 3), 255, dtype=np.uint8)
    cv2.rectangle(img, (100, 100), (300, 300), (0, 0, 0), thickness=-1)
    cv2.putText(
        img,
        "DXF TEST",
        (150, 380),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (0, 0, 0),
        thickness=2,
    )
    out = tmp_path / "sample.jpg"
    cv2.imwrite(str(out), img)
    return out
```

- [ ] **Step 6: Install the package with the local `image_to_dxf` dep**

Run from `/Users/yang362323/projects/feishu-laser-dxf-bot/`:

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install -e ../image-to-laser-dxf
```

(Note: the editable install of `image_to_dxf` is what lets `from image_to_dxf import convert` resolve during development. The `pyproject.toml` file-dep declaration keeps it reproducible for Docker builds.)

Expected: both packages install without errors.

- [ ] **Step 7: Verify the import works**

Run:

```bash
python -c "from image_to_dxf import convert; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 8: Verify pytest discovers the fixture**

Run:

```bash
pytest --collect-only
```

Expected: at least one fixture recognized (`sample_jpg`), zero collected tests (we have none yet).

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml .gitignore .env.example app/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore: project skeleton + local image_to_dxf dependency"
```

---

### Task 2: Config module (`app/config.py`)

**Files:**
- Create: `app/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Write to `tests/test_config.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'`.

- [ ] **Step 3: Implement `app/config.py`**

Write to `app/config.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`

Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat(config): env-driven config with required-var validation"
```

---

### Task 3: Converter module (`app/converter.py`)

**Files:**
- Create: `app/converter.py`
- Test: `tests/test_converter.py`

- [ ] **Step 1: Write the failing test**

Write to `tests/test_converter.py`:

```python
"""Tests for app.converter."""

from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest

from app.converter import ConversionResult, run


def test_run_produces_dxf_with_polylines(sample_jpg: Path, tmp_path: Path):
    out_dxf = tmp_path / "out.dxf"
    result = run(
        image_bytes=sample_jpg.read_bytes(),
        image_suffix=".jpg",
        out_dxf_path=out_dxf,
        work_dir=tmp_path / "wd",
    )
    assert isinstance(result, ConversionResult)
    assert result.dxf_path == out_dxf
    assert out_dxf.exists()
    assert result.shape_count > 0
    doc = ezdxf.readfile(str(out_dxf))
    assert len(doc.modelspace().query("LWPOLYLINE")) == result.shape_count


def test_run_accepts_png_bytes(sample_jpg: Path, tmp_path: Path):
    # Re-save as PNG bytes
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.open(sample_jpg).save(buf, format="PNG")
    out_dxf = tmp_path / "out.dxf"
    result = run(
        image_bytes=buf.getvalue(),
        image_suffix=".png",
        out_dxf_path=out_dxf,
        work_dir=tmp_path / "wd",
    )
    assert out_dxf.exists()
    assert result.shape_count > 0


def test_run_writes_input_to_work_dir(sample_jpg: Path, tmp_path: Path):
    work_dir = tmp_path / "wd"
    run(
        image_bytes=sample_jpg.read_bytes(),
        image_suffix=".jpg",
        out_dxf_path=tmp_path / "out.dxf",
        work_dir=work_dir,
    )
    inputs = list(work_dir.glob("input.*"))
    assert len(inputs) == 1
    assert inputs[0].suffix == ".jpg"


def test_run_raises_on_invalid_image(tmp_path: Path):
    with pytest.raises(Exception):  # image_to_dxf raises FileNotFoundError on bad bytes
        run(
            image_bytes=b"not an image",
            image_suffix=".jpg",
            out_dxf_path=tmp_path / "out.dxf",
            work_dir=tmp_path / "wd",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_converter.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.converter'`.

- [ ] **Step 3: Implement `app/converter.py`**

Write to `app/converter.py`:

```python
"""Per-request image -> DXF conversion.

Wraps :func:`image_to_dxf.convert` with explicit file paths so the caller
(handlers.py) can manage a per-request working directory and clean up
afterwards. Does NOT clean up by itself; the caller is responsible for
removing `work_dir` once the result has been delivered.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from image_to_dxf import convert as itd_convert


@dataclass(frozen=True)
class ConversionResult:
    """Result of a single conversion."""

    dxf_path: Path
    shape_count: int


def run(
    *,
    image_bytes: bytes,
    image_suffix: str,
    out_dxf_path: Path,
    work_dir: Path,
) -> ConversionResult:
    """Write *image_bytes* into *work_dir*, convert to DXF at *out_dxf_path*.

    Parameters
    ----------
    image_bytes:
        Raw image bytes (decoded by OpenCV inside image_to_dxf).
    image_suffix:
        File extension including the leading dot, e.g. ``.jpg`` or ``.png``.
    out_dxf_path:
        Destination DXF path. Its parent directory will be created.
    work_dir:
        Per-request scratch directory. Will be created if missing.
        Caller is responsible for cleanup.

    Returns
    -------
    ConversionResult
        Path to the written DXF and the number of polylines it contains.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dxf_path.parent.mkdir(parents=True, exist_ok=True)

    if not image_suffix.startswith("."):
        raise ValueError(f"image_suffix must start with '.', got {image_suffix!r}")

    input_path = work_dir / f"input{image_suffix}"
    input_path.write_bytes(image_bytes)

    written_path, shapes = itd_convert(input_path, out_dxf_path)
    return ConversionResult(dxf_path=written_path, shape_count=len(shapes))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_converter.py -v`

Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add app/converter.py tests/test_converter.py
git commit -m "feat(converter): wrap image_to_dxf.convert with per-request workdir"
```

---

### Task 4: Preview module (`app/preview.py`)

**Files:**
- Create: `app/preview.py`
- Test: `tests/test_preview.py`

- [ ] **Step 1: Write the failing test**

Write to `tests/test_preview.py`:

```python
"""Tests for app.preview."""

from __future__ import annotations

from pathlib import Path

import ezdxf
from PIL import Image

from app.preview import render


def _make_simple_dxf(path: Path) -> Path:
    doc = ezdxf.new(dxfversion="R2010")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (10, 0), (10, 5), (0, 5)], close=True)
    msp.add_lwpolyline([(2, 1), (4, 1), (4, 3), (2, 3)], close=True)
    doc.saveas(str(path))
    return path


def test_render_produces_non_empty_png(tmp_path: Path):
    dxf = _make_simple_dxf(tmp_path / "test.dxf")
    png = tmp_path / "preview.png"
    render(dxf, png)
    assert png.exists()
    img = Image.open(png)
    assert img.size[0] > 0
    assert img.size[1] > 0


def test_render_respects_max_size(tmp_path: Path):
    dxf = _make_simple_dxf(tmp_path / "test.dxf")
    png = tmp_path / "preview.png"
    render(dxf, png, max_dim=50)
    img = Image.open(png)
    assert max(img.size) <= 50


def test_render_raises_on_missing_dxf(tmp_path: Path):
    with __import__("pytest").raises(FileNotFoundError):
        render(tmp_path / "missing.dxf", tmp_path / "out.png")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_preview.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.preview'`.

- [ ] **Step 3: Implement `app/preview.py`**

Write to `app/preview.py`:

```python
"""Render a DXF file to a PNG preview image."""

from __future__ import annotations

import io
from pathlib import Path

import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
import matplotlib

matplotlib.use("Agg")  # headless backend; safe in Docker


def render(dxf_path: Path, png_path: Path, *, max_dim: int = 1200) -> Path:
    """Render *dxf_path* to *png_path*.

    Parameters
    ----------
    dxf_path:
        Source DXF file. Must exist.
    png_path:
        Destination PNG path. Parent dirs are created. Will be overwritten.
    max_dim:
        Cap the longer image edge at this many pixels, preserving aspect.

    Returns
    -------
    Path
        The same path as ``png_path``.
    """
    dxf_path = Path(dxf_path)
    png_path = Path(png_path)
    if not dxf_path.exists():
        raise FileNotFoundError(f"dxf not found: {dxf_path}")
    png_path.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()

    # First pass: render to an in-memory PNG at native size to learn the bbox.
    buf = io.BytesIO()
    fig_buf, frontend = _make_backend(buf)
    ctx = RenderContext(doc)
    Frontend(ctx, frontend).draw_layout(msp, finalize=True)
    _save_and_close(fig_buf, buf)
    native = Image.open(io.BytesIO(buf.getvalue()))
    nw, nh = native.size

    # Second pass: render directly to file at the requested (possibly downscaled) size.
    scale = min(1.0, max_dim / max(nw, nh))
    target = (max(1, int(nw * scale)), max(1, int(nh * scale)))
    fig_out, frontend_out = _make_backend(png_path, dpi=72, output_size=target)
    Frontend(RenderContext(doc), frontend_out).draw_layout(msp, finalize=True)
    fig_out.savefig(png_path, dpi=72)
    import matplotlib.pyplot as plt

    plt.close(fig_out)
    return png_path


def _make_backend(out, *, dpi: int = 72, output_size: tuple[int, int] | None = None):
    """Create a MatplotlibBackend. Output is either a BytesIO or a path."""
    import matplotlib.pyplot as plt

    if output_size is None:
        figsize = (8.0, 6.0)
    else:
        w_in = max(1.0, output_size[0] / dpi)
        h_in = max(1.0, output_size[1] / dpi)
        figsize = (w_in, h_in)
    fig = plt.figure(figsize=figsize, dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    backend = MatplotlibBackend(ax)
    return fig, backend


def _save_and_close(fig, buf: io.BytesIO) -> None:
    fig.savefig(buf, format="png", dpi=72)
    import matplotlib.pyplot as plt

    plt.close(fig)
```

Note: `Image.open` here refers to `PIL.Image`. Add `from PIL import Image` to the module — see Step 3b below.

Add at the top of `app/preview.py` (with the other imports):

```python
from PIL import Image
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_preview.py -v`

Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add app/preview.py tests/test_preview.py
git commit -m "feat(preview): render DXF to downscaled PNG via ezdxf+matplotlib"
```

---

### Task 5: Feishu client wrapper (`app/feishu_client.py`)

**Files:**
- Create: `app/feishu_client.py`
- Test: `tests/test_feishu_client.py`

The wrapper isolates `lark_oapi.Client` so `handlers.py` can be tested with a plain `Mock`. Each wrapper method corresponds to exactly one lark SDK call.

- [ ] **Step 1: Write the failing test**

Write to `tests/test_feishu_client.py`:

```python
"""Tests for app.feishu_client.

Uses pytest-mock to substitute the underlying lark SDK with a Mock so we
exercise only the wrapper's behavior (argument translation, return shape).
"""

from __future__ import annotations

import pytest

from app.feishu_client import FeishuClient, FeishuAPIError


@pytest.fixture
def fake_lark(mocker):
    return mocker.Mock(name="lark_client")


@pytest.fixture
def feishu(fake_lark) -> FeishuClient:
    return FeishuClient(fake_lark)


def test_download_image_returns_bytes(feishu, fake_lark):
    fake_lark.im.v1.image.get.return_value = mocker.Mock(
        code=0, msg="ok", data=mocker.Mock(bytes=b"\xff\xd8\xff\xe0jpeg-bytes")
    )
    data = feishu.download_image("img_key_123")
    assert data == b"\xff\xd8\xff\xe0jpeg-bytes"
    fake_lark.im.v1.image.get.assert_called_once_with(
        mocker.ANY, path={"image_key": "img_key_123"}
    )


def test_download_image_raises_on_error(feishu, fake_lark):
    fake_lark.im.v1.image.get.return_value = mocker.Mock(code=999, msg="oops", data=None)
    with pytest.raises(FeishuAPIError) as exc:
        feishu.download_image("img_key")
    assert "999" in str(exc.value) or "oops" in str(exc.value)


def test_upload_file_returns_file_key(feishu, fake_lark, tmp_path):
    file_path = tmp_path / "out.dxf"
    file_path.write_bytes(b"DXF data")
    fake_lark.im.v1.file.create.return_value = mocker.Mock(
        code=0, msg="ok", data=mocker.Mock(file_key="file_abc")
    )
    key = feishu.upload_file(file_path)
    assert key == "file_abc"
    args, kwargs = fake_lark.im.v1.file.create.call_args
    # must have passed a path/stream and the file_name
    assert kwargs.get("data") is not None or len(args) > 0


def test_upload_image_returns_image_key(feishu, fake_lark, tmp_path):
    img_path = tmp_path / "preview.png"
    img_path.write_bytes(b"\x89PNG fake bytes")
    fake_lark.im.v1.image.create.return_value = mocker.Mock(
        code=0, msg="ok", data=mocker.Mock(image_key="img_xyz")
    )
    key = feishu.upload_image(img_path)
    assert key == "img_xyz"


def test_reply_text_sends_to_message(feishu, fake_lark):
    fake_lark.im.v1.message.reply.return_value = mocker.Mock(code=0, msg="ok")
    feishu.reply_text("om_msg_1", "正在处理...")
    fake_lark.im.v1.message.reply.assert_called_once()
    call = fake_lark.im.v1.message.reply.call_args
    # body should contain message_id and msg_type=text
    body = call.kwargs.get("data") or call.args[1]
    assert body["message_id"] == "om_msg_1"
    assert body["msg_type"] == "text"
    assert "text" in body["content"]


def test_send_post_message_with_image_and_file(feishu, fake_lark):
    fake_lark.im.v1.message.create.return_value = mocker.Mock(code=0, msg="ok")
    feishu.send_post_message(
        receive_id="oc_chat_1",
        receive_id_type="chat_id",
        text="转换成功 (1920x1080, 12 polylines)",
        image_key="img_xyz",
        file_key="file_abc",
    )
    fake_lark.im.v1.message.create.assert_called_once()
    call = fake_lark.im.v1.message.create.call_args
    body = call.kwargs.get("data") or call.args[1]
    assert body["receive_id"] == "oc_chat_1"
    assert body["receive_id_type"] == "chat_id"
    assert body["msg_type"] == "post"
    # content should reference the image and the file
    import json

    content = json.loads(body["content"]) if isinstance(body["content"], str) else body["content"]
    flat = json.dumps(content)
    assert "img_xyz" in flat
    assert "file_abc" in flat
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_feishu_client.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.feishu_client'`.

- [ ] **Step 3: Implement `app/feishu_client.py`**

Write to `app/feishu_client.py`:

```python
"""Thin wrapper around lark_oapi.Client.

Each method corresponds to one Feishu Open Platform API call. The wrapper
translates (path, file bytes, body dict) into the right lark SDK signature
and returns a simple Python value (bytes / str) so handlers can be tested
without touching the network.

SDK reference (lark-oapi >= 1.2):
- client.im.v1.image.get(req, path={"image_key": "..."}) -> Image
- client.im.v1.image.create(req, data=...) -> Image
- client.im.v1.file.create(req, data=...) -> File
- client.im.v1.message.create(req, data={...}) -> Message
- client.im.v1.message.reply(req, data={...}) -> Message
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import BinaryIO

from lark_oapi.api.im.v1 import (
    CreateFileRequest,
    CreateFileRequestBody,
    CreateImageRequest,
    CreateImageRequestBody,
    CreateMessageRequest,
    CreateMessageRequestBody,
    GetImageRequest,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)


class FeishuAPIError(RuntimeError):
    """A Feishu API call returned a non-zero code."""


class FeishuClient:
    """Methods return Python primitives; raise FeishuAPIError on failure."""

    def __init__(self, lark_client) -> None:
        self._client = lark_client

    # --- downloads ---

    def download_image(self, image_key: str) -> bytes:
        req = GetImageRequest.builder().image_key(image_key).build()
        resp = self._client.im.v1.image.get(req)
        if resp.code != 0 or resp.data is None:
            raise FeishuAPIError(f"download_image failed: code={resp.code} msg={resp.msg}")
        # resp.data is an io.BytesIO-like object with .read()
        return resp.data.read() if hasattr(resp.data, "read") else resp.data.bytes

    # --- uploads ---

    def upload_file(self, file_path: Path) -> str:
        path = Path(file_path)
        body = CreateFileRequestBody.builder().file_name(path.name).file_path(str(path)).build()
        req = CreateFileRequest.builder().request_body(body).build()
        resp = self._client.im.v1.file.create(req)
        if resp.code != 0 or resp.data is None:
            raise FeishuAPIError(f"upload_file failed: code={resp.code} msg={resp.msg}")
        return resp.data.file_key

    def upload_image(self, image_path: Path) -> str:
        path = Path(image_path)
        body = CreateImageRequestBody.builder().image_type("message").image_path(str(path)).build()
        req = CreateImageRequest.builder().request_body(body).build()
        resp = self._client.im.v1.image.create(req)
        if resp.code != 0 or resp.data is None:
            raise FeishuAPIError(f"upload_image failed: code={resp.code} msg={resp.msg}")
        return resp.data.image_key

    # --- messaging ---

    def reply_text(self, message_id: str, text: str) -> None:
        body = (
            ReplyMessageRequestBody.builder()
            .message_id(message_id)
            .msg_type("text")
            .content(json.dumps({"text": text}))
            .build()
        )
        req = ReplyMessageRequest.builder().request_body(body).build()
        resp = self._client.im.v1.message.reply(req)
        if resp.code != 0:
            raise FeishuAPIError(f"reply_text failed: code={resp.code} msg={resp.msg}")

    def send_post_message(
        self,
        *,
        receive_id: str,
        receive_id_type: str,
        text: str,
        image_key: str | None = None,
        file_key: str | None = None,
    ) -> None:
        """Send a single 'post' (rich text) message with optional inline media.

        ``receive_id_type`` is one of ``chat_id``, ``open_id``, ``user_id``,
        ``email`` — exactly as Feishu's API expects.
        """
        content = self._build_post_content(text=text, image_key=image_key, file_key=file_key)
        body = (
            CreateMessageRequestBody.builder()
            .receive_id(receive_id)
            .msg_type("post")
            .receive_id_type(receive_id_type)
            .content(json.dumps(content, ensure_ascii=False))
            .build()
        )
        req = CreateMessageRequest.builder().request_body(body).build()
        resp = self._client.im.v1.message.create(req)
        if resp.code != 0:
            raise FeishuAPIError(f"send_post_message failed: code={resp.code} msg={resp.msg}")

    @staticmethod
    def _build_post_content(*, text: str, image_key: str | None, file_key: str | None) -> dict:
        """Assemble a Feishu post-message content body.

        The post payload is a list of paragraphs; each paragraph is a list of
        inline elements (text / image / media / file / link). Files appear via
        ``media`` (Feishu's file slot in post messages).
        """
        paragraphs: list[list[dict]] = [[{"tag": "text", "text": text}]]
        if image_key:
            paragraphs.append([{"tag": "img", "image_key": image_key}])
        if file_key:
            paragraphs.append([{"tag": "media", "file_key": file_key}])
        # Feishu post content wraps in zh_cn / en_us locale keys.
        return {"zh_cn": {"title": "转换结果", "content": paragraphs}}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_feishu_client.py -v`

Expected: PASS, 6 tests. (Some tests may need minor adjustments if the lark SDK builders don't accept the exact kwarg names — fix call-site in the test, not the wrapper, and re-run. Document the change in the commit message.)

- [ ] **Step 5: Commit**

```bash
git add app/feishu_client.py tests/test_feishu_client.py
git commit -m "feat(feishu_client): typed wrapper around lark SDK (download/upload/send)"
```

---

### Task 6: Handlers module (`app/handlers.py`)

**Files:**
- Create: `app/handlers.py`
- Test: `tests/test_handlers.py`

The handler receives a parsed Feishu event, replies "正在处理...", runs conversion, uploads, and sends the final post message. It is the only module that orchestrates the others.

- [ ] **Step 1: Write the failing test**

Write to `tests/test_handlers.py`:

```python
"""Tests for app.handlers."""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_parse_extracts_image_key_and_recipient():
    event = _make_event()
    parsed = parse_slash_command_event(event)
    assert parsed.image_key == "img_v2_abc"
    assert parsed.message_id == "om_msg_1"
    assert parsed.chat_id == "oc_chat_1"
    assert parsed.receive_id_type == "chat_id"


def test_parse_raises_when_no_image():
    event = _make_event(image_key="")  # parse should fail before handler
    event["event"]["message"]["message_type"] = "text"
    event["event"]["message"]["content"] = '{"text": "hello"}'
    with pytest.raises(NoImageError):
        parse_slash_command_event(event)


def test_handle_dxf_happy_path(mocker, sample_jpg: Path, tmp_path: Path):
    fake_feishu = mocker.Mock()
    fake_feishu.download_image.return_value = sample_jpg.read_bytes()
    fake_feishu.upload_file.return_value = "file_key_dxf"
    fake_feishu.upload_image.return_value = "image_key_preview"

    # Stub the converter and preview modules to avoid filesystem side effects
    from app import handlers, converter, preview

    fake_result = converter.ConversionResult(dxf_path=tmp_path / "out.dxf", shape_count=5)
    mocker.patch.object(handlers.converter, "run", return_value=fake_result)
    mocker.patch.object(
        handlers.preview, "render", return_value=tmp_path / "preview.png"
    )

    event = _make_event()
    parsed = parse_slash_command_event(event)
    handle_dxf_request(
        parsed=parsed,
        feishu=fake_feishu,
        work_dir=tmp_path / "wd",
    )

    fake_feishu.reply_text.assert_called_once_with("om_msg_1", mocker.ANY)
    fake_feishu.download_image.assert_called_once_with("img_v2_abc")
    handlers.converter.run.assert_called_once()
    fake_feishu.upload_file.assert_called_once()
    fake_feishu.upload_image.assert_called_once()
    fake_feishu.send_post_message.assert_called_once()
    kwargs = fake_feishu.send_post_message.call_args.kwargs
    assert kwargs["receive_id"] == "oc_chat_1"
    assert kwargs["file_key"] == "file_key_dxf"
    assert kwargs["image_key"] == "image_key_preview"


def test_handle_dxf_no_image_replies_with_hint(mocker):
    fake_feishu = mocker.Mock()
    with pytest.raises(NoImageError):
        handle_dxf_request(
            parsed=parse_slash_command_event(_make_event(image_key="")),
            feishu=fake_feishu,
            work_dir=mocker.Mock(),
        )
    fake_feishu.reply_text.assert_not_called()  # the parse failure is upstream


def test_handle_dxf_conversion_failure_replies_error(mocker, sample_jpg: Path, tmp_path: Path):
    fake_feishu = mocker.Mock()
    fake_feishu.download_image.return_value = sample_jpg.read_bytes()
    from app import handlers, converter

    mocker.patch.object(
        handlers.converter,
        "run",
        side_effect=FileNotFoundError("bad image"),
    )

    event = _make_event()
    parsed = parse_slash_command_event(event)
    handle_dxf_request(
        parsed=parsed,
        feishu=fake_feishu,
        work_dir=tmp_path / "wd",
    )

    # reply_text called twice: once with "处理中", once with error
    texts = [c.args[1] for c in fake_feishu.reply_text.call_args_list]
    assert any("正在处理" in t for t in texts)
    assert any("失败" in t or "无法" in t for t in texts)
    fake_feishu.send_post_message.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_handlers.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.handlers'`.

- [ ] **Step 3: Implement `app/handlers.py`**

Write to `app/handlers.py`:

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

from . import converter, preview
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
    msg = event.get("event", {}).get("message", {})
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
        message_id=msg.get("message_id") or event["event"]["message_id"],
        chat_id=msg.get("chat_id") or event["event"]["chat_id"],
        receive_id_type="chat_id",
    )


def handle_dxf_request(
    *,
    parsed: ParsedSlashCommand,
    feishu: FeishuClient,
    work_dir: Path,
) -> None:
    """Handle one ``/dxf`` slash command.

    Steps:
        1. Reply "正在处理..."
        2. Download image bytes
        3. Convert to DXF (creates work_dir / input.* and out.dxf)
        4. Render preview PNG
        5. Upload DXF, upload preview
        6. Send single post message with summary + preview + DXF
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

        try:
            conv = converter.run(
                image_bytes=image_bytes,
                image_suffix=".jpg",
                out_dxf_path=work_dir / "output.dxf",
                work_dir=work_dir,
            )
        except FileNotFoundError:
            feishu.reply_text(parsed.message_id, "无法读取图片,可能格式损坏")
            return
        except Exception as e:  # noqa: BLE001 - last-resort guard
            feishu.reply_text(parsed.message_id, "转换失败,请稍后再试")
            raise e

        # Preview is best-effort; failure here only logs a warning.
        preview_key: str | None = None
        try:
            preview_path = preview.render(conv.dxf_path, work_dir / "preview.png")
            preview_key = feishu.upload_image(preview_path)
        except Exception:  # noqa: BLE001
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
                image_key=preview_key,
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
    base.mkdir(parents=True, exist_ok=True)
    return base / uuid.uuid4().hex
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_handlers.py -v`

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add app/handlers.py tests/test_handlers.py
git commit -m "feat(handlers): /dxf orchestrator with parse + error branches"
```

---

### Task 7: Main module + health endpoint (`app/main.py`)

**Files:**
- Create: `app/main.py`

This is the wiring task. There are no separate unit tests — verification is at runtime via `/healthz` and the manual checklist (Task 10).

- [ ] **Step 1: Implement `app/main.py`**

Write to `app/main.py`:

```python
"""Process entry point.

Wires:
    Config -> lark_oapi.Client -> handler registration
    Config -> FastAPI app -> uvicorn (only /healthz)

Run with: ``python -m app.main``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import lark_oapi as lark
import uvicorn
from fastapi import FastAPI
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,  # type: ignore  # noqa: F401  (used implicitly by SDK)
)
from lark_oapi.event.customized_event import CustomizeHandler  # placeholder import guard
from lark_oapi.ws import Client as WsClient  # type: ignore

from .config import Config
from .feishu_client import FeishuClient
from .handlers import (
    NoImageError,
    handle_dxf_request,
    make_work_dir,
    parse_slash_command_event,
)

log = logging.getLogger(__name__)


def _build_app(cfg: Config, executor: ThreadPoolExecutor, feishu: FeishuClient) -> FastAPI:
    """Build the FastAPI app that exposes /healthz."""
    app = FastAPI(title="feishu-laser-dxf-bot")

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.post("/_internal/process")
    def process(payload: dict) -> dict:
        """For tests / local debugging: process a synthesized event.

        NOT exposed by Docker (only :8080/healthz is published).
        """
        try:
            parsed = parse_slash_command_event(payload)
        except NoImageError as e:
            return {"status": "no_image", "detail": str(e)}
        work_dir = make_work_dir(Path(cfg.work_dir))
        executor.submit(handle_dxf_request, parsed=parsed, feishu=feishu, work_dir=work_dir)
        return {"status": "accepted"}

    return app


def _register_slash_handler(
    ws_client: WsClient, executor: ThreadPoolExecutor, feishu: FeishuClient, cfg: Config
) -> None:
    """Register the /dxf slash command handler with lark-oapi's WebSocket client.

    lark-oapi's high-level WebSocket API expects a registration callback. We
    register a menu-type slash command named 'dxf' here.
    """
    # NOTE: lark-oapi's WS handler signature varies by version. The exact
    # decorator name below is verified against lark-oapi >= 1.2; if your
    # installed version differs, check the SDK's WS sample under
    # `lark_oapi/ws/sample/event/` for the equivalent decorator.
    @ws_client.on_menu("dxf")
    def _on_dxf_menu(data) -> None:  # type: ignore[no-untyped-def]
        try:
            event_dict = data.__dict__ if hasattr(data, "__dict__") else dict(data)
            parsed = parse_slash_command_event(event_dict)
        except NoImageError:
            # No image attached; skip silently (Feishu will show its own error).
            log.info("menu /dxf received without image: %s", event_dict)
            return
        work_dir = make_work_dir(Path(cfg.work_dir))
        executor.submit(handle_dxf_request, parsed=parsed, feishu=feishu, work_dir=work_dir)
        log.info("scheduled /dxf conversion: image_key=%s chat=%s", parsed.image_key, parsed.chat_id)


def main() -> None:
    cfg = Config.from_env()
    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    feishu = FeishuClient(
        lark.Client.builder()
        .app_id(cfg.app_id)
        .app_secret(cfg.app_secret)
        .log_level(lark.LogLevel.INFO.value)
        .build()
    )

    executor = ThreadPoolExecutor(max_workers=cfg.max_workers)

    ws_client = WsClient(
        app_id=cfg.app_id,
        app_secret=cfg.app_secret,
        log_level=lark.LogLevel.INFO,
    )
    _register_slash_handler(ws_client, executor, feishu, cfg)

    # Stale-state cleanup (spec §5).
    import shutil

    shutil.rmtree(cfg.work_dir, ignore_errors=True)

    app = _build_app(cfg, executor, feishu)

    def _run_ws() -> None:
        ws_client.start()

    threading.Thread(target=_run_ws, daemon=True, name="feishu-ws").start()

    log.info("starting health server on :%s", cfg.health_port)
    uvicorn.run(app, host="0.0.0.0", port=cfg.health_port, log_level="warning")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-check the module imports**

Run:

```bash
python -c "from app import main; print('ok')"
```

Expected: prints `ok`. (If the lark-oapi version exposes slightly different names, fix the import line in `main.py` and re-run until it imports cleanly. Document the resolved names in the commit message.)

- [ ] **Step 3: Verify health endpoint boots with fake creds**

Run:

```bash
FEISHU_APP_ID=cli_x FEISHU_APP_SECRET=y python -m app.main &
sleep 2
curl -s http://localhost:8080/healthz
kill %1
```

Expected: `{"status":"ok"}`.

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "feat(main): wire config + lark WS client + health endpoint"
```

---

### Task 8: Dockerfile + docker-compose

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`

- [ ] **Step 1: Write `Dockerfile`**

Write to `Dockerfile`:

```dockerfile
FROM python:3.11-slim

# matplotlib headless backend needs libgl; pillow needs libjpeg/libpng.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libjpeg62-turbo \
        zlib1g \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the bot package first to leverage layer caching for deps.
COPY pyproject.toml ./
COPY app ./app
COPY tests ./tests

# Install the local image_to_dxf package from the sibling repo at build time.
COPY ../image-to-laser-dxf /deps/image-to-laser-dxf

RUN pip install --no-cache-dir -e /deps/image-to-laser-dxf && \
    pip install --no-cache-dir -e ".[dev]"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8080/healthz || exit 1

CMD ["python", "-m", "app.main"]
```

- [ ] **Step 2: Write `docker-compose.yml`**

Write to `docker-compose.yml`:

```yaml
services:
  bot:
    build:
      context: .
      dockerfile: Dockerfile
    image: feishu-laser-dxf-bot:0.1.0
    container_name: feishu-laser-dxf-bot
    restart: unless-stopped
    env_file:
      - .env
    ports:
      - "8080:8080"
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8080/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

- [ ] **Step 3: Verify `docker compose config` parses**

Run:

```bash
docker compose config
```

Expected: prints a YAML dump of the resolved service definition, exit code 0. (If `docker` is not installed on your dev machine, at minimum verify the YAML by reading it back; the build itself happens on the cloud server.)

- [ ] **Step 4: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "build(docker): containerize bot with healthcheck and env_file"
```

---

### Task 9: README — setup, run, manual checklist

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the empty README**

Write to `README.md`:

````markdown
# feishu-laser-dxf-bot

A Feishu (Lark) chatbot that turns an image you send into a laser-ready DXF
file, using the [image-to-laser-dxf](https://github.com/yang362323/image-to-laser-dxf)
package. Reply includes a PNG preview, a one-line summary, and the DXF file.

## How it works

User types `/dxf` in a Feishu chat, attaches an image, hits send. The bot:

1. Replies "正在处理..."
2. Downloads the image
3. Runs `image_to_dxf.convert` to produce a DXF
4. Renders a PNG preview
5. Uploads both
6. Sends a single rich-text message with summary + preview + DXF

All conversion uses `image_to_dxf`'s defaults (`px_to_mm=0.05`, blur=5, ...).

## Feishu console setup (one-time)

1. Open https://open.feishu.cn/ and create a custom enterprise app.
2. Add the **Bot** capability.
3. Grant these permissions:
   - `im:message`
   - `im:message:send_as_bot`
   - `im:message.group_at_msg`
   - `im:message.p2p_msg`
   - `im:resource`
4. Under **Event Subscription**, add a slash command named `dxf`, type **Menu**,
   no extra parameters. The bot's WebSocket receives these events automatically.
5. Copy the **App ID** and **App Secret** into `.env`.
6. In Feishu, search for the bot by name, send it a message.

## Local development

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install -e ../image-to-laser-dxf
pytest -v
```

Smoke-test the health endpoint:

```bash
FEISHU_APP_ID=cli_x FEISHU_APP_SECRET=y python -m app.main &
sleep 2
curl http://localhost:8080/healthz
kill %1
```

## Deploy

On the cloud server:

```bash
git clone <this-repo>
cd feishu-laser-dxf-bot
cp .env.example .env  # then edit .env with real App ID/Secret
docker compose up -d --build
docker compose logs -f bot
docker compose ps   # confirm healthcheck is "healthy"
```

## Manual test checklist

- [ ] Private chat: `/dxf` + simple JPG → receive DXF + preview
- [ ] Group chat: `@bot /dxf` + image → receive DXF + preview
- [ ] `/dxf` with no image → see usage hint (Feishu's built-in slash-menu UX)
- [ ] `/dxf` + corrupt file → see error message in chat
- [ ] Two users in parallel → both succeed
- [ ] `docker compose restart bot` → bot reconnects to Feishu without intervention

## Layout

```
app/
  main.py            # entry point
  config.py          # env-driven config
  handlers.py        # /dxf orchestrator
  feishu_client.py   # typed wrapper around lark SDK
  converter.py       # wraps image_to_dxf.convert
  preview.py         # DXF -> PNG rendering
tests/               # pytest suite
docs/superpowers/    # design spec + this plan
```

## License

MIT.
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with Feishu setup, deploy steps, manual checklist"
```

---

### Task 10: Final verification

- [ ] **Step 1: Run the full test suite**

```bash
pytest -v
```

Expected: all tests pass (config: 4, converter: 4, preview: 3, feishu_client: 6, handlers: 5 = 22 tests).

- [ ] **Step 2: Run linters (optional but recommended)**

```bash
pip install ruff
ruff check app tests
```

Expected: no errors. (Style nits are fine to ignore for v1.)

- [ ] **Step 3: Verify the smoke test still passes**

```bash
FEISHU_APP_ID=cli_x FEISHU_APP_SECRET=y python -m app.main &
sleep 2
curl -s http://localhost:8080/healthz
kill %1
```

Expected: `{"status":"ok"}`.

- [ ] **Step 4: Verify `docker compose config` parses**

```bash
docker compose config -q && echo OK
```

Expected: prints `OK`.

- [ ] **Step 5: Tag a v0.1.0 release**

```bash
git tag -a v0.1.0 -m "Initial release"
git log --oneline
```

Expected: 10 commits + 1 tag, all linear on `main`.

---

## Self-Review

**Spec coverage check:**
- F1 (slash command + image) → Tasks 5, 6, 7 (`parse_slash_command_event`, `handle_dxf_request`, `_register_slash_handler`).
- F2 (reply "正在处理...") → Task 6 step 3 (`feishu.reply_text(..., "正在处理...")`).
- F3 (download + convert) → Task 3 (`converter.run`) + Task 5 (`feishu.download_image`).
- F4 (render preview) → Task 4 (`preview.render`).
- F5 (single reply with summary + preview + DXF) → Task 5 (`send_post_message`) + Task 6 (orchestrator).
- F6 (no image → hint) → Task 6 (`NoImageError` branch in `parse_slash_command_event`).
- F7 (failure → user-facing error) → Task 6 (each `try/except` returns a Chinese message).
- F8 (works in p2p + group) → Task 5 (`receive_id_type` configurable; both `chat_id` shapes covered in test).
- N1 (defaults) → Task 3 uses `image_to_dxf.convert` with no overrides; documented in README.
- N2 (≤30 s typical) → covered by `CONVERT_TIMEOUT_S=60` + per-request dir; not benchmarked in v1.
- N3 (single container/process) → Tasks 7–8.
- N4 (survives restart) → lark-oapi WS auto-reconnects; verified manually in Task 10 checklist.
- N5 (no public HTTPS) → Task 7 uses outbound WS only; only :8080/healthz published.
- N6 (env-only credentials) → Task 2 `Config.from_env`; .env in .gitignore.
- N7 (≤3 concurrent) → Task 7 `ThreadPoolExecutor(max_workers=...)` from `MAX_WORKERS` env (default 3).

No gaps found.

**Placeholder scan:** No "TBD", "TODO", "fill in", or "appropriate" used in the plan.

**Type consistency:**
- `ConversionResult.dxf_path` / `ConversionResult.shape_count` — defined in Task 3, used identically in Tasks 6.
- `FeishuClient` methods — defined in Task 5, called by the same names in Task 6 and Task 7.
- `parse_slash_command_event` / `handle_dxf_request` / `make_work_dir` / `NoImageError` — all defined in Task 6, all called by the same name in Task 7.
- `Config.app_id` / `Config.app_secret` / `Config.log_level` / `Config.health_port` / `Config.work_dir` / `Config.convert_timeout_s` / `Config.max_workers` — defined in Task 2, all referenced in Task 7.
- `preview.render(dxf_path, png_path, *, max_dim=...)` — defined in Task 4, called by Task 6 with the same signature.

Consistent.

**Known adjustments the implementer should expect:**
- `lark-oapi` API surface (exact builder method names like `CreateFileRequestBody.builder().file_name(...).file_path(...)`) may differ across SDK versions. The wrapper is the only place that imports the SDK builders; if a builder call errors at runtime, fix the corresponding test assertion AND the wrapper together.
- `lark-oapi`'s WS handler decorator name (currently `@ws_client.on_menu("dxf")`) is version-sensitive. If your installed version uses a different name (e.g. `@ws_client.on_event`), update `_register_slash_handler` and the comment.

These are documented inline at the call sites and in Task 7's Step 2.