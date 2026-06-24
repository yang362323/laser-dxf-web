"""Fixed Chinese prompt for the Doubao image normalization step.

Single source of truth for the prompt sent to the model on every /dxf
request. Edit only with intent — the spec ties this exact wording to the
expected behaviour of the pipeline.
"""

from __future__ import annotations

DEFAULT_PROMPT: str = (
    "先提高图片清晰度，把图片的 logo 摆正，"
    "图片中的 logo 改为纯黑色，然后背景改成纯白。"
)
