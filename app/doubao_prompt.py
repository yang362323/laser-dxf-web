"""Fixed Chinese prompt for the Doubao image normalization step.

Single source of truth for the prompt sent to the model on every /dxf
request. Edit only with intent — the spec ties this exact wording to the
expected behaviour of the pipeline.
"""

from __future__ import annotations

DEFAULT_PROMPT: str = (
    "第一步：检测图片中的 logo 或图形是否歪斜，如果有倾斜，请精确旋转图片使主体图案"
    "完全水平对齐（横平竖直），这是最重要的步骤，必须优先完成。"
    "第二步：提高图片清晰度，锐化边缘。"
    "第三步：将 logo 或图形的所有线条改为纯黑色 (#000000)，线条要清晰连续。"
    "第四步：将背景改为纯白色 (#FFFFFF)，不能有任何灰色残留。"
)
