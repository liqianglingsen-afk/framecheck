from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postscore.report import create_mock_report, write_reports


class ReportTest(unittest.TestCase):
    def test_mock_report_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            report = create_mock_report(output_dir)
            paths = write_reports(report, output_dir, write_html=True, write_json=True)
            self.assertTrue(paths["html"].exists())
            self.assertTrue(paths["json"].exists())
            html = paths["html"].read_text(encoding="utf-8")
            self.assertIn("视频后期评分", html)
            self.assertIn(str(report.overall_score), html)
            self.assertIn("画面平均清晰度偏低", html)
            self.assertIn("关键指标：清晰度", html)
            self.assertIn("平均亮度", html)
            self.assertIn("对比度", html)
            self.assertIn("timeline-events", html)
            self.assertIn("repeat(auto-fit, minmax(220px, 1fr))", html)
            self.assertIn("object-fit: contain", html)
            self.assertEqual(html.count("<h2>最终建议</h2>"), 1)
            self.assertLess(html.index("<h2>最终建议</h2>"), html.index('<section class="grid">'))
            self.assertIn("verdict-item primary", html)
            self.assertIn("#101f36", html)
            self.assertIn("结论", html)
            self.assertNotIn("'sharpness'", html)
            data = json.loads(paths["json"].read_text(encoding="utf-8"))
            self.assertIn("overall_score", data)
            self.assertIn("issues", data)


if __name__ == "__main__":
    unittest.main()
