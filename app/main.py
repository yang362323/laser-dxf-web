"""Process entry point — DingTalk Stream Mode.

Wires:
    Config -> DingTalkClient (sync REST API calls)
    Config -> DingTalkStreamClient (WebSocket, receives messages)
    Config -> FastAPI app (only /healthz)

Run with: ``python -m app.main``.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import dingtalk_stream
import uvicorn
from dingtalk_stream import AckMessage, ChatbotMessage
from fastapi import FastAPI

from .config import Config
from .dingtalk_client import DingTalkClient
from .handlers import (
    ParsedImageMessage,
    handle_dxf_request,
    make_work_dir,
)

log = logging.getLogger(__name__)


def _build_app() -> FastAPI:
    """Build the FastAPI app that exposes /healthz."""
    app = FastAPI(title="dingtalk-laser-dxf-bot")

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app


class DxfBotHandler(dingtalk_stream.ChatbotHandler):
    """Receives messages from DingTalk Stream, dispatches image conversion."""

    def __init__(
        self,
        cfg: Config,
        dingtalk: DingTalkClient,
        executor: ThreadPoolExecutor,
    ) -> None:
        super().__init__()
        self._cfg = cfg
        self._dingtalk = dingtalk
        self._executor = executor

    async def process(self, callback: dingtalk_stream.Callback) -> tuple[int, str]:
        """Handle one incoming message.

        Only processes image (picture) messages. Returns AckMessage.STATUS_OK
        immediately — the actual processing runs on a thread pool so we don't
        block the WebSocket.
        """
        try:
            msg = ChatbotMessage.from_dict(callback.data)
        except Exception:
            log.warning("failed to parse incoming message: %r", callback.data)
            return AckMessage.STATUS_OK, "parse error"

        # Only handle picture messages
        msg_type = getattr(msg, "message_type", "") or ""
        if msg_type != "picture":
            log.info("ignoring non-picture message: type=%s", msg_type)
            return AckMessage.STATUS_OK, "not an image"

        # Extract download code
        download_code = ""
        try:
            image_list = msg.get_image_list() if callable(getattr(msg, "get_image_list", None)) else []
        except Exception:
            image_list = []
        if image_list:
            download_code = getattr(image_list[0], "download_code", "")
        if not download_code:
            img_content = getattr(msg, "image_content", None)
            if img_content:
                download_code = getattr(img_content, "download_code", "")

        if not download_code:
            log.warning("picture message has no download_code")
            return AckMessage.STATUS_OK, "no download code"

        session_webhook = getattr(msg, "session_webhook", "") or ""
        conversation_id = getattr(msg, "conversation_id", "") or ""

        if not session_webhook:
            log.warning("no session_webhook in message")
            return AckMessage.STATUS_OK, "no webhook"

        parsed = ParsedImageMessage(
            download_code=download_code,
            session_webhook=session_webhook,
            conversation_id=conversation_id,
        )

        work_dir = make_work_dir(Path(self._cfg.work_dir))

        # Dispatch to thread pool so we don't block the WebSocket.
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            self._executor,
            lambda: handle_dxf_request(
                parsed=parsed,
                dingtalk=self._dingtalk,
                work_dir=work_dir,
                settings=self._cfg,
            ),
        )

        log.info(
            "scheduled conversion: download_code=%s... conversation=%s",
            download_code[:20],
            conversation_id,
        )
        return AckMessage.STATUS_OK, "ok"


def main() -> None:
    cfg = Config.from_env()
    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Stale-state cleanup
    shutil.rmtree(cfg.work_dir, ignore_errors=True)

    # Sync REST client for downloading / uploading
    dingtalk = DingTalkClient(
        app_key=cfg.dingtalk_app_key,
        app_secret=cfg.dingtalk_app_secret,
        robot_code=cfg.dingtalk_robot_code,
    )

    # Thread pool for blocking work (image processing, API calls)
    executor = ThreadPoolExecutor(max_workers=cfg.max_workers)

    # Stream client — receives messages via WebSocket
    credential = dingtalk_stream.Credential(
        cfg.dingtalk_app_key, cfg.dingtalk_app_secret
    )
    stream_client = dingtalk_stream.DingTalkStreamClient(credential)
    handler = DxfBotHandler(cfg, dingtalk, executor)
    stream_client.register_callback_handler(ChatbotMessage.TOPIC, handler)

    # Health server in daemon thread
    app = _build_app()

    def _run_health() -> None:
        uvicorn.run(app, host="0.0.0.0", port=cfg.health_port, log_level="warning")

    health_thread = threading.Thread(target=_run_health, daemon=True, name="health")
    health_thread.start()
    log.info("health server listening on :%s", cfg.health_port)

    # Block forever on the Stream connection
    log.info("starting DingTalk Stream client...")
    stream_client.start_forever()


if __name__ == "__main__":
    main()
