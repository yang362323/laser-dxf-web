"""Tests for app.preview."""

from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest
from PIL import Image

from app.preview import render


def _make_simple_dxf(path: Path) -> Path:
    doc = ezdxf.new(dxfversion="R2010")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (10, 0), (10, 5), (0, 5)], close=True)
    msp.add_lwpolyline([(2, 1), (4, 1), (4, 3), (2, 3)], close=True)
    doc.saveas(str(path))
    return path


def test_render_produces_non_empty_png(tmp_path: Path):
    dxf = _make_simple_dxf(tmp_path / "test.dxf")
    png = tmp_path / "preview.png"
    render(dxf, png)
    assert png.exists()
    img = Image.open(png)
    assert img.size[0] > 0
    assert img.size[1] > 0


def test_render_respects_max_size(tmp_path: Path):
    dxf = _make_simple_dxf(tmp_path / "test.dxf")
    png = tmp_path / "preview.png"
    render(dxf, png, max_dim=50)
    img = Image.open(png)
    assert max(img.size) <= 50


def test_render_raises_on_missing_dxf(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        render(tmp_path / "missing.dxf", tmp_path / "out.png")
