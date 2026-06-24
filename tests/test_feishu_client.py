"""Tests for app.feishu_client.

We mock the underlying lark client and verify our wrapper translates method
calls and return values correctly.
"""

from __future__ import annotations

import json

import pytest

from app.feishu_client import FeishuAPIError, FeishuClient


@pytest.fixture
def fake_lark(mocker):
    return mocker.Mock(name="lark_client")


@pytest.fixture
def feishu(fake_lark) -> FeishuClient:
    return FeishuClient(fake_lark)


def test_download_image_returns_bytes(feishu, fake_lark, mocker):
    import io

    fake_lark.im.v1.image.get.return_value = mocker.Mock(
        code=0, msg="ok", file=io.BytesIO(b"\xff\xd8\xff\xe0jpeg-bytes")
    )
    data = feishu.download_image("img_key_123")
    assert data == b"\xff\xd8\xff\xe0jpeg-bytes"
    fake_lark.im.v1.image.get.assert_called_once()
    # Request should carry the image_key
    req = fake_lark.im.v1.image.get.call_args.args[0]
    assert req.image_key == "img_key_123"


def test_download_image_raises_on_error(feishu, fake_lark, mocker):
    fake_lark.im.v1.image.get.return_value = mocker.Mock(code=999, msg="oops", file=None)
    with pytest.raises(FeishuAPIError) as exc:
        feishu.download_image("img_key")
    assert "999" in str(exc.value)


def test_upload_file_returns_file_key(feishu, fake_lark, tmp_path, mocker):
    file_path = tmp_path / "out.dxf"
    file_path.write_bytes(b"DXF data")
    fake_lark.im.v1.file.create.return_value = mocker.Mock(
        code=0, msg="ok", data=mocker.Mock(file_key="file_abc")
    )
    key = feishu.upload_file(file_path)
    assert key == "file_abc"
    fake_lark.im.v1.file.create.assert_called_once()
    req = fake_lark.im.v1.file.create.call_args.args[0]
    body = req.request_body
    assert body.file_name == "out.dxf"
    assert body.file_type == "stream"
    assert body.file is not None
    body.file.close()


def test_upload_image_returns_image_key(feishu, fake_lark, tmp_path, mocker):
    img_path = tmp_path / "preview.png"
    img_path.write_bytes(b"\x89PNG fake bytes")
    fake_lark.im.v1.image.create.return_value = mocker.Mock(
        code=0, msg="ok", data=mocker.Mock(image_key="img_xyz")
    )
    key = feishu.upload_image(img_path)
    assert key == "img_xyz"
    fake_lark.im.v1.image.create.assert_called_once()
    req = fake_lark.im.v1.image.create.call_args.args[0]
    body = req.request_body
    assert body.image_type == "message"
    assert body.image is not None
    body.image.close()


def test_reply_text_sends_to_message(feishu, fake_lark, mocker):
    fake_lark.im.v1.message.reply.return_value = mocker.Mock(code=0, msg="ok")
    feishu.reply_text("om_msg_1", "正在处理...")
    fake_lark.im.v1.message.reply.assert_called_once()
    req = fake_lark.im.v1.message.reply.call_args.args[0]
    assert req.message_id == "om_msg_1"
    body = req.request_body
    assert body.msg_type == "text"
    content = json.loads(body.content)
    assert content["text"] == "正在处理..."


def test_send_post_message_with_image_and_file(feishu, fake_lark, mocker):
    fake_lark.im.v1.message.create.return_value = mocker.Mock(code=0, msg="ok")
    feishu.send_post_message(
        receive_id="oc_chat_1",
        receive_id_type="chat_id",
        text="转换成功 (12 个轮廓)",
        image_key="img_xyz",
        file_key="file_abc",
    )
    fake_lark.im.v1.message.create.assert_called_once()
    req = fake_lark.im.v1.message.create.call_args.args[0]
    assert req.receive_id_type == "chat_id"
    body = req.request_body
    assert body.receive_id == "oc_chat_1"
    assert body.msg_type == "post"
    content = json.loads(body.content)
    flat = json.dumps(content, ensure_ascii=False)
    assert "img_xyz" in flat
    assert "file_abc" in flat
    assert "转换成功" in flat


def test_send_post_message_without_preview(feishu, fake_lark, mocker):
    fake_lark.im.v1.message.create.return_value = mocker.Mock(code=0, msg="ok")
    feishu.send_post_message(
        receive_id="oc_chat_1",
        receive_id_type="chat_id",
        text="仅 DXF",
        file_key="file_abc",
    )
    req = fake_lark.im.v1.message.create.call_args.args[0]
    content = json.loads(req.request_body.content)
    flat = json.dumps(content, ensure_ascii=False)
    assert "file_abc" in flat
    assert "img_" not in flat
