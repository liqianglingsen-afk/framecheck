from __future__ import annotations

import json
from pathlib import Path

from .models import VideoInfo
from .utils import check_executable, file_size, parse_fraction, run_command


def probe_video(path: Path, source: str | None = None) -> VideoInfo:
    """Read container, video, and audio metadata with ffprobe."""
    if not check_executable("ffprobe"):
        raise RuntimeError("未检测到 ffprobe。请先安装 FFmpeg，并确保 ffprobe 在 PATH 中。")

    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 读取视频失败：{result.stderr.strip()}")

    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    fmt = payload.get("format", {})
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

    duration = parse_fraction(video_stream.get("duration") or fmt.get("duration"))
    bitrate = int(float(fmt.get("bit_rate") or video_stream.get("bit_rate") or 0))
    return VideoInfo(
        source=source or str(path),
        resolved_path=str(path),
        filename=path.name,
        duration_seconds=duration,
        width=int(video_stream.get("width") or 0),
        height=int(video_stream.get("height") or 0),
        fps=parse_fraction(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")),
        video_codec=video_stream.get("codec_name") or "unknown",
        audio_codec=audio_stream.get("codec_name") or "none",
        bitrate=bitrate,
        file_size=file_size(path),
        audio_sample_rate=int(audio_stream.get("sample_rate") or 0),
        audio_channels=int(audio_stream.get("channels") or 0),
    )
