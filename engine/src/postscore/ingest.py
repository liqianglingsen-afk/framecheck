from __future__ import annotations

import urllib.parse
import urllib.request
from pathlib import Path

from .utils import check_executable, ensure_dir, run_command, safe_slug


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def is_url(source: str) -> bool:
    parsed = urllib.parse.urlparse(source)
    return parsed.scheme in {"http", "https"}


def resolve_input(source: str, reports_dir: Path) -> Path:
    """Resolve a local path or download a public URL into the reports workspace."""
    if not is_url(source):
        path = Path(source).expanduser()
        if not path.exists():
            raise RuntimeError(f"找不到本地视频文件：{source}")
        return path.resolve()

    downloads_dir = ensure_dir(reports_dir / "downloads")
    if check_executable("yt-dlp"):
        output_template = str(downloads_dir / "%(title).80s-%(id)s.%(ext)s")
        result = run_command(
            ["yt-dlp", "-f", "bv*+ba/b", "--merge-output-format", "mp4", "-o", output_template, source],
            timeout=600,
        )
        if result.returncode == 0:
            candidates = sorted(downloads_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
            for candidate in candidates:
                if candidate.suffix.lower() in VIDEO_EXTENSIONS:
                    return candidate.resolve()
        raise RuntimeError(
            "视频链接下载失败。请确认链接可公开访问，或改用本地视频路径。\n"
            f"yt-dlp 输出：{result.stderr.strip() or result.stdout.strip()}"
        )

    parsed = urllib.parse.urlparse(source)
    if Path(parsed.path).suffix.lower() not in VIDEO_EXTENSIONS:
        raise RuntimeError("当前环境没有 yt-dlp，公开视频链接无法下载。请安装 yt-dlp，或提供本地视频文件。")

    target = downloads_dir / f"{safe_slug(parsed.path)}{Path(parsed.path).suffix}"
    try:
        urllib.request.urlretrieve(source, target)
    except Exception as exc:
        raise RuntimeError(f"链接下载失败，请换成本地视频文件：{exc}") from exc
    return target.resolve()
