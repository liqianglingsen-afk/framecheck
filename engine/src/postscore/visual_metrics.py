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
        raise RuntimeError("视觉检测需要 OpenCV 和 NumPy。请先安装 requirements.txt。") from exc
    return cv2, np


def analyze_visual_quality(keyframes: list[Keyframe]) -> dict:
    """Measure sharpness, exposure, contrast, and simple visual risks on sampled frames."""
    cv2, np = _load_cv2_numpy()
    frame_metrics: list[dict] = []
    for frame in keyframes:
        image = read_image(frame.path, cv2, np)
        if image is None:
            continue
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(np.mean(gray))
        contrast = float(np.std(gray))
        under = float(np.mean(gray < 20))
        over = float(np.mean(gray > 245))
        h, w = gray.shape[:2]
        center = gray[h // 4 : h * 3 // 4, w // 4 : w * 3 // 4]
        center_sharpness = float(cv2.Laplacian(center, cv2.CV_64F).var())
        center_brightness = float(np.mean(center))
        frame.metrics.update(
            {
                "sharpness": round(sharpness, 2),
                "brightness": round(brightness, 2),
                "contrast": round(contrast, 2),
                "underexposed_ratio": round(under, 4),
                "overexposed_ratio": round(over, 4),
                "center_sharpness": round(center_sharpness, 2),
                "center_brightness": round(center_brightness, 2),
            }
        )
        frame_metrics.append(
            {
                "path": frame.path,
                "timestamp": frame.timestamp_seconds,
                "timestamp_label": frame.timestamp_label,
                "sharpness": sharpness,
                "brightness": brightness,
                "contrast": contrast,
                "underexposed_ratio": under,
                "overexposed_ratio": over,
                "center_sharpness": center_sharpness,
                "center_brightness": center_brightness,
            }
        )

    if not frame_metrics:
        return {"frames": [], "error": "没有可分析的关键帧"}

    worst_frames = sorted(frame_metrics, key=lambda item: item["sharpness"])[:5]
    low_sharpness_frames = [item for item in frame_metrics if item["sharpness"] < 80]
    low_contrast_frames = [item for item in frame_metrics if item["contrast"] < 32]
    return {
        "frames": frame_metrics,
        "avg_sharpness": mean(item["sharpness"] for item in frame_metrics),
        "avg_brightness": mean(item["brightness"] for item in frame_metrics),
        "avg_contrast": mean(item["contrast"] for item in frame_metrics),
        "underexposed_ratio_mean": mean(item["underexposed_ratio"] for item in frame_metrics),
        "overexposed_ratio_mean": mean(item["overexposed_ratio"] for item in frame_metrics),
        "low_sharpness_frames": low_sharpness_frames,
        "low_contrast_frames": low_contrast_frames,
        "worst_frames": worst_frames,
        "center_sharpness_mean": mean(item["center_sharpness"] for item in frame_metrics),
        "center_brightness_mean": mean(item["center_brightness"] for item in frame_metrics),
    }
