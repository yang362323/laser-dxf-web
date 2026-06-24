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
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    return base / uuid.uuid4().hex
