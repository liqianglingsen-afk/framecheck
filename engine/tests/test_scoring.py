from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postscore.models import AudioMetrics, Keyframe, VideoInfo
from postscore.scoring import grade_for_score, score_report


class ScoringTest(unittest.TestCase):
    def test_grade_calculation(self) -> None:
        self.assertEqual(grade_for_score(96), "S")
        self.assertEqual(grade_for_score(91), "A")
        self.assertEqual(grade_for_score(82), "B")
        self.assertEqual(grade_for_score(72), "C")
        self.assertEqual(grade_for_score(63), "D")
        self.assertEqual(grade_for_score(50), "E")

    def test_issue_deductions(self) -> None:
        video = VideoInfo(
            source="mock",
            resolved_path="mock",
            filename="mock.mp4",
            duration_seconds=60,
            width=640,
            height=360,
            fps=30,
            video_codec="h264",
            audio_codec="aac",
            audio_sample_rate=48000,
            audio_channels=2,
        )
        frame = Keyframe(path="frame.jpg", timestamp_seconds=3, timestamp_label="00:03.00")
        report = score_report(
            video_info=video,
            visual_metrics={
                "frames": [{"path": "frame.jpg", "timestamp": 3, "sharpness": 30}],
                "worst_frames": [{"path": "frame.jpg", "timestamp": 3, "sharpness": 30}],
                "avg_sharpness": 35,
                "avg_contrast": 25,
                "underexposed_ratio_mean": 0.1,
                "overexposed_ratio_mean": 0.0,
                "low_sharpness_frames": [{"path": "frame.jpg", "timestamp": 3}],
                "center_sharpness_mean": 40,
                "center_brightness_mean": 45,
            },
            color_metrics={"avg_saturation": 20, "temperature_bias": "neutral", "color_inconsistency": 0},
            edit_metrics={"black_frames": [], "repeated_frame_ratio": 0.0, "static_segments": []},
            audio_metrics=AudioMetrics(approx_loudness_db=-20, peak_db=-2),
            subtitle_metrics={"bottom_activity_mean": 0.0, "safe_margin_risk_mean": 0.0},
            keyframes=[frame],
        )
        self.assertLess(report.module_scores["visual_quality"], 25)
        self.assertLess(report.module_scores["export_specs"], 5)
        self.assertTrue(any(issue.problem == "画面平均清晰度偏低" for issue in report.issues))
        self.assertTrue(all(issue.recommendation for issue in report.issues))


if __name__ == "__main__":
    unittest.main()
