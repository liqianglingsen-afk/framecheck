"""Combine an editor's evidence with technical signals, keeping the original score intact."""
from __future__ import annotations

import csv
from decimal import Decimal
import hashlib
import html
import json
import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .creative_evidence import Criteria, HOOK_DIM, template

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
CHECKS = ("入口承诺", "前3秒", "中段兑现", "事实依据", "画面与包装", "收藏分享与品牌", "结尾行动", "行动承接")
AXES = {
    "传播": ("受众场景", "点击收益", "真实证据", "标题配合", "正文兑现"),
    "美学": ("主体构图", "文字层级", "光色质感", "品牌识别", "裁切可读"),
}
CREATIVE_WEIGHTS = {
    "前3秒语言心理钩子": 17, "选题/标题/封面承诺": 10, "脚本结构与信息递进": 12, "高光句音画同步": 8,
    "视觉画面与审美": 10, "拍摄与运镜": 6, "剪辑节奏与留存": 10, "字幕与包装": 8,
    "证据链与可信度": 9, "转化/关注/评论引导": 10,
}
PENDING = "传播待核"
MEDIA_SCHEMA = "editorial-0.3"


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Check(Record):
    status: Literal["已核", "待核", "须修"]
    evidence: Text


class CoverMark(Record):
    score: Annotated[int, Field(strict=True, ge=0, le=10)]
    evidence: Text


class CreativeMark(Record):
    score: Annotated[Decimal, Field(ge=0, max_digits=8, decimal_places=4)]
    evidence: Text


class Creative(Record):
    version: Literal["creative-100-v1"]
    marks: dict[str, CreativeMark]
    overall_cap: Annotated[Decimal, Field(ge=0, le=100)] | None = None
    cap_reason: str = ""

    def result(self, target):
        if set(self.marks) != set(CREATIVE_WEIGHTS):
            raise ValueError("内容分须包含十个固定维度")
        if any(m.score > CREATIVE_WEIGHTS[k] for k,m in self.marks.items()):
            raise ValueError("内容得分超出单项权重")
        if self.overall_cap is not None and not self.cap_reason.strip():
            raise ValueError("总分封顶缺依据")
        raw = sum(m.score for m in self.marks.values())
        total = min(raw, self.overall_cap) if self.overall_cap is not None else raw
        return self.model_dump(mode="json") | dict(raw=str(raw), total=str(total), target=target,
                                                   status="达到目标" if total >= target else "低于目标")


class Cover(Record):
    name: Text
    role: Literal["发布封面", "独立封面", "首帧", "候选"]
    image: Text
    integrity: Check
    marks: dict[str, CoverMark]
    correction: Text


class Finding(Record):
    topic: Text
    stage: Literal["入口承诺", "前3秒", "中段兑现", "事实依据", "画面与包装", "收藏分享与品牌", "结尾行动", "行动承接"]
    level: Literal["发布前须改", "影响目标", "精修"]
    evidence: Text
    action: Text
    acceptance: Text
    confidence: Literal["实测", "编辑判断", "待验证"]
    cost: Literal["现有素材剪辑", "新增包装或配音", "补拍"]
    # Use the exact technical issue title when the same problem has been reviewed.
    technical_issue: str = ""


class ReviewNotes(Record):
    schema_version: Literal["editorial-0.3", "editorial-0.5"]
    criteria: Criteria | None = None
    source_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    audience: Text
    goal: Text
    entry: Text
    bottleneck: Text
    checks: dict[str, Check]
    keep: list[Text]
    findings: list[Finding]
    covers: list[Cover] = Field(default_factory=list)
    content: Creative | None = None
    cover_required: bool = False
    # Reviewed technical alerts with a reason to retain the shot.
    retain_alerts: dict[str, Text] = Field(default_factory=dict)
    experiment: dict[Literal["变量", "对照", "挑战", "主指标", "护栏", "停止条件"], Text]
    metrics_csv: str = ""


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def blank_notes(source: Path, *, current=False) -> dict:
    data = dict(schema_version=MEDIA_SCHEMA, source_sha256=digest(source), audience="待核", goal="待核",
                entry="待核", bottleneck="待核", checks={k: {"status": "待核", "evidence": "待核"} for k in CHECKS}, keep=[], findings=[],
                covers=[], content=None, cover_required=False, retain_alerts={},
                experiment=dict.fromkeys(("变量", "对照", "挑战", "主指标", "护栏", "停止条件"), "待核"),
                metrics_csv="")
    if current:
        data.update(schema_version="editorial-0.5", criteria=template())
    return data


def read_metrics(path: Path, expected_hash: str) -> list[dict]:
    result = []
    fields = {"source_sha256", "variant", "traffic", "window", "metric", "numerator", "denominator"}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not fields.issubset(reader.fieldnames or []):
            raise ValueError("发布指标 CSV 缺少版本、来源、窗口或分子分母")
        for row in reader:
            if row["source_sha256"] != expected_hash or any(not (row[k] or "").strip() for k in fields):
                raise ValueError("发布数据缺字段或属于其他成片")
            n, d = int(row["numerator"]), int(row["denominator"])
            if min(n, d) < 0:
                raise ValueError("指标计数必须非负")
            kind = row.get("kind") or "proportion"
            if kind not in {"proportion", "per_view"} or (kind == "proportion" and n > d):
                raise ValueError("占比的分子不可超过分母；每观看次数请显式填 kind=per_view")
            result.append({"kind": kind} | {k: row[k] for k in ("variant", "traffic", "window", "metric")} |
                          {"numerator": n, "denominator": d, "rate": n / d if d else None})
    return result


def pending_review():
    return {"schema_version": MEDIA_SCHEMA, "status": PENDING, "checks": dict.fromkeys(CHECKS, "待核"),
            "priorities": [], "covers": [], "cover_status": "发布封面待评", "blockers": []}


def evaluate(notes_path: Path, video: Path, issues=(), target: int = 85) -> dict:
    notes = ReviewNotes.model_validate_json(notes_path.read_text(encoding="utf-8"))
    criteria = notes.criteria
    if (notes.schema_version == "editorial-0.5") != (criteria is not None):
        raise ValueError("新版综合审片须完整填写 criteria；历史审片沿用其原版本")
    if criteria and notes.content and (HOOK_DIM not in notes.content.marks or notes.content.marks[HOOK_DIM].score != criteria.hook_total):
        raise ValueError("前三秒十维表得分与四项证据合计不一致")
    if notes.source_sha256 != digest(video):
        raise ValueError("审片证据与当前视频指纹不一致，请对本次导出重评")
    if set(notes.checks) != set(CHECKS) or notes.bottleneck not in (*CHECKS, "待核"):
        raise ValueError("须填写八个观看环节，并选出其中一个瓶颈或标待核")
    if set(notes.experiment) != set(("变量", "对照", "挑战", "主指标", "护栏", "停止条件")):
        raise ValueError("实验需填写变量、对照、挑战、主指标、护栏和停止条件，未知可标待核")
    entries = []
    for cover in notes.covers:
        source = (notes_path.parent / cover.image).resolve()
        if not source.is_file():
            raise ValueError("找不到封面素材：" + cover.image)
        from .image_io import read_image
        import cv2
        import numpy as np
        if read_image(source, cv2, np) is None:
            raise ValueError("封面须为可解码图像：" + cover.image)
        dimensions = {key for keys in AXES.values() for key in keys}
        if set(cover.marks) != dimensions:
            raise ValueError("封面评分须包含十个有证据的分项")
        axes = {axis: sum(cover.marks[k].score for k in keys) for axis, keys in AXES.items()}
        failed = cover.integrity.status == "须修" or any(cover.marks[k].score == 0 for k in ("真实证据", "正文兑现"))
        gate = "须修" if failed else cover.integrity.status
        entries.append(dict(gate=gate, integrity=cover.integrity.evidence, name=cover.name, role=cover.role, image=str(source), axes=axes, total=sum(axes.values()),
                            marks={k: v.model_dump() for k, v in cover.marks.items()}, correction=cover.correction))
    cover_origin = criteria.covers(entries, target) if criteria else ""
    actual = [item for item in entries if item["role"] == "发布封面"]
    if len(actual) > 1:
        raise ValueError("每份报告对应一个发布入口的当前封面")
    cover_status = "发布封面待评" if not actual else ("封面达到目标" if actual[0]["total"] >= target else "封面低于目标")
    if actual and actual[0]["gate"] != "已核":
        cover_status = "封面发布前须改" if actual[0]["gate"] == "须修" else "发布封面待核"
    if criteria:
        cover_status = cover_origin + " ｜ " + (cover_status if actual else "平台实显待核")
    levels = ("发布前须改", "影响目标", "精修")
    costs = ("现有素材剪辑", "新增包装或配音", "补拍")
    confidence = ("实测", "编辑判断", "待验证")
    items = (list(criteria.findings()) if criteria else []) + [f.model_dump() for f in notes.findings]
    for stage, check in notes.checks.items():
        if check.status == "须修" and not any(f["stage"] == stage and f["level"] == levels[0] for f in items):
            raise ValueError(f"{stage} 判为须修，请补有时码与验收方式的发布前修改项")
    if actual and actual[0]["gate"] == "须修":
        cover = actual[0]
        items.append(dict(topic="修正发布封面的真实承诺", stage="入口承诺", level=levels[0],
            evidence=cover["integrity"] + " · " + cover["marks"]["正文兑现"]["evidence"], action=cover["correction"],
            acceptance="对照标题、首帧和正文重新核实封面承诺", confidence="编辑判断", cost="现有素材剪辑", technical_issue=""))
    linked = {f.technical_issue: f.level for f in notes.findings}
    for issue in issues:
        if linked.get(issue.problem) == levels[0] or (issue.severity != "critical" and (issue.problem in linked or issue.problem in notes.retain_alerts)):
            continue
        items.append(dict(topic=issue.problem, stage="后期技术", level=levels[0 if issue.severity == "critical" else 2],
                          evidence=f"{issue.timestamp_start if issue.timestamp_start is not None else '全片'} · {issue.module}",
                          action=issue.recommendation, acceptance="按相同预设和抽样参数复测，并回看对应画面或音轨",
                          confidence="实测", cost="现有素材剪辑", technical_issue=issue.problem))
    items.sort(key=lambda f: (levels.index(f["level"]), f["stage"] != notes.bottleneck,
                              confidence.index(f["confidence"]), costs.index(f["cost"])))
    unique = {}
    for item in items:
        unique.setdefault(item["topic"], item)
    blockers = [i["topic"] for i in unique.values() if i["level"] == levels[0]]
    unknowns = {"待核", "未知", "待定", "未提供"}
    uncertain = (any(x.status == "待核" or x.evidence in unknowns for x in notes.checks.values())
                 or any(v in unknowns for v in (notes.goal, notes.entry, notes.audience, notes.bottleneck)))
    content = notes.content.result(target) if notes.content else None
    cover_pending = notes.cover_required and (not actual or actual[0]["gate"] == "待核")
    status = "发布前须改" if blockers or (content and content["status"] == "低于目标") or (notes.cover_required and actual and actual[0]["total"] < target) else (
        PENDING if uncertain or cover_pending or (criteria and criteria.pending()) else "已完成传播审片")
    metrics = read_metrics(notes_path.parent / notes.metrics_csv, notes.source_sha256) if notes.metrics_csv else []
    return notes.model_dump(exclude={"findings", "covers", "content"}) | dict(content=content, status=status, cover_status=cover_status,
        checks={k: v.status + " · " + v.evidence for k,v in notes.checks.items()},
        covers=entries, priorities=list(unique.values())[:3], findings=list(unique.values()), blockers=blockers,
        metrics=metrics)


def render_editorial(review: dict, output_dir: Path | None = None) -> str:
    def e(value):
        return html.escape(str(value), quote=True)
    source_id = e(review.get("source_sha256", ""))
    lines = [f'<section class="panel" data-editorial="{e(review.get('schema_version', MEDIA_SCHEMA).removeprefix('editorial-'))}" data-source-sha256="{source_id}"><h2>传播与美学复核</h2>',
             f'<p><b>{e(review["status"])}</b> · {e(review["cover_status"])}</p>']
    if "goal" in review:
        lines.append(f'<p>{e(review["audience"])} · {e(review["entry"])} · 目标 {e(review["goal"])} · 瓶颈 {e(review["bottleneck"])}</p>')
    content = review.get("content")
    if content:
        lines.append(f'<details><summary>内容 {e(content["total"])}/100 · {e(content["status"])} · {e(content["version"])}</summary>')
        for key, mark in content["marks"].items():
            lines.append(f'<p>{e(key)} {e(mark["score"])}/{CREATIVE_WEIGHTS[key]} · {e(mark["evidence"])}</p>')
        if content["overall_cap"] is not None:
            lines.append(f'<p>总分封顶 {e(content["overall_cap"])} · {e(content["cap_reason"])}</p>')
        lines.append('</details>')
    else:
        lines.append('<p>十维内容分待评</p>')
    for item in review["priorities"]:
        lines.append(f'<article><h3>{e(item["level"])} · {e(item["topic"])}</h3><p>{e(item["confidence"])} · {e(item["evidence"])}</p><p>{e(item["cost"])} · {e(item["action"])}</p><p>验收　{e(item["acceptance"])}</p></article>')
    if review["blockers"]:
        lines.append('<p>全部发布前问题　' + e(' / '.join(review["blockers"])) + '</p>')
    if review.get("criteria"):
        from jinja2 import Environment, PackageLoader
        env = Environment(loader=PackageLoader("postscore", "views"), autoescape=True)
        lines.append(env.get_template("criteria.html").render(c=review["criteria"], review=review))
    for key, value in review["checks"].items():
        lines.append(f'<p><b>{e(key)}</b>　{e(value)}</p>')
    for note in review.get("keep", []):
        lines.append(f'<p>建议保留　{e(note)}</p>')
    for title, reason in review.get("retain_alerts", {}).items():
        lines.append(f'<p>技术告警复核　{e(title)} · {e(reason)}</p>')
    for cover in review["covers"]:
        lines.append(f'<h3>{e(cover["role"])} · {e(cover["name"])}</h3><p>传播 {cover["axes"]["传播"]}/50 · 美学 {cover["axes"]["美学"]}/50 · 合计 {cover["total"]}/100 · 审查 {e(cover["gate"])} {e(cover.get("decision", ""))}</p>')
        location = Path(cover["image"])
        if output_dir is not None:
            try:
                url = os.path.relpath(location, output_dir).replace(os.sep, "/")
            except ValueError:
                url = location.as_uri()
            lines.append(f'<img style="max-width:240px;width:100%;height:auto;object-fit:contain" src="{e(url)}" alt="{e(cover["name"])}">')
        lines.append(f'<p>{e(cover["correction"])}</p>')
        for key, mark in cover["marks"].items():
            lines.append(f'<p>{e(key)} {mark["score"]}/10 · {e(mark["evidence"])}</p>')
    if "experiment" in review:
        lines.append('<h3>对照试验</h3>')
        for key, value in review["experiment"].items():
            lines.append(f'<p>{e(key)}　{e(value)}</p>')
    for row in review.get("metrics", []):
        rate = "待核" if row["rate"] is None else (f'{row["rate"]:.1%}' if row["kind"] == "proportion" else f'{row["rate"]:.3g} 次/观看')
        lines.append(f'<p>发布数据　{e(row["variant"])} · {e(row["traffic"])} · {e(row["window"])} · {e(row["metric"])} {row["numerator"]}/{row["denominator"]}（{rate}）</p>')
    return ''.join(lines) + '</section>'


def calibration(manifest: Path) -> list[dict]:
    """Audit two independent labels against already generated ranked reports."""
    cases = []
    seen = set()
    with manifest.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        keys = {"case", "type", "report", "first_a", "first_b", "score_a", "score_b"}
        if not keys.issubset(reader.fieldnames or []):
            raise ValueError("校准清单缺少样本、类型、报告、两位评审的首项或分数")
        for row in reader:
            if not all((row[k] or "").strip() for k in keys) or row["case"] in seen:
                raise ValueError("校准样本缺字段或编号重复")
            seen.add(row["case"])
            record = json.loads((manifest.parent / row["report"]).read_text(encoding="utf-8"))
            review = record["editorial"]
            if not review or not review.get("source_sha256"):
                raise ValueError("校准需要已结合真实审片文件的报告")
            scores = [Decimal(row[k]) for k in ("score_a","score_b")]
            if not all(s.is_finite() and 0 <= s <= 100 for s in scores):
                raise ValueError("校准分数须在 0 到 100 之间")
            top = [item["topic"] for item in review["priorities"]]
            agreement = row["first_a"] == row["first_b"]
            cases.append(dict(case=row["case"], type=row["type"], agreement=agreement, editor_gap=str(abs(scores[0]-scores[1])),
                              consensus_in_top3=(row["first_a"] in top if agreement else None), first_a=row["first_a"],
                              first_b=row["first_b"], top3=top))
    return cases
