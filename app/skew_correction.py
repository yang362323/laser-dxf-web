"""Detect and correct skew/rotation in an image before normalization.

Uses Hough line detection to find the dominant orientation of straight
edges in the image, then rotates so the subject is axis-aligned.
This is far more reliable than minAreaRect on contours for logos
with straight lines and geometric shapes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from math import degrees

import cv2
import numpy as np

log = logging.getLogger(__name__)

#: Angles within this band around 0°, 90°, -90° are considered "aligned".
_ALIGNED_TOLERANCE = 0.3  # degrees

#: Ignore angles smaller than this (noise floor).
_MIN_ANGLE = 0.15  # degrees

#: Maximum absolute correction angle.
_MAX_ANGLE = 45.0  # degrees

#: Hough line threshold (votes). Scaled relative to image diagonal.
_HOUGH_THRESHOLD_RATIO = 0.05

#: Hough probabilistic — minimum line length as fraction of diagonal.
_MIN_LINE_LENGTH_RATIO = 0.04

#: Hough probabilistic — max gap between segments, fraction of diagonal.
_MAX_GAP_RATIO = 0.02


@dataclass(frozen=True)
class SkewResult:
    """Result of skew detection and correction."""

    corrected_bytes: bytes
    angle_deg: float
    was_corrected: bool


def correct(image_bytes: bytes) -> SkewResult:
    """Detect and correct skew in *image_bytes*.

    Uses Hough Line Probabilistic detection to find straight edges,
    computes the consensus angle, and rotates the image to align them.
    Falls back to minAreaRect on contours if Hough finds insufficient lines.
    """
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        log.warning("skew: cannot decode image")
        return SkewResult(corrected_bytes=image_bytes, angle_deg=0.0, was_corrected=False)

    angle = _detect_angle(img)
    if angle is None:
        log.info("skew: no dominant angle detected")
        return SkewResult(corrected_bytes=image_bytes, angle_deg=0.0, was_corrected=False)

    if abs(angle) < _MIN_ANGLE:
        log.info("skew: angle too small (%.2f°), skipping", angle)
        return SkewResult(corrected_bytes=image_bytes, angle_deg=0.0, was_corrected=False)

    if abs(angle) > _MAX_ANGLE:
        log.info("skew: angle too large (%.2f°), skipping", angle)
        return SkewResult(corrected_bytes=image_bytes, angle_deg=0.0, was_corrected=False)

    corrected = _rotate_image(img, angle)
    success, buf = cv2.imencode(".png", corrected)
    if not success:
        log.warning("skew: failed to encode corrected image")
        return SkewResult(corrected_bytes=image_bytes, angle_deg=0.0, was_corrected=False)

    log.info("skew: corrected %.2f°", angle)
    return SkewResult(corrected_bytes=buf.tobytes(), angle_deg=round(angle, 2), was_corrected=True)


def _detect_angle(img: np.ndarray) -> float | None:
    """Detect the dominant rotation angle using Hough lines.

    Returns None if no clear consensus is found.
    """
    h, w = img.shape[:2]
    diag = np.sqrt(h * h + w * w)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Adaptive threshold for robustness against varying lighting
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 21, 5
    )

    # Canny edge detection
    edges = cv2.Canny(binary, 50, 150, apertureSize=3)

    # Hough probabilistic line detection
    min_len = max(20, int(diag * _MIN_LINE_LENGTH_RATIO))
    max_gap = max(5, int(diag * _MAX_GAP_RATIO))
    threshold = max(10, int(diag * _HOUGH_THRESHOLD_RATIO))

    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold,
                            minLineLength=min_len, maxLineGap=max_gap)

    angles: list[float] = []

    if lines is not None and len(lines) > 0:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle_rad = np.arctan2(y2 - y1, x2 - x1)
            angle_deg = float(degrees(angle_rad))
            # Normalize to [-45, 45] — we care about deviation from horizontal.
            while angle_deg > 45:
                angle_deg -= 90
            while angle_deg < -45:
                angle_deg += 90
            # Keep angles that deviate from 0 (horizontal) or 90 (vertical)
            # but aren't the 90° lines themselves (which are normal).
            angles.append(angle_deg)

    # If Hough found few lines, fall back to contour-based detection.
    if len(angles) < 4:
        log.info("skew: Hough found %d lines, falling back to contours", len(angles))
        return _detect_angle_contour(binary)

    # Use median angle — robust against outliers from diagonal lines.
    median = float(np.median(angles))
    return median


def _detect_angle_contour(binary: np.ndarray) -> float | None:
    """Fallback: detect angle via minAreaRect on largest contours."""
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Use top-3 largest contours, weighted by area.
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:3]
    angles: list[float] = []
    weights: list[float] = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 200:
            continue
        rect = cv2.minAreaRect(cnt)
        angle = rect[2]
        rw, rh = rect[1]
        if rw < rh:
            angle += 90
        if angle > 45:
            angle -= 90
        elif angle < -45:
            angle += 90
        angles.append(angle)
        weights.append(area)

    if not angles:
        return None

    # Weighted average
    weighted = sum(a * w for a, w in zip(angles, weights)) / sum(weights)
    return float(weighted)


def _rotate_image(img: np.ndarray, angle_deg: float) -> np.ndarray:
    """Rotate *img* by *angle_deg*, filling new pixels with white."""
    h, w = img.shape[:2]
    center = (w // 2, h // 2)
    rot_mat = cv2.getRotationMatrix2D(center, angle_deg, 1.0)

    # Expand canvas so no content is cropped
    cos = abs(rot_mat[0, 0])
    sin = abs(rot_mat[0, 1])
    new_w = int(h * sin + w * cos)
    new_h = int(h * cos + w * sin)
    rot_mat[0, 2] += (new_w / 2.0) - center[0]
    rot_mat[1, 2] += (new_h / 2.0) - center[1]

    return cv2.warpAffine(
        img, rot_mat, (new_w, new_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )
