"""Thin wrapper around lark_oapi.Client.

Each method corresponds to one Feishu Open Platform API call. The wrapper
translates (file path, body dict) into the right lark SDK signature and
returns a simple Python value (bytes / str key) so handlers can be tested
without touching the network.

SDK reference (lark-oapi >= 1.2):
- client.im.v1.image.get(req) -> GetImageResponse with .file (IO[bytes])
- client.im.v1.image.create(req) -> CreateImageResponse with .data.image_key
- client.im.v1.file.create(req) -> CreateFileResponse with .data.file_key
- client.im.v1.message.create(req) -> CreateMessageResponse
- client.im.v1.message.reply(req) -> ReplyMessageResponse
"""

from __future__ import annotations

import io
import json
from pathlib import Path

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
        """Download a message image by its image_key. Returns raw bytes."""
        req = GetImageRequest.builder().image_key(image_key).build()
        resp = self._client.im.v1.image.get(req)
        if not resp.success() or resp.file is None:
            raise FeishuAPIError(f"download_image failed: code={resp.code} msg={resp.msg}")
        return resp.file.read()

    # --- uploads ---

    def upload_file(self, file_path: Path) -> str:
        """Upload a binary file (e.g. DXF). Returns the file_key."""
        path = Path(file_path)
        with open(path, "rb") as fp:
            body = (
                CreateFileRequestBody.builder()
                .file_type("stream")
                .file_name(path.name)
                .file(fp)
                .build()
            )
            req = CreateFileRequest.builder().request_body(body).build()
            resp = self._client.im.v1.file.create(req)
        if not resp.success() or resp.data is None:
            raise FeishuAPIError(f"upload_file failed: code={resp.code} msg={resp.msg}")
        return resp.data.file_key

    def upload_image(self, image_path: Path) -> str:
        """Upload an image (e.g. preview PNG). Returns the image_key."""
        path = Path(image_path)
        with open(path, "rb") as fp:
            body = (
                CreateImageRequestBody.builder()
                .image_type("message")
                .image(fp)
                .build()
            )
            req = CreateImageRequest.builder().request_body(body).build()
            resp = self._client.im.v1.image.create(req)
        if not resp.success() or resp.data is None:
            raise FeishuAPIError(f"upload_image failed: code={resp.code} msg={resp.msg}")
        return resp.data.image_key

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

    # --- messaging ---

    def reply_text(self, message_id: str, text: str) -> None:
        """Reply to an existing message with a plain text payload."""
        body = (
            ReplyMessageRequestBody.builder()
            .msg_type("text")
            .content(json.dumps({"text": text}, ensure_ascii=False))
            .build()
        )
        req = ReplyMessageRequest.builder().message_id(message_id).request_body(body).build()
        resp = self._client.im.v1.message.reply(req)
        if not resp.success():
            raise FeishuAPIError(f"reply_text failed: code={resp.code} msg={resp.msg}")

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
