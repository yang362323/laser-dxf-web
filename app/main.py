"""Laser DXF Web App — PWA frontend + image conversion API.

Run with: ``python -m app.main``.
"""

from __future__ import annotations

import logging
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from .config import Config
from . import converter, doubao_normalizer, doubao_prompt, preview
from .doubao_normalizer import DoubaoAPIError

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def _build_app(cfg: Config, executor: ThreadPoolExecutor) -> FastAPI:
    app = FastAPI(title="laser-dxf")

    # ── health ──────────────────────────────────────────────────────────
    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    # ── static files (PWA frontend) ─────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/{filename}")
    async def static_file(filename: str):
        """Serve static assets, but only for known file types."""
        path = STATIC_DIR / filename
        if not path.exists() or not path.is_file():
            raise HTTPException(404)
        media_map = {
            ".js": "application/javascript",
            ".json": "application/json",
            ".png": "image/png",
            ".ico": "image/x-icon",
        }
        ext = Path(filename).suffix
        return FileResponse(str(path), media_type=media_map.get(ext, "application/octet-stream"))

    # ── convert API ────────────────────────────────────────────────────
    @app.post("/api/convert")
    def api_convert(file: UploadFile = File(...)) -> dict:
        """Upload an image, convert to DXF, return preview + download URLs."""
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(400, "only image files are supported")

        image_bytes = file.file.read()
        if not image_bytes:
            raise HTTPException(400, "empty file")

        job_id = uuid.uuid4().hex
        job_dir = Path(cfg.work_dir) / "output" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Pipeline (sync, runs in thread pool via FastAPI's async)
            result = _process_image(
                image_bytes=image_bytes,
                job_dir=job_dir,
                ark_api_key=cfg.ark_api_key,
                ark_model=cfg.ark_model,
            )
        except DoubaoAPIError as e:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(500, f"AI 处理失败: {e.user_msg}")
        except Exception:
            log.exception("conversion failed")
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(500, "转换失败，请重试")

        return {
            "job_id": job_id,
            "preview_url": f"/api/output/{job_id}/preview.png",
            "dxf_url": f"/api/output/{job_id}/output.dxf",
            "shape_count": result["shape_count"],
        }

    # ── serve output files ─────────────────────────────────────────────
    @app.get("/api/output/{job_id}/{filename}")
    def download_output(job_id: str, filename: str):
        file_path = Path(cfg.work_dir) / "output" / job_id / filename
        if not file_path.exists():
            raise HTTPException(404, "文件不存在或已过期")
        media_type = "image/png" if filename.endswith(".png") else "application/octet-stream"
        return FileResponse(
            str(file_path),
            media_type=media_type,
            filename=filename,
        )

    return app


def _process_image(
    *,
    image_bytes: bytes,
    job_dir: Path,
    ark_api_key: str,
    ark_model: str,
) -> dict:
    """Run the full image-to-DXF pipeline, save results to job_dir."""
    t0 = time.monotonic()

    # 1. Doubao AI normalization (straighten + clarity + black logo + white bg)
    normalized = doubao_normalizer.run(
        image_bytes=image_bytes,
        prompt=doubao_prompt.DEFAULT_PROMPT,
        work_dir=job_dir,
        api_key=ark_api_key,
        model=ark_model,
    )

    # 2. DXF conversion
    conv = converter.run(
        image_bytes=normalized.cleaned_bytes,
        image_suffix=".png",
        out_dxf_path=job_dir / "output.dxf",
        work_dir=job_dir,
    )

    # 3. Preview
    try:
        preview_path = preview.render(conv.dxf_path, job_dir / "preview.png")
    except Exception:
        log.exception("preview render failed")
        preview_path = None

    duration = time.monotonic() - t0
    log.info(
        "conversion complete: job=%s shapes=%d duration=%.1fs",
        job_dir.name, conv.shape_count, duration,
    )

    return {
        "shape_count": conv.shape_count,
    }


def main() -> None:
    cfg = Config.from_env()
    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    shutil.rmtree(cfg.work_dir, ignore_errors=True)

    executor = ThreadPoolExecutor(max_workers=cfg.max_workers)
    app = _build_app(cfg, executor)

    log.info("starting laser-dxf web app on :%s", cfg.port)
    uvicorn.run(app, host="0.0.0.0", port=cfg.port, log_level="warning")


if __name__ == "__main__":
    main()
