from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_windows() -> bool:
    return os.name == "nt"


def check_executable(name: str) -> bool:
    return shutil.which(name) is not None


def run_command(args: Sequence[str], timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def parse_fraction(value: str | int | float | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if "/" in value:
        left, right = value.split("/", 1)
        denominator = float(right)
        if denominator == 0:
            return 0.0
        return float(left) / denominator
    try:
        return float(value)
    except ValueError:
        return 0.0


def seconds_to_label(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    seconds = max(float(seconds), 0.0)
    minutes = int(seconds // 60)
    remaining = seconds - minutes * 60
    return f"{minutes:02d}:{remaining:05.2f}"


def safe_slug(text: str, default: str = "video") -> str:
    text = Path(text).stem or default
    text = re.sub(r"[^\w\-.]+", "_", text, flags=re.UNICODE).strip("._")
    return text or default


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def relative_or_absolute(path: str | Path, base: Path) -> str:
    path_obj = Path(path)
    try:
        return path_obj.resolve().relative_to(base.resolve()).as_posix()
    except Exception:
        return str(path_obj)


def print_console(message: str) -> None:
    try:
        from rich.console import Console

        Console().print(message)
    except Exception:
        print(message)


def open_in_default_app(path: Path) -> None:
    if is_windows():
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        run_command(["open", str(path)])
    else:
        run_command(["xdg-open", str(path)])
