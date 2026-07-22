from __future__ import annotations

from pathlib import Path
from statistics import mean

from .image_io import read_image
from .models import Keyframe


def _load_cv2_numpy():
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception as exc:
        raise RuntimeError("剪辑节奏检测需要 OpenCV 和 NumPy。请先安装 requirements.txt。") from exc
    return cv2, np


def analyze_editing_rhythm(keyframes: list[Keyframe], duration_seconds: float) -> dict:
    """Estimate black frames, repeated frames, static stretches, and rough shot rhythm."""
    cv2, np = _load_cv2_numpy()
    grayscale_frames: list[dict] = []
    for frame in keyframes:
        image = read_image(frame.path, cv2, np)
        if image is None:
            continue
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (96, 54), interpolation=cv2.INTER_AREA)
        grayscale_frames.append(
            {
                "path": frame.path,
                "timestamp": frame.timestamp_seconds,
                "timestamp_label": frame.timestamp_label,
                "gray": small,
                "brightness": float(np.mean(gray)),
            }
        )

    if not grayscale_frames:
        return {"error": "没有可分析的关键帧", "black_frames": []}

    changes: list[dict] = []
    for index in range(1, len(grayscale_frames)):
        previous = grayscale_frames[index - 1]["gray"].astype("float32")
        current = grayscale_frames[index]["gray"].astype("float32")
        diff = float(np.mean(np.abs(current - previous)))
        changes.append(
            {
                "timestamp": grayscale_frames[index]["timestamp"],
                "timestamp_label": grayscale_frames[index]["timestamp_label"],
                "path": grayscale_frames[index]["path"],
                "diff": diff,
            }
        )

    black_frames = [row for row in grayscale_frames if row["brightness"] < 8]
    repeated_changes = [row for row in changes if row["diff"] < 1.5]
    shot_changes = [row for row in changes if row["diff"] > 22]
    static_segments = _merge_static_segments(repeated_changes)
    shot_count = max(len(shot_changes) + 1, 1)
    avg_shot_length = duration_seconds / shot_count if duration_seconds else 0.0
    return {
        "black_frames": black_frames,
        "frame_changes": changes,
        "frame_change_mean": mean(row["diff"] for row in changes) if changes else 0.0,
        "repeated_frame_ratio": len(repeated_changes) / max(len(changes), 1),
        "static_segments": static_segments,
        "shot_count_estimate": shot_count,
        "avg_shot_length": avg_shot_length,
    }


def _merge_static_segments(changes: list[dict]) -> list[dict[str, float]]:
    if not changes:
        return []
    segments: list[dict[str, float]] = []
    start = changes[0]["timestamp"]
    last = start
    for row in changes[1:]:
        if row["timestamp"] - last <= 1.5:
            last = row["timestamp"]
            continue
        if last - start >= 2.0:
            segments.append({"start": start, "end": last})
        start = row["timestamp"]
        last = start
    if last - start >= 2.0:
        segments.append({"start": start, "end": last})
    return segments
