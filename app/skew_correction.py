"""Detect and correct skew/rotation in an image before normalization.

Uses OpenCV to find the dominant orientation of the content and rotate
the image so the subject is axis-aligned. This is a deterministic
geometric correction — far more reliable than asking an AI model to
"straighten" things.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

#: Ignore angles smaller than this (degrees). Tiny corrections are often
#: noise from the contour detector rather than real skew.
MIN_ANGLE_DEG = 0.5

#: Maximum absolute correction angle. Beyond this we assume the detection
#: is wrong (e.g. a circular logo with no clear orientation).
MAX_ANGLE_DEG = 45.0


@dataclass(frozen=True)
class SkewResult:
    """Result of skew detection and correction."""

    corrected_bytes: bytes
    angle_deg: float
    was_corrected: bool


def correct(image_bytes: bytes) -> SkewResult:
    """Detect and correct skew in *image_bytes*.

    Returns the corrected image (PNG bytes) and the detected angle.
    If no significant skew is found, returns the original bytes unchanged.
    """
    # Decode image
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        log.warning("skew_correction: cannot decode image, returning original")
        return SkewResult(
            corrected_bytes=image_bytes, angle_deg=0.0, was_corrected=False
        )

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Threshold: content becomes white (255), background black (0).
    # Otsu works well for logos on contrasting backgrounds.
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Find the dominant rotation angle via the largest contour's minAreaRect.
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        log.info("skew_correction: no contours found")
        return SkewResult(
            corrected_bytes=image_bytes, angle_deg=0.0, was_corrected=False
        )

    # Use the largest contour (by area) to estimate the skew.
    largest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest)
    if area < 100:
        log.info("skew_correction: largest contour too small (area=%d)", int(area))
        return SkewResult(
            corrected_bytes=image_bytes, angle_deg=0.0, was_corrected=False
        )

    rect = cv2.minAreaRect(largest)
    angle = rect[2]

    # minAreaRect returns an angle in [-90, 0). Convert to the actual tilt.
    # If width < height, the angle is measured from vertical; adjust.
    (rw, rh) = rect[1]
    if rw < rh:
        angle = angle + 90.0

    # Normalise to [-45, +45]
    if angle > 45:
        angle -= 90
    elif angle < -45:
        angle += 90

    # Ignore tiny angles — they're usually noise.
    if abs(angle) < MIN_ANGLE_DEG:
        log.info("skew_correction: angle too small (%.1f°), skipping", angle)
        return SkewResult(
            corrected_bytes=image_bytes, angle_deg=0.0, was_corrected=False
        )

    if abs(angle) > MAX_ANGLE_DEG:
        log.info("skew_correction: angle too large (%.1f°), skipping", angle)
        return SkewResult(
            corrected_bytes=image_bytes, angle_deg=0.0, was_corrected=False
        )

    # Rotate to correct
    h, w = img.shape[:2]
    center = (w // 2, h // 2)
    rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)

    # Compute new bounds so nothing is cropped
    cos = abs(rot_mat[0, 0])
    sin = abs(rot_mat[0, 1])
    new_w = int(h * sin + w * cos)
    new_h = int(h * cos + w * sin)
    rot_mat[0, 2] += (new_w / 2.0) - center[0]
    rot_mat[1, 2] += (new_h / 2.0) - center[1]

    rotated = cv2.warpAffine(
        img,
        rot_mat,
        (new_w, new_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )

    # Encode back to PNG bytes
    success, buf = cv2.imencode(".png", rotated)
    if not success:
        log.warning("skew_correction: failed to encode corrected image")
        return SkewResult(
            corrected_bytes=image_bytes, angle_deg=0.0, was_corrected=False
        )

    log.info("skew_correction: corrected %.1f° skew", angle)
    return SkewResult(
        corrected_bytes=buf.tobytes(), angle_deg=angle, was_corrected=True
    )
