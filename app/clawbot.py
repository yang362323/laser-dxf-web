"""WeChat ClawBot (iLink protocol) client.

QR-code login, long-polling message receive, CDN media download/upload
with AES-128-ECB encryption, and message sending.

Runs as a background thread alongside the FastAPI web app.

Refs:
  https://github.com/SiverKing/weixin-ClawBot-API
  https://github.com/wong2/weixin-agent-sdk
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import random
import string
import threading
import time
from typing import Callable

import httpx
import qrcode
from Crypto.Cipher import AES

log = logging.getLogger(__name__)

ILINK_BASE = "https://ilinkai.weixin.qq.com"
CLIENT_ID = "openclaw-weixin-" + "".join(random.choices(string.hexdigits.lower(), k=32))


# ── crypto ─────────────────────────────────────────────────────────────────

def _aes_encrypt(data: bytes, key_hex: str) -> bytes:
    key = bytes.fromhex(key_hex)
    pad = 16 - len(data) % 16
    data = data + bytes([pad] * pad)
    return AES.new(key, AES.MODE_ECB).encrypt(data)


def _aes_decrypt(data: bytes, key_hex: str) -> bytes:
    key = bytes.fromhex(key_hex)
    decrypted = AES.new(key, AES.MODE_ECB).decrypt(data)
    return decrypted[:-decrypted[-1]]


def _aes_key_b64(hex_key: str) -> str:
    return base64.b64encode(hex_key.encode("ascii")).decode()


# ── HTTP helpers ───────────────────────────────────────────────────────────

def _headers(token: str) -> dict:
    return {
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {token}",
        "X-WECHAT-UIN": base64.b64encode(str(random.randint(0, 2**32 - 1)).encode()).decode(),
        "iLink-App-Id": "bot",
        "Content-Type": "application/json; charset=utf-8",
    }


# ── login ──────────────────────────────────────────────────────────────────

def _login(http: httpx.Client) -> tuple[str, str, str]:
    """QR-code login. Returns (bot_token, uin, aes_key)."""
    # Step 1: get QR code
    resp = http.post(f"{ILINK_BASE}/ilink/bot/get_bot_qrcode?bot_type=3",
                     json={"local_token_list": []})
    data = resp.json()
    qr_str = data.get("qrcode") or data.get("qr_code") or ""
    if not qr_str:
        raise RuntimeError(f"no qrcode in response: {data}")

    qr = qrcode.QRCode()
    qr.add_data(qr_str)
    qr.make(fit=True)
    qr.print_ascii(invert=True)
    log.info("scan QR code with WeChat to login")

    # Step 2: poll for confirmation
    from urllib.parse import quote
    for i in range(180):
        time.sleep(2)
        resp = http.get(
            f"{ILINK_BASE}/ilink/bot/get_qrcode_status?qrcode={quote(qr_str, safe='')}"
        )
        data = resp.json()
        status = data.get("status") or ""

        if status == "confirmed" or "bot_token" in data:
            token = data.get("bot_token") or ""
            uin = str(data.get("uin") or data.get("wx_uin") or "")
            aes_key = data.get("aes_key") or data.get("aesKey") or ""
            log.info("WeChat login success: uin=%s", uin)
            return token, uin, aes_key
        elif status == "expired":
            raise RuntimeError("QR code expired")
        elif status in ("scaned", "scaned_but_redirect"):
            log.info("scanned, waiting for confirmation...")
        elif status == "need_verifycode":
            log.warning("pairing code required — not supported yet")
        elif i % 15 == 0:
            log.info("waiting for scan... (status=%s)", status or "unknown")

    raise RuntimeError("login timed out")


# ── CDN media ──────────────────────────────────────────────────────────────

def _download_cdn(http: httpx.Client, cdn_url: str, aes_key: str) -> bytes:
    resp = http.get(cdn_url)
    if resp.status_code != 200:
        raise RuntimeError(f"CDN download: HTTP {resp.status_code}")
    return _aes_decrypt(resp.content, aes_key)


def _upload_cdn(http: httpx.Client, file_bytes: bytes, file_name: str,
                token: str, uin: str, aes_key: str) -> str:
    """Upload to WeChat CDN. Returns CDN URL."""
    # Get upload URL
    resp = http.post(
        f"{ILINK_BASE}/ilink/bot/getuploadurl",
        headers=_headers(token),
        json={"file_name": file_name, "file_size": len(file_bytes)},
    )
    data = resp.json()
    upload_url = data.get("upload_url") or data.get("url") or ""
    if not upload_url:
        raise RuntimeError(f"getuploadurl: {data}")

    encrypted = _aes_encrypt(file_bytes, aes_key)
    md5_hash = hashlib.md5(file_bytes).hexdigest()
    key_b64 = _aes_key_b64(aes_key)

    resp = http.post(
        upload_url,
        files={"file": (file_name, io.BytesIO(encrypted), "application/octet-stream")},
        data={"md5": md5_hash, "aes_key": key_b64},
    )
    if resp.status_code not in (200, 201, 204):
        raise RuntimeError(f"CDN upload: HTTP {resp.status_code}")
    result = resp.json() if resp.content else {}
    cdn_url = result.get("cdn_url") or result.get("url") or ""
    if not cdn_url:
        raise RuntimeError(f"CDN upload no URL: {result}")
    return cdn_url


# ── send ───────────────────────────────────────────────────────────────────

def _send(http, token, uin, to_user, ctx_token, items):
    payload = {
        "msg": {
            "from_user_id": "", "to_user_id": to_user,
            "client_id": CLIENT_ID, "message_type": 2, "message_state": 2,
            "context_token": ctx_token, "item_list": items,
        },
        "base_info": {"channel_version": "2.4.3", "bot_agent": "laser-dxf-web/1.0"},
    }
    resp = http.post(f"{ILINK_BASE}/ilink/bot/sendmessage",
                     headers=_headers(token), json=payload)
    if resp.status_code != 200:
        log.error("sendmessage: HTTP %s %s", resp.status_code, resp.text[:200])


def _send_text(http, token, uin, to, ctx, text):
    _send(http, token, uin, to, ctx, [{"type": 1, "text_item": {"text": text}}])


def _send_image(http, token, uin, to, ctx, img_bytes, aes_key):
    cdn = _upload_cdn(http, img_bytes, "image.png", token, uin, aes_key)
    _send(http, token, uin, to, ctx,
          [{"type": 3, "image_item": {"cdn_url": cdn, "aes_key": _aes_key_b64(aes_key)}}])


def _send_file(http, token, uin, to, ctx, file_bytes, name, aes_key):
    cdn = _upload_cdn(http, file_bytes, name, token, uin, aes_key)
    _send(http, token, uin, to, ctx,
          [{"type": 6, "file_item": {"cdn_url": cdn, "file_name": name, "aes_key": _aes_key_b64(aes_key)}}])


# ── public API ─────────────────────────────────────────────────────────────

class ClawBotClient:
    """Manages WeChat iLink connection in a background thread."""

    def __init__(self, on_image: Callable[[bytes, str, str], None] | None = None):
        self._on_image = on_image
        self._http = httpx.Client(timeout=httpx.Timeout(10, read=65))
        self._running = False
        self._token = ""
        self._uin = ""
        self._aes_key = ""
        self._last_ctx = ""
        self._buf = ""

    def send_text(self, to_user: str, text: str):
        _send_text(self._http, self._token, self._uin, to_user, self._last_ctx, text)

    def send_image(self, to_user: str, image_bytes: bytes):
        _send_image(self._http, self._token, self._uin, to_user, self._last_ctx, image_bytes, self._aes_key)

    def send_file(self, to_user: str, file_bytes: bytes, file_name: str):
        _send_file(self._http, self._token, self._uin, to_user, self._last_ctx, file_bytes, file_name, self._aes_key)

    def start(self):
        self._running = True
        t = threading.Thread(target=self._run, daemon=True, name="clawbot")
        t.start()

    def _run(self):
        while self._running:
            try:
                self._token, self._uin, self._aes_key = _login(self._http)
                break
            except Exception:
                log.exception("clawbot login failed, retrying in 10s")
                time.sleep(10)
        else:
            return
        log.info("clawbot polling...")
        while self._running:
            try:
                self._poll()
            except Exception:
                log.exception("clawbot poll error")
                time.sleep(10)

    def _poll(self):
        resp = self._http.post(
            f"{ILINK_BASE}/ilink/bot/getupdates",
            headers=_headers(self._token),
            json={"get_updates_buf": self._buf, "base_info": {}},
            timeout=httpx.Timeout(10, read=65),
        )
        if resp.status_code != 200:
            return
        data = resp.json()
        self._buf = data.get("get_updates_buf") or data.get("next_buf") or ""
        for msg in data.get("messages") or data.get("msg_list") or []:
            self._handle(msg)

    def _handle(self, msg: dict):
        msg_type = msg.get("message_type") or msg.get("msg_type") or 0
        from_user = msg.get("from_user_id") or msg.get("from_user") or ""
        ctx = msg.get("context_token") or ""
        if ctx:
            self._last_ctx = ctx

        if msg_type == 3 and self._on_image:
            for item in msg.get("item_list") or []:
                img = item.get("image_item") or item
                cdn = img.get("cdn_url") or img.get("url") or ""
                if cdn:
                    try:
                        img_bytes = _download_cdn(self._http, cdn, self._aes_key)
                        self._on_image(img_bytes, from_user, ctx)
                    except Exception:
                        log.exception("image download failed")
        elif msg_type == 1:
            text = "".join(
                (item.get("text_item") or {}).get("text", "")
                for item in msg.get("item_list") or []
            )
            log.info("clawbot text from %s: %s", from_user, text[:100])
