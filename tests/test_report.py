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


class StandaloneSvgTest(unittest.TestCase):
    """그림 파일 하나로 낼 때. 보고서 CSS 없이도 보여야 한다."""

    def chart(self):
        return report.bar_chart([("영업", 100.0), ("개발", 80.0)], unit="만원")

    def test_it_is_valid_xml(self):
        import xml.etree.ElementTree as ET

        out = report.standalone_svg(self.chart())
        ET.fromstring(out.split("?>", 1)[1])       # 깨지면 여기서 걸린다

    def test_namespace_and_style_are_inside(self):
        out = report.standalone_svg(self.chart())
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', out)
        # 색을 안 넣으면 글자도 막대도 모두 검게 나온다
        self.assertIn(".mark { fill:", out)

    def test_title_is_escaped(self):
        out = report.standalone_svg(self.chart(), title='<나쁜 & 제목>')
        self.assertIn("&lt;나쁜 &amp; 제목&gt;", out)

    def test_refuses_something_that_is_not_svg(self):
        with self.assertRaises(ValueError):
            report.standalone_svg("<p>그림이 아니다</p>")


if __name__ == "__main__":
    unittest.main()
