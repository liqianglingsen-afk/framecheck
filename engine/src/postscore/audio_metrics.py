from __future__ import annotations

import os
import re
from pathlib import Path

from .models import AudioMetrics
from .utils import check_executable, run_command


def analyze_audio_quality(video_path: Path) -> AudioMetrics:
    """Measure approximate loudness, peak, silence, and clipping risk with FFmpeg filters."""
    if not check_executable("ffmpeg"):
        return AudioMetrics(
            has_audio=False,
            recommendations=["未检测到 ffmpeg，无法执行音频检测。请安装 FFmpeg 后重新运行。"],
        )

    volume = run_command(
        ["ffmpeg", "-hide_banner", "-i", str(video_path), "-vn", "-af", "volumedetect", "-f", "null", os.devnull],
        timeout=300,
    )
    text = f"{volume.stdout}\n{volume.stderr}"
    if "Output file #0 does not contain any stream" in text or "Audio: none" in text:
        return AudioMetrics(has_audio=False, recommendations=["视频未检测到可分析的音轨。"])

    mean_volume = _parse_db(text, r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB")
    max_volume = _parse_db(text, r"max_volume:\s*(-?\d+(?:\.\d+)?) dB")

    silence = run_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(video_path),
            "-vn",
            "-af",
            "silencedetect=n=-35dB:d=0.7",
            "-f",
            "null",
            os.devnull,
        ],
        timeout=300,
    )
    silence_text = f"{silence.stdout}\n{silence.stderr}"
    segments = _parse_silence_segments(silence_text)
    too_quiet = mean_volume is not None and mean_volume < -30
    too_loud = max_volume is not None and max_volume > -1
    clipping = max_volume is not None and max_volume > -0.5
    recommendations: list[str] = []
    if too_quiet:
        recommendations.append("整体响度偏低，建议提升人声或主声音量，并控制背景音乐遮盖。")
    if too_loud or clipping:
        recommendations.append("峰值接近 0 dB，存在爆音或削波风险，建议降低总线峰值并加限幅器。")
    if segments:
        recommendations.append("存在静音段，请确认是否为设计留白，否则应补齐环境声或音乐衔接。")

    return AudioMetrics(
        approx_loudness_db=mean_volume,
        peak_db=max_volume,
        silence_segments=segments,
        too_quiet=too_quiet,
        too_loud=too_loud,
        clipping_risk=clipping,
        recommendations=recommendations,
    )


def _parse_db(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text)
    if not match:
        return None
    return float(match.group(1))


def _parse_silence_segments(text: str) -> list[dict[str, float]]:
    starts = [float(value) for value in re.findall(r"silence_start:\s*([0-9.]+)", text)]
    ends = [float(value) for value in re.findall(r"silence_end:\s*([0-9.]+)", text)]
    segments: list[dict[str, float]] = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else start
        segments.append({"start": start, "end": end, "duration": max(end - start, 0.0)})
    return segments
