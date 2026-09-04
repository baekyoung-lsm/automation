"""차트·보고서 만들기 시험."""

import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools.docs import report
class ReportTest(unittest.TestCase):
    def test_bar_path_rounds_only_the_far_end(self):
        path = report._bar_path(0, 0, 100, 20, radius=4)
        self.assertTrue(path.startswith("M0,0"))
        self.assertIn("A4,4", path)           # 끝쪽만 둥글다
        self.assertEqual(path.count("A4,4"), 2)
        self.assertEqual(report._bar_path(0, 0, 0, 20), "")   # 길이 0이면 안 그린다

    def test_bar_chart_labels_every_value(self):
        html = report.bar_chart([("영업", 52), ("개발", 31)], unit="건")
        self.assertIn("52건", html)
        self.assertIn("31건", html)
        self.assertIn("data-tip", html)        # 마크마다 툴팁
        self.assertIn('role="img"', html)

    def test_bar_chart_empty(self):
        self.assertIn("보여줄 값이 없습니다", report.bar_chart([]))

    def test_line_chart_needs_two_points(self):
        self.assertIn("두 시점 이상", report.line_chart([("1월", 3)]))
        html = report.line_chart([("1월", 3), ("2월", 9)])
        self.assertIn("<polyline", html)
        self.assertIn("class=\"dot\"", html)

    def test_line_chart_baseline_includes_zero(self):
        # 금액 합계 같은 값은 0부터 그려야 크기를 오해하지 않는다
        html = report.line_chart([("1월", 100), ("2월", 110)])
        self.assertIn(">0<", html)

    def test_table_html_escapes(self):
        html = report.table_html(["<열>"], [["a & b"]])
        self.assertIn("&lt;열&gt;", html)
        self.assertIn("a &amp; b", html)

    def test_page_has_both_theme_scopes(self):
        html = report.page("제목", "부제", ["<section>내용</section>"])
        self.assertIn("prefers-color-scheme: dark", html)
        self.assertIn('[data-theme="dark"]', html)
        self.assertIn("<section>내용</section>", html)
        self.assertNotIn("<script src", html)   # 외부 의존 없음

    def test_tiles_html(self):
        html = report.tiles_html([report.Tile("행", "1,204", "전체")])
        self.assertIn("1,204", html)
        self.assertIn("전체", html)


if __name__ == "__main__":
    unittest.main()
