from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .models import AudioMetrics, Issue, Keyframe, ReviewReport, VideoInfo
from .utils import seconds_to_label


MODULES: dict[str, tuple[str, float]] = {
    "visual_quality": ("画面基础质量", 25.0),
    "color_grading": ("调色与色彩一致性", 20.0),
    "editing_rhythm": ("剪辑节奏", 15.0),
    "audio_quality": ("声音质量", 15.0),
    "subtitles_graphics": ("字幕与图文包装", 10.0),
    "commercial_expression": ("商业表现力", 10.0),
    "export_specs": ("导出技术规范", 5.0),
}


def grade_for_score(score: float) -> str:
    if score >= 95:
        return "S"
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "E"


def publish_recommendation(score: float) -> str:
    if score >= 90:
        return "可直接发布"
    if score >= 80:
        return "建议小幅优化后发布"
    if score >= 70:
        return "可发布但建议先处理明显问题"
    if score >= 60:
        return "不建议直接发布，需先修改"
    return "需要重做或大幅返工"


def score_report(
    video_info: VideoInfo,
    visual_metrics: dict[str, Any] | None = None,
    color_metrics: dict[str, Any] | None = None,
    edit_metrics: dict[str, Any] | None = None,
    audio_metrics: AudioMetrics | dict[str, Any] | None = None,
    subtitle_metrics: dict[str, Any] | None = None,
    keyframes: list[Keyframe] | None = None,
    preset: str = "default",
    mode: str = "deep",
) -> ReviewReport:
    """Convert measured metrics into module scores and evidence-backed issues."""
    visual_metrics = visual_metrics or {}
    color_metrics = color_metrics or {}
    edit_metrics = edit_metrics or {}
    subtitle_metrics = subtitle_metrics or {}
    keyframes = keyframes or []
    audio = _coerce_audio(audio_metrics)

    impacts: dict[str, float] = defaultdict(float)
    issues: list[Issue] = []

    _score_visual(visual_metrics, issues, impacts)
    _score_color(color_metrics, issues, impacts, preset)
    _score_editing(edit_metrics, issues, impacts, preset)
    _score_audio(audio, issues, impacts)
    _score_subtitles(subtitle_metrics, issues, impacts, preset)
    _score_commercial(visual_metrics, color_metrics, subtitle_metrics, issues, impacts, preset)
    _score_export(video_info, issues, impacts, preset)

    module_max = {key: max_score for key, (_, max_score) in MODULES.items()}
    module_names = {key: name for key, (name, _) in MODULES.items()}
    module_scores = {
        key: round(max(max_score - min(impacts.get(key, 0.0), max_score), 0.0), 1)
        for key, (_, max_score) in MODULES.items()
    }
    overall = round(sum(module_scores.values()), 1)
    issues.sort(key=lambda item: (_severity_rank(item.severity), item.score_impact), reverse=True)

    return ReviewReport(
        video_info=video_info,
        overall_score=overall,
        grade=grade_for_score(overall),
        publish_recommendation=publish_recommendation(overall),
        module_scores=module_scores,
        module_score_max=module_max,
        module_names=module_names,
        issues=issues,
        keyframes=keyframes,
        audio_metrics=audio,
        export_recommendations=_export_recommendations(video_info, preset),
        revision_checklist=_revision_checklist(issues),
        preset=preset,
        mode=mode,
    )


def _coerce_audio(audio_metrics: AudioMetrics | dict[str, Any] | None) -> AudioMetrics:
    if audio_metrics is None:
        return AudioMetrics(has_audio=False, recommendations=["未提供音频检测结果。"])
    if isinstance(audio_metrics, AudioMetrics):
        return audio_metrics
    return AudioMetrics(**audio_metrics)


def _add_issue(
    issues: list[Issue],
    impacts: dict[str, float],
    *,
    module: str,
    severity: str,
    score_impact: float,
    problem: str,
    recommendation: str,
    timestamp_start: float | None = None,
    timestamp_end: float | None = None,
    evidence_image: str | None = None,
    metric_value: Any = None,
    threshold: Any = None,
) -> None:
    priority = "P2"
    if severity in {"critical", "high"} or score_impact >= 5:
        priority = "P0"
    elif severity == "medium" or score_impact >= 3:
        priority = "P1"
    impacts[module] += score_impact
    issues.append(
        Issue(
            module=module,
            severity=severity,  # type: ignore[arg-type]
            score_impact=round(score_impact, 1),
            timestamp_start=timestamp_start,
            timestamp_end=timestamp_end,
            evidence_image=evidence_image,
            metric_value=_round_metric(metric_value),
            threshold=threshold,
            problem=problem,
            recommendation=recommendation,
            priority=priority,  # type: ignore[arg-type]
        )
    )


def _score_visual(metrics: dict[str, Any], issues: list[Issue], impacts: dict[str, float]) -> None:
    worst = _first(metrics.get("worst_frames"))
    avg_sharpness = metrics.get("avg_sharpness")
    if avg_sharpness is not None and avg_sharpness < 80:
        _add_issue(
            issues,
            impacts,
            module="visual_quality",
            severity="high" if avg_sharpness < 45 else "medium",
            score_impact=6 if avg_sharpness < 45 else 4,
            problem="画面平均清晰度偏低",
            recommendation="检查导出码率、素材分辨率和锐化设置；低清片段建议替换素材或重新导出。",
            timestamp_start=_time(worst),
            evidence_image=_path(worst),
            metric_value=avg_sharpness,
            threshold=">= 80 Laplacian variance",
        )
    low_ratio = len(metrics.get("low_sharpness_frames") or []) / max(len(metrics.get("frames") or []), 1)
    if low_ratio > 0.2:
        _add_issue(
            issues,
            impacts,
            module="visual_quality",
            severity="medium",
            score_impact=3,
            problem="低清晰度关键帧比例偏高",
            recommendation="定位低清晰度时间点，优先检查缩放、降噪过度、运动模糊和压缩损失。",
            timestamp_start=_time(worst),
            evidence_image=_path(worst),
            metric_value=low_ratio,
            threshold="<= 20%",
        )
    under = metrics.get("underexposed_ratio_mean")
    if under is not None and under > 0.08:
        _add_issue(
            issues,
            impacts,
            module="visual_quality",
            severity="medium",
            score_impact=3,
            problem="暗部压死比例偏高",
            recommendation="提升阴影细节或调整曲线，避免主体和产品细节丢失。",
            timestamp_start=_time(worst),
            evidence_image=_path(worst),
            metric_value=under,
            threshold="<= 0.08",
        )
    over = metrics.get("overexposed_ratio_mean")
    if over is not None and over > 0.04:
        _add_issue(
            issues,
            impacts,
            module="visual_quality",
            severity="medium",
            score_impact=3,
            problem="高光 clipping 风险偏高",
            recommendation="压低高光和白场，检查产品反光、皮肤高光和字幕白色区域。",
            timestamp_start=_time(worst),
            evidence_image=_path(worst),
            metric_value=over,
            threshold="<= 0.04",
        )
    contrast = metrics.get("avg_contrast")
    if contrast is not None and contrast < 32:
        _add_issue(
            issues,
            impacts,
            module="visual_quality",
            severity="low",
            score_impact=2,
            problem="对比度偏低，画面容易显灰",
            recommendation="增强黑白场层次，避免整体曲线过平。",
            timestamp_start=_time(worst),
            evidence_image=_path(worst),
            metric_value=contrast,
            threshold=">= 32 grayscale std",
        )


def _score_color(metrics: dict[str, Any], issues: list[Issue], impacts: dict[str, float], preset: str) -> None:
    first_frame = _first(metrics.get("frames"))
    saturation = metrics.get("avg_saturation")
    if saturation is not None and saturation > 110:
        impact = 5 if preset == "amazon_product" else 4
        _add_issue(
            issues,
            impacts,
            module="color_grading",
            severity="medium",
            score_impact=impact,
            problem="整体饱和度偏高",
            recommendation="降低全局饱和度，优先检查产品色彩是否失真和肤色是否过红。",
            timestamp_start=_time(first_frame),
            evidence_image=_path(first_frame),
            metric_value=saturation,
            threshold="<= 110 HSV saturation mean",
        )
    if saturation is not None and saturation < 28:
        _add_issue(
            issues,
            impacts,
            module="color_grading",
            severity="low",
            score_impact=3,
            problem="整体饱和度偏低",
            recommendation="提升主体和背景的色彩区分，避免商业画面显灰。",
            timestamp_start=_time(first_frame),
            evidence_image=_path(first_frame),
            metric_value=saturation,
            threshold=">= 28 HSV saturation mean",
        )
    bias = metrics.get("temperature_bias")
    if bias in {"cold", "warm"}:
        problem = "色温偏冷" if bias == "cold" else "色温偏黄"
        _add_issue(
            issues,
            impacts,
            module="color_grading",
            severity="low",
            score_impact=2.5,
            problem=problem,
            recommendation="校正白平衡，并检查肤色、产品白色/金属/透明材质是否自然。",
            timestamp_start=_time(first_frame),
            evidence_image=_path(first_frame),
            metric_value=metrics.get("temperature_delta"),
            threshold="blue-red mean delta within +/-10",
        )
    inconsistency = metrics.get("color_inconsistency")
    inconsistent = _first(metrics.get("inconsistent_frames"))
    if inconsistency is not None and inconsistency > 45:
        _add_issue(
            issues,
            impacts,
            module="color_grading",
            severity="medium",
            score_impact=4,
            problem="相邻关键帧色彩一致性不足",
            recommendation="按镜头组统一白平衡、曝光和 LUT 强度，避免剪辑点前后色彩跳变。",
            timestamp_start=_time(inconsistent),
            evidence_image=_path(inconsistent),
            metric_value=inconsistency,
            threshold="<= 45 RGB vector delta",
        )


def _score_editing(metrics: dict[str, Any], issues: list[Issue], impacts: dict[str, float], preset: str) -> None:
    black = _first(metrics.get("black_frames"))
    if metrics.get("black_frames"):
        _add_issue(
            issues,
            impacts,
            module="editing_rhythm",
            severity="high",
            score_impact=4,
            problem="检测到黑场关键帧",
            recommendation="检查转场、素材断点和导出错误；非设计黑场应直接删除或补画面。",
            timestamp_start=_time(black),
            evidence_image=_path(black),
            metric_value=len(metrics.get("black_frames") or []),
            threshold="0",
        )
    repeated_ratio = metrics.get("repeated_frame_ratio")
    if repeated_ratio is not None and repeated_ratio > 0.12:
        _add_issue(
            issues,
            impacts,
            module="editing_rhythm",
            severity="medium",
            score_impact=3,
            problem="重复帧或静止变化比例偏高",
            recommendation="检查卡顿、冻结帧和 B-roll 留白；短视频建议增强画面变化。",
            timestamp_start=None,
            metric_value=repeated_ratio,
            threshold="<= 0.12",
        )
    static = _first(metrics.get("static_segments"))
    if static:
        _add_issue(
            issues,
            impacts,
            module="editing_rhythm",
            severity="medium",
            score_impact=3,
            problem="静止画面持续过久",
            recommendation="缩短静止段，增加切镜、推拉、字幕动画或产品细节镜头。",
            timestamp_start=static.get("start"),
            timestamp_end=static.get("end"),
            metric_value=static,
            threshold="< 2s continuous repeated sampled frames",
        )
    avg_shot = metrics.get("avg_shot_length")
    if avg_shot is not None and preset == "short_social" and avg_shot > 4.5:
        _add_issue(
            issues,
            impacts,
            module="editing_rhythm",
            severity="medium",
            score_impact=3,
            problem="短视频镜头平均时长偏长",
            recommendation="前 3 秒加快信息推进，减少长镜头停顿，提升移动端留存。",
            metric_value=avg_shot,
            threshold="<= 4.5s for short_social",
        )


def _score_audio(audio: AudioMetrics, issues: list[Issue], impacts: dict[str, float]) -> None:
    if not audio.has_audio:
        _add_issue(
            issues,
            impacts,
            module="audio_quality",
            severity="high",
            score_impact=8,
            problem="未检测到可分析音轨",
            recommendation="确认是否需要声音；如果是商业视频，建议补充人声、音乐或环境声并重新导出。",
            metric_value="no audio",
            threshold="has audio track",
        )
        return
    if audio.too_quiet:
        _add_issue(
            issues,
            impacts,
            module="audio_quality",
            severity="medium",
            score_impact=4,
            problem="整体音量偏低",
            recommendation="提升主声音量，并用响度表检查平台推荐响度范围。",
            metric_value=audio.approx_loudness_db,
            threshold=">= -30 dB mean volume approximation",
        )
    if audio.too_loud or audio.clipping_risk:
        _add_issue(
            issues,
            impacts,
            module="audio_quality",
            severity="high" if audio.clipping_risk else "medium",
            score_impact=5 if audio.clipping_risk else 3,
            problem="峰值过高，有爆音风险",
            recommendation="降低总线峰值，加入限幅器，导出前检查是否削波。",
            metric_value=audio.peak_db,
            threshold="<= -1 dB peak",
        )
    if audio.silence_segments:
        first = audio.silence_segments[0]
        _add_issue(
            issues,
            impacts,
            module="audio_quality",
            severity="low",
            score_impact=2,
            problem="存在静音段",
            recommendation="确认静音是否为设计留白；非设计静音应补齐音乐、环境声或转场音效。",
            timestamp_start=first.get("start"),
            timestamp_end=first.get("end"),
            metric_value=len(audio.silence_segments),
            threshold="0 unplanned silence segments",
        )


def _score_subtitles(metrics: dict[str, Any], issues: list[Issue], impacts: dict[str, float], preset: str) -> None:
    dense = _first(metrics.get("dense_bottom_frames"))
    activity = metrics.get("bottom_activity_mean")
    if activity is not None and activity > 0.12:
        _add_issue(
            issues,
            impacts,
            module="subtitles_graphics",
            severity="medium" if preset == "short_social" else "low",
            score_impact=3,
            problem="底部字幕/图形区域信息密度偏高",
            recommendation="减少底部花字堆叠，保留移动端安全区，确保字幕不遮挡主体。",
            timestamp_start=_time(dense),
            evidence_image=_path(dense),
            metric_value=activity,
            threshold="<= 0.12 edge density",
        )
    unsafe = _first(metrics.get("unsafe_margin_frames"))
    margin = metrics.get("safe_margin_risk_mean")
    if margin is not None and margin > 0.08:
        _add_issue(
            issues,
            impacts,
            module="subtitles_graphics",
            severity="medium",
            score_impact=3,
            problem="字幕或图形疑似贴近底部安全边距",
            recommendation="将字幕和重要图形上移，适配手机端 UI 遮挡区域。",
            timestamp_start=_time(unsafe),
            evidence_image=_path(unsafe),
            metric_value=margin,
            threshold="<= 0.08 edge density near bottom margin",
        )


def _score_commercial(
    visual: dict[str, Any],
    color: dict[str, Any],
    subtitles: dict[str, Any],
    issues: list[Issue],
    impacts: dict[str, float],
    preset: str,
) -> None:
    first = _first(visual.get("worst_frames") or visual.get("frames"))
    center_sharpness = visual.get("center_sharpness_mean")
    if center_sharpness is not None and center_sharpness < 70:
        impact = 4 if preset == "amazon_product" else 3
        _add_issue(
            issues,
            impacts,
            module="commercial_expression",
            severity="medium",
            score_impact=impact,
            problem="主体区域清晰度不足",
            recommendation="优先保证产品或人物所在中心区域清晰，必要时重新选镜头或提高导出质量。",
            timestamp_start=_time(first),
            evidence_image=_path(first),
            metric_value=center_sharpness,
            threshold=">= 70 center Laplacian variance",
        )
    center_brightness = visual.get("center_brightness_mean")
    if center_brightness is not None and (center_brightness < 55 or center_brightness > 210):
        _add_issue(
            issues,
            impacts,
            module="commercial_expression",
            severity="low",
            score_impact=2,
            problem="主体区域亮度不理想",
            recommendation="让产品或人物主体处于更稳定的曝光范围，避免过暗或过亮影响识别。",
            timestamp_start=_time(first),
            evidence_image=_path(first),
            metric_value=center_brightness,
            threshold="55-210 mean luma",
        )
    saturation = color.get("avg_saturation")
    if saturation is not None and (saturation < 24 or saturation > 125):
        _add_issue(
            issues,
            impacts,
            module="commercial_expression",
            severity="low",
            score_impact=2,
            problem="商业画面色彩表现力不稳定",
            recommendation="根据投放平台校正饱和度，让主体醒目但不失真。",
            timestamp_start=_time(first),
            evidence_image=_path(first),
            metric_value=saturation,
            threshold="24-125 HSV saturation mean",
        )
    if subtitles.get("bottom_activity_mean", 0) > 0.16:
        _add_issue(
            issues,
            impacts,
            module="commercial_expression",
            severity="low",
            score_impact=1.5,
            problem="画面包装可能分散主体注意力",
            recommendation="减少与主体竞争的文字、贴纸或装饰层，突出产品卖点。",
            timestamp_start=_time(first),
            evidence_image=_path(first),
            metric_value=subtitles.get("bottom_activity_mean"),
            threshold="<= 0.16",
        )


def _score_export(video: VideoInfo, issues: list[Issue], impacts: dict[str, float], preset: str) -> None:
    if video.width < 720 or video.height < 720:
        _add_issue(
            issues,
            impacts,
            module="export_specs",
            severity="medium",
            score_impact=2,
            problem="分辨率低于常见发布标准",
            recommendation="建议至少导出 1080p；电商和品牌片应优先保证产品细节。",
            metric_value=f"{video.width}x{video.height}",
            threshold=">= 720p minimum, 1080p recommended",
        )
    if video.fps and not (23 <= video.fps <= 61):
        _add_issue(
            issues,
            impacts,
            module="export_specs",
            severity="low",
            score_impact=1,
            problem="帧率不在常见发布范围",
            recommendation="根据平台要求导出 24/25/30/50/60 fps，避免异常帧率造成兼容问题。",
            metric_value=video.fps,
            threshold="23-61 fps",
        )
    if video.audio_sample_rate and video.audio_sample_rate < 44100:
        _add_issue(
            issues,
            impacts,
            module="export_specs",
            severity="low",
            score_impact=1,
            problem="音频采样率偏低",
            recommendation="建议使用 44.1kHz 或 48kHz 音频采样率重新导出。",
            metric_value=video.audio_sample_rate,
            threshold=">= 44100 Hz",
        )
    if video.video_codec not in {"h264", "hevc", "h265", "prores", "vp9", "av1", "unknown"}:
        _add_issue(
            issues,
            impacts,
            module="export_specs",
            severity="low",
            score_impact=1,
            problem="视频编码格式可能不适合通用发布",
            recommendation="建议根据平台使用 H.264/H.265，并检查码率和兼容性。",
            metric_value=video.video_codec,
            threshold="h264/hevc/prores/vp9/av1",
        )


def _export_recommendations(video: VideoInfo, preset: str) -> list[str]:
    recommendations = [
        "通用建议：H.264/H.265，1080p 或更高，音频 48kHz，峰值低于 -1 dB。",
        "短视频建议：竖屏平台优先 1080x1920，字幕避开底部和右侧 UI 安全区。",
    ]
    if preset == "amazon_product":
        recommendations.append("Amazon 产品视频建议保持产品颜色准确，避免过重 LUT 和过度锐化。")
    if preset == "brand_commercial":
        recommendations.append("品牌片建议保留更高码率母版，交付前检查全片调色一致性。")
    if video.width and video.height:
        recommendations.append(f"当前视频：{video.width}x{video.height}，{round(video.fps, 2)} fps，编码 {video.video_codec}。")
    return recommendations


def _revision_checklist(issues: list[Issue]) -> dict[str, list[str]]:
    checklist = {"P0": [], "P1": [], "P2": []}
    for issue in issues:
        label = seconds_to_label(issue.timestamp_start)
        checklist[issue.priority].append(f"{label} - {issue.problem}：{issue.recommendation}")
    return checklist


def _first(items: Any) -> Any:
    if isinstance(items, list) and items:
        return items[0]
    return None


def _time(item: Any) -> float | None:
    if isinstance(item, dict):
        return item.get("timestamp") or item.get("start")
    return None


def _path(item: Any) -> str | None:
    if isinstance(item, dict):
        path = item.get("path")
        return str(Path(path)) if path else None
    return None


def _round_metric(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    return value


def _severity_rank(severity: str) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(severity, 0)
