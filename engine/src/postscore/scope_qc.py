"""Task-scoped QC alongside the original, reproducible raw score."""

from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import cv2

from .revision import timestamps


def scoped_quality(report, audio, shot_style, color_style, export_context="平台发布"):
    excluded = {}
    if audio == "设计无声" or (audio == "可选" and not report.audio_metrics.has_audio):
        excluded["audio_quality"] = audio
    ignored = {}
    pending_signals = []
    if export_context == "保留源规格":
        excluded["export_specs"] = "简报要求保留源规格，逐项核对实际导出"
    elif export_context == "待核":
        pending_signals = [
            i.problem for i in report.issues if i.module == "export_specs"
        ]

    titles = {i.problem for i in report.issues}
    if shot_style == "有意长镜或静止":
        for title in (
            "重复帧或静止变化比例偏高",
            "静止画面持续过久",
            "短视频镜头平均时长偏长",
        ):
            ignored[title] = "简报约定有意停留"
    elif {"静止画面持续过久", "重复帧或静止变化比例偏高"} <= titles:
        # Suppress only when the repeated-sample exposure is explained by that span.
        static = next(i for i in report.issues if i.problem == "静止画面持续过久")
        ratio = next(
            i.metric_value
            for i in report.issues
            if i.problem == "重复帧或静止变化比例偏高"
        )
        if (static.timestamp_end or 0) - (
            static.timestamp_start or 0
        ) >= ratio * report.video_info.duration_seconds:
            ignored["重复帧或静止变化比例偏高"] = "同一时段的连续静止已计入"
    if color_style == "有意风格化":
        for title in (
            "整体饱和度偏低",
            "整体饱和度偏高",
            "色温偏冷",
            "色温偏黄",
            "商业画面色彩表现力不稳定",
        ):
            ignored[title] = "约定光色风格，个别镜头失真须另行复核"
    losses = defaultdict(Decimal)
    for issue in report.issues:
        if issue.problem not in ignored:
            losses[issue.module] += Decimal(str(issue.score_impact))
    modules = {
        k: max(Decimal(0), Decimal(str(w)) - losses[k])
        for k, w in report.module_score_max.items()
        if k not in excluded
    }
    earned = sum(modules.values())
    possible = sum(Decimal(str(report.module_score_max[k])) for k in modules)
    blockers = []
    if audio == "设计无声" and report.audio_metrics.has_audio:
        blockers.append("设计无声的交付含非约定音轨")
    if audio == "必需" and not report.audio_metrics.has_audio:
        blockers.append("约定必需的音轨缺失")
    measured = bool(
        report.sampling
        and report.keyframes
        and (
            not report.optimization
            or report.optimization.status not in {"unverified", "mock"}
        )
    )
    return {
        "version": "technical-0.6",
        "scope": {"audio": audio, "shot_style": shot_style, "color_style": color_style},
        "pending_signals": pending_signals,
        "export_context": export_context,
        "raw": report.overall_score,
        "score": float(earned * 100 / possible) if measured else None,
        "earned": float(earned),
        "possible": float(possible),
        "modules": {k: float(v) for k, v in modules.items()},
        "excluded": excluded,
        "signals": {k: v for k, v in ignored.items() if k in titles},
        "blockers": blockers,
    }


def key_intervals(editorial, duration):
    windows = [(0, min(3, duration)), (max(0, duration - 1), duration)]
    c = editorial["criteria"]
    windows.extend(
        (max(0, s["start"] - 0.2), min(duration, s["start"] + 0.2)) for s in c["shots"]
    )
    for span in [s.get("sequence") for s in c["displays"]] + [
        i.get("interval") for i in editorial["findings"]
    ]:
        if span:
            windows.append((span["start"], span["end"]))
    windows.extend((s["start"], s["end"]) for s in c.get("inspect_spans", []))
    merged = []
    for start, end in sorted(windows):
        if end > duration + 0.001:
            raise ValueError("逐帧复核区间超出成片")
        if merged and merged[-1][1] >= start:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def scan_single_frames(video: Path, windows=None):
    """Inspect consecutive source frames within each selected presentation-time range."""
    pts = timestamps(video)
    ranges = (
        [(0, len(pts))]
        if windows is None
        else [
            (int(pts.searchsorted(start)), int(pts.searchsorted(end)))
            for start, end in windows
        ]
    )
    cap = cv2.VideoCapture(str(video))
    candidates = []
    count = 0
    try:
        for start, end in ranges:
            if start:
                cap.set(cv2.CAP_PROP_POS_FRAMES, start)
            preceding = previous = None
            for idx in range(start, end):
                ok, frame = cap.read()
                if not ok:
                    raise ValueError("解码不完整，无法确认逐帧覆盖")
                current = cv2.resize(frame, (128, 72), interpolation=cv2.INTER_AREA)
                if preceding is not None:
                    left = cv2.absdiff(preceding, previous).mean()
                    right = cv2.absdiff(previous, current).mean()
                    across = cv2.absdiff(preceding, current).mean()
                    if min(left, right) >= 12 and across < 0.45 * min(left, right):
                        candidates.append(
                            {"frame": idx - 1, "time": float(pts[idx - 1])}
                        )
                preceding, previous = previous, current
                count += 1
        if windows is None and cap.read()[0]:
            raise ValueError("时码与解码帧数不符")
    finally:
        cap.release()
    return dict(
        mode="全帧" if windows is None else "关键区间逐帧",
        decoded=count,
        windows=windows,
        candidates=candidates,
        status="候选待回看" if candidates else "已查区间未见孤立突变候选",
    )
