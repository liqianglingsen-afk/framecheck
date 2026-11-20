"""Exercise 0.6 through the CLI with generated, noncommercial two-second media."""

import csv
import json
import subprocess

import cv2
import numpy as np
import pytest

from postscore.cli import main
from postscore.creative_evidence import HOOK, HOOK_DIM
from postscore.editorial import AXES, CREATIVE_WEIGHTS, digest


def call(*args):
    return main(list(map(str, args)))


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def read(path):
    return json.loads(path.read_text())


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", *map(str, args)], check=True)


@pytest.fixture
def source(tmp_path):
    video = tmp_path / "motion.mp4"
    ff("-f", "lavfi", "-i", "testsrc2=s=180x240:r=10:d=2", "-c:v", "libx264", video)
    return video


def notes_for(source, path):
    assert call("brief", source, "--output", path) == 0
    n = read(path)
    n.update(
        goal="理解运动方向",
        audience="播放器设计师",
        entry="演示屏自动播放",
        bottleneck="前3秒",
    )
    n["brief"].update(
        entry_type="自动播放",
        audio_intent="设计无声",
        purpose="辨认运动",
        constraints="保持时长",
        placements=["本地演示屏"],
    )
    n["criteria"].update(
        primary_task="理解运动",
        secondary_angle="色彩",
        reveal_order="形状进入并移动",
        cover_source={
            "independent": "无独立封面",
            "displayed": "待核",
            "evidence": "交付清单仅有视频",
        },
        payoff="1.5 秒形状抵达画面右侧",
        identity={
            "sound_on": "清楚",
            "muted": "清楚",
            "evidence": "测试图案移动",
            "fix": "保留",
        },
        shots=[
            {
                "start": 0,
                "end": 2,
                "purpose": "显示运动",
                "evidence": "0–2 秒连续视频",
                "events": ["边缘变化"],
            }
        ],
        no_assets_reason="完整测试镜头",
        no_display_reason="无状态切换",
        verified_frames=True,
        ending_action="不适用",
    )
    for k, w in HOOK.items():
        n["criteria"]["hook"][k].update(
            score=w, time=0.1, evidence="0.1 秒出现可辨运动"
        )
    n["content"].update(
        marks={
            k: {"score": w, "evidence": "测试标注，连续动作可见"}
            for k, w in CREATIVE_WEIGHTS.items()
        },
        pending={},
    )
    n["checks"] = {
        k: {"status": "已核", "evidence": "依据目标核对本地连续演示"}
        for k in n["checks"]
    }
    return n


def review(source, n, root, expected=0):
    root.mkdir()
    rc = call(
        "review",
        source,
        "--editorial",
        save(root / "notes.json", n),
        "--html",
        "--json",
        "--preset",
        "short_social",
        "--output-dir",
        root / "out",
    )
    assert rc == expected
    if rc == 0:
        return next((root / "out").glob("*.json"))


def test_precision_partial_late_hook_and_missing_action(source, tmp_path):
    n = notes_for(source, tmp_path / "blank")
    for k, v in [("脚本结构与信息递进", 1), ("视觉画面与审美", 5.99)]:
        n["content"]["marks"][k]["score"] = v
    r = read(review(source, n, tmp_path / "below"))
    assert r["editorial"]["content"]["total"] == "84.99"
    assert r["editorial"]["content"]["status"] == "低于目标"
    n["content"]["marks"]["视觉画面与审美"]["score"] = 6
    r = read(review(source, n, tmp_path / "meets"))
    assert r["editorial"]["content"]["status"] == "达到目标"
    n["criteria"]["hook"]["受众相关"]["time"] = 7
    review(source, n, tmp_path / "late", 2)
    n["criteria"]["hook"]["受众相关"]["time"] = 0.2
    n["brief"]["action_required"] = True
    n["criteria"]["ending_action"] = "缺失"
    review(source, n, tmp_path / "cta", 2)
    key = "转化/关注/评论引导"
    n["content"]["marks"][key]["score"] = 2
    key = "证据链与可信度"
    del n["content"]["marks"][key]
    n["content"]["pending"][key] = "缺待核来源"
    r = read(review(source, n, tmp_path / "partial"))
    assert r["editorial"]["content"]["total"] is None


def test_sound_contract_batch_and_frame_scan(source, tmp_path):
    tone = tmp_path / "tone.mp4"
    ff(
        "-i",
        source,
        "-f",
        "lavfi",
        "-i",
        "sine=duration=2",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        tone,
    )
    out = tmp_path / "batch"
    assert (
        call(
            "batch",
            source,
            tone,
            "--preset",
            "short_social",
            "--audio-intent",
            "设计无声",
            "--output-dir",
            out,
        )
        == 0
    )
    rows = list(csv.DictReader(next(out.glob("*.csv")).open(encoding="utf-8-sig")))
    assert rows[0]["technical_score"] == rows[1]["technical_score"]
    assert (
        rows[0]["score"] != rows[1]["score"]
        and rows[1]["editorial_status"] == "发布前须改"
    )
    assert not rows[0]["content_score"] and all(
        row["status"] == "success" for row in rows
    )
    out = tmp_path / "voice"
    assert call("review", source, "--audio-intent", "必需", "--output-dir", out) == 0
    assert read(next(out.glob("*.json")))["technical"]["blockers"]
    flash = tmp_path / "flash.mp4"
    ff(
        "-f",
        "lavfi",
        "-i",
        "color=black:s=180x240:r=10:d=2",
        "-vf",
        "drawbox=color=white:t=fill:enable='eq(n,7)'",
        "-c:v",
        "libx264",
        flash,
    )
    out = tmp_path / "scan"
    assert call("review", flash, "--full-frame-scan", "--output-dir", out) == 0
    scan = read(next(out.glob("*.json")))["frame_coverage"]
    assert scan["decoded"] == 20 and scan["candidates"] == [{"frame": 7, "time": 0.7}]


def test_cover_floor_and_designs(source, tmp_path):
    n = notes_for(source, tmp_path / "blank")
    n["brief"]["entry_type"] = "列表"
    n["cover_required"] = True
    n["criteria"]["cover_source"]["displayed"] = "平台选帧"
    image = tmp_path / "cover.png"
    assert cv2.imwrite(str(image), np.full((100, 150, 3), 128, np.uint8))
    marks = {
        k: {"score": 10, "evidence": "测试示意"} for axis in AXES.values() for k in axis
    }
    marks["点击收益"]["score"] = 2
    n["covers"] = [
        {
            "role": "发布封面",
            "name": "实显",
            "image": str(image),
            "integrity": {"status": "已核", "evidence": "入口样张"},
            "marks": marks,
            "correction": "使用可见结果",
        }
    ]
    n["criteria"]["previews"] = {
        "实显": {
            "source": "样张",
            "size": "180px",
            "subject": "正确",
            "benefit": "可辨",
            "topic": "演示",
        }
    }
    designs = [
        {
            "motive": m,
            "headline": "运动轨迹",
            "source_frame": "0.2 秒",
            "crop": "竖幅",
            "focus": "轨迹",
            "placement": "左上",
            "rationale": "留白",
            "failure": "遮挡",
        }
        for m in ["看起点", "看终点"]
    ]
    n["criteria"]["cover_plans"] = designs
    review(source, n, tmp_path / "same", 2)
    designs[1]["source_frame"] = "1.5 秒"
    ed = read(review(source, n, tmp_path / "covers"))["editorial"]
    assert ed["covers"][0]["total"] == 92 and ed["covers"][0]["decision"] == "需优化"
    assert ed["status"] == "发布前须改"


def test_findings_keep_positions_and_check_state(source, tmp_path):
    n = notes_for(source, tmp_path / "blank")
    finding = {
        "topic": "提示迟到",
        "stage": "事实依据",
        "level": "影响目标",
        "track": "图形",
        "dimension": "字幕与包装",
        "evidence": "相邻帧",
        "action": "前移两帧",
        "acceptance": "文字与动作同步",
        "confidence": "编辑判断",
        "cost": "现有素材剪辑",
        "score_review": "检查信息可读性",
        "disposition": "保留动作，调整文字",
    }
    n["findings"] = [
        finding | {"interval": {"start": t, "end": t + 0.1}} for t in (0.3, 1.7)
    ]
    n["criteria"]["displays"] = [
        {
            "time": "1.2秒",
            "action": "结束",
            "expected": "静止",
            "observed": "继续移动",
            "reference": "演示简报",
            "timing_reference": "逐帧",
            "status": "符合",
            "timing": "已核",
            "fix": "复查结束动作",
            "expected_state": "静止",
            "observed_state": "移动",
            "precondition": "到达边缘",
            "sequence": {"start": 1, "end": 1.5},
        }
    ]
    ed = read(review(source, n, tmp_path / "obs"))["editorial"]
    ids = [i["id"] for i in ed["findings"] if i["topic"] == "提示迟到"]
    assert (
        len(set(ids)) == 2
        and ed["status"] == "发布前须改"
        and "状态观察与结论矛盾" in ed["blockers"]
    )


def test_two_second_opening(source, tmp_path):
    n = notes_for(source, tmp_path / "blank")
    n["criteria"]["hook"]["继续观看理由"]["score"] = 1
    n["criteria"]["hook"]["前三秒可信线索"]["score"] = 2
    n["content"]["marks"][HOOK_DIM]["score"] = 11
    n["criteria"]["openings"] = [
        {
            "motive": m,
            "next_shot": "回到起点",
            "beats": [
                {
                    "start": 0,
                    "end": 2,
                    "subject": "形状",
                    "picture": m,
                    "audio": "无",
                    "caption": "无",
                }
            ],
        }
        for m in ["方向反转", "预测运动终点"]
    ]
    result = read(review(source, n, tmp_path / "short"))
    assert len(result["editorial"]["criteria"]["shots"]) == 1
    n["criteria"]["openings"][0]["beats"][0]["end"] = 3
    review(source, n, tmp_path / "too_long", 2)


def test_plan_render_pair_and_blind_dispute(source, tmp_path):
    n = notes_for(source, tmp_path / "baseline-brief.json")
    baseline = review(source, n, tmp_path / "before")
    draft = tmp_path / "draft.json"
    assert call("revision-init", source, baseline, "--output", draft) == 0
    d = read(draft)
    d["timeline"][0].update(
        picture="保留两秒画面",
        sound="保留静音",
        graphics="原有图形",
        screen="无显示状态",
        reason="动作连续",
        acceptance="逐帧复核",
    )
    d.update(
        no_assets_reason="整段保留",
        strategy="保持原长及声音意图",
        next_if_short="在演示版位核对字幕",
        packaging_plan=dict.fromkeys(d["packaging_plan"], "按本地显示器检查视觉指向"),
    )
    d["forecast"] = {
        k: {
            "low": w - 1,
            "expected": w,
            "high": w,
            "basis": "保持本段已核动作",
            "confidence": "中",
        }
        for k, w in CREATIVE_WEIGHTS.items()
    }
    reference = tmp_path / "art.png"
    assert cv2.imwrite(str(reference), np.full((240, 180, 3), 100, np.uint8))
    d["inputs"] = {
        "版位": {
            "path": str(reference),
            "role": "版位参考",
            "sha256": digest(reference),
        }
    }
    d["uses"] = [{"asset": "版位", "output": {"start": 0, "end": 2}}]
    d["placement_plan"] = [
        {
            "platform": "本地",
            "placement": "调试预览",
            "ui_state": "展开",
            "reference": "参考图",
            "layout": "避开按钮",
            "acceptance": "全时段无碰撞",
            "elements": {
                "主图": [{"start": 0, "end": 2}],
                "文字": [{"start": 0.2, "end": 1}],
            },
        }
    ]
    d["decisions"] = {key: [0] for key in d["decisions"]}
    backup = json.loads(json.dumps(d))
    for mark in backup["forecast"].values():
        mark["expected"] = mark["low"] = 0
    assert (
        call(
            "revision-plan",
            source,
            baseline,
            save(draft, backup),
            "--output",
            tmp_path / "insufficient",
        )
        == 2
    )
    backup["pickups"] = [
        dict(
            searched="原片及素材库",
            attempted="调整揭示顺序",
            gap="缺少结尾状态",
            minimum="录一段结果镜头",
            destination=dict(start=1.5, end=2),
            acceptance="结果可辨",
        )
    ]
    assert (
        call(
            "revision-plan",
            source,
            baseline,
            save(draft, backup),
            "--output",
            tmp_path / "fallback",
        )
        == 0
    )
    pack = tmp_path / "plan"
    assert (
        call("revision-plan", source, baseline, save(draft, d), "--output", pack) == 0
    )
    plan = pack / "plan.json"
    assert read(plan)["totals"]["expected"] == "100"
    export = tmp_path / "render"
    assert (
        call(
            "revision-render",
            source,
            plan,
            "--output",
            export,
            "--exec",
            "ffmpeg",
            "-v",
            "error",
            "-i",
            "{source}",
            "-c",
            "copy",
            "{output}",
        )
        == 0
    )
    revised = export / "edited.mp4"
    a_path = tmp_path / "audit.json"
    assert call("revision-audit", plan, revised, "--output", a_path) == 0
    a = read(a_path)
    a.update(
        reviewer="独立测试",
        review_mode="独立盲审",
        blind_sheet="blind.json",
        render_receipt=str(export / "receipt.json"),
        packaging={
            k: {"status": "已核", "evidence": "逐层复核"} for k in a["packaging"]
        },
        placements=[
            {
                "platform": "本地",
                "placement": "调试预览",
                "ui_state": "展开",
                "source": "版位实证",
                "reference": str(reference),
                "reference_date": "2026-11-21",
                "coverage_checked": True,
                "zones": {"按钮": {"x": 0.8, "y": 0.8, "w": 0.1, "h": 0.1}},
                "tracks": [
                    {
                        "name": "主图",
                        "end": 2,
                        "keys": [{"time": 0, "x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}],
                    }
                ],
            }
        ],
        timeline_check={"status": "已核", "evidence": "原时长完整"},
        variance="末镜重看",
        next_edit="等待实际验收",
    )
    n["source_sha256"] = digest(revised)
    after = review(revised, n, tmp_path / "after")
    blind = tmp_path / "blind.json"

    def prepare_blind():
        b = read(blind)
        b.update(
            reviewer=a["reviewer"],
            hook=n["criteria"]["hook"],
            payoff=n["criteria"]["payoff"],
            content=json.loads(json.dumps(n["content"])),
        )
        b["content"]["marks"]["脚本结构与信息递进"]["score"] = 0
        b["content"]["marks"]["视觉画面与审美"]["score"] = 3
        save(blind, b)

    assert (
        call(
            "revision-blind",
            revised,
            "--goal",
            n["goal"],
            "--brief",
            tmp_path / "after" / "notes.json",
            "--output",
            blind,
        )
        == 0
    )
    prepare_blind()
    a["disputes"] = [
        {
            "time": "无关时刻",
            "issue": "无关问题",
            "evidence": "对照实片",
            "decision": "已裁决",
        }
    ]

    def pair(name, after_path=after, code=0):
        out = tmp_path / name
        assert (
            call(
                "revision-compare",
                plan,
                source,
                revised,
                after_path,
                save(a_path, a),
                "--output",
                out,
            )
            == code
        )
        return read(out / "comparison.json") if not code else None

    r = pair("pair")
    assert r["prediction_verified"] and r["content_comparable"]
    assert any("跨越目标线" in x for x in r["pending"])
    assert r["placements"][0]["status"] == "待核"
    a.update(review_mode="自评", blind_sheet="", disputes=[])
    n["audience"] = "另一用途的受众"
    changed = review(revised, n, tmp_path / "different")
    paired = pair("different-pair", changed)
    assert not paired["content_comparable"] and not paired["prediction_verified"]
    assert "口径不同" in (tmp_path / "different-pair" / "comparison.html").read_text()
    reference.write_bytes(b"changed reference")
    pair("stale-inputs", code=2)


def test_changed_evidence_reopens_scores_and_choices(source, tmp_path):
    n = notes_for(source, tmp_path / "blank")
    n["findings"] = [
        {
            "topic": "文字与动作错位",
            "stage": "画面与包装",
            "level": "影响目标",
            "track": "图形",
            "dimension": "字幕与包装",
            "interval": {"start": 0.2, "end": 0.5},
            "evidence": "在动作之后出现",
            "action": "提前",
            "acceptance": "同步",
            "confidence": "编辑判断",
            "cost": "现有素材剪辑",
            "disposition": "提前提示",
            "score_review": "扣一分",
        }
    ]
    previous = review(source, n, tmp_path / "old")
    n["findings"][0]["evidence"] = "连续帧显示文字提前出现"
    n["findings"][0]["action"] = "延后"
    for i, expected in enumerate([True, False]):
        root = tmp_path / ("again" + str(i))
        if i:
            n["findings"][0].update(
                disposition="现在延后两帧", score_review="仍扣一分，原因是提前抢读"
            )
        assert (
            call(
                "review",
                source,
                "--editorial",
                save(tmp_path / "revised.json", n),
                "--previous-review",
                previous,
                "--output-dir",
                root,
            )
            == 0
        )
        ed = read(next(root.glob("*.json")))["editorial"]
        assert bool(ed["reassessment"]["pending"]) == expected


def test_scoped_report_filters_checklist_and_formats_score(source, tmp_path):
    n = notes_for(source, tmp_path / "blank")
    n["brief"]["color_style"] = "有意风格化"
    path = review(source, n, tmp_path / "filtered")
    r = read(path)
    page = path.with_suffix(".html").read_text()
    assert r["issues"] and all(not rows for rows in r["revision_checklist"].values())
    assert "None dB" not in page and "建议至少导出 1080p" not in page
    from postscore.models import ReviewReport

    model = ReviewReport.model_validate(r)
    assert '<div class="score">' + model.technical_display + "</div>" in page
    assert len(model.technical_display) < 7
    from postscore.report import _radar_svg

    model.module_scores = model.technical["modules"]
    assert "声音质量" not in _radar_svg(model)


def test_unobserved_hook_is_not_a_zero(source, tmp_path):
    n = notes_for(source, tmp_path / "blank")
    n["criteria"]["hook"] = {}
    n["content"]["pending"] = {HOOK_DIM: "开场源证据缺失"}
    del n["content"]["marks"][HOOK_DIM]
    out = review(source, n, tmp_path / "partial-opening")
    ed = read(out)["editorial"]
    assert ed["content"]["total"] is None and not ed["criteria"]["hook"]
    assert "继续观看理由 · 待核" in out.with_suffix(".html").read_text()
