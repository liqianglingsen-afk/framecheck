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
        raise RuntimeError("字幕与图文包装检测需要 OpenCV 和 NumPy。请先安装 requirements.txt。") from exc
    return cv2, np


def analyze_subtitles_graphics(keyframes: list[Keyframe]) -> dict:
    """Estimate bottom caption density and safe-margin risks with edge heuristics."""
    cv2, np = _load_cv2_numpy()
    rows: list[dict] = []
    for frame in keyframes:
        image = read_image(frame.path, cv2, np)
        if image is None:
            continue
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        height, width = gray.shape[:2]
        bottom = gray[int(height * 0.65) :, :]
        edges = cv2.Canny(bottom, 80, 160)
        bottom_activity = float(np.mean(edges > 0))
        margin = int(min(width, height) * 0.04)
        unsafe_region = gray[height - margin :, :]
        safe_margin_risk = float(np.mean(cv2.Canny(unsafe_region, 80, 160) > 0))
        rows.append(
            {
                "path": frame.path,
                "timestamp": frame.timestamp_seconds,
                "timestamp_label": frame.timestamp_label,
                "bottom_activity": bottom_activity,
                "safe_margin_risk": safe_margin_risk,
            }
        )
        frame.metrics.update(
            {
                "bottom_activity": round(bottom_activity, 4),
                "safe_margin_risk": round(safe_margin_risk, 4),
            }
        )

    if not rows:
        return {"frames": [], "error": "没有可分析的关键帧"}

    return {
        "frames": rows,
        "bottom_activity_mean": mean(row["bottom_activity"] for row in rows),
        "safe_margin_risk_mean": mean(row["safe_margin_risk"] for row in rows),
        "dense_bottom_frames": [row for row in rows if row["bottom_activity"] > 0.12],
        "unsafe_margin_frames": [row for row in rows if row["safe_margin_risk"] > 0.08],
        "ocr_available": False,
    }
