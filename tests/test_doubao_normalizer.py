"""Tests for app.doubao_normalizer."""

from __future__ import annotations

import base64
import io
import time
from unittest.mock import MagicMock, patch

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
    run as doubao_run,
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


def test_resize_returns_bytes_unchanged_when_unrecognised():
    """Non-image bytes pass through unchanged so downstream callers can
    decide what to do (e.g. surface a 4xx from Ark)."""
    garbage = b"not an image at all"
    assert _resize_if_needed(garbage) == garbage


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


# --- run() orchestrator ---------------------------------------------------


def _valid_png_b64() -> str:
    return base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 16).decode()


def _ok_response() -> MagicMock:
    resp = MagicMock()
    resp.data = [MagicMock(b64_json=_valid_png_b64(), url=None)]
    return resp


# --- happy path ----------------------------------------------------------


def test_run_happy_path_writes_file_and_returns_bytes(tmp_path):
    client = MagicMock(spec=OpenAI)
    client.images.generate.return_value = _ok_response()
    with patch("app.doubao_normalizer.time.sleep"):  # never sleep on success
        result = doubao_run(
            image_bytes=b"orig",
            prompt="p",
            work_dir=tmp_path,
            api_key="ark-x",
            model="m",
            client=client,
        )
    assert isinstance(result, NormalizedImage)
    assert result.cleaned_bytes.startswith(b"\x89PNG")
    assert result.cleaned_path.exists()
    assert result.cleaned_path.read_bytes() == result.cleaned_bytes
    # Exactly one SDK call, no sleep
    assert client.images.generate.call_count == 1


# --- resize --------------------------------------------------------------


def test_run_resizes_input_before_calling_sdk(tmp_path):
    big = _make_png_bytes(5000, 3000)
    client = MagicMock(spec=OpenAI)
    client.images.generate.return_value = _ok_response()

    doubao_run(
        image_bytes=big,
        prompt="p",
        work_dir=tmp_path,
        api_key="ark-x",
        model="m",
        client=client,
    )
    # The bytes sent to Ark should be a resized PNG, <= 2048 on long edge
    kwargs = client.images.generate.call_args.kwargs
    sent = kwargs["image"][0]
    payload = base64.b64decode(sent.split(",", 1)[1])
    img = Image.open(io.BytesIO(payload))
    assert max(img.size) <= 2048


def test_run_does_not_resize_when_under_limit(tmp_path):
    small = _make_png_bytes(1000, 1000)
    client = MagicMock(spec=OpenAI)
    client.images.generate.return_value = _ok_response()

    doubao_run(
        image_bytes=small,
        prompt="p",
        work_dir=tmp_path,
        api_key="ark-x",
        model="m",
        client=client,
    )
    kwargs = client.images.generate.call_args.kwargs
    sent = kwargs["image"][0]
    payload = base64.b64decode(sent.split(",", 1)[1])
    assert payload == small  # bytes unchanged


# --- retry semantics -----------------------------------------------------


def test_run_retries_once_on_connection_error_then_succeeds(tmp_path):
    client = MagicMock(spec=OpenAI)
    client.images.generate.side_effect = [
        APIConnectionError(request=None),
        _ok_response(),
    ]
    with patch("app.doubao_normalizer.time.sleep") as mock_sleep:
        result = doubao_run(
            image_bytes=b"x", prompt="p", work_dir=tmp_path,
            api_key="k", model="m", client=client,
        )
    assert isinstance(result, NormalizedImage)
    assert client.images.generate.call_count == 2
    mock_sleep.assert_called_once_with(1.0)


def test_run_connection_error_two_strikes_raises(tmp_path):
    client = MagicMock(spec=OpenAI)
    client.images.generate.side_effect = [
        APIConnectionError(request=None),
        APIConnectionError(request=None),
    ]
    with patch("app.doubao_normalizer.time.sleep"):
        with pytest.raises(DoubaoAPIError) as exc_info:
            doubao_run(
                image_bytes=b"x", prompt="p", work_dir=tmp_path,
                api_key="k", model="m", client=client,
            )
    assert "网络" in exc_info.value.user_msg
    assert client.images.generate.call_count == 2


def test_run_4xx_no_retry_raises(tmp_path):
    client = MagicMock(spec=OpenAI)
    client.images.generate.side_effect = _make_status_error(400)
    with pytest.raises(DoubaoAPIError) as exc_info:
        doubao_run(
            image_bytes=b"x", prompt="p", work_dir=tmp_path,
            api_key="k", model="m", client=client,
        )
    assert client.images.generate.call_count == 1
    assert exc_info.value.user_msg == "请求被拒绝"


def test_run_audit_reject_no_retry_raises(tmp_path):
    client = MagicMock(spec=OpenAI)
    client.images.generate.side_effect = _make_status_error(400, "AuditReject")
    with pytest.raises(DoubaoAPIError) as exc_info:
        doubao_run(
            image_bytes=b"x", prompt="p", work_dir=tmp_path,
            api_key="k", model="m", client=client,
        )
    assert client.images.generate.call_count == 1
    assert "拒绝" in exc_info.value.user_msg


def test_run_arrearage_no_retry_raises(tmp_path):
    client = MagicMock(spec=OpenAI)
    client.images.generate.side_effect = _make_status_error(401, "Arrearage")
    with pytest.raises(DoubaoAPIError) as exc_info:
        doubao_run(
            image_bytes=b"x", prompt="p", work_dir=tmp_path,
            api_key="k", model="m", client=client,
        )
    assert "欠费" in exc_info.value.user_msg


def test_run_5xx_retries_once_then_succeeds(tmp_path):
    client = MagicMock(spec=OpenAI)
    client.images.generate.side_effect = [
        _make_status_error(500),
        _ok_response(),
    ]
    with patch("app.doubao_normalizer.time.sleep"):
        result = doubao_run(
            image_bytes=b"x", prompt="p", work_dir=tmp_path,
            api_key="k", model="m", client=client,
        )
    assert isinstance(result, NormalizedImage)
    assert client.images.generate.call_count == 2


def test_run_5xx_two_strikes_raises(tmp_path):
    client = MagicMock(spec=OpenAI)
    client.images.generate.side_effect = [
        _make_status_error(500),
        _make_status_error(500),
    ]
    with patch("app.doubao_normalizer.time.sleep"):
        with pytest.raises(DoubaoAPIError) as exc_info:
            doubao_run(
                image_bytes=b"x", prompt="p", work_dir=tmp_path,
                api_key="k", model="m", client=client,
            )
    assert "服务" in exc_info.value.user_msg
    assert client.images.generate.call_count == 2


def test_run_401_403_no_retry_raises(tmp_path):
    for s in (401, 403):
        client = MagicMock(spec=OpenAI)
        client.images.generate.side_effect = _make_status_error(s)
        with pytest.raises(DoubaoAPIError) as exc_info:
            doubao_run(
                image_bytes=b"x", prompt="p", work_dir=tmp_path,
                api_key="k", model="m", client=client,
            )
        assert client.images.generate.call_count == 1
        assert "鉴权" in exc_info.value.user_msg