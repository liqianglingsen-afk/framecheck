import csv
import json
from pathlib import Path

import pytest

from postscore.cli import main
from postscore.edit_metrics import _merge_static_segments
from postscore.models import VideoInfo
from postscore.report import _asset_path
from postscore.scoring import check_optimization, score_report


@pytest.mark.parametrize("score,target,status,gap", [
    (84.9, 85, "below_target", 0.1), (85.0, 85, "meets_target", 0),
    (85, 90, "below_target", 5), (100, 100, "meets_target", 0),
])
def test_floor(score, target, status, gap):
    result = check_optimization(score, target, measured=True, mock=False)
    assert (result.status, result.gap) == (status, gap)


def test_missing_evidence_and_existing_presets():
    info = VideoInfo(source="video.mp4", resolved_path="video.mp4", filename="video.mp4")
    for preset in ("default", "amazon_product", "brand_commercial"):
        assert score_report(info, preset=preset).optimization is None
    result = score_report(info, preset="short_social")
    assert result.optimization.status == "unverified"
    assert result.optimization.gap is None
    with pytest.raises(ValueError):
        score_report(info, optimization_target=84)


def test_mock_batch_and_higher_target(tmp_path):
    path = tmp_path / "input.mp4"
    path.touch()
    assert main(["batch", str(path), "--mock", "--preset", "amazon_product",
                 "--optimization-target", "90", "--output-dir", str(tmp_path)]) == 0
    data = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert data["optimization"]["target"] == 90
    assert data["optimization"]["status"] == "mock"
    assert data["optimization"]["gap"] is None
    html = next(tmp_path.glob("batch_001*.html")).read_text(encoding="utf-8")
    assert "90 / 100" in html and "示例数据" in html
    with next(tmp_path.glob("*.csv")).open(encoding="utf-8-sig") as handle:
        row = next(csv.DictReader(handle))
        assert "示例数据" in row["recommendation"]
        assert (row["optimization_target"], row["optimization_gap"], row["optimization_status"]) == ("90", "", "mock")
    index_html = next(tmp_path.glob("batch_index*.html")).read_text(encoding="utf-8")
    assert "目标 90 分" in index_html and "示例数据" in index_html


def test_adjacent_static_evidence_and_zero_timestamp():
    changes = [
        {"start": i / 2, "timestamp": (i + 1) / 2, "diff": diff}
        for i, diff in enumerate([0, 0, 4, 0, 0, 4, 0, 0, 0, 0, 0])
    ]
    assert _merge_static_segments(changes) == [{"start": 3.0, "end": 5.5}]
    info = VideoInfo(source="a", filename="a", resolved_path="a")
    report = score_report(info, edit_metrics={"black_frames": [{"timestamp": 0.0}]})
    black = next(issue for issue in report.issues if issue.problem == "检测到黑场关键帧")
    assert black.timestamp_start == 0.0


def test_relative_evidence_links(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    directory = Path("outputs/review/baseline")
    assert _asset_path(str(directory / "assets/frame.jpg"), directory) == "assets/frame.jpg"
