"""Tests for app.doubao_normalizer."""

from __future__ import annotations

import base64
import io
from unittest.mock import MagicMock

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, OpenAI
from PIL import Image

from app.doubao_normalizer import (
    DoubaoAPIError,
    NormalizedImage,
    _call_once,
    _classify_error,
    _resize_if_needed,
)

MAX_LONG_EDGE = 2048


def _make_png_bytes(width: int, height: int) -> bytes:
    """Return PNG bytes of a solid-color image of the given size."""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_resize_no_op_when_under_limit():
    original = _make_png_bytes(1000, 1000)
    out = _resize_if_needed(original)
    assert out == original


def test_resize_no_op_when_exactly_at_limit():
    original = _make_png_bytes(MAX_LONG_EDGE, MAX_LONG_EDGE)
    out = _resize_if_needed(original)
    assert out == original


def test_resize_scales_down_when_over_limit():
    original = _make_png_bytes(5000, 3000)
    out = _resize_if_needed(original)
    img = Image.open(io.BytesIO(out))
    # Long edge must be at the cap; aspect ratio must be preserved.
    # Pillow's thumbnail() rounds rather than floors, so 5000x3000 -> 2048x1229.
    assert max(img.size) == MAX_LONG_EDGE
    assert img.size == (2048, 1229)


def test_resize_returns_png_bytes():
    original = _make_png_bytes(5000, 5000)
    out = _resize_if_needed(original)
    # PNG signature: 89 50 4E 47
    assert out[:4] == b"\x89PNG"


def _make_status_error(status: int, code: str | None = None) -> APIStatusError:
    """Build an APIStatusError suitable for testing _classify_error."""
    fake_request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    fake_response = httpx.Response(status_code=status, headers={}, request=fake_request)
    body = {"code": code} if code is not None else None
    return APIStatusError(message="boom", response=fake_response, body=body)


def test_classify_connection_error_is_retryable():
    decision = _classify_error(APIConnectionError(request=None))
    assert decision.retry is True
    assert "网络" in decision.user_msg


def test_classify_5xx_is_retryable():
    decision = _classify_error(_make_status_error(500))
    assert decision.retry is True
    assert "服务" in decision.user_msg


def test_classify_4xx_audit_reject_is_terminal():
    decision = _classify_error(_make_status_error(400, "AuditReject"))
    assert decision.retry is False
    assert "拒绝" in decision.user_msg


def test_classify_4xx_arrearage_is_terminal():
    decision = _classify_error(_make_status_error(401, "Arrearage"))
    assert decision.retry is False
    assert "欠费" in decision.user_msg


def test_classify_4xx_generic_is_terminal():
    decision = _classify_error(_make_status_error(400))
    assert decision.retry is False


def test_classify_401_403_is_terminal_with_auth_msg():
    for s in (401, 403):
        decision = _classify_error(_make_status_error(s))
        assert decision.retry is False
        assert "鉴权" in decision.user_msg


def _fake_b64_response(b64_png: str) -> MagicMock:
    """Build a Mock that mimics the openai ImagesResponse shape we use."""
    resp = MagicMock()
    resp.data = [MagicMock(b64_json=b64_png, url=None)]
    return resp


def test_call_once_returns_decoded_bytes():
    png_bytes = _make_png_bytes(8, 8)
    b64 = base64.b64encode(png_bytes).decode()
    client = MagicMock(spec=OpenAI)
    client.images.generate.return_value = _fake_b64_response(b64)

    out = _call_once(
        client=client,
        model="doubao-seedream-5-0-2 60128",
        prompt="do the thing",
        image_bytes=b"original",
    )
    assert out == png_bytes


def test_call_once_sends_image_as_data_url():
    png_bytes = _make_png_bytes(8, 8)
    b64 = base64.b64encode(png_bytes).decode()
    client = MagicMock(spec=OpenAI)
    client.images.generate.return_value = _fake_b64_response(b64)

    _call_once(
        client=client,
        model="m",
        prompt="p",
        image_bytes=b"orig",
    )
    client.images.generate.assert_called_once()
    kwargs = client.images.generate.call_args.kwargs
    assert kwargs["model"] == "m"
    assert kwargs["prompt"] == "p"
    assert isinstance(kwargs["image"], list) and len(kwargs["image"]) == 1
    sent = kwargs["image"][0]
    assert sent.startswith("data:image/png;base64,")
    # Round-trip the base64 portion back to bytes
    payload = sent.split(",", 1)[1]
    assert base64.b64decode(payload) == b"orig"


def test_call_once_raises_when_no_b64_and_no_url():
    client = MagicMock(spec=OpenAI)
    resp = MagicMock()
    resp.data = [MagicMock(b64_json=None, url=None)]
    client.images.generate.return_value = resp

    with pytest.raises(DoubaoAPIError) as exc_info:
        _call_once(
            client=client, model="m", prompt="p", image_bytes=b"x"
        )
    assert "返回数据异常" in exc_info.value.user_msg


def test_call_once_raises_on_garbage_b64():
    client = MagicMock(spec=OpenAI)
    # Valid base64, but not valid PNG
    bad_b64 = base64.b64encode(b"not a png").decode()
    client.images.generate.return_value = _fake_b64_response(bad_b64)

    with pytest.raises(DoubaoAPIError) as exc_info:
        _call_once(
            client=client, model="m", prompt="p", image_bytes=b"x"
        )
    assert "返回数据异常" in exc_info.value.user_msg