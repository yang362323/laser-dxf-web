"""Chinese prompt for Doubao image preprocessing.

The model handles clarity and colour normalisation. Geometric correction
(skew) is done deterministically after this step by OpenCV Hough lines.
"""

from __future__ import annotations

DEFAULT_PROMPT: str = (
    "你是一个专业的图像预处理助手。请严格按照以下步骤处理图片：\n\n"
    "第一步：大幅提高图片清晰度和锐度，使边缘更加锐利分明。\n\n"
    "第二步：将图片中的所有图形和文字改为纯黑色（#000000），线条必须连续"
    "不断裂。\n\n"
    "第三步：将背景完全改为纯白色（#FFFFFF），不能有任何灰色残留、阴影或"
    "杂质。\n\n"
    "最终结果必须是一张干净的纯黑图形在纯白背景上的图片。"
)
