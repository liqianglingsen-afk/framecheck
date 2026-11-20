"""Commands for planning, rendering and comparing a specific edit."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import os
from urllib.parse import quote
import subprocess
import cv2
from tempfile import TemporaryDirectory

from .editorial import CREATIVE_WEIGHTS, digest
from .probe import probe_video
from .revision import (
    PACKAGING,
    compare,
    fingerprint,
    publish,
    read_plan,
    report_summary,
    requires_change,
    seal_plan,
    write_json,
)


def add_commands(sub):
    specs = [
        ("revision-init", "为原片生成剪前底稿", ("source", "baseline")),
        ("revision-plan", "复算预测并保存完整剪前方案", ("source", "baseline", "draft")),
        ("revision-render", "按已保存方案执行编辑命令并记录成片指纹", ("source", "plan")),
        ("revision-audit", "为改片生成原改对照验收底稿", ("plan", "revised")),
        ("revision-blind", "生成仅含成片、目标和量表的独立评分表", ("revised",)),
        (
            "revision-compare",
            "导出标准原改对照 HTML 和 JSON",
            ("plan", "source", "revised", "review", "audit"),
        ),
    ]
    for name, help_text, fields in specs:
        command = sub.add_parser(name, help=help_text)
        for field in fields:
            command.add_argument(field, type=Path)
        command.add_argument("--output", required=True, type=Path)
        if name == "revision-blind":
            command.add_argument("--goal", required=True)
        if name == "revision-render":
            command.add_argument(
                "--exec",
                dest="editor",
                nargs=argparse.REMAINDER,
                required=True,
                help="编辑命令及参数；{source}、{output} 分别替换为原片、独立 MP4 输出",
            )


def render(source, plan, editor, output):
    record = read_plan(plan)
    binding = digest(plan)
    sha = digest(source)
    if (
        sha != record["plan"]["source_sha256"]
        or not editor
        or not all(k in editor for k in ("{source}", "{output}"))
    ):
        raise ValueError("请匹配原片并在编辑命令中分别传入 {source} 和 {output}")
    if output.exists():
        raise ValueError("输出目录已存在")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temp:
        folder = Path(temp) / "export"
        folder.mkdir()
        video = (folder / "edited.mp4").resolve()
        args = [{"{source}": str(source.resolve()), "{output}": str(video)}.get(x, x) for x in editor]
        started = datetime.now(timezone.utc).isoformat()
        subprocess.run(args, check=True)
        info = probe_video(video)
        if min(info.width, info.height, info.duration_seconds) <= 0:
            raise ValueError("编辑器未生成有效视频轨")
        cap = cv2.VideoCapture(str(video))
        try:
            if not cap.read()[0]:
                raise ValueError("编辑器输出无可解码画面")
        finally:
            cap.release()
        if digest(plan) != binding or digest(source) != sha:
            raise ValueError("导出过程中原片或快照发生变化")
        revised_sha = digest(video)
        if revised_sha == sha and requires_change(record["plan"]):
            raise ValueError("要求改剪的导出与原片字节完全相同")
        receipt = dict(
            schema_version="render-0.4",
            plan_sha256=binding,
            source_sha256=sha,
            revised_sha256=revised_sha,
            started_at=started,
            completed_at=datetime.now(timezone.utc).isoformat(),
            command=editor,
        )
        receipt["seal"] = fingerprint(receipt)
        write_json(folder / "receipt.json", receipt)
        folder.rename(output)


def artifact_links(data, root, **files):
    links = {}
    for name, path in files.items():
        try:
            url = quote(Path(os.path.relpath(path.resolve(), root.resolve())).as_posix(), safe="/")
        except ValueError:
            url = path.resolve().as_uri()
        links[name] = url
    data["links"] = links
    if data["kind"] == "plan":
        data.pop("seal")
        data["seal"] = fingerprint(data)
    return data


def run_command(a):
    if a.command == "revision-init":
        sha = digest(a.source)
        before = report_summary(a.baseline, sha)
        duration = probe_video(a.source).duration_seconds
        data = dict(
            schema_version="cut-plan-0.4",
            source_sha256=sha,
            goal=before["goal"],
            target=before["content"]["target"],
            forecast_context="剪前预测",
            forecast={
                k: dict(low=None, expected=None, high=None, basis="", confidence="中") for k in CREATIVE_WEIGHTS
            },
            timeline=[
                dict(
                    source=dict(start=0, end=duration),
                    action="保留",
                    destinations=[dict(start=0, end=duration)],
                    picture="",
                    sound="",
                    graphics="",
                    screen="",
                    reason="",
                    acceptance="",
                )
            ],
            protect=[
                dict(name=asset["name"], kind="其他", source=dict(start=None, end=None),
                     value=asset["value"], handling=asset["source"] + " · " + asset["reason"])
                for asset in (before.get("criteria") or {}).get("assets", [])
            ],
            no_assets_reason="",
            packaging_plan={k: "" for k in PACKAGING},
            placement_plan=[
                dict(platform="", placement="", ui_state="", reference="", layout="", acceptance="")
            ],
            strategy="",
            next_if_short="",
        )
        write_json(a.output, data)
    elif a.command == "revision-plan":
        publish(
            a.output,
            lambda out: artifact_links(
                seal_plan(a.draft, a.source, a.baseline), a.output, 原片=a.source, 原片评分=a.baseline
            ),
        )
    elif a.command == "revision-render":
        render(a.source, a.plan, a.editor, a.output)
    elif a.command == "revision-audit":
        snap = read_plan(a.plan)
        data = dict(
            schema_version="cut-audit-0.4",
            plan_sha256=digest(a.plan),
            revised_sha256=digest(a.revised),
            protected={
                v["name"]: dict(status="待核", output=None, evidence="待核", tradeoff="待核")
                for v in snap["plan"]["protect"]
            },
            packaging={k: dict(status="待核", evidence="待核") for k in PACKAGING},
            placements=[],
            pending_placements=[],
            reviewer="",
            review_mode="自评",
            disputes=[],
            blind_sheet="",
            render_receipt="",
            timeline_check=dict(status="待核", evidence="待核"),
            variance="",
            next_edit="",
        )
        write_json(a.output, data)
    elif a.command == "revision-blind":
        write_json(
            a.output,
            dict(
                source=str(a.revised.resolve()),
                source_sha256=digest(a.revised),
                goal=a.goal,
                reviewer="",
                rubric=CREATIVE_WEIGHTS,
                observations=[],
                rubric_version="editorial-0.5",
                hook={k: dict(score=None, evidence="") for k in ("主体与动作", "受众相关", "继续观看理由", "前三秒可信线索")},
                payoff="",
                content=dict(
                    version="creative-100-v1",
                    marks={k: dict(score=None, evidence="") for k in CREATIVE_WEIGHTS},
                ),
            ),
        )
    elif a.command == "revision-compare":
        publish(
            a.output,
            lambda out: artifact_links(
                compare(a.plan, a.source, a.revised, a.review, a.audit, out),
                a.output,
                原片=a.source,
                改片=a.revised,
                剪前快照=a.plan,
                改片评分=a.review,
            ),
        )
    print(a.output)
