"""Tests for app.doubao_normalizer."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.doubao_normalizer import (
    DoubaoAPIError,
    NormalizedImage,
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