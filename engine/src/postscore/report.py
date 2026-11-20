from __future__ import annotations

import html
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import AudioMetrics, Issue, Keyframe, ReviewReport, VideoInfo, model_to_dict
from .scoring import MODULES, score_report
from .utils import ensure_dir, package_root, safe_slug, seconds_to_label


METRIC_LABELS_ZH: dict[str, str] = {
    "sharpness": "清晰度",
    "brightness": "平均亮度",
    "contrast": "对比度",
    "underexposed_ratio": "过暗比例",
    "overexposed_ratio": "过曝比例",
    "center_sharpness": "中心区域清晰度",
    "center_brightness": "中心区域亮度",
    "saturation": "饱和度",
    "red_mean": "红色均值",
    "green_mean": "绿色均值",
    "blue_mean": "蓝色均值",
    "bottom_activity": "底部文字/图形活跃度",
    "safe_margin_risk": "安全边距风险",
    "timestamp": "时间点",
    "start": "开始时间",
    "end": "结束时间",
    "duration": "持续时间",
    "diff": "帧间变化强度",
    "delta": "色彩差异",
    "path": "证据图",
}

PERCENT_METRICS = {
    "underexposed_ratio",
    "overexposed_ratio",
    "bottom_activity",
    "safe_margin_risk",
}


def write_reports(
    report: ReviewReport,
    output_dir: Path,
    write_html: bool = True,
    write_json: bool = True,
    stem_prefix: str | None = None,
) -> dict[str, Path]:
    """Write HTML and JSON report files and return their paths."""
    ensure_dir(output_dir)
    stem = f"{safe_slug(report.video_info.filename)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if stem_prefix:
        stem = f"{safe_slug(stem_prefix)}_{stem}"
    paths: dict[str, Path] = {}
    if write_json:
        json_path = output_dir / f"{stem}.json"
        json_path.write_text(json.dumps(model_to_dict(report), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        paths["json"] = json_path
    if write_html:
        html_path = output_dir / f"{stem}.html"
        html_path.write_text(render_html(report, output_dir=output_dir), encoding="utf-8")
        paths["html"] = html_path
    return paths


def render_html(report: ReviewReport, output_dir: Path | None = None) -> str:
    """Render a single-file Chinese QC report, using Jinja2 when installed."""
    output_dir = output_dir or Path.cwd()
    context = {
        "report": report,
        "modules": _module_cards(report),
        "top_issues": report.issues[:10],
        "radar_svg": _radar_svg(report),
        "timeline": _timeline_items(report),
        "format_time": seconds_to_label,
        "asset_path": lambda path: _asset_path(path, output_dir),
        "format_metrics": _format_metrics_zh,
        "format_metric_value": _format_metric_value_zh,
    }
    template_path = package_root() / "templates" / "report.html.j2"
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        env = Environment(
            loader=FileSystemLoader(str(template_path.parent)),
            autoescape=select_autoescape(["html", "xml"]),
        )
        return env.get_template(template_path.name).render(**context)
    except Exception:
        return _fallback_html(report, context)


def create_mock_report(
    output_dir: Path,
    preset: str = "default",
    mode: str = "deep",
    source: str = "mock://demo",
    resolved_path: str = "mock://demo",
    filename: str = "mock_video.mp4",
    optimization_target: int | None = None,
) -> ReviewReport:
    """Create evidence-shaped mock data for report and CLI tests without a real video."""
    assets_dir = ensure_dir(output_dir / "assets" / "mock_keyframes")
    keyframe_path = assets_dir / "mock_frame_001.svg"
    keyframe_path.write_text(_mock_svg(), encoding="utf-8")
    video = VideoInfo(
        source=source,
        resolved_path=resolved_path,
        filename=filename,
        duration_seconds=180.0,
        width=1920,
        height=1080,
        fps=30.0,
        video_codec="h264",
        audio_codec="aac",
        bitrate=8_000_000,
        file_size=128_000_000,
        audio_sample_rate=48000,
        audio_channels=2,
    )
    keyframes = [
        Keyframe(
            path=str(keyframe_path),
            timestamp_seconds=12.0,
            timestamp_label="00:12.00",
            metrics={"sharpness": 42.0, "brightness": 51.0, "contrast": 28.0},
        )
    ]
    visual = {
        "frames": [{"path": str(keyframe_path), "timestamp": 12.0, "sharpness": 42.0}],
        "avg_sharpness": 72.0,
        "avg_brightness": 58.0,
        "avg_contrast": 29.0,
        "underexposed_ratio_mean": 0.09,
        "overexposed_ratio_mean": 0.01,
        "low_sharpness_frames": [{"path": str(keyframe_path), "timestamp": 12.0, "sharpness": 42.0}],
        "low_contrast_frames": [{"path": str(keyframe_path), "timestamp": 12.0, "contrast": 28.0}],
        "worst_frames": [{"path": str(keyframe_path), "timestamp": 12.0, "sharpness": 42.0}],
        "center_sharpness_mean": 65.0,
        "center_brightness_mean": 52.0,
    }
    color = {
        "frames": [{"path": str(keyframe_path), "timestamp": 12.0}],
        "avg_saturation": 24.0,
        "temperature_bias": "warm",
        "temperature_delta": -14.0,
        "color_inconsistency": 18.0,
        "inconsistent_frames": [],
    }
    editing = {
        "black_frames": [],
        "repeated_frame_ratio": 0.04,
        "static_segments": [],
        "avg_shot_length": 3.8,
    }
    audio = AudioMetrics(
        approx_loudness_db=-32.0,
        peak_db=-2.4,
        too_quiet=True,
        silence_segments=[{"start": 66.0, "end": 67.2, "duration": 1.2}],
        recommendations=["整体响度偏低，建议提升主声音量。"],
    )
    subtitles = {
        "bottom_activity_mean": 0.13,
        "safe_margin_risk_mean": 0.04,
        "dense_bottom_frames": [{"path": str(keyframe_path), "timestamp": 12.0}],
        "unsafe_margin_frames": [],
    }
    return score_report(video, visual, color, editing, audio, subtitles, keyframes, preset=preset, mode=mode,
                        optimization_target=optimization_target, mock=True)


def _module_cards(report: ReviewReport) -> list[dict[str, Any]]:
    cards = []
    for key, (name, max_score) in MODULES.items():
        score = report.module_scores.get(key, 0)
        cards.append({"key": key, "name": name, "score": score, "max": max_score, "percent": round(score / max_score * 100, 1)})
    return cards


def _timeline_items(report: ReviewReport) -> list[Issue]:
    return [issue for issue in report.issues if issue.timestamp_start is not None]


def _radar_svg(report: ReviewReport) -> str:
    points = []
    labels = []
    center = 145
    radius = 105
    modules = list(MODULES.items())
    for index, (key, (name, max_score)) in enumerate(modules):
        angle = -math.pi / 2 + index * 2 * math.pi / len(modules)
        percent = report.module_scores.get(key, 0) / max_score
        x = center + math.cos(angle) * radius * percent
        y = center + math.sin(angle) * radius * percent
        points.append(f"{x:.1f},{y:.1f}")
        lx = center + math.cos(angle) * (radius + 22)
        ly = center + math.sin(angle) * (radius + 22)
        labels.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle">{html.escape(name[:6])}</text>')
    grid = []
    for level in (0.25, 0.5, 0.75, 1.0):
        ring = []
        for index in range(len(modules)):
            angle = -math.pi / 2 + index * 2 * math.pi / len(modules)
            ring.append(f"{center + math.cos(angle) * radius * level:.1f},{center + math.sin(angle) * radius * level:.1f}")
        grid.append(f'<polygon points="{" ".join(ring)}" fill="none" stroke="#d7dde8" stroke-width="1"/>')
    return (
        '<svg viewBox="0 0 290 290" class="radar" role="img" aria-label="分项评分雷达图">'
        + "".join(grid)
        + f'<polygon points="{" ".join(points)}" fill="rgba(30,92,168,.22)" stroke="#1e5ca8" stroke-width="2"/>'
        + "".join(labels)
        + "</svg>"
    )


def _asset_path(path: str | None, output_dir: Path) -> str:
    if not path:
        return ""
    path_obj = Path(path)
    try:
        return path_obj.resolve().relative_to(output_dir.resolve()).as_posix()
    except ValueError:
        if not path_obj.is_absolute() and path_obj.parts and path_obj.parts[0] == output_dir.name:
            return Path(*path_obj.parts[1:]).as_posix()
        return path_obj.as_posix()


def _format_metrics_zh(metrics: dict[str, Any] | None) -> str:
    """Format frame metrics with Chinese labels for report readability."""
    if not metrics:
        return "暂无关键指标"

    ordered_keys = [key for key in METRIC_LABELS_ZH if key in metrics]
    ordered_keys.extend(key for key in metrics if key not in METRIC_LABELS_ZH)
    parts = []
    for key in ordered_keys:
        label = METRIC_LABELS_ZH.get(key, key)
        value = _format_metric_by_key(key, metrics[key])
        parts.append(f"{label}：{value}")
    return "；".join(parts)


def _format_metric_value_zh(value: Any) -> str:
    """Format arbitrary issue metric values without exposing raw Python dict syntax."""
    if isinstance(value, dict):
        return _format_metrics_zh(value)
    if isinstance(value, list):
        return "；".join(_format_metric_value_zh(item) for item in value) if value else "无"
    if isinstance(value, float):
        return f"{value:.4g}"
    if value is None:
        return "无"
    return str(value)


def _format_metric_by_key(key: str, value: Any) -> str:
    if isinstance(value, dict):
        return _format_metrics_zh(value)
    if isinstance(value, list):
        return _format_metric_value_zh(value)
    if isinstance(value, (int, float)):
        numeric = float(value)
        if key in PERCENT_METRICS:
            return f"{numeric * 100:.2f}%"
        if key in {"timestamp", "start", "end", "duration"}:
            suffix = " 秒"
            return f"{numeric:.2f}{suffix}"
        return f"{numeric:.2f}"
    return str(value)


def _fallback_html(report: ReviewReport, context: dict[str, Any]) -> str:
    asset_path = context["asset_path"]
    format_metrics = context["format_metrics"]
    issue_cards = "\n".join(_issue_card(issue, asset_path) for issue in report.issues[:10])
    module_cards = "\n".join(
        f"<div class='card'><span>{html.escape(card['name'])}</span><strong>{card['score']}/{card['max']}</strong><div class='bar'><i style='width:{card['percent']}%'></i></div></div>"
        for card in context["modules"]
    )
    duration = max(report.video_info.duration_seconds, 1.0)
    timeline = "\n".join(
        f"<span class='tick {issue.severity}' style='left:{max(min((issue.timestamp_start or 0) / duration * 100, 100), 0):.2f}%' title='{seconds_to_label(issue.timestamp_start)} {html.escape(issue.problem)}'></span>"
        for issue in report.issues
        if issue.timestamp_start is not None
    )
    timeline_cards = "\n".join(
        f"<div class='timeline-event {issue.severity}'><b>{seconds_to_label(issue.timestamp_start)}</b><span>{html.escape(issue.problem)}</span></div>"
        for issue in report.issues[:12]
        if issue.timestamp_start is not None
    )
    keyframes = "\n".join(
        f"<article class='issue low'><img src='{html.escape(asset_path(frame.path))}' alt='关键帧'><div><b>{html.escape(frame.timestamp_label)}</b><p class='muted'>关键指标：{html.escape(format_metrics(frame.metrics))}</p></div></article>"
        for frame in report.keyframes[:8]
    )
    verdict_items = [
        ("后期优化验收" if report.optimization else "是否可发布", report.publish_recommendation),
        ("是否适合投放", "适合投放" if report.overall_score >= 85 else "建议优化后再投放"),
        ("是否建议重剪", "是" if report.module_scores.get("editing_rhythm", 0) < 10 else "否"),
        ("是否建议重调色", "是" if report.module_scores.get("color_grading", 0) < 14 else "否"),
        ("是否建议重新导出", "是" if report.module_scores.get("export_specs", 0) < 4 else "否"),
    ]
    if report.optimization:
        verdict_items[1] = ("验收目标", f"{report.optimization.target} / 100，内容拆解另评")
    verdict_html = "".join(
        "<div class='verdict-item{primary}'><span>{label}</span><b>{value}</b></div>".format(
            primary=" primary" if idx == 0 else "",
            label=html.escape(label),
            value=html.escape(value),
        )
        for idx, (label, value) in enumerate(verdict_items)
    )
    checklist = "\n".join(
        f"<h3>{priority}</h3><ul>{''.join(f'<li>{html.escape(item)}</li>' for item in items)}</ul>"
        for priority, items in report.revision_checklist.items()
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>视频后期评分报告</title>{_fallback_css()}</head>
<body><main>
<section class="hero"><div><p>视频后期评分系统</p><h1>{html.escape(report.video_info.filename)}</h1><p>{html.escape(report.publish_recommendation)}</p></div><div class="score">{report.overall_score}<small>{report.grade}</small></div></section>
<section class="panel verdict-panel"><h2>最终建议</h2><div class="verdict-grid">{verdict_html}</div></section>
<section class="grid">{module_cards}</section>
<section class="panel"><h2>分项雷达图</h2>{context["radar_svg"]}</section>
<section class="panel"><h2>时间轴问题分布</h2><div class="timeline">{timeline}</div><div class="timeline-events">{timeline_cards}</div></section>
<section class="panel"><h2>Top 10 问题列表</h2>{issue_cards or '<p>未发现明显扣分项。</p>'}</section>
<section class="panel"><h2>关键帧证据区</h2>{keyframes or '<p>没有关键帧证据。</p>'}</section>
<section class="panel"><h2>音频分析</h2><p>近似响度：{report.audio_metrics.approx_loudness_db} dB，峰值：{report.audio_metrics.peak_db} dB，静音段：{len(report.audio_metrics.silence_segments)}</p></section>
<section class="panel"><h2>导出规范区</h2><table><tr><th>项目</th><th>当前参数</th><th>建议</th></tr><tr><td>分辨率</td><td>{report.video_info.width}x{report.video_info.height}</td><td>普通发布至少 1080p，电商和品牌片优先保留细节。</td></tr><tr><td>帧率</td><td>{report.video_info.fps:.2f} fps</td><td>按平台选择 24/25/30/50/60 fps。</td></tr><tr><td>编码</td><td>{html.escape(report.video_info.video_codec)}</td><td>根据平台使用 H.264/H.265，并检查码率。</td></tr><tr><td>音频采样率</td><td>{report.video_info.audio_sample_rate}</td><td>建议 44.1kHz 或 48kHz。</td></tr></table><ul>{''.join(f'<li>{html.escape(item)}</li>' for item in report.export_recommendations)}</ul></section>
<section class="panel"><h2>修改优先级清单</h2>{checklist}</section>
</main></body></html>"""


def _issue_card(issue: Issue, asset_path) -> str:
    image = f"<img src='{html.escape(asset_path(issue.evidence_image))}' alt='证据截图'>" if issue.evidence_image else ""
    return (
        f"<article class='issue {issue.severity}'>{image}<div><b>{html.escape(issue.problem)}</b>"
        f"<p>{html.escape(issue.recommendation)}</p><small>{html.escape(issue.module)} | {html.escape(issue.severity)} | "
        f"{seconds_to_label(issue.timestamp_start)} | 扣 {issue.score_impact} 分</small></div></article>"
    )


def _fallback_css() -> str:
    return """<style>
body{margin:0;background:#f4f6fa;color:#162033;font-family:Arial,'Microsoft YaHei',sans-serif}main{max-width:1180px;margin:auto;padding:28px}
.hero{display:flex;justify-content:space-between;align-items:center;background:#152033;color:white;padding:28px;border-radius:8px}.hero h1{margin:.2em 0;font-size:30px}.score{font-size:72px;font-weight:800}.score small{display:block;font-size:24px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:18px 0}.card,.panel{background:white;border:1px solid #e3e7ef;border-radius:8px;padding:18px}.card strong{display:block;font-size:26px;margin:10px 0}
.verdict-panel{margin:18px 0;background:#101f36;border-color:#315f9d;color:white;box-shadow:0 16px 38px rgba(16,31,54,.22)}.verdict-panel h2{display:flex;align-items:center;gap:10px;color:white;font-size:24px}.verdict-panel h2:before{content:"结论";display:inline-flex;align-items:center;border-radius:99px;padding:3px 10px;background:#e7effa;color:#0f376b;font-size:13px;line-height:1.5;font-weight:700}.verdict-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.verdict-item{background:rgba(255,255,255,.09);border:1px solid rgba(255,255,255,.18);border-radius:8px;padding:12px;min-width:0}.verdict-item.primary{grid-column:span 2;background:white;color:#12233c;border-color:white;box-shadow:0 10px 24px rgba(3,12,28,.22)}.verdict-item span{display:block;color:#b9c9df;font-size:12px}.verdict-item.primary span{color:#49627f}.verdict-item b{display:block;margin-top:4px;font-size:19px;line-height:1.25;overflow-wrap:anywhere}.verdict-item.primary b{font-size:28px}
.bar{height:8px;background:#e8edf5;border-radius:99px;overflow:hidden}.bar i{display:block;height:100%;background:#1e5ca8}.radar{max-width:360px}
.timeline{position:relative;min-height:28px;border-top:2px solid #cbd5e1;margin-top:22px;margin-bottom:14px}.tick{position:absolute;top:-9px;width:18px;height:18px;border-radius:50%;border:3px solid #fff;transform:translateX(-50%);box-shadow:0 0 0 1px rgba(0,0,0,.12)}
.timeline-events{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px}.timeline-event{border:1px solid #e3e7ef;border-left:5px solid #60799c;border-radius:8px;background:#fbfcfe;padding:8px 10px}.timeline-event b{display:block;font-size:12px;color:#1e5ca8}.timeline-event span{display:block;font-size:12px;overflow-wrap:anywhere}
.issue{display:grid;grid-template-columns:1fr;grid-template-rows:auto 1fr;gap:10px;border-left:6px solid #6e7e96;padding:12px;margin:12px 0;background:#f8fafc}.issue img{width:100%;height:clamp(130px,14vw,210px);object-fit:contain;background:#0f172a;border-radius:6px}.critical{border-color:#7a1020}.high{border-color:#d62839}.medium{border-color:#f28c28}.low{border-color:#60799c}
.issue-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #e3e7ef;padding:9px;text-align:left;vertical-align:top}th{color:#667085}
@media(max-width:720px){.hero{display:block}.score{font-size:52px}.issue-list,.timeline-events{grid-template-columns:1fr}.verdict-item.primary{grid-column:auto}.issue img{height:clamp(160px,52vw,300px)}}
</style>"""


def _mock_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
<rect width="960" height="540" fill="#20242e"/>
<rect x="92" y="76" width="664" height="348" fill="#384052"/>
<rect x="132" y="116" width="420" height="220" fill="#596174"/>
<text x="130" y="476" font-family="Arial" font-size="34" fill="#f2f5fa">Mock keyframe evidence</text>
<text x="132" y="166" font-family="Arial" font-size="28" fill="#c9d3e4">Low sharpness / low contrast sample</text>
</svg>"""
