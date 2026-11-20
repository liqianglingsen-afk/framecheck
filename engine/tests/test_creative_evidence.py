"""Exercise the public editor brief and report commands with real decoded media."""

import json
import subprocess

import cv2
import numpy as np
import pytest

from postscore.cli import main
from postscore.editorial import AXES, CREATIVE_WEIGHTS

HOOK = "前3秒语言心理钩子"


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    root = tmp_path_factory.mktemp("product")
    video = root / "demo.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=128x96:r=5:d=4",
            "-c:v",
            "mpeg4",
            str(video),
        ],
        check=True,
    )
    return video


@pytest.fixture
def setup(tmp_path, source):
    notes = tmp_path / "brief.json"
    assert main(["brief", str(source), "--output", str(notes)]) == 0
    n = json.loads(notes.read_text())
    n.update(goal="了解产品", audience="手冲用户", entry="教程列表", bottleneck="前3秒")
    n["checks"] = {
        k: {"status": "已核", "evidence": "相同实物的操作示意"} for k in n["checks"]
    }
    n["content"] = {
        "version": "creative-100-v1",
        "marks": {
            k: {"score": w, "evidence": "本例的编辑标注"}
            for k, w in CREATIVE_WEIGHTS.items()
        },
    }
    c = n["criteria"]
    c.update(
        primary_task="展示操作",
        secondary_angle="节省按键",
        reveal_order="旧款再到新款",
        cover_source={
            "independent": "无独立封面",
            "displayed": "待核",
            "evidence": "用户确认独立封面缺失",
        },
        payoff="第 3 秒显示结果",
        identity={
            "sound_on": "清楚",
            "muted": "清楚",
            "evidence": "提前揭示有型号对照",
            "fix": "保留标注",
        },
        no_assets_reason="仅作基本操作演示",
        no_display_reason="本例默认无状态转换",
    )
    for (k, m), w in zip(c["hook"].items(), [4, 4, 5, 4]):
        m.update(score=w, evidence="第 1 秒同时见手和可辨的实际动作")
    for motive, headline, frame in [
        ("空间适配", "能放进去吗", "1.0 秒"),
        ("操作收益", "省哪一步", "2.2 秒"),
    ]:
        c["cover_plans"].append(
            {
                "motive": motive,
                "headline": headline,
                "source_frame": frame,
                "crop": "保留边缘",
                "focus": "产品与手",
                "placement": "左上留白",
                "rationale": "同框可以看清",
                "failure": "遮住边缘则重排",
            }
        )

    def run(ok=True):
        path = tmp_path / "filled.json"
        path.write_text(json.dumps(n, ensure_ascii=False))
        folder = tmp_path / "review"
        result = main(
            [
                "review",
                str(source),
                "--preset",
                "short_social",
                "--editorial",
                str(path),
                "--output-dir",
                str(folder),
                "--html",
                "--json",
            ]
        )
        if not ok:
            assert result != 0
            return
        assert result == 0
        report = json.loads(next(folder.glob("*.json")).read_text())["editorial"]
        html = next(folder.glob("*.html")).read_text()
        assert (
            report["schema_version"] == "editorial-0.5"
            and 'data-criteria="0.5"' in html
        )
        return report, html

    return n, c, run


def add_cover(n, c, root, role, subject="正确", benefit="可辨", score=9):
    cover = root / "cover.png"
    assert cv2.imwrite(str(cover), np.ones((90, 180, 3), dtype=np.uint8))
    n["covers"].append(
        {
            "name": "封面对象",
            "role": role,
            "image": str(cover),
            "integrity": {"status": "已核", "evidence": "实物可核"},
            "marks": {
                k: {"score": score, "evidence": "缩略逐项核对"}
                for group in AXES.values()
                for k in group
            },
            "correction": "替换错误对象或保留实物",
        }
    )
    c["previews"]["封面对象"] = {
        "source": "素材目录",
        "size": "实际 180px",
        "subject": subject,
        "benefit": benefit,
        "topic": "题目能解释画面动作",
    }


def test_no_cover_wrong_first_frame(setup, tmp_path):
    n, c, run = setup
    add_cover(n, c, tmp_path, "首帧", "错误或缺失", "不清")
    report, html = run()
    assert report["cover_status"] == "无独立封面 · N/A ｜ 平台实显待核"
    assert report["covers"][0]["decision"] == "淘汰" and len(c["cover_plans"]) == 2
    assert report["content"]["total"] == "100" and "省哪一步" in html


def test_missing_cover_requires_two_different_directions(setup):
    _, c, run = setup
    c["cover_plans"].pop()
    run(False)


def test_verified_platform_frame_with_no_independent_cover_preserves_zero(
    setup, tmp_path
):
    n, c, run = setup
    c["cover_source"]["displayed"] = "平台选帧"
    add_cover(n, c, tmp_path, "发布封面", score=0)
    r, _ = run()
    assert "无独立封面 · N/A" in r["cover_status"] and r["covers"][0]["total"] == 0
    assert r["status"] == "发布前须改"


def test_strong_cover_and_labelled_flashforward(setup, tmp_path):
    n, c, run = setup
    c["cover_source"].update(independent="有独立封面", displayed="独立封面")
    add_cover(n, c, tmp_path, "发布封面")
    c["cover_plans"] = []
    r, _ = run()
    assert "封面达到目标" in r["cover_status"] and r["covers"][0]["decision"] == "可用"
    assert "主体切换导致误认" not in r["blockers"]


@pytest.mark.parametrize(
    "mismatch,missing,ok",
    [(True, False, False), (False, True, False), (False, False, True)],
)
def test_weak_question_requires_matching_marks_and_alternatives(
    setup, mismatch, missing, ok
):
    n, c, run = setup
    for k, v in zip(c["hook"], [3, 4, 2, 1]):
        c["hook"][k]["score"] = v
    n["content"]["marks"][HOOK]["score"] = 13 if mismatch else 10
    for label in ["真实适配问题", "希望少按两次"]:
        beat = {"subject": "量具", "picture": label, "audio": label, "caption": label}
        c["openings"].append(
            {"motive": label, "beats": [beat] * 3, "next_shot": "操作镜头"}
        )
    if missing:
        c["openings"].pop()
    result = run(ok)
    if ok:
        r, h = result
        assert r["content"]["total"] == "93" and "希望少按两次" in h


def test_unexplained_identity_switch_blocks_high_score(setup):
    _, c, run = setup
    c["identity"]["muted"] = "误认"
    r, _ = run()
    assert (
        r["content"]["total"] == "100"
        and "主体切换导致误认" in r["blockers"]
        and r["status"] == "发布前须改"
    )


@pytest.mark.parametrize(
    "status,expected", [("擦空", True), ("错误", True), ("符合", False)]
)
def test_display_state(setup, status, expected):
    _, c, run = setup
    c["displays"] = [
        {
            "time": "3.2 秒",
            "action": "移杯复位",
            "expected": "两组零值",
            "observed": "擦掉数字" if expected else "两组归零",
            "reference": "同机零值字形",
            "timing_reference": "同模式连续记录",
            "status": status,
            "timing": "已核",
            "fix": "保留图标与亮度",
        }
    ]
    r, _ = run()
    assert ("产品屏显错误 · 3.2 秒" in r["blockers"]) == expected


@pytest.mark.parametrize(
    "picture,loss,blocked", [("保留", "保留价值", False), ("删除", "无据丢失", True)]
)
def test_repair_caption_separately(setup, picture, loss, blocked):
    _, c, run = setup
    c["assets"] = [
        {
            "name": "纹理近景",
            "source": "1–2 秒",
            "value": "可见饰面",
            "picture": picture,
            "display": "保留",
            "graphics": "只替换误写的字幕",
            "sound": "保留",
            "output": "无对应镜头" if blocked else "1–2 秒",
            "reason": "字幕可以局部修",
            "loss": loss,
        }
    ]
    r, h = run()
    assert (
        "价值镜头丢失 · 纹理近景" in r["blockers"]
    ) == blocked and "只替换误写的字幕" in h


def test_weak_alternative_does_not_disqualify_strong_cover(setup, tmp_path):
    n, c, run = setup
    c["cover_source"].update(independent="有独立封面", displayed="独立封面")
    add_cover(n, c, tmp_path, "发布封面")
    n["covers"].append(n["covers"][0] | {"name": "备选", "role": "候选"})
    c["previews"]["备选"] = c["previews"]["封面对象"] | {"subject": "错误或缺失"}
    c["cover_plans"] = []
    r, _ = run()
    assert [x["decision"] for x in r["covers"]] == ["可用", "淘汰"]


def test_usable_artwork_below_target_requires_improvement(setup, tmp_path):
    n, c, run = setup
    c["cover_source"].update(independent="有独立封面")
    add_cover(n, c, tmp_path, "独立封面", score=8)
    r, _ = run()
    assert (
        r["covers"][0]["decision"] == "需优化" and "平台实显待核" in r["cover_status"]
    )


def test_current_plan_and_independent_score_through_cli(setup, tmp_path, source):

    _, c, run = setup
    c["assets"] = [
        {
            "name": "质感镜头",
            "source": "1–2 秒",
            "value": "纹理清楚",
            "picture": "保留",
            "display": "无屏",
            "graphics": "保留",
            "sound": "原声",
            "output": "1–2 秒",
            "reason": "产品外观证据",
            "loss": "保留价值",
        }
    ]
    run()
    report = next((tmp_path / "review").glob("*.json"))

    def call(*args):
        return main(list(map(str, args)))

    def save(path, data):
        path.write_text(json.dumps(data, ensure_ascii=False))
        return path

    draft = tmp_path / "plan-draft.json"
    assert call("revision-init", source, report, "--output", draft) == 0
    d = json.loads(draft.read_text())
    asset = d["protect"].pop()
    assert asset["name"] == "质感镜头"
    asset["source"] = {"start": 1, "end": 2}
    d.update(
        strategy="保留动作顺序", next_if_short="核对读数", no_assets_reason="误删记录"
    )
    for dim, w in CREATIVE_WEIGHTS.items():
        d["forecast"][dim] = {
            "low": w - 1,
            "expected": w,
            "high": w,
            "basis": "原镜头保留",
            "confidence": "中",
        }
    for field in ("picture", "graphics", "sound", "reason", "acceptance", "screen"):
        d["timeline"][0][field] = "原镜逐层核对"
    d["packaging_plan"] = dict.fromkeys(d["packaging_plan"], "以实际成片手机预览核对")
    d["placement_plan"] = [dict.fromkeys(d["placement_plan"][0], "本地竖屏校样")]
    folder = tmp_path / "plan"

    def plan():
        return call("revision-plan", source, report, save(draft, d), "--output", folder)

    assert plan() == 2
    d["protect"] = [asset]
    d["timeline"][0]["screen"] = ""
    assert plan() == 2
    d["timeline"][0]["screen"] = "此段无屏显"
    assert plan() == 0
    snap = folder / "plan.json"
    audit = tmp_path / "audit.json"
    assert call("revision-audit", snap, source, "--output", audit) == 0
    a = json.loads(audit.read_text())
    a.update(
        reviewer="独立测试标签",
        review_mode="独立盲审",
        blind_sheet="blind.json",
        pending_placements=["缺平台截图"],
        variance="校准测试",
        next_edit="按实片修正",
        timeline_check={"status": "已核", "evidence": "原片顺序"},
    )
    blind = tmp_path / "blind.json"
    assert call("revision-blind", source, "--goal", "了解产品", "--output", blind) == 0
    b = json.loads(blind.read_text())
    b.update(
        reviewer=a["reviewer"],
        hook=c["hook"],
        payoff=c["payoff"],
        content=json.loads((tmp_path / "filled.json").read_text())["content"],
    )
    b["observations"] = [
        {
            "time": "1.50 秒",
            "issue": "主体标注错误",
            "evidence": "独立核对该镜头",
            "decision": "须修",
        }
    ]
    b["content"]["marks"][HOOK]["score"] = 15
    output = tmp_path / "pair"

    def compare():
        save(blind, b)
        return call(
            "revision-compare",
            snap,
            source,
            source,
            report,
            save(audit, a),
            "--output",
            output,
        )

    assert compare() == 2 and not output.exists()
    b["content"]["marks"][HOOK]["score"] = 17
    assert compare() == 0
    pair = json.loads((output / "comparison.json").read_text())
    assert pair["status"] == "发布前须改" and any(
        "主体标注错误" in x for x in pair["fixes"]
    )
    assert pair["blind"]["result"]["total"] == "100"
