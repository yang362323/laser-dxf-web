"""Tests for app.doubao_normalizer."""

from __future__ import annotations

import io

import httpx
import pytest
from openai import APIConnectionError, APIStatusError
from PIL import Image

from app.doubao_normalizer import (
    DoubaoAPIError,
    NormalizedImage,
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