from __future__ import annotations

from pathlib import Path
from typing import Any


def read_image(path: str | Path, cv2: Any, np: Any):
    """Read an image from paths containing non-ASCII characters on Windows."""
    data = np.fromfile(str(Path(path)), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)
