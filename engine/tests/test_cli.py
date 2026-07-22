from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postscore.cli import build_parser, main


class CliTest(unittest.TestCase):
    def test_parse_review_args(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["review", "video.mp4", "--preset", "short_social", "--html"])
        self.assertEqual(args.command, "review")
        self.assertEqual(args.source, "video.mp4")
        self.assertEqual(args.mode, "deep")
        self.assertEqual(args.preset, "short_social")
        self.assertTrue(args.html)
        self.assertEqual(args.max_sampled_frames, 360)
        self.assertEqual(args.frame_width, 720)

    def test_fast_mode_is_removed(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["review", "video.mp4", "--mode", "fast"])

    def test_mock_cli_generates_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code = main(["review", "--mock", "--html", "--json", "--output-dir", tmp])
            self.assertEqual(code, 0)
            self.assertTrue(list(Path(tmp).glob("*.html")))
            self.assertTrue(list(Path(tmp).glob("*.json")))

    def test_parse_batch_args(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["batch", "videos", "https://example.com/watch/abc", "--preset", "short_social", "--recursive"])
        self.assertEqual(args.command, "batch")
        self.assertEqual(args.sources, ["videos", "https://example.com/watch/abc"])
        self.assertEqual(args.mode, "deep")
        self.assertEqual(args.preset, "short_social")
        self.assertTrue(args.recursive)

    def test_mock_batch_generates_index_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            videos = root / "videos"
            reports = root / "reports"
            videos.mkdir()
            (videos / "clip_a.mp4").write_bytes(b"")
            (videos / "clip_b.mov").write_bytes(b"")

            code = main(
                [
                    "batch",
                    str(videos),
                    "https://example.com/explore/online_video_123",
                    "--mock",
                    "--output-dir",
                    str(reports),
                ]
            )

            self.assertEqual(code, 0)
            batch_indexes = list(reports.glob("batch_index_*.html"))
            batch_csvs = list(reports.glob("batch_summary_*.csv"))
            self.assertEqual(len(batch_indexes), 1)
            self.assertEqual(len(batch_csvs), 1)
            self.assertGreaterEqual(len(list(reports.glob("batch_*.html"))), 4)

            html = batch_indexes[0].read_text(encoding="utf-8")
            self.assertIn("clip_a", html)
            self.assertIn("clip_b", html)
            self.assertIn("online_video_123", html)
            self.assertIn("原始链接", html)
            self.assertIn("文件位置", html)

            csv_text = batch_csvs[0].read_text(encoding="utf-8-sig")
            self.assertIn("display_name", csv_text)
            self.assertIn("clip_a", csv_text)
            self.assertIn("https://example.com/explore/online_video_123", csv_text)

    def test_batch_always_generates_complete_per_video_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            videos = root / "videos"
            reports = root / "reports"
            videos.mkdir()
            (videos / "clip_only_json_flag.mp4").write_bytes(b"")

            code = main(["batch", str(videos), "--mock", "--json", "--output-dir", str(reports)])

            self.assertEqual(code, 0)
            self.assertTrue(list(reports.glob("batch_001_*.html")))
            self.assertTrue(list(reports.glob("batch_001_*.json")))
            index_html = next(reports.glob("batch_index_*.html")).read_text(encoding="utf-8")
            self.assertIn("HTML", index_html)
            self.assertIn("JSON", index_html)


if __name__ == "__main__":
    unittest.main()
