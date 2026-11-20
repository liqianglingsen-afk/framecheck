"""Versioned cut plans and evidence-backed paired reviews."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from typing import Annotated, Literal

import cv2
import numpy as np
from jinja2 import Environment, PackageLoader
from pydantic import Field, model_validator

from .assessment import CurrentCriteria
from .editorial import CREATIVE_WEIGHTS, Check, Creative, Record, Text, digest
from .models import ReviewReport
from .probe import probe_video
from .revision_safety import Placement, Seconds, placement_review, save_image


Score = Annotated[Decimal, Field(ge=0, le=100, max_digits=8, decimal_places=4)]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
PACKAGING = ("行动收益", "手机易读性", "画面美感")


class Span(Record):
    start: Seconds
    end: Seconds

    @model_validator(mode="after")
    def validate_span(self):
        if self.end <= self.start:
            raise ValueError("出点必须晚于入点")
        return self


class Forecast(Record):
    low: Score
    expected: Score
    high: Score
    basis: Text
    confidence: Literal["低", "中", "高"]


class Edit(Record):
    source: Span
    action: Literal["保留", "微调", "替换", "删除"]
    destinations: list[Span]
    picture: Text
    sound: Text
    graphics: Text
    screen: str = ""
    reason: Text
    acceptance: Text


class InputFile(Record):
    path: Text
    role: Literal["视频", "配音", "音乐", "字幕", "版位参考", "其他"]
    sha256: Hash


class InputUse(Record):
    asset: Text
    source: Span | None = None
    output: Span


class Asset(Record):
    name: Text
    kind: Literal["动态运镜", "原字幕", "品牌声音", "表演动作", "音乐落点", "其他"]
    source: Span
    value: Text
    handling: Text


class PlacementPlan(Record):
    platform: Text
    placement: Text
    ui_state: Text
    reference: Text
    layout: Text
    acceptance: Text
    elements: dict[Text,list[Span]] = Field(default_factory=dict)


class Pickup(Record):
    searched: Text
    attempted: Text
    gap: Text
    minimum: Text
    destination: Span
    acceptance: Text


class Plan(Record):
    schema_version: Literal["cut-plan-0.4","cut-plan-0.6"]
    route: Literal["现有素材剪辑","保留原版","最小增补"] = "现有素材剪辑"
    pickups: list[Pickup] = Field(default_factory=list)
    inputs: dict[Text,InputFile] = Field(default_factory=dict)
    uses: list[InputUse] = Field(default_factory=list)
    decisions: dict[Text,list[int]] = Field(default_factory=dict)
    source_sha256: Hash
    goal: Text
    target: Annotated[int, Field(strict=True, ge=85, le=100)]
    forecast: dict[str, Forecast]
    timeline: Annotated[list[Edit], Field(min_length=1)]
    protect: list[Asset]
    no_assets_reason: str = ""
    packaging_plan: dict[str, Text] = Field(default_factory=dict)
    placement_plan: list[PlacementPlan] = Field(default_factory=list)
    strategy: Text
    forecast_context: Literal["剪前预测", "历史回放"]
    next_if_short: Text


class AssetReview(Record):
    status: Literal["保留", "替换已核", "丢失", "待核"]
    output: Span | None
    evidence: Text
    tradeoff: Text


class Receipt(Record):
    schema_version: Literal["render-0.4","render-0.6"]
    inputs: dict[Text,Hash] = Field(default_factory=dict)
    source_sha256: Hash
    revised_sha256: Hash
    plan_sha256: Hash
    started_at: datetime
    completed_at: datetime
    command: Annotated[list[Text], Field(min_length=1)]
    seal: Hash


class Dispute(Record):
    time: Text
    issue: Text
    evidence: Text
    decision: Literal["须修", "待核", "已裁决"]


class Audit(Record):
    schema_version: Literal["cut-audit-0.4","cut-audit-0.6"]
    plan_sha256: Hash
    revised_sha256: Hash
    protected: dict[str, AssetReview]
    packaging: dict[str, Check]
    placements: list[Placement]
    pending_placements: list[Text]
    reviewer: Text
    review_mode: Literal["自评", "独立盲审"]
    disputes: list[Dispute] = Field(default_factory=list)
    blind_sheet: str = ""
    render_receipt: str = ""
    timeline_check: Check
    variance: Text
    next_edit: Text


def substantive(value):
    return value.strip().casefold() not in {
        "",
        "待核",
        "待填",
        "未知",
        "待定",
        "未提供",
        "todo",
        "tbd",
        "n/a",
        "...",
    }


def requires_change(plan):
    return any(u for u in plan.get("uses",[]) if plan["inputs"][u["asset"]]["role"] != "版位参考") or any(s["action"] != "保留" or s["destinations"] != [s["source"]] for s in plan["timeline"])


def write_json(path, data):
    with path.open("x", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def fingerprint(data):
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def report_summary(report_path, video_hash):
    report = ReviewReport.model_validate(load_json(report_path))
    ed = report.editorial or {}
    if ed.get("source_sha256") != video_hash or not ed.get("content"):
        raise ValueError("需要匹配该成片指纹、含十维内容分的真实报告")
    if report.optimization and report.optimization.status in {"mock", "unverified"}:
        raise ValueError("技术检测缺实片证据")
    content = ed["content"]
    if content.get("total") is None:
        raise ValueError("剪前预测需要完整内容基线，请先补评缺项")
    parsed = Creative.model_validate({k: v for k, v in content.items() if k in Creative.model_fields})
    result = parsed.result(content["target"])
    if any(Decimal(result[k]) != Decimal(str(content[k])) for k in ("raw", "total")):
        raise ValueError("存档内容合计与十维得分不一致")
    criteria = ed.get("criteria")
    if ed.get("schema_version") in {"editorial-0.5","editorial-0.6"}:
        from .creative_evidence import Criteria, HOOK_DIM
        current = (CurrentCriteria if ed["schema_version"] == "editorial-0.6" else Criteria).model_validate(criteria)
        if current.hook_total != parsed.marks[HOOK_DIM].score:
            raise ValueError("存档钩子与四项不一致")
        if set(f["topic"] for f in current.findings()) - set(ed.get("blockers", [])):
            raise ValueError("存档报告缺少发布前错误")
    return dict(
        criteria=criteria,
        report_sha256=digest(report_path),
        content=result,
        scope=dict(brief=ed.get("brief"), audience=ed.get("audience"), entry=ed.get("entry"),goal=ed.get("goal")),
        editorial_schema=ed.get("schema_version"),
        priorities=ed.get("priorities",[]),
        technical_scope=report.technical and dict(scope=report.technical["scope"],excluded=report.technical["excluded"],export_context=report.technical.get("export_context")),
        technical=report.technical["score"] if report.technical else report.overall_score,
        modules=report.module_scores,
        module_names=report.module_names,
        preset=report.preset,
        mode=report.mode,
        sampling=report.sampling,
        status=ed["status"],
        blockers=ed.get("blockers", []),
        cover_status=ed.get("cover_status", "待评"),
        covers=[{k: c.get(k) for k in ("role", "name", "total", "gate", "axes")} for c in ed.get("covers", [])],
        metrics=ed.get("metrics", []),
        goal=ed.get("goal", "待核"),
        filename=report.video_info.filename,
    )


def full_cover(spans, end, tolerance, *, allow_overlap):
    cursor = 0.0
    for span in sorted(spans, key=lambda s: s.start):
        if span.start > cursor + tolerance or (not allow_overlap and span.start < cursor - tolerance):
            raise ValueError(f"时间线在 {cursor:g} 秒附近有缺口或未拆开的重叠")
        if span.end > end + tolerance:
            raise ValueError("时间线越过成片时长")
        cursor = max(cursor, span.end)
    if abs(end - cursor) > tolerance:
        raise ValueError("时间线没有覆盖到片尾")


def verify_inputs(inputs):
    for key, entry in inputs.items():
        if digest(Path(entry["path"])) != entry["sha256"]:
            raise ValueError("素材已变化，须重新确认方案并导出：" + key)
    return {key:entry["sha256"] for key,entry in inputs.items()}


def seal_plan(draft, source, baseline):
    p = Plan.model_validate(load_json(draft))
    sha = digest(source)
    if sha != p.source_sha256:
        raise ValueError("剪辑单与原片指纹不匹配")
    info = probe_video(source, source=str(source))
    before = report_summary(baseline, sha)
    modern = before["editorial_schema"] == "editorial-0.6"
    if modern != (p.schema_version == "cut-plan-0.6"):
        raise ValueError("剪辑底稿与原片量表版本不一致")
    if modern:
        for item in p.inputs.values():
            item.path = str((draft.parent / item.path).resolve())
        verify_inputs({k:v.model_dump() for k,v in p.inputs.items()})
        if p.forecast_context == "剪前预测":
            ids = {item["id"] for item in before["priorities"]}
            if ids != set(p.decisions) or any(not rows or any(i < 0 or i >= len(p.timeline) for i in rows) for rows in p.decisions.values()):
                raise ValueError("首页首选须逐项关联全片时间线行（从 0 起）")
            for item in before["priorities"]:
                action = item.get("selected_edit")
                if action and action not in {p.timeline[i].action for i in p.decisions[item["id"]]}:
                    raise ValueError("首页选定的操作与执行单矛盾：" + item["topic"])
        if set(p.inputs) != {u.asset for u in p.uses}:
            raise ValueError("外部素材与时间线引用不完整")
    if before.get("criteria") and p.forecast_context == "剪前预测":
        names = {asset.name for asset in p.protect}
        missing = {asset["name"] for asset in before["criteria"]["assets"]} - names
        if missing or any(not substantive(row.screen) for row in p.timeline):
            raise ValueError("剪前须承接逐项保留资产并注明各段屏显处理：" + "、".join(sorted(missing)))
    if p.goal != before["goal"]:
        raise ValueError("方案目标不同于原片审片目标，请按新目标重评原片")
    tolerance = 0.51 / max(info.fps, 1)
    full_cover([s.source for s in p.timeline], info.duration_seconds, tolerance, allow_overlap=False)
    for u in p.uses:
        if p.inputs[u.asset].role == "视频":
            if u.source is None or u.source.end > probe_video(Path(p.inputs[u.asset].path)).duration_seconds + tolerance:
                raise ValueError("外部视频引用缺源时段或越界：" + u.asset)
    outputs = [dst for shot in p.timeline for dst in shot.destinations]
    if not outputs or any((s.action == "删除") != (not s.destinations) for s in p.timeline):
        raise ValueError("删除段去向应为空，其余片段须填写成片位置")
    if any(
        not substantive(x)
        for row in p.timeline
        for x in (row.picture, row.sound, row.graphics, row.reason, row.acceptance)
    ):
        raise ValueError("每段须有具体声画、包装、理由和验收")
    if not substantive(p.strategy) or not substantive(p.next_if_short):
        raise ValueError("须写明全片路线和残余差距的处理")
    expected_duration = max(s.end for s in outputs)
    full_cover(outputs, expected_duration, tolerance, allow_overlap=True)
    if modern and before["scope"]["brief"]["target_duration"] == "保持原时长" and abs(expected_duration-info.duration_seconds)>tolerance:
        raise ValueError("方案时长偏离已约定原时长")
    if any(u.output.end > expected_duration+tolerance for u in p.uses):
        raise ValueError("外部素材的成片时段越界")
    for placement in p.placement_plan:
        if any(not spans or any(s.end>expected_duration+tolerance for s in spans) for spans in placement.elements.values()):
            raise ValueError("版位必需元素的显示时间无效")
    if (not p.protect and not p.no_assets_reason.strip()) or len({s.name for s in p.protect}) != len(p.protect):
        raise ValueError("须登记具体保留资产，或给出没有可保留项的原因")
    if any(s.source.end > info.duration_seconds + tolerance for s in p.protect):
        raise ValueError("保留资产时码越界")
    if p.forecast_context == "剪前预测" and set(p.forecast) != set(CREATIVE_WEIGHTS):
        raise ValueError("缺少十维剪前预测")
    if p.forecast_context == "剪前预测":
        if set(p.packaging_plan) != set(PACKAGING) or not all(map(substantive, p.packaging_plan.values())):
            raise ValueError("须在剪前写明行动收益、手机阅读和画面美感的具体设计")
        if not p.placement_plan or any(
            not substantive(value) for row in p.placement_plan for value in row.model_dump(exclude={"elements"}).values()
        ):
            raise ValueError("须在剪前列明版位、遮挡状态、参考来源、避让设计和验收")
    if p.forecast_context == "历史回放" and p.forecast:
        raise ValueError("历史回放缺剪前快照时不能追填预测")
    for k, row in p.forecast.items():
        if not substantive(row.basis):
            raise ValueError("预计分缺具体依据：" + k)
        if not row.low <= row.expected <= row.high <= CREATIVE_WEIGHTS[k]:
            raise ValueError("预计得分顺序或单项上限有误：" + k)
    totals = (
        {key: str(sum(getattr(v, key) for v in p.forecast.values())) for key in ("low", "expected", "high")}
        if p.forecast
        else {}
    )
    if modern and p.forecast_context == "剪前预测":
        if (p.route == "最小增补" or Decimal(totals["expected"]) < p.target) and not p.pickups:
            raise ValueError("现有素材预计不足或需增补时，须列已查素材、已试剪法、缺口及最小补充")
        if any(x.destination.end > expected_duration+tolerance for x in p.pickups):
            raise ValueError("增补镜头的成片位置越界")
        if p.route == "保留原版" and requires_change(p.model_dump(mode="json")):
            raise ValueError("保留原版的首选与执行单操作不一致")
    record = dict(
        schema_version="revision-0.6" if modern else "revision-0.4",
        kind="plan",
        created_at=datetime.now(timezone.utc).isoformat(),
        plan=p.model_dump(mode="json"),
        baseline=before,
        duration=info.duration_seconds,
        planned_duration=expected_duration,
        totals=totals,
        source_file=source.name,
    )
    record["seal"] = fingerprint(record)
    return record


def read_plan(path):
    record = load_json(path)
    content = dict(record)
    seal = content.pop("seal", None)
    if (
        record.get("kind") != "plan"
        or record.get("schema_version") not in {"revision-0.4","revision-0.6"}
        or fingerprint(content) != seal
    ):
        raise ValueError("剪前快照校验失败，请使用 revision-plan 的原始 plan.json")
    return record


def packet(out, data):
    kind = data["kind"]
    write_json(out / (kind + ".json"), data)
    (out / (kind + ".html")).write_text(render_packet(data), encoding="utf-8")


def render_packet(data):
    env = Environment(loader=PackageLoader("postscore", "views"), autoescape=True)
    env.globals["delta"] = lambda a, b: format(Decimal(str(a)) - Decimal(str(b)), "+f")
    return env.get_template("revision.html").render(
        d=data, weights=CREATIVE_WEIGHTS, record_hash=fingerprint(data)
    )


def publish(output, build):
    if output.exists():
        raise ValueError("请使用新的输出目录，原交付应保留")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temp:
        result = Path(temp) / "packet"
        result.mkdir()
        data = build(result)
        packet(result, data)
        result.rename(output)


def timestamps(video):
    raw = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "csv=p=0",
            str(video),
        ],
        text=True,
    )
    vals = [
        float(line.split(",")[0])
        for line in raw.splitlines()
        if line.split(",")[0].strip().replace(".", "", 1).lstrip("-").isdigit()
    ]
    if not vals:
        raise ValueError("无法取得成片逐帧时码")
    arr = np.asarray(vals)
    return arr - arr[0]


def sample_span(cap, span, out, name, pts):
    indices = np.flatnonzero((pts >= span.start - 0.000001) & (pts < span.end - 0.0000001))
    if len(indices) == 0:
        indices = [max(0, np.searchsorted(pts, span.start, side="right") - 1)]
    images = []
    for frac in (0.12, 0.5, 0.88):
        index = indices[round((len(indices) - 1) * frac)]
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(index))
        ok, frame = cap.read()
        if not ok:
            raise ValueError(f"无法解码证据帧 {index}")
        h, w = frame.shape[:2]
        images.append(cv2.resize(frame, (240, max(1, round(240 * h / w))), interpolation=cv2.INTER_AREA))
    motion = max(float(cv2.absdiff(a, b).mean()) for a, b in zip(images, images[1:]))
    save_image(out / name, np.concatenate(images, axis=1))
    return motion


def compare(plan_path, source, revised, report_path, audit_path, out):
    snap = read_plan(plan_path)
    plan = Plan.model_validate(snap["plan"])
    audit = Audit.model_validate(load_json(audit_path))
    if (
        digest(source) != plan.source_sha256
        or digest(revised) != audit.revised_sha256
        or digest(plan_path) != audit.plan_sha256
    ):
        raise ValueError("原片、改片或剪前快照与复评记录不匹配")
    if plan.source_sha256 == audit.revised_sha256 and requires_change(snap["plan"]):
        raise ValueError("方案要求修改，但输入与导出为同一文件内容")
    for check in [*audit.packaging.values(), audit.timeline_check]:
        if check.status != "待核" and not substantive(check.evidence):
            raise ValueError("已核或须修需提供实际证据")
    for check in audit.protected.values():
        if check.status != "待核" and (not substantive(check.evidence) or not substantive(check.tradeoff)):
            raise ValueError("资产复核缺少证据或取舍说明")
    before = snap["baseline"]
    after = report_summary(report_path, audit.revised_sha256)
    if before.get("criteria") and not after.get("criteria"):
        raise ValueError("新版基线须用同版审片依据复评")
    modern = plan.schema_version == "cut-plan-0.6"
    if modern != (audit.schema_version == "cut-audit-0.6"):
        raise ValueError("验收底稿版本与快照不一致")
    def comparison_scope(side):
        scope = dict(side.get("scope") or {})
        if scope.get("brief"):
            scope["brief"] = {k:v for k,v in scope["brief"].items() if k != "commission"}
        return scope
    same_content = comparison_scope(before) == comparison_scope(after) and before["content"]["version"] == after["content"]["version"]
    if not modern and after["goal"] != plan.goal:
        raise ValueError("两次评分的业务目标不一致")
    if set(audit.packaging) != set(PACKAGING) or set(audit.protected) != {x.name for x in plan.protect}:
        raise ValueError("包装三项和所有保留资产必须逐一复核")
    if any(not substantive(t) for t in audit.pending_placements):
        raise ValueError("须写明缺哪种版位证据")
    if not audit.placements and not audit.pending_placements:
        raise ValueError("缺少版位复核或待验原因")
    placements = [(s.platform, s.placement, s.ui_state) for s in audit.placements]
    if len(set(placements)) != len(placements):
        raise ValueError("同版位同状态重复")
    fixes = list(after["blockers"])
    pending = list(audit.pending_placements)
    for target in plan.placement_plan:
        key = (target.platform, target.placement, target.ui_state)
        if key not in placements:
            pending.append("剪前指定版位尚缺对应校样 · " + " / ".join(key))
    if modern and not same_content:
        pending.append("受众、入口、简报或量表不一致；按同一口径重评后比较")
    input_hashes = verify_inputs({k:v.model_dump() for k,v in plan.inputs.items()})
    receipt = None
    if audit.render_receipt:
        receipt = load_json(audit_path.parent / audit.render_receipt)
        parsed = Receipt.model_validate(receipt)
        if parsed.inputs != input_hashes or modern != (parsed.schema_version == "render-0.6"):
            raise ValueError("导出凭据素材清单或版本不符")
        if (
            fingerprint({k: v for k, v in receipt.items() if k != "seal"}) != parsed.seal
            or not all(k in parsed.command for k in ("{source}", "{output}"))
            or parsed.started_at.tzinfo is None
            or parsed.completed_at.tzinfo is None
            or not datetime.fromisoformat(snap["created_at"])
            <= parsed.started_at
            <= parsed.completed_at
            <= datetime.now(timezone.utc)
        ):
            raise ValueError("导出凭据不完整或时间顺序错误")
        if (
            receipt["plan_sha256"] != audit.plan_sha256
            or receipt["source_sha256"] != plan.source_sha256
            or receipt["revised_sha256"] != audit.revised_sha256
        ):
            raise ValueError("导出凭据与实际文件不匹配")
    prediction_verified = bool(receipt and snap["totals"] and same_content)
    if snap["totals"] and not prediction_verified:
        pending.append("缺绑定剪前快照的导出凭据，预测与实得差暂不作验证")
    if audit.timeline_check.status == "须修":
        fixes.append("实际时间线 · " + audit.timeline_check.evidence)
    elif audit.timeline_check.status == "待核":
        pending.append("实际时间线待逐段核对")
    actual = Decimal(after["content"]["total"])
    if after["technical"] is None:
        pending.append("按简报技术分待核")
    if actual < plan.target or (after["technical"] is not None and after["technical"] < plan.target):
        fixes.append("内容或后期技术未达到约定目标")
    if same_content and actual < Decimal(before["content"]["total"]):
        fixes.append("改版内容低于原版，需复核取舍")
    if after["status"] == "发布前须改" and not fixes:
        fixes.append("成片单条审片存在尚未通过的条件")
    if after["status"] == "传播待核":
        pending.append("传播或行动承接仍有待核项")
    comparable = (
        before["preset"] == after["preset"]
        and before.get("technical_scope") == after.get("technical_scope")
        and before["mode"] == after["mode"]
        and before["sampling"] is not None
        and before["sampling"] == after["sampling"]
    )
    if not comparable:
        pending.append("技术预设、工具版本或抽样参数未确认一致，保留两次原值")
    for k, check in audit.packaging.items():
        if check.status == "须修":
            fixes.append(k + " · " + check.evidence)
        elif check.status == "待核":
            pending.append(k + " · " + check.evidence)
    blind = None
    if audit.review_mode == "独立盲审":
        blind = load_json(audit_path.parent / audit.blind_sheet)
        if (
            blind.get("source_sha256") != audit.revised_sha256
            or blind.get("goal") != plan.goal
            or blind.get("reviewer") != audit.reviewer
        ):
            raise ValueError("独立评分表的成片、目标或评审者不符")
        rating = Creative.model_validate(blind["content"]).result(plan.target)
        blind_version = blind.get("rubric_version", "历史十维盲审")
        expected_version = after.get("editorial_schema","editorial-0.5")
        if modern and (blind_version != expected_version or rating["version"] != after["content"]["version"] or blind.get("scope") != after.get("scope")):
            raise ValueError("盲审须使用匹配的版本、简报和量表")
        if after.get("criteria") and blind_version == expected_version:
            from .creative_evidence import HOOK_DIM, Mark, hook_score
            from .assessment import HookMark
            model = HookMark if modern else Mark
            scored = {k:model.model_validate(v) for k,v in blind["hook"].items()}
            if modern:
                limit = min(3,probe_video(revised).duration_seconds)
                if any(m.time is not None and m.time >= limit for m in scored.values()) or (
                    sum(m.score for m in scored.values()) > 5 and any(m.score and m.time is None for m in scored.values())):
                    raise ValueError("盲审钩子证据超出实际开场或缺少时码")
            if hook_score(scored, blind["payoff"]) != Decimal(rating["marks"][HOOK_DIM]["score"]):
                raise ValueError("盲审钩子与独立四项不一致")
        if after.get("criteria") and blind_version != expected_version:
            pending.append("历史盲审缺新版四项钩子，仅列原值")
        blind_findings = [Dispute.model_validate(row) for row in blind.get("observations", [])]
        for row in blind_findings:
            decision = next((d for d in audit.disputes if (d.time,d.issue)==(row.time,row.issue)), None)
            if modern and decision and decision.decision == "已裁决" and substantive(decision.evidence):
                continue
            if row.decision == "须修":
                fixes.append("盲审须改 · " + row.time + " · " + row.issue + " · " + row.evidence)
            elif row.decision == "待核":
                pending.append("盲审待核 · " + row.time + " · " + row.issue)
        blind = dict(reviewer=audit.reviewer, result=rating, version=blind_version, observations=[r.model_dump() for r in blind_findings])
        if (Decimal(rating["total"]) >= plan.target) != (actual >= plan.target):
            relevant = {(d.issue,d.time) for d in audit.disputes if d.decision != "待核"}
            required = {(d.issue,d.time) for d in blind_findings if d.decision != "已裁决"}
            if modern:
                required |= {(k,"评分分歧") for k,m in rating["marks"].items() if Decimal(m["score"]) != Decimal(after["content"]["marks"][k]["score"])}
            if (modern and (not required or not required <= relevant)) or not audit.disputes or any(d.decision == "待核" for d in audit.disputes):
                pending.append("独立评审与制作自评跨越目标线，须按具体镜头裁决分歧")
    elif audit.blind_sheet:
        raise ValueError("自评模式不能附作独立评分")
    for dispute in audit.disputes:
        if not all(substantive(x) for x in (dispute.time, dispute.issue, dispute.evidence)):
            raise ValueError("分歧裁决须有时码、问题及实片证据")
        if dispute.decision == "须修":
            fixes.append("裁决须改 · " + dispute.time + " · " + dispute.issue)
        elif dispute.decision == "待核":
            pending.append("分歧待核 · " + dispute.time + " · " + dispute.issue)
    info = probe_video(revised, source=str(revised))
    duration = info.duration_seconds
    if abs(duration - snap["planned_duration"]) > 0.51 / max(info.fps, 1):
        pending.append("实际成片时长偏离剪辑单，请核对变更")
    cap0, cap1 = cv2.VideoCapture(str(source)), cv2.VideoCapture(str(revised))
    assets = []
    try:
        pts0 = timestamps(source) if plan.protect else []
        pts = timestamps(revised) if plan.protect or audit.placements else []
        for i, item in enumerate(plan.protect):
            check = audit.protected[item.name]
            if check.status in ("保留", "替换已核") and not check.output:
                raise ValueError("声称保留或替换时需要成片时码")
            if check.output and check.output.end > duration + 0.51 / max(info.fps, 1):
                raise ValueError("保留资产的成片时码越界")
            left = f"asset-{i}-before.jpg"
            old_motion = sample_span(cap0, item.source, out, left, pts0)
            right = None
            motion_note = ""
            if check.output:
                right = f"asset-{i}-after.jpg"
                new_motion = sample_span(cap1, check.output, out, right, pts)
                if item.kind == "动态运镜" and old_motion > 2 and new_motion < 0.75:
                    motion_note = "三帧差异提示改版近似定格，请回放确认"
                    if check.status == "保留":
                        pending.append(item.name + " · " + motion_note)
            if check.status == "丢失":
                fixes.append("保留资产丢失 · " + item.name)
            elif check.status == "待核":
                pending.append("资产待核 · " + item.name)
            assets.append(
                dict(
                    name=item.name,
                    kind=item.kind,
                    source=item.source.model_dump(),
                    value=item.value,
                    **check.model_dump(),
                    before_image=left,
                    after_image=right,
                    motion_note=motion_note,
                )
            )
        required_elements = {(p.platform,p.placement,p.ui_state):p.elements for p in plan.placement_plan}
        safety = [
            placement_review(p, audit_path.parent, cap1, pts, duration, out, i, required_elements.get((p.platform,p.placement,p.ui_state),{}) if modern else None)
            for i, p in enumerate(audit.placements)
        ]
    finally:
        cap0.release()
        cap1.release()
    for placement in safety:
        label = " / ".join(placement[k] for k in ("platform", "placement", "ui_state"))
        if placement["status"] == "须修":
            fixes.append("关键元素碰撞 · " + label)
        if placement["status"] == "待核" or not placement["coverage_checked"]:
            pending.append("版位覆盖待核 · " + label)
    return dict(
        schema_version=snap["schema_version"],
        content_comparable=same_content,
        kind="comparison",
        plan=snap["plan"],
        seal=snap["seal"],
        plan_sha256=audit.plan_sha256,
        baseline=before,
        after=after,
        source_file=source.name,
        revised_file=revised.name,
        revised_sha256=audit.revised_sha256,
        totals=snap["totals"],
        assets=assets,
        placements=safety,
        blind=blind,
        disputes=[d.model_dump() for d in audit.disputes],
        packaging={k: v.model_dump() for k, v in audit.packaging.items()},
        review_mode=audit.review_mode,
        reviewer=audit.reviewer,
        technical_comparable=comparable,
        timeline_check=audit.timeline_check.model_dump(),
        prediction_verified=prediction_verified,
        render_receipt=receipt,
        variance=audit.variance,
        next_edit=audit.next_edit,
        fixes=fixes,
        pending=pending,
        status="发布前须改" if fixes else ("待核" if pending else "已通过本轮复评"),
    )
