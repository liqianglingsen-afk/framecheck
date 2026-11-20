from pathlib import Path
import json
import shutil
import subprocess

import cv2
import numpy as np
import pytest

from postscore.cli import main
from postscore.editorial import CREATIVE_WEIGHTS, blank_notes
from postscore.revision import fingerprint, read_plan
from postscore.revision_safety import Box, Track, scan_track


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, d):
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return path


def call(*args):
    return main(list(map(str, args)))


@pytest.fixture
def source(tmp_path):
    if not all(shutil.which(x) for x in ("ffmpeg", "ffprobe")):
        pytest.skip("requires local media tools")
    p = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=200x300:rate=10:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=500:duration=1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(p),
        ],
        check=True,
    )
    return p


def review(video, root):
    root.mkdir()
    notes = blank_notes(video)
    notes.update(
        goal="认出测试色块",
        audience="测试观众",
        entry="本地模拟",
        bottleneck="画面与包装",
        checks={k: dict(status="已核", evidence="测试夹具正常播放") for k in notes["checks"]},
        content=dict(
            version="creative-100-v1",
            marks={k: dict(score=v, evidence="测试用评分") for k, v in CREATIVE_WEIGHTS.items()},
        ),
    )
    path = save(root / "notes.json", notes)
    assert (
        call("review", video, "--preset", "short_social", "--editorial", path, "--output-dir", root / "review")
        == 0
    )
    return next((root / "review").glob("*.json"))


def test_timeline_and_render_and_paired_report(source, tmp_path):
    before = review(source, tmp_path / "before")
    draft = tmp_path / "draft.json"
    assert call("revision-init", source, before, "--output", draft) == 0
    data = read(draft)
    data.update(
        strategy="测试包装改动",
        next_if_short="回看可读性",
        protect=[
            dict(
                name="最后一帧",
                kind="原字幕",
                source=dict(start=0.9, end=1),
                value="验证末帧证据",
                handling="保留",
            )
        ],
    )
    data["timeline"][0].update(
        action="微调",
        picture="原画面",
        graphics="白框",
        sound="保留原声",
        reason="测版位",
        acceptance="框可见",
    )
    for k, w in CREATIVE_WEIGHTS.items():
        data["forecast"][k] = dict(low=w - 1, expected=w, high=w, basis="示例假设", confidence="低")
    data["timeline"][0]["source"]["start"] = 0.2
    pack = tmp_path / "plan"
    assert call("revision-plan", source, before, save(draft, data), "--output", pack) == 2
    assert not pack.exists()
    data["timeline"][0]["source"]["start"] = 0
    assert call("revision-plan", source, before, save(draft, data), "--output", pack) == 2
    data["packaging_plan"] = {k: "用单行白框字幕引导识别测试色块" for k in data["packaging_plan"]}
    data["placement_plan"] = [
        dict(
            platform="测试平台",
            placement="竖屏",
            ui_state="组件展开",
            reference="本地测试遮罩",
            layout="白框避开顶部按钮",
            acceptance="套版复核白框边界",
        )
    ]
    data["forecast_context"] = "历史回放"
    assert call("revision-plan", source, before, save(draft, data), "--output", pack) == 2
    data["forecast_context"] = "剪前预测"
    assert call("revision-plan", source, before, save(draft, data), "--output", pack) == 0
    plan = pack / "plan.json"
    assert read_plan(plan)["totals"] == dict(low="90", expected="100", high="100")
    export = tmp_path / "export"
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
            "-vn",
            "{output}",
        )
        == 2
    )
    assert not export.exists()
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
            "-vf",
            "drawbox=x=2:y=2:w=60:h=40:color=white:t=4",
            "-c:a",
            "copy",
            "{output}",
        )
        == 0
    )
    revised = export / "edited.mp4"
    after = review(revised, tmp_path / "after")
    audit_path = tmp_path / "audit.json"
    assert call("revision-audit", plan, revised, "--output", audit_path) == 0
    audit = read(audit_path)
    audit.update(
        reviewer="夹具自评",
        render_receipt="export/receipt.json",
        variance="测试用分数",
        next_edit="移动白框",
        timeline_check=dict(status="已核", evidence="逐段回看测试片"),
    )
    audit["protected"]["最后一帧"].update(
        status="保留", output=dict(start=0.9, end=1), evidence="末帧可读", tradeoff="白框新增"
    )
    audit["packaging"] = {k: dict(status="已核", evidence="本地校样") for k in audit["packaging"]}
    cv2.imencode(".png", np.zeros((300, 200, 3), np.uint8))[1].tofile(str(tmp_path / "ui.png"))
    audit["placements"] = [
        dict(
            platform="本地测试",
            placement="全屏",
            ui_state="展开",
            source="版位实证",
            reference="ui.png",
            reference_date="2026-11-20",
            coverage_checked=True,
            zones={"顶部": dict(x=0, y=0, w=1, h=0.1)},
            tracks=[dict(name="白框", keys=[dict(time=0, x=0.01, y=0.01, w=0.3, h=0.13)], end=1)],
        )
    ]
    comparison = tmp_path / "result"

    def compare():
        return call(
            "revision-compare", plan, source, revised, after, save(audit_path, audit), "--output", comparison
        )

    audit["packaging"]["画面美感"]["evidence"] = "待核"
    assert compare() == 2
    audit["packaging"]["画面美感"]["evidence"] = "已看新增白框的画面"
    receipt = read(export / "receipt.json")
    save(tmp_path / "bad.json", {k: receipt[k] for k in ("source_sha256", "plan_sha256", "revised_sha256")})
    audit["render_receipt"] = "bad.json"
    assert compare() == 2
    audit["render_receipt"] = "export/receipt.json"
    assert compare() == 0
    result = read(comparison / "comparison.json")
    assert result["prediction_verified"] and result["technical_comparable"]
    assert result["status"] == "发布前须改"
    assert any("剪前指定版位" in item for item in result["pending"])
    assert result["placements"][0]["hits"][0]["time"] == 0
    for f in ["asset-0-before.jpg", "asset-0-after.jpg", "ui-0-0-0.jpg", "clean-0-0-0.jpg"]:
        assert (comparison / f).is_file()
    assert fingerprint(result) in (comparison / "comparison.html").read_text(encoding="utf-8")
    forged = read(plan)
    forged["totals"]["expected"] = "15"
    with pytest.raises(ValueError):
        read_plan(save(tmp_path / "bad-plan.json", forged))


def test_animated_midpoint_overlap_and_hold():
    spec = dict(
        name="字幕",
        keys=[dict(time=0, x=0, y=0, w=0.1, h=0.1), dict(time=0.8, x=0.8, y=0, w=0.1, h=0.1)],
        end=1,
    )
    zones = {"交互": Box(x=0.4, y=0, w=0.1, h=0.1)}
    pts = np.arange(10) / 10
    found = scan_track(Track(**spec), zones, pts)
    assert found and 0.3 <= found[0]["time"] <= 0.4 and found[0]["fix"]
    assert scan_track(Track(**spec, interpolation="hold"), zones, pts) == []
