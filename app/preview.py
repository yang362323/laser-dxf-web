"""Render a DXF file to a PNG preview image."""

from __future__ import annotations

from pathlib import Path

import ezdxf
import matplotlib
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from PIL import Image

matplotlib.use("Agg")  # headless backend; safe in Docker / no DISPLAY


def render(dxf_path: Path, png_path: Path, *, max_dim: int = 1200) -> Path:
    """Render *dxf_path* to *png_path*.

    Parameters
    ----------
    dxf_path:
        Source DXF file. Must exist.
    png_path:
        Destination PNG path. Parent dirs are created. Will be overwritten.
    max_dim:
        Cap the longer image edge at this many pixels, preserving aspect.
        Values <= 0 disable downscaling.

    Returns
    -------
    Path
        The same path as ``png_path``.
    """
    dxf_path = Path(dxf_path)
    png_path = Path(png_path)
    if not dxf_path.exists():
        raise FileNotFoundError(f"dxf not found: {dxf_path}")
    png_path.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()

    _render_to_file(doc, msp, png_path)

    if max_dim > 0:
        _downscale_in_place(png_path, max_dim)

    return png_path


def _render_to_file(doc, msp, png_path: Path) -> None:
    """One-shot render of *msp* into *png_path* at a default 8x6 inch figure."""
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(8.0, 6.0), dpi=72)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    backend = MatplotlibBackend(ax)
    Frontend(RenderContext(doc), backend).draw_layout(msp, finalize=True)
    fig.savefig(str(png_path), format="png", dpi=72)
    plt.close(fig)


def _downscale_in_place(png_path: Path, max_dim: int) -> None:
    """Resize *png_path* so the longer edge is at most *max_dim* pixels."""
    img = Image.open(str(png_path))
    nw, nh = img.size
    if max(nw, nh) <= max_dim:
        img.close()
        return
    scale = max_dim / max(nw, nh)
    new_size = (max(1, int(nw * scale)), max(1, int(nh * scale)))
    resized = img.resize(new_size, Image.LANCZOS)
    resized.save(str(png_path))
    img.close()
    resized.close()
