from __future__ import annotations

from .models import Keyframe


def optional_ai_review(keyframes: list[Keyframe], max_frames: int) -> dict:
    """Reserved interface for future AI aesthetic review.

    The MVP never calls a cloud model by default. This keeps the tool usable
    offline and prevents visual issues from being invented without evidence.
    """
    selected = keyframes[:max_frames]
    return {
        "enabled": False,
        "reviewed_frames": len(selected),
        "notes": "MVP 未启用云端 AI 审美判断，商业表现力由关键帧指标启发式评估。",
        "issues": [],
    }
