"""마크다운 목차·링크·표 시험."""

import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import mdkit


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


if __name__ == "__main__":
    unittest.main()
