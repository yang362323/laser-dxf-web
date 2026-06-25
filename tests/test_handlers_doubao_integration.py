"""Handler-level tests covering the Doubao normalization step."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import converter, doubao_normalizer, handlers, preview
from app.handlers import handle_dxf_request, parse_slash_command_event


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


@pytest.fixture
def fake_doubao_ok(mocker, tmp_path):
    """Patch doubao_normalizer.run to return a fixed small PNG."""
    cleaned_path = tmp_path / "normalized.png"
    cleaned_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 16)
    fake = MagicMock()
    fake.cleaned_bytes = cleaned_path.read_bytes()
    fake.cleaned_path = cleaned_path
    mocker.patch.object(handlers.doubao_normalizer, "run", return_value=fake)
    return fake


@pytest.fixture
def fake_doubao_fail(mocker):
    from app.doubao_normalizer import DoubaoAPIError

    err = DoubaoAPIError(user_msg="网络问题", internal_msg="boom")
    mocker.patch.object(handlers.doubao_normalizer, "run", side_effect=err)


@pytest.fixture
def fake_converter(mocker, tmp_path):
    fake_result = converter.ConversionResult(
        dxf_path=tmp_path / "out.dxf", shape_count=5
    )
    mocker.patch.object(handlers.converter, "run", return_value=fake_result)


@pytest.fixture
def fake_preview(mocker, tmp_path):
    preview_path = tmp_path / "preview.png"
    preview_path.write_bytes(b"\x89PNG")
    mocker.patch.object(handlers.preview, "render", return_value=preview_path)


def _settings(**overrides):
    from app.config import Config

    base = dict(
        app_id="cli_x",
        app_secret="secret",
        log_level="INFO",
        health_port=8080,
        work_dir="/tmp/x",
        convert_timeout_s=60,
        max_workers=3,
        ark_api_key="ark-test",
        ark_model="doubao-seedream-5-0-2 60128",
    )
    base.update(overrides)
    return Config(**base)


def test_happy_path_passes_cleaned_key_to_post(
    mocker, tmp_path, fake_doubao_ok, fake_converter, fake_preview
):
    fake_feishu = mocker.Mock()
    fake_feishu.download_image.return_value = b"original"
    fake_feishu.upload_file.return_value = "file_key_dxf"
    fake_feishu.upload_image.return_value = "image_key_preview"
    fake_feishu.upload_image_bytes.return_value = "image_key_cleaned"

    handle_dxf_request(
        parsed=parse_slash_command_event(_make_event()),
        feishu=fake_feishu,
        work_dir=tmp_path,
        settings=_settings(),
    )

    # The cleaned image key was uploaded and forwarded to the post
    fake_feishu.upload_image_bytes.assert_called_once()
    fake_feishu.send_post_message.assert_called_once()
    kwargs = fake_feishu.send_post_message.call_args.kwargs
    assert kwargs["image_keys"] == ["image_key_cleaned", "image_key_preview"]
    assert kwargs["file_key"] == "file_key_dxf"


def test_doubao_failure_replies_and_skips_converter(
    mocker, tmp_path, fake_doubao_fail
):
    fake_feishu = mocker.Mock()
    fake_feishu.download_image.return_value = b"original"

    handle_dxf_request(
        parsed=parse_slash_command_event(_make_event()),
        feishu=fake_feishu,
        work_dir=tmp_path,
        settings=_settings(),
    )

    texts = [c.args[1] for c in fake_feishu.reply_text.call_args_list]
    assert any("AI 标准化失败" in t for t in texts)
    assert any("网络问题" in t for t in texts)
    fake_feishu.send_post_message.assert_not_called()


def test_doubao_ok_but_converter_fails(
    mocker, tmp_path, fake_doubao_ok, fake_preview
):
    from app import handlers

    mocker.patch.object(
        handlers.converter, "run", side_effect=FileNotFoundError("bad")
    )
    fake_feishu = mocker.Mock()
    fake_feishu.download_image.return_value = b"original"

    handle_dxf_request(
        parsed=parse_slash_command_event(_make_event()),
        feishu=fake_feishu,
        work_dir=tmp_path,
        settings=_settings(),
    )

    fake_feishu.send_post_message.assert_not_called()


def test_doubao_ok_but_upload_cleaned_fails(
    mocker, tmp_path, fake_doubao_ok, fake_converter, fake_preview
):
    from app.feishu_client import FeishuAPIError

    fake_feishu = mocker.Mock()
    fake_feishu.download_image.return_value = b"original"
    fake_feishu.upload_image_bytes.side_effect = FeishuAPIError("nope")

    handle_dxf_request(
        parsed=parse_slash_command_event(_make_event()),
        feishu=fake_feishu,
        work_dir=tmp_path,
        settings=_settings(),
    )

    texts = [c.args[1] for c in fake_feishu.reply_text.call_args_list]
    assert any("清理后图片上传失败" in t for t in texts)
    fake_feishu.send_post_message.assert_not_called()