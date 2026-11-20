from __future__ import annotations

import argparse
import csv
import html
import json
import sys
import subprocess
from . import __version__
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .ai_review import optional_ai_review
from .audio_metrics import analyze_audio_quality
from .color_metrics import analyze_color_grading
from .editorial import calibration, blank_notes, digest, evaluate, pending_review
from .edit_metrics import analyze_editing_rhythm
from .frame_sampler import sample_frames
from .ingest import VIDEO_EXTENSIONS, is_url, resolve_input
from .models import AudioMetrics
from .probe import probe_video
from .report import create_mock_report, write_reports
from .scoring import MINIMUM_OPTIMIZATION_SCORE, score_report
from .subtitle_metrics import analyze_subtitles_graphics
from .utils import ensure_dir, open_in_default_app, package_root, print_console, relative_or_absolute, safe_slug, seconds_to_label
from .visual_metrics import analyze_visual_quality


PRESETS = ("default", "amazon_product", "short_social", "brand_commercial")
MODES = ("deep",)
DEFAULT_MODE = "deep"
DEFAULT_SAMPLE_FPS = 3.0
DEFAULT_MAX_AI_FRAMES = 48
DEFAULT_MAX_SAMPLED_FRAMES = 360
DEFAULT_FRAME_WIDTH = 720


@dataclass(frozen=True)
class BatchTarget:
    source: str
    source_type: str
    origin: str
    display_hint: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="postscore", description="视频后期评分系统 / 后期质检系统")
    subparsers = parser.add_subparsers(dest="command")
    review = subparsers.add_parser("review", help="分析视频后期处理质量并生成报告")
    review.add_argument("source", nargs="?", help="本地视频路径或可下载公开视频链接")
    review.add_argument("--mode", choices=MODES, default=DEFAULT_MODE, help="检测模式，固定为 deep")
    review.add_argument("--preset", choices=PRESETS, default="default", help="评分预设，默认 default")
    review.add_argument("--html", action="store_true", help="生成 HTML 报告")
    review.add_argument("--json", action="store_true", help="生成 JSON 报告")
    review.add_argument("--open", action="store_true", help="生成后自动打开 HTML 报告")
    review.add_argument("--sample-fps", type=float, default=None, help="深度抽帧频率，默认 3")
    review.add_argument("--max-sampled-frames", type=int, default=DEFAULT_MAX_SAMPLED_FRAMES, help="默认最多抽取约 360 张关键帧，0 表示不限制")
    review.add_argument("--frame-width", type=int, default=DEFAULT_FRAME_WIDTH, help="关键帧最长宽度，默认 720")
    review.add_argument("--max-ai-frames", type=int, default=None, help="AI 审美判断最多关键帧数，默认 48")
    review.add_argument("--output-dir", default=None, help="报告输出目录，默认 postscore-ai/reports")
    review.add_argument("--mock", action="store_true", help="使用 mock 数据生成示例报告，不需要真实视频")
    batch = subparsers.add_parser("batch", help="批量分析多个视频链接、本地文件或文件夹")
    batch.add_argument("sources", nargs="+", help="多个本地视频路径、文件夹或可下载公开视频链接")
    batch.add_argument("--mode", choices=MODES, default=DEFAULT_MODE, help="检测模式，固定为 deep")
    batch.add_argument("--preset", choices=PRESETS, default="default", help="评分预设，默认 default")
    batch.add_argument("--html", action="store_true", help="兼容参数；批量模式始终为每条视频生成完整 HTML 报告")
    batch.add_argument("--json", action="store_true", help="兼容参数；批量模式始终为每条视频生成完整 JSON 报告")
    batch.add_argument("--open", action="store_true", help="生成后自动打开批量总览 HTML")
    batch.add_argument("--sample-fps", type=float, default=None, help="深度抽帧频率，默认 3")
    batch.add_argument("--max-sampled-frames", type=int, default=DEFAULT_MAX_SAMPLED_FRAMES, help="默认最多抽取约 360 张关键帧，0 表示不限制")
    batch.add_argument("--frame-width", type=int, default=DEFAULT_FRAME_WIDTH, help="关键帧最长宽度，默认 720")
    batch.add_argument("--max-ai-frames", type=int, default=None, help="AI 审美判断最多关键帧数，默认 48")
    batch.add_argument("--output-dir", default=None, help="报告输出目录，默认 postscore-ai/reports")
    batch.add_argument("--recursive", action="store_true", help="扫描文件夹时递归包含子文件夹")
    batch.add_argument("--mock", action="store_true", help="使用 mock 数据生成示例报告，不需要真实视频")
    batch.add_argument("--no-index", action="store_true", help="不生成批量总览 HTML，仅输出 CSV 和单条报告")
    for command in (review, batch):
        command.add_argument("--optimization-target", type=int, choices=range(MINIMUM_OPTIMIZATION_SCORE, 101),
                             metavar="85..100", help="短视频后期验收目标；short_social 默认 85，其他预设可显式启用")
    review.add_argument("--editorial", type=Path, help="本次导出的编辑审片 JSON")
    batch.add_argument("--editorial-dir", type=Path, help="以成片 SHA256.json 命名的审片文件目录")
    calibrate = subparsers.add_parser("calibrate", help="比较两位独立评审首选及报告前三项")
    calibrate.add_argument("manifest", type=Path)
    calibrate.add_argument("--output", required=True, type=Path)
    brief = subparsers.add_parser("brief", help="为当前文件生成可编辑的传播审片输入")
    brief.add_argument("source", type=Path)
    brief.add_argument("--output", required=True, type=Path)
    from .revision_cli import add_commands
    add_commands(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command and args.command.startswith("revision-"):
        from .revision_cli import run_command
        try:
            run_command(args)
            return 0
        except (ValueError, OSError, KeyError, TypeError, ArithmeticError, RuntimeError, subprocess.SubprocessError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command in {"brief", "calibrate"}:
        try:
            data = blank_notes(args.source, current=True) if args.command == "brief" else calibration(args.manifest)
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
            return 0
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
            print_console(str(exc))
            return 2
    if args.command == "review":
        return run_review(args)
    if args.command == "batch":
        return run_batch(args)
    parser.print_help()
    return 0


def run_review(args: argparse.Namespace) -> int:
    output_dir = ensure_dir(Path(args.output_dir) if args.output_dir else package_root() / "reports")
    write_html = bool(args.html or args.open or args.mock)
    write_json = True if not args.json else bool(args.json)
    try:
        if args.mock:
            report = create_mock_report(output_dir, preset=args.preset, mode=args.mode, optimization_target=args.optimization_target)
        else:
            if not args.source:
                raise RuntimeError("请提供本地视频路径或可下载公开视频链接；示例：python -m postscore review \"video.mp4\" --html")
            report = _analyze_video(args, output_dir)
        attach_editorial(args, report)
        paths = write_reports(report, output_dir, write_html=write_html, write_json=write_json)
        _print_summary(report, paths)
        if args.open and "html" in paths:
            open_in_default_app(paths["html"])
        return 0
    except Exception as exc:
        print_console(f"[red]分析失败：{exc}[/red]")
        return 2


def run_batch(args: argparse.Namespace) -> int:
    output_dir = ensure_dir(Path(args.output_dir) if args.output_dir else package_root() / "reports")
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    write_html = True
    write_json = True
    targets = _expand_batch_sources(args.sources, recursive=args.recursive)
    results: list[dict[str, object]] = []

    if not targets:
        print_console("[red]批量分析失败：没有找到可分析的视频文件或链接。[/red]")
        return 2

    total = len(targets)
    for index, target in enumerate(targets, start=1):
        print_console(f"[cyan]({index}/{total}) 开始分析：{target.display_hint}[/cyan]")
        started = time.perf_counter()
        try:
            if target.source_type == "invalid":
                raise RuntimeError("找不到本地视频文件、可识别视频扩展名或可下载链接")
            if args.mock:
                report = create_mock_report(
                    output_dir,
                    preset=args.preset,
                    mode=args.mode,
                    optimization_target=args.optimization_target,
                    source=target.source,
                    resolved_path=target.source,
                    filename=_mock_filename_for_target(target),
                )
            else:
                item_args = argparse.Namespace(**vars(args))
                item_args.source = target.source
                report = _analyze_video(item_args, output_dir)
            attach_editorial(args, report)
            paths = write_reports(
                report,
                output_dir,
                write_html=write_html,
                write_json=write_json,
                stem_prefix=f"batch_{index:03d}",
            )
            elapsed = round(time.perf_counter() - started, 2)
            results.append(_batch_success_row(index, target, report, paths, elapsed))
            print_console(f"[green]完成：{report.video_info.filename} / {report.overall_score} / {report.grade} / {elapsed}s[/green]")
        except Exception as exc:
            elapsed = round(time.perf_counter() - started, 2)
            results.append(_batch_failure_row(index, target, exc, elapsed))
            print_console(f"[red]失败：{target.display_hint} - {exc}[/red]")

    summary_paths = _write_batch_outputs(results, output_dir, batch_id, write_index=not args.no_index)
    _print_batch_summary(results, summary_paths)
    if args.open and "html" in summary_paths:
        open_in_default_app(summary_paths["html"])
    return 0 if all(row["status"] == "success" for row in results) else 1


def attach_editorial(args, report) -> None:
    notes = getattr(args, "editorial", None)
    directory = getattr(args, "editorial_dir", None)
    source = Path(report.video_info.resolved_path)
    if directory is not None and not directory.is_dir():
        raise ValueError("找不到批量审片目录")
    if directory is not None and not args.mock:
        candidate = directory / (digest(source) + ".json")
        notes = candidate if candidate.is_file() else None
    if notes is not None and args.mock:
        raise ValueError("模拟技术报告不能附入真实成片审片证据")
    if notes is not None:
        target = report.optimization.target if report.optimization else 85
        report.editorial = evaluate(notes, source, report.issues, target)
        if report.editorial.get("criteria") and report.optimization and report.optimization.status == "below_target":
            report.editorial["status"] = "发布前须改"
            report.editorial["blockers"].append(f"后期技术 {report.overall_score:g} 分，低于约定目标 {target}")
    else:
        report.editorial = pending_review()
    technical = report.optimization.verdict if report.optimization else f"后期技术 {report.overall_score:g}/100"
    if args.mock and not report.optimization:
        technical = "技术示例数据"
    report.publish_recommendation = technical + " · " + report.editorial["status"]


def _analyze_video(args: argparse.Namespace, output_dir: Path):
    requested_sample_fps = args.sample_fps if args.sample_fps is not None else DEFAULT_SAMPLE_FPS
    max_ai_frames = args.max_ai_frames if args.max_ai_frames is not None else DEFAULT_MAX_AI_FRAMES
    video_path = resolve_input(args.source, output_dir)
    video_info = probe_video(video_path, source=args.source)
    sample_fps = _effective_sample_fps(
        requested_sample_fps,
        video_info.duration_seconds,
        args.max_sampled_frames,
    )
    run_id = f"{safe_slug(video_info.filename)}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    frame_dir = output_dir / "assets" / "keyframes" / run_id
    keyframes = sample_frames(video_path, frame_dir, sample_fps=sample_fps, scale_width=args.frame_width)
    visual = analyze_visual_quality(keyframes)
    color = analyze_color_grading(keyframes)
    editing = analyze_editing_rhythm(keyframes, video_info.duration_seconds)
    audio = (analyze_audio_quality(video_path) if video_info.audio_codec != "none"
             else AudioMetrics(has_audio=False, recommendations=["视频未检测到音轨。"]))
    subtitles = analyze_subtitles_graphics(keyframes)
    optional_ai_review(keyframes, max_frames=max_ai_frames)
    report = score_report(
        video_info=video_info,
        visual_metrics=visual,
        color_metrics=color,
        edit_metrics=editing,
        audio_metrics=audio,
        subtitle_metrics=subtitles,
        keyframes=keyframes,
        preset=args.preset,
        mode=args.mode,
        optimization_target=args.optimization_target,
    )
    report.sampling = dict(engine=__version__, sample_fps=requested_sample_fps, max_frames=args.max_sampled_frames,
                           frame_width=args.frame_width, effective_fps=sample_fps)
    return report


def _expand_batch_sources(sources: Sequence[str], recursive: bool = False) -> list[BatchTarget]:
    targets: list[BatchTarget] = []
    for source in sources:
        if is_url(source):
            targets.append(BatchTarget(source=source, source_type="url", origin=source, display_hint=_url_display_hint(source)))
            continue

        path = Path(source).expanduser()
        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            files = sorted(
                (candidate for candidate in path.glob(pattern) if candidate.is_file() and candidate.suffix.lower() in VIDEO_EXTENSIONS),
                key=lambda candidate: str(candidate).lower(),
            )
            if not files:
                targets.append(
                    BatchTarget(
                        source=str(path.resolve()),
                        source_type="invalid",
                        origin=str(path.resolve()),
                        display_hint=f"{path.name}（未找到视频）",
                    )
                )
                continue
            for video_path in files:
                targets.append(
                    BatchTarget(
                        source=str(video_path.resolve()),
                        source_type="file",
                        origin=str(path.resolve()),
                        display_hint=video_path.name,
                    )
                )
            continue

        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
            targets.append(
                BatchTarget(
                    source=str(path.resolve()),
                    source_type="file",
                    origin=str(path.resolve()),
                    display_hint=path.name,
                )
            )
            continue

        targets.append(BatchTarget(source=source, source_type="invalid", origin=source, display_hint=source))
    return targets


def _batch_success_row(index: int, target: BatchTarget, report, paths: dict[str, Path], elapsed_seconds: float) -> dict[str, object]:
    display_name = _report_display_name(report.video_info.filename, target)
    top_issues = " | ".join(issue.problem for issue in report.issues[:5]) or "未发现明显扣分项"
    optimization = report.optimization
    return {
        "index": index,
        "status": "success",
        "source_type": target.source_type,
        "display_name": display_name,
        "online_link": target.source if target.source_type == "url" else "",
        "file_name": report.video_info.filename,
        "file_path": report.video_info.resolved_path,
        "input_source": target.source,
        "origin": target.origin,
        "score": report.overall_score,
        "grade": report.grade,
        "recommendation": report.publish_recommendation,
        "optimization_target": optimization.target if optimization else "",
        "optimization_gap": optimization.gap if optimization else "",
        "optimization_status": optimization.status if optimization else "",
        "editorial_status": report.editorial["status"] if report.editorial else "",
        "editorial_priority": " | ".join(i["topic"] for i in report.editorial["priorities"]) if report.editorial else "",
        "duration": report.video_info.duration_seconds,
        "resolution": f"{report.video_info.width}x{report.video_info.height}",
        "fps": round(report.video_info.fps, 2),
        "elapsed_seconds": elapsed_seconds,
        "top_issues": top_issues,
        "html_report": str(paths.get("html", "")),
        "json_report": str(paths.get("json", "")),
        "error": "",
    }


def _batch_failure_row(index: int, target: BatchTarget, exc: Exception, elapsed_seconds: float) -> dict[str, object]:
    return {
        "index": index,
        "status": "failed",
        "source_type": target.source_type,
        "display_name": target.display_hint,
        "online_link": target.source if target.source_type == "url" else "",
        "file_name": "",
        "file_path": target.source if target.source_type == "file" else "",
        "input_source": target.source,
        "origin": target.origin,
        "score": "",
        "grade": "",
        "recommendation": "",
        "duration": "",
        "resolution": "",
        "fps": "",
        "elapsed_seconds": elapsed_seconds,
        "top_issues": "",
        "html_report": "",
        "json_report": "",
        "error": str(exc),
    }


def _write_batch_outputs(results: list[dict[str, object]], output_dir: Path, batch_id: str, write_index: bool = True) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    csv_path = output_dir / f"batch_summary_{batch_id}.csv"
    fieldnames = [
        "index",
        "status",
        "source_type",
        "display_name",
        "online_link",
        "file_name",
        "file_path",
        "input_source",
        "origin",
        "score",
        "grade",
        "recommendation",
        "optimization_target",
        "optimization_gap",
        "optimization_status",
        "editorial_status",
        "editorial_priority",
        "duration",
        "resolution",
        "fps",
        "elapsed_seconds",
        "top_issues",
        "html_report",
        "json_report",
        "error",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    paths["csv"] = csv_path

    if write_index:
        html_path = output_dir / f"batch_index_{batch_id}.html"
        html_path.write_text(_render_batch_index(results, output_dir), encoding="utf-8")
        paths["html"] = html_path
    return paths


def _render_batch_index(results: list[dict[str, object]], output_dir: Path) -> str:
    success_count = sum(1 for row in results if row["status"] == "success")
    failed_count = len(results) - success_count
    rows = "\n".join(_render_batch_row(row, output_dir) for row in results)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>批量后期评分总览</title>
  <style>
    body{{margin:0;background:#f5f7fb;color:#172033;font-family:Arial,"Microsoft YaHei",sans-serif;line-height:1.55}}
    main{{max-width:1280px;margin:0 auto;padding:28px}}
    header{{background:#152033;color:#fff;border-radius:8px;padding:24px 28px;margin-bottom:18px}}
    h1{{margin:0 0 8px;font-size:28px;letter-spacing:0}}
    .summary{{display:flex;gap:18px;flex-wrap:wrap;color:#c8d2e3}}
    .summary b{{color:#fff;font-size:20px}}
    table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #dfe5ee;border-radius:8px;overflow:hidden}}
    th,td{{border-bottom:1px solid #dfe5ee;padding:10px;text-align:left;vertical-align:top;font-size:14px}}
    th{{color:#667085;background:#f8fafc;font-weight:700}}
    tr:last-child td{{border-bottom:0}}
    a{{color:#1e5ca8;text-decoration:none}}
    .status{{display:inline-flex;border-radius:99px;padding:2px 8px;color:#fff;font-size:12px}}
    .success{{background:#177245}}
    .failed{{background:#b42318}}
    .score{{font-size:22px;font-weight:800}}
    .muted{{color:#667085;font-size:12px;overflow-wrap:anywhere}}
    .issues{{max-width:360px}}
    @media(max-width:820px){{main{{padding:16px}}table,thead,tbody,tr,th,td{{display:block}}thead{{display:none}}td{{border-bottom:0}}tr{{border-bottom:1px solid #dfe5ee;padding:10px}}td::before{{content:attr(data-label);display:block;color:#667085;font-size:12px;margin-bottom:2px}}}}
  </style>
</head>
<body>
<main>
  <header>
    <h1>批量后期评分总览</h1>
    <div class="summary"><span>总数 <b>{len(results)}</b></span><span>成功 <b>{success_count}</b></span><span>失败 <b>{failed_count}</b></span></div>
  </header>
  <table>
    <thead><tr><th>#</th><th>状态</th><th>视频名称与来源</th><th>分数</th><th>等级</th><th>主要问题</th><th>报告</th><th>耗时</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</main>
</body>
</html>"""


def _render_batch_row(row: dict[str, object], output_dir: Path) -> str:
    status = str(row["status"])
    source_type = str(row["source_type"])
    source_label = "在线视频" if source_type == "url" else "本地文件"
    display_name = html.escape(str(row["display_name"]))
    source_html = _source_html(row)
    report_links = _report_links(row, output_dir)
    score = html.escape(str(row["score"]))
    target_detail = ""
    if row.get("optimization_target"):
        verdict = html.escape(str(row["recommendation"]))
        target_detail = f'<div class="muted">目标 {row["optimization_target"]} 分 · {verdict}</div>'
    if row.get("editorial_status"):
        target_detail += '<div class="muted">' + html.escape(str(row["editorial_status"])) + '</div>'
    grade = html.escape(str(row["grade"]))
    issues = html.escape(str(row["top_issues"] or row["error"]))
    if row.get("editorial_priority"):
        issues = html.escape(str(row["editorial_priority"])) + "<br>" + issues
    return f"""<tr>
  <td data-label="#">{row["index"]}</td>
  <td data-label="状态"><span class="status {status}">{html.escape(status)}</span></td>
  <td data-label="视频名称与来源"><strong>{display_name}</strong><div class="muted">{source_label}</div>{source_html}</td>
  <td data-label="分数"><span class="score">{score}</span>{target_detail}</td>
  <td data-label="等级">{grade}</td>
  <td data-label="主要问题" class="issues">{issues}</td>
  <td data-label="报告">{report_links}</td>
  <td data-label="耗时">{row["elapsed_seconds"]}s</td>
</tr>"""


def _source_html(row: dict[str, object]) -> str:
    if row["source_type"] == "url":
        online_link = html.escape(str(row["online_link"]))
        resolved = html.escape(str(row["file_path"]))
        return f'<div><a href="{online_link}">原始链接</a></div><div class="muted">本地源：{resolved}</div>'
    file_path = html.escape(str(row["file_path"] or row["input_source"]))
    origin = html.escape(str(row["origin"]))
    return f'<div class="muted">文件位置：{file_path}</div><div class="muted">来源：{origin}</div>'


def _report_links(row: dict[str, object], output_dir: Path) -> str:
    links = []
    html_report = str(row.get("html_report") or "")
    json_report = str(row.get("json_report") or "")
    if html_report:
        links.append(f'<a href="{html.escape(relative_or_absolute(html_report, output_dir))}">HTML</a>')
    if json_report:
        links.append(f'<a href="{html.escape(relative_or_absolute(json_report, output_dir))}">JSON</a>')
    return " / ".join(links) if links else html.escape(str(row.get("error") or "无报告"))


def _print_batch_summary(results: list[dict[str, object]], paths: dict[str, Path]) -> None:
    success_count = sum(1 for row in results if row["status"] == "success")
    failed_count = len(results) - success_count
    lines = [f"批量分析完成：成功 {success_count} / 失败 {failed_count} / 总数 {len(results)}"]
    for row in results:
        if row["status"] == "success":
            detail = f" · {row['recommendation']}" if row.get("optimization_target") else ""
            editorial = " · ".join(str(row[k]) for k in ("editorial_status", "editorial_priority") if row.get(k))
            lines.append(f"{row['index']}. {row['display_name']}：{row['score']} / {row['grade']}{detail} · {editorial} - {row['top_issues']}")
        else:
            lines.append(f"{row['index']}. {row['display_name']}：失败 - {row['error']}")
    if "html" in paths:
        lines.append(f"批量总览 HTML：{paths['html']}")
    if "csv" in paths:
        lines.append(f"批量汇总 CSV：{paths['csv']}")
    print_console("\n".join(lines))


def _report_display_name(filename: str, target: BatchTarget) -> str:
    name = Path(filename).stem or target.display_hint
    if target.source_type == "url" and not name:
        name = _url_display_hint(target.source)
    return name[:100]


def _mock_filename_for_target(target: BatchTarget) -> str:
    if target.source_type == "url":
        return f"{safe_slug(_url_display_hint(target.source))}.mp4"
    return Path(target.source).name or f"{safe_slug(target.display_hint)}.mp4"


def _url_display_hint(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path_name = Path(urllib.parse.unquote(parsed.path)).stem
    if path_name:
        return path_name[:100]
    return (parsed.netloc or "online_video")[:100]


def _effective_sample_fps(requested_fps: float, duration_seconds: float, max_sampled_frames: int | None) -> float:
    """Cap deep-mode sampling work while preserving denser analysis for short videos."""
    if requested_fps <= 0:
        raise ValueError("--sample-fps 必须大于 0")
    if not max_sampled_frames or max_sampled_frames <= 0 or duration_seconds <= 0:
        return requested_fps
    capped_fps = max_sampled_frames / duration_seconds
    return max(min(requested_fps, capped_fps), 0.25)


def _print_summary(report, paths: dict[str, Path]) -> None:
    top = report.issues[:5]
    lines = [
        f"总分：{report.overall_score}",
        f"等级：{report.grade}",
    ]
    if report.editorial:
        lines.append("传播审片：" + report.editorial["status"])
        lines.extend(i["topic"] for i in report.editorial["priorities"])
    if report.optimization:
        lines.append(f"后期优化目标 {report.optimization.target} 分 · {report.optimization.verdict}")
    lines.append("Top 5 问题：")
    if top:
        for index, issue in enumerate(top, start=1):
            lines.append(f"{index}. [{issue.severity}] {issue.problem} - {issue.recommendation}")
    else:
        lines.append("未发现明显扣分项。")
    if "html" in paths:
        lines.append(f"HTML 报告：{paths['html']}")
    if "json" in paths:
        lines.append(f"JSON 报告：{paths['json']}")
    print_console("\n".join(lines))
