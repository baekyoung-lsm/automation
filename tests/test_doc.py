"""마크다운 목차·링크·표 시험."""

import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import sheet
from attools.docs import mdkit
class MdkitTest(unittest.TestCase):
    DOC = ("# 문서 제목\n\n## 설치 방법\n### 요구 사항\n##### 너무 깊음\n"
           "## 설치 방법\n```\n# 코드 안 제목\n```\n")

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_slug_matches_github_rules(self):
        self.assertEqual(mdkit.github_slug("설치 방법"), "설치-방법")
        self.assertEqual(mdkit.github_slug("API 응답: 비교!"), "api-응답-비교")
        self.assertEqual(mdkit.github_slug("`code` 와 **굵게**"), "code-와-굵게")

    def test_duplicate_slugs_get_suffix(self):
        seen = {}
        self.assertEqual(mdkit.github_slug("설치", seen), "설치")
        self.assertEqual(mdkit.github_slug("설치", seen), "설치-1")

    def test_headings_ignore_code_fences(self):
        items = mdkit.headings(self.DOC)
        self.assertEqual([h.title for h in items],
                         ["문서 제목", "설치 방법", "요구 사항", "너무 깊음", "설치 방법"])
        self.assertEqual(items[-1].slug, "설치-방법-1")

    def test_build_toc_skips_leading_h1(self):
        toc = mdkit.build_toc(mdkit.headings(self.DOC), depth=3)
        self.assertNotIn("문서 제목", toc)
        self.assertIn("- [설치 방법](#설치-방법)", toc)
        self.assertIn("  - [요구 사항](#요구-사항)", toc)

    def test_build_toc_respects_depth(self):
        toc = mdkit.build_toc(mdkit.headings(self.DOC), depth=2)
        self.assertNotIn("요구 사항", toc)

    def test_update_toc_replaces_between_markers(self):
        doc = f"# 제목\n\n{mdkit.TOC_START}\n낡음\n{mdkit.TOC_END}\n\n## 설치\n"
        new, changed = mdkit.update_toc(doc, "- [설치](#설치)")
        self.assertTrue(changed)
        self.assertIn("- [설치](#설치)", new)
        self.assertNotIn("낡음", new)

        again, changed = mdkit.update_toc(new, "- [설치](#설치)")
        self.assertFalse(changed)   # 같은 목차면 다시 쓰지 않는다

    def test_update_toc_without_markers_is_noop(self):
        new, changed = mdkit.update_toc("# 제목\n", "- x")
        self.assertFalse(changed)

    def test_links_collects_inline_and_reference(self):
        doc = ("[하나](./a.md) ![그림](./b.png)\n"
               "[둘][ref]\n\n[ref]: ./c.md\n")
        found = mdkit.links(doc)
        self.assertEqual({l.target for l in found}, {"./a.md", "./b.png", "./c.md"})
        self.assertEqual([l.kind for l in found if l.target == "./b.png"], ["image"])

    def test_check_links_finds_missing_files_and_anchors(self):
        (self.root / "config.md").write_text("# 설정\n\n## 옵션\n", encoding="utf-8")
        doc = self.root / "README.md"
        doc.write_text(
            "# 제목\n\n## 설치\n\n"
            "[있음](./config.md) [없음](./nope.md) [내부](#설치) [틀림](#없는곳) "
            "[남의것](./config.md#옵션) [남의틀림](./config.md#없음) "
            "[외부](https://example.com)\n", encoding="utf-8")

        issues = mdkit.check_links(doc)
        self.assertEqual([(i.kind, i.detail) for i in issues],
                         [("파일 없음", "./nope.md"),
                          ("앵커 없음", "#없는곳"),
                          ("앵커 없음", "./config.md#없음")])

    def test_check_headings_flags_jump_and_duplicates(self):
        kinds = [i.kind for i in mdkit.check_headings(self.DOC)]
        self.assertIn("제목 단계 건너뜀", kinds)
        self.assertIn("같은 제목 반복", kinds)

    def test_check_headings_clean_doc(self):
        self.assertEqual(mdkit.check_headings("# 제목\n\n## 하나\n\n## 둘\n"), [])

    SPLIT_DOC = ("머리말입니다.\n\n# 안내서\n\n첫 절.\n\n## 설치\n\n"
                 "```\n## 코드 안 제목은 무시\n```\n\n## 사용법\n\n끝.\n")

    def test_split_sections_keeps_order_and_preface(self):
        preface, secs = mdkit.split_sections(self.SPLIT_DOC, level=2)
        self.assertEqual(preface, "머리말입니다.")
        self.assertEqual([s.title for s in secs], ["안내서", "설치", "사용법"])
        self.assertEqual([s.number for s in secs], [1, 2, 3])
        self.assertEqual([s.level for s in secs], [1, 2, 2])

    def test_split_sections_ignores_headings_in_code_fence(self):
        _, secs = mdkit.split_sections(self.SPLIT_DOC, level=2)
        설치 = secs[1]
        self.assertIn("## 코드 안 제목은 무시", 설치.body)
        self.assertEqual(len(secs), 3)

    def test_split_sections_level_limits_cut_points(self):
        doc = "# 하나\n\n## 둘\n\n### 셋\n"
        _, secs = mdkit.split_sections(doc, level=1)
        self.assertEqual([s.title for s in secs], ["하나"])
        self.assertIn("## 둘", secs[0].body)

    def test_split_sections_without_headings(self):
        preface, secs = mdkit.split_sections("제목 없는 글\n")
        self.assertEqual(preface, "제목 없는 글")
        self.assertEqual(secs, [])

    def test_section_filename_numbers_and_slugs(self):
        _, secs = mdkit.split_sections(self.SPLIT_DOC, level=2)
        self.assertEqual(mdkit.section_filename(secs[0]), "01-안내서.md")
        self.assertEqual(mdkit.section_filename(secs[2], digits=3), "003-사용법.md")

    def test_section_filename_falls_back_when_slug_empty(self):
        _, secs = mdkit.split_sections("# ...\n\n내용\n")
        self.assertEqual(mdkit.section_filename(secs[0]), "01-절1.md")

    TABLE_DOC = ("# 문서\n\n| 이름 | 값 | 비고 |\n|---|:-:|---:|\n"
                 "| 가나다 | 1 | 짧음 |\n| 라 | 22222 | 긴 설명 |\n\n끝.\n")

    def test_display_width_counts_hangul_as_two(self):
        self.assertEqual(mdkit.display_width("가나"), 4)
        self.assertEqual(mdkit.display_width("ab"), 2)

    def test_find_tables_reads_header_and_aligns(self):
        blocks = mdkit.find_tables(self.TABLE_DOC)
        self.assertEqual(len(blocks), 1)
        t = blocks[0]
        self.assertEqual(t.header, ["이름", "값", "비고"])
        self.assertEqual(t.aligns, ["왼쪽", "가운데", "오른쪽"])
        self.assertEqual(len(t.rows), 2)
        self.assertEqual((t.start, t.end), (3, 6))

    def test_find_tables_ignores_code_fence_and_lone_pipes(self):
        doc = "```\n| 코드 | 안 |\n|---|---|\n```\n\n그냥 | 막대\n"
        self.assertEqual(mdkit.find_tables(doc), [])

    def test_format_table_pads_by_display_width(self):
        block = mdkit.find_tables(self.TABLE_DOC)[0]
        lines = mdkit.format_table(block)
        widths = {mdkit.display_width(l) for l in lines}
        self.assertEqual(len(widths), 1)          # 모든 줄이 같은 너비

    def test_format_table_keeps_alignment_marks(self):
        lines = mdkit.format_table(mdkit.find_tables(self.TABLE_DOC)[0])
        marks = [c.strip() for c in lines[1].strip("| ").split("|")]
        self.assertTrue(marks[0].startswith("-") and not marks[0].endswith(":"))
        self.assertTrue(marks[1].startswith(":") and marks[1].endswith(":"))
        self.assertTrue(marks[2].endswith(":") and not marks[2].startswith(":"))

    def test_split_row_keeps_escaped_pipe(self):
        self.assertEqual(mdkit.split_row(r"| 가\|나 | 다 |"), [r"가\|나", "다"])

    def test_format_tables_is_idempotent(self):
        once, touched = mdkit.format_tables(self.TABLE_DOC)
        self.assertEqual(touched, 1)
        twice, again = mdkit.format_tables(once)
        self.assertEqual((twice, again), (once, 0))

    def test_format_tables_keeps_text_around_and_trailing_newline(self):
        new, _ = mdkit.format_tables(self.TABLE_DOC)
        self.assertTrue(new.startswith("# 문서\n"))
        self.assertTrue(new.endswith("끝.\n"))

    def test_format_tables_fills_short_rows(self):
        doc = "| 가 | 나 |\n|---|---|\n| 하나 |\n"
        new, _ = mdkit.format_tables(doc)
        self.assertEqual(len(new.splitlines()), 3)
        self.assertEqual({mdkit.display_width(l) for l in new.splitlines()}, {14})


class TablesToSheetTest(unittest.TestCase):
    """마크다운 표를 표 모델로 옮길 때 지켜야 하는 것들."""

    DOC = ("# 문서\n\n| 이름 | 수량 |\n|---|---:|\n| 가 | 3 |\n| 나 | 12 |\n\n"
           "글.\n\n| A | B | C |\n|---|---|---|\n| 1 | 2 |\n")

    def test_finds_every_table(self):
        blocks = mdkit.find_tables(self.DOC)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].header, ["이름", "수량"])
        self.assertEqual(blocks[1].columns, 3)

    def test_short_row_is_padded_not_dropped(self):
        block = mdkit.find_tables(self.DOC)[1]
        self.assertEqual(len(block.rows[0]), 2)      # 원본은 두 칸뿐
        self.assertEqual(block.columns, 3)           # 머리글 기준으로 세 칸

    def test_numbers_are_recognised_for_later_math(self):
        block = mdkit.find_tables(self.DOC)[0]
        values = [sheet.parse_number(r[1]) for r in block.rows]
        self.assertEqual(values, [3, 12])


class ImageLinkTest(unittest.TestCase):
    """문서가 가리키는 이미지를 찾을 때 지켜야 하는 것들."""

    DOC = ("# 안내\n\n![표지](그림/표지.png)\n\n![](그림/작은것.png)\n\n"
           "[문서 링크](다른.md)\n\n![바깥](https://example.com/a.png)\n")

    def test_only_image_links_are_picked(self):
        images = [l for l in mdkit.links(self.DOC) if l.kind == "image"]
        self.assertEqual([l.target for l in images],
                         ["그림/표지.png", "그림/작은것.png",
                          "https://example.com/a.png"])

    def test_alt_text_is_kept(self):
        images = [l for l in mdkit.links(self.DOC) if l.kind == "image"]
        self.assertEqual(images[0].text, "표지")
        self.assertEqual(images[1].text, "")      # 설명 없는 이미지

    def test_images_in_code_fence_are_ignored(self):
        body = "```\n![코드 안](그림/무시.png)\n```\n"
        self.assertEqual(mdkit.links(body), [])


class TermVariantTest(unittest.TestCase):
    DOCS = [("a.md", "API 를 부른다. api 는 빠르다. `api` 는 코드다.\n"
                     "데이터베이스에 넣는다."),
            ("b.md", "Api 응답. 데이터 베이스 설정. 데이터 베이스 이름.")]

    def test_case_variants_are_grouped(self):
        found = {u.key: u for u in mdkit.term_variants(self.DOCS)}
        self.assertEqual(dict(found["api"].forms), {"API": 1, "api": 1, "Api": 1})

    def test_inline_code_is_not_counted(self):
        # `api` 는 코드라서 세지 않는다 (세면 흔들림이 부풀려진다)
        self.assertEqual(mdkit.term_variants(self.DOCS)[0].forms["api"], 1)

    def test_spacing_variants_need_a_joined_form_somewhere(self):
        found = {u.key: u for u in mdkit.term_variants(self.DOCS)}
        self.assertEqual(found["데이터베이스"].kind, "띄어쓰기")
        self.assertEqual(found["데이터베이스"].forms["데이터 베이스"], 2)

    def test_particles_do_not_hide_the_joined_form(self):
        # '데이터베이스에' 처럼 조사가 붙어도 같은 말로 본다
        docs = [("a.md", "데이터베이스에 넣는다."), ("b.md", "데이터 베이스 설정")]
        self.assertTrue(any(u.kind == "띄어쓰기" for u in mdkit.term_variants(docs)))

    def test_spacing_alone_is_not_reported(self):
        # 붙여 쓴 표기가 아예 없으면 흔들림이 아니다
        docs = [("a.md", "서버 설정 파일"), ("b.md", "서버 설정 값")]
        self.assertEqual([u for u in mdkit.term_variants(docs)
                          if u.kind == "띄어쓰기"], [])

    def test_code_fence_and_url_are_skipped(self):
        docs = [("a.md", "```\nAPI api\n```\nhttps://example.com/Api\n")]
        self.assertEqual(mdkit.term_variants(docs), [])

    def test_consistent_spelling_is_not_reported(self):
        self.assertEqual(mdkit.term_variants([("a.md", "API 와 API")]), [])


class ToHtmlTest(unittest.TestCase):
    def render(self, md: str, **kw) -> str:
        html = mdkit.to_html(md, **kw)
        return html.split('<div class="wrap">')[1].split("</div>")[0]

    def test_headings_get_anchors(self):
        body = self.render("# 제목\n\n## 설치 방법\n")
        self.assertIn('<h1 id="제목">제목</h1>', body)
        self.assertIn('<h2 id="설치-방법">', body)

    def test_inline_syntax(self):
        body = self.render("**굵게** *기울임* ~~취소~~ `코드` [링크](https://a.b)\n")
        for piece in ("<strong>굵게</strong>", "<em>기울임</em>", "<del>취소</del>",
                      "<code>코드</code>", '<a href="https://a.b">링크</a>'):
            self.assertIn(piece, body)

    def test_html_in_text_is_escaped(self):
        body = self.render("문단에 <script>alert(1)</script> 가 있다.\n")
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)

    def test_code_block_keeps_markup_as_text(self):
        body = self.render("```\n**굵게 아님** <b>태그</b>\n```\n")
        self.assertIn("<pre><code>", body)
        self.assertIn("**굵게 아님**", body)
        self.assertIn("&lt;b&gt;", body)

    def test_inline_code_is_not_reformatted(self):
        body = self.render("`**별표 그대로**`\n")
        self.assertIn("<code>**별표 그대로**</code>", body)

    def test_nested_list_goes_inside_the_item(self):
        body = self.render("- 하나\n- 둘\n  - 안쪽\n- 셋\n")
        self.assertIn("<li>둘\n<ul>\n<li>안쪽</li>\n</ul></li>", body)

    def test_ordered_list(self):
        self.assertIn("<ol>", self.render("1. 첫째\n2. 둘째\n"))

    def test_table_alignment_is_kept(self):
        body = self.render("| 이름 | 값 |\n|---|---:|\n| 가 | 1 |\n")
        self.assertIn('<th style="text-align:right">값</th>', body)
        self.assertIn('<td style="text-align:right">1</td>', body)

    def test_quote_and_rule(self):
        body = self.render("> 인용\n\n---\n")
        self.assertIn("<blockquote><p>인용</p></blockquote>", body)
        self.assertIn("<hr/>", body)

    def test_toc_lists_h2_and_h3_only(self):
        body = self.render("# 제목\n\n## 둘\n\n### 셋\n\n#### 넷\n", toc=True)
        toc = body.split("</nav>")[0]
        self.assertIn("#둘", toc)
        self.assertIn("#셋", toc)
        self.assertNotIn("#넷", toc)

    def test_print_styles_are_included(self):
        self.assertIn("@media print", mdkit.to_html("# 가\n"))


if __name__ == "__main__":
    unittest.main()
