"""Process entry point.

Wires:
    Config -> lark_oapi.Client (for API calls) -> FeishuClient wrapper
    Config -> EventDispatcherHandler (subscribes to message-receive events)
    Config -> FastAPI app (only /healthz)

Run with: ``python -m app.main``.
"""

from __future__ import annotations

import logging
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import lark_oapi as lark
import uvicorn
from fastapi import FastAPI
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler

from .config import Config
from .feishu_client import FeishuClient
from .handlers import (
    NoImageError,
    handle_dxf_request,
    make_work_dir,
    parse_slash_command_event,
)

log = logging.getLogger(__name__)


def _build_app(cfg: Config) -> FastAPI:
    """Build the FastAPI app that exposes /healthz."""
    app = FastAPI(title="feishu-laser-dxf-bot")

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app


def _make_message_handler(cfg: Config, feishu: FeishuClient, executor: ThreadPoolExecutor):
    """Build a callback that handles incoming Feishu messages.

    The handler is registered with ``EventDispatcherHandler`` for the
    ``p2.im.message.receive_v1`` event. It:
    1. Converts the typed event to the dict shape parse_slash_command_event expects.
    2. Tries to parse a /dxf command with an image.
    3. On success, schedules a conversion on the thread pool.
    """

    def _on_message(data: P2ImMessageReceiveV1) -> None:
        try:
            event_dict = _typed_event_to_dict(data)
        except AttributeError:
            log.warning("malformed event: %r", data)
            return

        try:
            parsed = parse_slash_command_event(event_dict)
        except NoImageError as e:
            log.info("ignoring message (not a /dxf image): %s", e)
            return

        work_dir = make_work_dir(Path(cfg.work_dir))
        executor.submit(handle_dxf_request, parsed=parsed, feishu=feishu, work_dir=work_dir)
        log.info(
            "scheduled /dxf conversion: image_key=%s chat=%s msg=%s",
            parsed.image_key,
            parsed.chat_id,
            parsed.message_id,
        )

    return _on_message


def _typed_event_to_dict(data: P2ImMessageReceiveV1) -> dict:
    """Convert a P2ImMessageReceiveV1 typed object into the flat dict shape
    that :func:`app.handlers.parse_slash_command_event` accepts."""
    msg = data.event.message
    header_type = data.header.event_type if data.header else "im.message.receive_v1"
    return {
        "header": {"event_type": header_type},
        "event": {
            "message_id": msg.message_id or "",
            "chat_id": msg.chat_id or "",
            "chat_type": msg.chat_type or "",
            "message": {
                "message_id": msg.message_id or "",
                "chat_id": msg.chat_id or "",
                "message_type": msg.message_type or "",
                "content": msg.content or "",
            },
        },
    }


def main() -> None:
    cfg = Config.from_env()
    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Stale-state cleanup (spec §5).
    shutil.rmtree(cfg.work_dir, ignore_errors=True)

    lark_api = (
        lark.Client.builder()
        .app_id(cfg.app_id)
        .app_secret(cfg.app_secret)
        .log_level(lark.LogLevel.INFO)
        .build()
    )
    feishu = FeishuClient(lark_api)

    executor = ThreadPoolExecutor(max_workers=cfg.max_workers)

    handler = (
        EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_make_message_handler(cfg, feishu, executor))
        .build()
    )

    ws_client = lark.ws.Client(
        app_id=cfg.app_id,
        app_secret=cfg.app_secret,
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )

    def _run_ws() -> None:
        ws_client.start()

    threading.Thread(target=_run_ws, daemon=True, name="feishu-ws").start()

    log.info("starting health server on :%s", cfg.health_port)
    app = _build_app(cfg)
    uvicorn.run(app, host="0.0.0.0", port=cfg.health_port, log_level="warning")


if __name__ == "__main__":
    main()
