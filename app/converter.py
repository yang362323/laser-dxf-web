"""Per-request image -> DXF conversion.

Wraps :func:`image_to_dxf.convert` with explicit file paths so the caller
(handlers.py) can manage a per-request working directory and clean up
afterwards. Does NOT clean up by itself; the caller is responsible for
removing `work_dir` once the result has been delivered.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from image_to_dxf import convert as itd_convert


@dataclass(frozen=True)
class ConversionResult:
    """Result of a single conversion."""

    dxf_path: Path
    shape_count: int


def run(
    *,
    image_bytes: bytes,
    image_suffix: str,
    out_dxf_path: Path,
    work_dir: Path,
) -> ConversionResult:
    """Write *image_bytes* into *work_dir*, convert to DXF at *out_dxf_path*.

    Parameters
    ----------
    image_bytes:
        Raw image bytes (decoded by OpenCV inside image_to_dxf).
    image_suffix:
        File extension including the leading dot, e.g. ``.jpg`` or ``.png``.
    out_dxf_path:
        Destination DXF path. Its parent directory will be created.
    work_dir:
        Per-request scratch directory. Will be created if missing.
        Caller is responsible for cleanup.

    Returns
    -------
    ConversionResult
        Path to the written DXF and the number of polylines it contains.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dxf_path.parent.mkdir(parents=True, exist_ok=True)

    if not image_suffix.startswith("."):
        raise ValueError(f"image_suffix must start with '.', got {image_suffix!r}")

    input_path = work_dir / f"input{image_suffix}"
    input_path.write_bytes(image_bytes)

    written_path, shapes = itd_convert(input_path, out_dxf_path)
    return ConversionResult(dxf_path=written_path, shape_count=len(shapes))
