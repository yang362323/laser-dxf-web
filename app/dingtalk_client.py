"""DingTalk Open API wrapper.

Uses synchronous HTTP (httpx.Client) for all API calls. Manages access
token caching internally. Each method corresponds to one DingTalk API
call and returns simple Python values.

References:
  - https://open.dingtalk.com/document/orgapp/obtain-orgapp-token
  - https://open.dingtalk.com/document/orgapp/robot-message-types-and-parameters
  - https://open.dingtalk.com/document/orgapp/download-file-attached-to-group-conversation
"""

from __future__ import annotations

import io
import json
import logging
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# ── token ────────────────────────────────────────────────────────────────────

_TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
_TOKEN_EXPIRY_S = 7000  # actual expiry is 7200s; refresh a bit early


class DingTalkAPIError(RuntimeError):
    """A DingTalk API call returned a non-zero code."""


class DingTalkClient:
    """Synchronous DingTalk API client with token caching."""

    def __init__(self, app_key: str, app_secret: str, robot_code: str) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._robot_code = robot_code
        self._http = httpx.Client(timeout=httpx.Timeout(15.0, read=60.0))
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ── token management ─────────────────────────────────────────────────

    def _get_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        now = time.monotonic()
        if self._token is not None and now < self._token_expires_at:
            return self._token

        resp = self._http.post(
            _TOKEN_URL,
            json={"appKey": self._app_key, "appSecret": self._app_secret},
        )
        data = resp.json()
        if resp.status_code != 200:
            raise DingTalkAPIError(
                f"token request failed: HTTP {resp.status_code} {data}"
            )
        self._token = data["accessToken"]
        self._token_expires_at = now + _TOKEN_EXPIRY_S
        log.info("dingtalk access token refreshed")
        return self._token

    # ── download ─────────────────────────────────────────────────────────

    def download_image(self, download_code: str) -> bytes:
        """Download an image that a user sent to the bot.

        Uses the modern messageFiles/download API. Returns raw bytes.
        """
        token = self._get_token()
        resp = self._http.post(
            "https://api.dingtalk.com/v1.0/robot/messageFiles/download",
            headers={"x-acs-dingtalk-access-token": token},
            json={"robotCode": self._robot_code, "downloadCode": download_code},
        )
        data = resp.json()
        if resp.status_code != 200:
            raise DingTalkAPIError(
                f"download_image failed: HTTP {resp.status_code} {data}"
            )

        download_url = data.get("downloadUrl")
        if not download_url:
            raise DingTalkAPIError(f"download_image: no downloadUrl in response: {data}")

        file_resp = self._http.get(download_url)
        if file_resp.status_code != 200:
            raise DingTalkAPIError(
                f"download_image fetch failed: HTTP {file_resp.status_code}"
            )
        log.info("downloaded image: %d bytes", len(file_resp.content))
        return file_resp.content

    # ── upload media ─────────────────────────────────────────────────────

    def upload_media(self, file_bytes: bytes, file_name: str, media_type: str) -> str:
        """Upload media (image/file) to DingTalk. Returns a media_id.

        ``media_type`` is ``"image"`` or ``"file"``.

        The returned media_id can be used in msgParam when sending messages
        or in sessionWebhook replies.
        """
        token = self._get_token()
        resp = self._http.post(
            "https://oapi.dingtalk.com/media/upload",
            params={"access_token": token, "type": media_type},
            files={"media": (file_name, io.BytesIO(file_bytes))},
        )
        data = resp.json()
        if data.get("errcode", -1) != 0:
            raise DingTalkAPIError(
                f"upload_media failed: errcode={data.get('errcode')} errmsg={data.get('errmsg')}"
            )
        media_id = data["media_id"]
        log.info("uploaded %s: media_id=%s (%d bytes)", media_type, media_id, len(file_bytes))
        return media_id

    # ── reply via sessionWebhook ─────────────────────────────────────────

    def reply_via_webhook(self, session_webhook: str, payload: dict) -> dict:
        """Send a message via the sessionWebhook URL.

        Returns the parsed JSON response. Raises DingTalkAPIError on failure.
        """
        resp = self._http.post(
            session_webhook,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        data = resp.json()
        if data.get("errcode", -1) != 0:
            raise DingTalkAPIError(
                f"reply_via_webhook failed: errcode={data.get('errcode')} errmsg={data.get('errmsg')}"
            )
        return data

    def reply_text(self, session_webhook: str, text: str) -> None:
        """Reply with a plain text message."""
        self.reply_via_webhook(
            session_webhook,
            {"msgtype": "text", "text": {"content": text}},
        )

    def reply_image(self, session_webhook: str, media_id: str) -> None:
        """Reply with an image message (requires pre-uploaded media_id).

        DingTalk webhook image format uses ``picURL``, not ``media_id``.
        """
        self.reply_via_webhook(
            session_webhook,
            {"msgtype": "image", "image": {"picURL": media_id}},
        )

    def reply_file(self, session_webhook: str, media_id: str,
                   file_name: str = "output.dxf") -> None:
        """Reply with a file via sessionWebhook.

        DingTalk webhook supports file messages with msgtype=file,
        requiring mediaId and fileType parameters.
        fileType should be a recognized category like "file", "xlsx", etc.
        """
        self.reply_via_webhook(
            session_webhook,
            {
                "msgtype": "file",
                "file": {
                    "mediaId": media_id,
                    "fileType": "file",
                    "fileName": file_name,
                },
            },
        )
        log.info("file sent via webhook: media_id=%s file_name=%s", media_id, file_name)

    def reply_markdown(self, session_webhook: str, title: str, text: str) -> None:
        """Reply with a markdown message."""
        self.reply_via_webhook(
            session_webhook,
            {"msgtype": "markdown", "markdown": {"title": title, "text": text}},
        )
