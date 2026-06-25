"""Message handler for DingTalk bot.

Receives a parsed message from the Stream SDK callback, runs the full
image-to-DXF pipeline synchronously (called from a thread pool), and
replies via sessionWebhook.
"""

from __future__ import annotations

import logging
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import converter, doubao_normalizer, doubao_prompt, preview, skew_correction
from .config import Config
from .dingtalk_client import DingTalkAPIError, DingTalkClient
from .doubao_normalizer import DoubaoAPIError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParsedImageMessage:
    """The fields we need from an incoming DingTalk image message."""

    download_code: str
    session_webhook: str
    conversation_id: str


def handle_dxf_request(
    *,
    parsed: ParsedImageMessage,
    dingtalk: DingTalkClient,
    work_dir: Path,
    settings: Config,
) -> None:
    """Handle one image-to-DXF conversion request.

    Steps:
        1. Reply "正在处理..."
        2. Download image bytes
        3. Skew correction (OpenCV)
        4. Reply "正在清理图片..."
        5. Normalize via Doubao
        6. Reply "正在转换 DXF..." (only if Doubao took >= 3s)
        7. Upload cleaned image, upload DXF, upload preview
        8. Reply with cleaned image + preview image + DXF file

    Errors at any step reply with a short Chinese message; nothing
    raises out of this function.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Step 1: acknowledge
        dingtalk.reply_text(parsed.session_webhook, "正在处理...")

        # Step 2: download
        try:
            image_bytes = dingtalk.download_image(parsed.download_code)
        except DingTalkAPIError:
            log.exception("download_image failed")
            dingtalk.reply_text(parsed.session_webhook, "图片下载失败,请重试")
            return

        # Step 3: skew correction
        skew = skew_correction.correct(image_bytes)
        if skew.was_corrected:
            log.info("skew corrected: %.1f°", skew.angle_deg)
            image_bytes = skew.corrected_bytes

        # Step 4: Doubao normalization
        dingtalk.reply_text(parsed.session_webhook, "正在清理图片...")
        doubao_start = time.monotonic()
        try:
            normalized = doubao_normalizer.run(
                image_bytes=image_bytes,
                prompt=doubao_prompt.DEFAULT_PROMPT,
                work_dir=work_dir,
                api_key=settings.ark_api_key,
                model=settings.ark_model,
            )
        except DoubaoAPIError as e:
            dingtalk.reply_text(
                parsed.session_webhook, f"AI 标准化失败: {e.user_msg}，请重试"
            )
            return

        # Step 5: progress update (skip if Doubao was fast)
        if time.monotonic() - doubao_start >= 3.0:
            dingtalk.reply_text(parsed.session_webhook, "正在转换 DXF...")

        # Step 6: upload cleaned image
        try:
            cleaned_media_id = dingtalk.upload_media(
                normalized.cleaned_bytes, "cleaned.png", "image"
            )
        except DingTalkAPIError:
            log.exception("cleaned image upload failed")
            dingtalk.reply_text(parsed.session_webhook, "清理后图片上传失败,请重试")
            return

        # Step 7: convert to DXF
        try:
            conv = converter.run(
                image_bytes=normalized.cleaned_bytes,
                image_suffix=".png",
                out_dxf_path=work_dir / "output.dxf",
                work_dir=work_dir,
            )
        except FileNotFoundError:
            log.exception("converter.run FileNotFoundError")
            dingtalk.reply_text(parsed.session_webhook, "无法读取图片,可能格式损坏")
            return

        # Step 8: preview (best-effort)
        preview_media_id: str | None = None
        try:
            preview_path = preview.render(conv.dxf_path, work_dir / "preview.png")
            preview_media_id = dingtalk.upload_media(
                preview_path.read_bytes(), "preview.png", "image"
            )
        except Exception:
            log.exception("preview generation failed (non-fatal)")
            preview_media_id = None

        # Step 9: upload DXF file
        try:
            dxf_media_id = dingtalk.upload_media(
                conv.dxf_path.read_bytes(), "output.dxf", "file"
            )
        except DingTalkAPIError:
            log.exception("dxf upload failed")
            dingtalk.reply_text(parsed.session_webhook, "DXF 上传失败,稍后再试")
            return

        # Step 10: send results
        summary = f"转换成功 ({conv.shape_count} 个轮廓)"
        try:
            dingtalk.reply_text(parsed.session_webhook, summary)
            dingtalk.reply_image(parsed.session_webhook, cleaned_media_id)
            if preview_media_id:
                dingtalk.reply_image(parsed.session_webhook, preview_media_id)
            dingtalk.reply_file(parsed.session_webhook, dxf_media_id, "output.dxf")
        except DingTalkAPIError:
            log.exception("send result messages failed")
            return

    except Exception:
        log.exception("unhandled error in /dxf handler")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def make_work_dir(base: Path) -> Path:
    """Create a per-request work directory with a UUID suffix."""
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    return base / uuid.uuid4().hex
