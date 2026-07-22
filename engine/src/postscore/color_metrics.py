from __future__ import annotations

from pathlib import Path
from statistics import mean, pstdev

from .image_io import read_image
from .models import Keyframe


def _load_cv2_numpy():
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception as exc:
        raise RuntimeError("色彩检测需要 OpenCV 和 NumPy。请先安装 requirements.txt。") from exc
    return cv2, np


def analyze_color_grading(keyframes: list[Keyframe]) -> dict:
    """Estimate saturation, color temperature bias, and frame-to-frame color consistency."""
    cv2, np = _load_cv2_numpy()
    rows: list[dict] = []
    for frame in keyframes:
        image = read_image(frame.path, cv2, np)
        if image is None:
            continue
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        sat = float(np.mean(hsv[:, :, 1]))
        red = float(np.mean(rgb[:, :, 0]))
        green = float(np.mean(rgb[:, :, 1]))
        blue = float(np.mean(rgb[:, :, 2]))
        color_vector = np.array([red, green, blue], dtype=float)
        rows.append(
            {
                "path": frame.path,
                "timestamp": frame.timestamp_seconds,
                "timestamp_label": frame.timestamp_label,
                "saturation": sat,
                "red_mean": red,
                "green_mean": green,
                "blue_mean": blue,
                "color_vector": color_vector,
            }
        )
        frame.metrics.update(
            {
                "saturation": round(sat, 2),
                "red_mean": round(red, 2),
                "green_mean": round(green, 2),
                "blue_mean": round(blue, 2),
            }
        )

    if not rows:
        return {"frames": [], "error": "没有可分析的关键帧"}

    vectors = [row["color_vector"] for row in rows]
    deltas = [float(np.linalg.norm(vectors[index] - vectors[index - 1])) for index in range(1, len(vectors))]
    avg_red = mean(row["red_mean"] for row in rows)
    avg_blue = mean(row["blue_mean"] for row in rows)
    temperature_delta = avg_blue - avg_red
    if temperature_delta > 10:
        temperature_bias = "cold"
    elif temperature_delta < -10:
        temperature_bias = "warm"
    else:
        temperature_bias = "neutral"

    return {
        "frames": rows,
        "avg_saturation": mean(row["saturation"] for row in rows),
        "saturation_std": pstdev([row["saturation"] for row in rows]) if len(rows) > 1 else 0.0,
        "temperature_bias": temperature_bias,
        "temperature_delta": temperature_delta,
        "color_inconsistency": mean(deltas) if deltas else 0.0,
        "inconsistent_frames": [
            {
                "path": rows[index]["path"],
                "timestamp": rows[index]["timestamp"],
                "timestamp_label": rows[index]["timestamp_label"],
                "delta": deltas[index - 1],
            }
            for index in range(1, len(rows))
            if deltas[index - 1] > 45
        ],
    }
