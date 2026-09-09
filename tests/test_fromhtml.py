"""HTML 을 마크다운으로 옮기는 시험."""

import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools.docs import fromhtml


def to_md(html: str) -> str:
    parser = fromhtml.Converter()
    parser.feed(html)
    return parser.result()


class FromHtmlTest(unittest.TestCase):
    def test_headings_and_paragraphs(self):
        self.assertEqual(to_md("<h1>제목</h1><p>글이다.</p>"), "# 제목\n\n글이다.\n")
        self.assertIn("### 셋", to_md("<h3>셋</h3>"))

    def test_inline_marks(self):
        md = to_md("<p><strong>굵게</strong> <em>기울임</em> <del>취소</del> "
                   "<code>코드</code></p>")
        self.assertIn("**굵게**", md)
        self.assertIn("*기울임*", md)
        self.assertIn("~~취소~~", md)
        self.assertIn("`코드`", md)

    def test_links_and_images(self):
        md = to_md('<p><a href="http://a.b">링크</a> <img src="a.png" alt="그림"></p>')
        self.assertIn("[링크](http://a.b)", md)
        self.assertIn("![그림](a.png)", md)

    def test_link_without_href_keeps_text(self):
        self.assertIn("글자", to_md("<p><a>글자</a></p>"))

    def test_unordered_and_ordered_lists(self):
        md = to_md("<ul><li>하나</li><li>둘</li></ul><ol><li>첫째</li><li>둘째</li></ol>")
        self.assertIn("- 하나", md)
        self.assertIn("1. 첫째", md)
        self.assertIn("2. 둘째", md)

    def test_nested_list_is_indented(self):
        md = to_md("<ul><li>둘<ul><li>안쪽</li></ul></li></ul>")
        self.assertIn("  - 안쪽", md)

    def test_pre_keeps_line_breaks(self):
        md = to_md("<pre><code>print(1)\nif x:\n    pass</code></pre>")
        self.assertIn("```", md)
        self.assertIn("    pass", md)      # 들여쓰기가 살아 있어야 코드다

    def test_table_gets_a_separator_row(self):
        md = to_md("<table><tr><th>이름</th><th>값</th></tr>"
                   "<tr><td>가</td><td>1</td></tr></table>")
        lines = [l for l in md.splitlines() if l.startswith("|")]
        self.assertEqual(lines[0], "| 이름 | 값 |")
        self.assertEqual(lines[1], "| --- | --- |")
        self.assertEqual(lines[2], "| 가 | 1 |")

    def test_colspan_and_rowspan_are_expanded(self):
        # 한 칸으로 세면 열이 밀려 뒤 열의 값이 통째로 어긋난다
        md = to_md("<table>"
                   '<tr><th rowspan="2">부서</th><th colspan="2">1분기</th>'
                   '<th rowspan="2">합계</th></tr>'
                   "<tr><th>1월</th><th>2월</th></tr>"
                   "<tr><td>영업</td><td>100</td><td>200</td><td>300</td></tr>"
                   "</table>")
        lines = [l for l in md.splitlines() if l.startswith("|")]
        self.assertEqual(lines[0], "| 부서 | 1분기 1월 | 1분기 2월 | 합계 |")
        self.assertEqual(lines[1], "| --- | --- | --- | --- |")
        self.assertEqual(lines[2], "| 영업 | 100 | 200 | 300 |")

    def test_rowspan_in_the_body_fills_down(self):
        md = to_md("<table><tr><th>이름</th><th>부서</th></tr>"
                   '<tr><td rowspan="2">홍길동</td><td>영업</td></tr>'
                   "<tr><td>관리</td></tr></table>")
        lines = [l for l in md.splitlines() if l.startswith("|")]
        self.assertEqual(lines[2], "| 홍길동 | 영업 |")
        self.assertEqual(lines[3], "| 홍길동 | 관리 |")

    def test_body_colspan_is_not_repeated(self):
        # 자료 칸을 되풀이하면 없던 값이 생겨 합계가 는다
        md = to_md("<table><tr><th>가</th><th>나</th></tr>"
                   '<tr><td colspan="2">합계 2건</td></tr></table>')
        lines = [l for l in md.splitlines() if l.startswith("|")]
        self.assertEqual(lines[2], "| 합계 2건 |  |")

    def test_table_without_header_says_so(self):
        md = to_md("<table><tr><td>가</td><td>나</td></tr>"
                   "<tr><td>1</td><td>2</td></tr></table>")
        self.assertIn("머리글이 없는 표", md)
        lines = [l for l in md.splitlines() if l.startswith("|")]
        self.assertEqual(lines[0], "| 가 | 나 |")
        self.assertEqual(lines[1], "| --- | --- |")

    def test_script_and_style_are_dropped(self):
        md = to_md("<style>p{color:red}</style><script>alert(1)</script><p>글</p>")
        self.assertEqual(md.strip(), "글")

    def test_blockquote_and_rule(self):
        md = to_md("<blockquote><p>인용</p></blockquote><hr>")
        self.assertIn("> 인용", md)
        self.assertIn("---", md)

    def test_unknown_tags_keep_their_text(self):
        self.assertIn("남는 글", to_md("<figure><figcaption>남는 글</figcaption></figure>"))

    def test_broken_html_does_not_raise(self):
        self.assertIn("글", to_md("<p>글<b>굵게</p>"))


if __name__ == "__main__":
    unittest.main()
