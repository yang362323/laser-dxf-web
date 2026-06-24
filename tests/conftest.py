"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest


@pytest.fixture
def sample_jpg(tmp_path: Path) -> Path:
    """Create a small black-on-white JPG with a clear shape for testing."""
    img = np.full((400, 600, 3), 255, dtype=np.uint8)
    cv2.rectangle(img, (100, 100), (300, 300), (0, 0, 0), thickness=-1)
    cv2.putText(
        img,
        "DXF TEST",
        (150, 380),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (0, 0, 0),
        thickness=2,
    )
    out = tmp_path / "sample.jpg"
    cv2.imwrite(str(out), img)
    return out
