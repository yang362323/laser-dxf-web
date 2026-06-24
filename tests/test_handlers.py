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
    event = _make_event()
    event["event"]["message"]["message_type"] = "text"
    event["event"]["message"]["content"] = '{"text": "hello"}'
    with pytest.raises(NoImageError):
        parse_slash_command_event(event)


def test_handle_dxf_happy_path(mocker, sample_jpg: Path, tmp_path: Path):
    fake_feishu = mocker.Mock()
    fake_feishu.download_image.return_value = sample_jpg.read_bytes()
    fake_feishu.upload_file.return_value = "file_key_dxf"
    fake_feishu.upload_image.return_value = "image_key_preview"

    from app import converter, handlers, preview

    fake_result = converter.ConversionResult(dxf_path=tmp_path / "out.dxf", shape_count=5)
    mocker.patch.object(handlers.converter, "run", return_value=fake_result)
    mocker.patch.object(handlers.preview, "render", return_value=tmp_path / "preview.png")

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
    # The parse failure is upstream; the handler should not have been called.
    fake_feishu.reply_text.assert_not_called()


def test_handle_dxf_conversion_failure_replies_error(mocker, sample_jpg: Path, tmp_path: Path):
    fake_feishu = mocker.Mock()
    fake_feishu.download_image.return_value = sample_jpg.read_bytes()
    from app import converter, handlers

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


def test_handle_dxf_preview_failure_still_sends_dxf(mocker, sample_jpg: Path, tmp_path: Path):
    """If preview rendering fails, the bot should still send the DXF."""
    fake_feishu = mocker.Mock()
    fake_feishu.download_image.return_value = sample_jpg.read_bytes()
    fake_feishu.upload_file.return_value = "file_key_dxf"
    # upload_image should NOT be called because preview failed

    from app import converter, handlers, preview

    fake_result = converter.ConversionResult(dxf_path=tmp_path / "out.dxf", shape_count=3)
    mocker.patch.object(handlers.converter, "run", return_value=fake_result)
    mocker.patch.object(handlers.preview, "render", side_effect=RuntimeError("render fail"))

    event = _make_event()
    parsed = parse_slash_command_event(event)
    handle_dxf_request(
        parsed=parsed,
        feishu=fake_feishu,
        work_dir=tmp_path / "wd",
    )

    fake_feishu.upload_image.assert_not_called()
    fake_feishu.send_post_message.assert_called_once()
    kwargs = fake_feishu.send_post_message.call_args.kwargs
    assert kwargs["image_key"] is None
    assert kwargs["file_key"] == "file_key_dxf"
