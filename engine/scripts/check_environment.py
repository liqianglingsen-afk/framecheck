from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    checks = []
    checks.append(("Python >= 3.10", sys.version_info >= (3, 10), f"当前版本：{sys.version.split()[0]}"))
    checks.append(("FFmpeg", shutil.which("ffmpeg") is not None, "安装后需确保 ffmpeg 在 PATH 中"))
    checks.append(("ffprobe", shutil.which("ffprobe") is not None, "安装后需确保 ffprobe 在 PATH 中"))
    checks.append(("yt-dlp", shutil.which("yt-dlp") is not None, "缺失时只影响链接下载，本地视频仍可分析"))

    imports = {
        "OpenCV(cv2)": "cv2",
        "Jinja2": "jinja2",
        "Plotly": "plotly",
        "PyYAML": "yaml",
        "Pydantic": "pydantic",
        "Rich": "rich",
    }
    for label, module in imports.items():
        checks.append((label, _can_import(module), f"运行：python -m pip install -r {ROOT / 'requirements.txt'}"))

    checks.append(("reports 目录", (ROOT / "reports").exists(), "运行时会自动创建，也可以手动创建 reports/"))
    checks.append(("templates/report.html.j2", (ROOT / "templates" / "report.html.j2").exists(), "请确认模板文件存在"))

    print("postscore-ai 环境检查")
    print("=" * 34)
    missing = []
    for label, ok, hint in checks:
        status = "OK" if ok else "MISSING"
        print(f"{status:8} {label}")
        if not ok:
            missing.append((label, hint))
    if missing:
        print("\n修复建议：")
        for label, hint in missing:
            print(f"- {label}: {hint}")
        print("\nWindows 可用 winget/choco/scoop 安装 FFmpeg；macOS 可用 brew install ffmpeg；Linux 可用 apt install ffmpeg。")
    else:
        print("\n环境检查通过，可以开始进行真实视频评分。")
    return 0


def _can_import(module: str) -> bool:
    try:
        importlib.import_module(module)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
