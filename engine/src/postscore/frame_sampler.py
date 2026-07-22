from __future__ import annotations

from pathlib import Path

from .models import Keyframe
from .utils import check_executable, ensure_dir, run_command, seconds_to_label


def sample_frames(video_path: Path, output_dir: Path, sample_fps: float, scale_width: int = 720) -> list[Keyframe]:
    """Sample resized keyframes with FFmpeg for deep quality analysis."""
    if sample_fps <= 0:
        raise ValueError("sample_fps must be greater than 0")
    if scale_width <= 0:
        raise ValueError("scale_width must be greater than 0")
    if not check_executable("ffmpeg"):
        raise RuntimeError("未检测到 ffmpeg。请先安装 FFmpeg，并确保 ffmpeg 在 PATH 中。")

    ensure_dir(output_dir)
    pattern = output_dir / "frame_%05d.jpg"
    result = run_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"fps={sample_fps:.6f},scale='min({scale_width},iw)':-2",
            "-q:v",
            "3",
            str(pattern),
        ],
        timeout=900,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg 抽帧失败：{result.stderr.strip()}")

    frames: list[Keyframe] = []
    for index, frame_path in enumerate(sorted(output_dir.glob("frame_*.jpg")), start=1):
        ts = (index - 1) / sample_fps
        frames.append(
            Keyframe(
                path=str(frame_path),
                timestamp_seconds=ts,
                timestamp_label=seconds_to_label(ts),
            )
        )
    if not frames:
        raise RuntimeError("FFmpeg 未生成关键帧，请检查视频是否可读取。")
    return frames
