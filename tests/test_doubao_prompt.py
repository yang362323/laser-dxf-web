"""Tests for app.doubao_prompt."""

from __future__ import annotations

from app.doubao_prompt import DEFAULT_PROMPT


def test_default_prompt_is_non_empty_string():
    assert isinstance(DEFAULT_PROMPT, str)
    assert DEFAULT_PROMPT.strip() != ""


def test_default_prompt_contains_all_four_instructions():
    # The four fixed instructions must all appear; order is significant
    # for the model's interpretation but not asserted here.
    fragments = [
        "提高图片清晰度",
        "logo 摆正",
        "logo 改为纯黑色",
        "背景改成纯白",
    ]
    for fragment in fragments:
        assert fragment in DEFAULT_PROMPT, f"missing fragment: {fragment!r}"
