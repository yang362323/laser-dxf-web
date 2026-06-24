"""Tests for app.converter."""

from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest

from app.converter import ConversionResult, run


def test_run_produces_dxf_with_polylines(sample_jpg: Path, tmp_path: Path):
    out_dxf = tmp_path / "out.dxf"
    result = run(
        image_bytes=sample_jpg.read_bytes(),
        image_suffix=".jpg",
        out_dxf_path=out_dxf,
        work_dir=tmp_path / "wd",
    )
    assert isinstance(result, ConversionResult)
    assert result.dxf_path == out_dxf
    assert out_dxf.exists()
    assert result.shape_count > 0
    doc = ezdxf.readfile(str(out_dxf))
    assert len(doc.modelspace().query("LWPOLYLINE")) == result.shape_count


def test_run_accepts_png_bytes(sample_jpg: Path, tmp_path: Path):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.open(sample_jpg).save(buf, format="PNG")
    out_dxf = tmp_path / "out.dxf"
    result = run(
        image_bytes=buf.getvalue(),
        image_suffix=".png",
        out_dxf_path=out_dxf,
        work_dir=tmp_path / "wd",
    )
    assert out_dxf.exists()
    assert result.shape_count > 0


def test_run_writes_input_to_work_dir(sample_jpg: Path, tmp_path: Path):
    work_dir = tmp_path / "wd"
    run(
        image_bytes=sample_jpg.read_bytes(),
        image_suffix=".jpg",
        out_dxf_path=tmp_path / "out.dxf",
        work_dir=work_dir,
    )
    inputs = list(work_dir.glob("input.*"))
    assert len(inputs) == 1
    assert inputs[0].suffix == ".jpg"


def test_run_raises_on_invalid_image(tmp_path: Path):
    with pytest.raises(Exception):  # image_to_dxf raises FileNotFoundError on bad bytes
        run(
            image_bytes=b"not an image",
            image_suffix=".jpg",
            out_dxf_path=tmp_path / "out.dxf",
            work_dir=tmp_path / "wd",
        )