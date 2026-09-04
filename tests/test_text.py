"""여러 파일 텍스트 처리 시험."""

import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import files, text


class TextTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, name, content, encoding="utf-8"):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode(encoding) if isinstance(content, str) else content)
        return p

    def files(self, **kw):
        return list(text.iter_files([self.root], **kw))

    def test_reads_cp949_and_keeps_bom_state(self):
        plain = self.make("a.txt", "한글")
        self.assertEqual(text.read_text_any(plain), ("한글", "utf-8"))

        bom = self.make("b.csv", b"\xef\xbb\xbf\xed\x95\x9c")
        self.assertEqual(text.read_text_any(bom), ("한", "utf-8-sig"))

        legacy = self.make("c.txt", "한글", encoding="cp949")
        self.assertEqual(text.read_text_any(legacy), ("한글", "cp949"))

    def test_rejects_binary(self):
        binary = self.make("x.dat", b"abc\0def")
        with self.assertRaises(text.TextError):
            text.read_text_any(binary)

    def test_iter_skips_binary_and_ignored_dirs(self):
        self.make("keep.py", "x")
        self.make("node_modules/skip.py", "x")
        self.make("image.png", b"\x89PNG")
        self.make(".hidden/also.py", "x")
        self.assertEqual([p.name for p in self.files()], ["keep.py"])

    def test_glob_filter(self):
        self.make("a.py", "x")
        self.make("b.md", "x")
        self.assertEqual([p.name for p in self.files(glob=["*.md"])], ["b.md"])

    def test_replace_treats_plain_text_literally(self):
        self.make("a.txt", "a.b and axb")
        pattern = text.build_pattern("a.b", regex=False, ignore_case=False, whole_word=False)
        changes = text.plan_replace(self.files(), pattern, "Z")
        self.assertEqual(changes[0].after, "Z and axb")   # 정규식이 아니면 . 은 문자 그대로
        self.assertEqual(changes[0].hits, 1)

    def test_replace_regex_with_group(self):
        self.make("a.txt", "버전 1.2.3")
        pattern = text.build_pattern(r"(\d+)\.(\d+)\.(\d+)", regex=True,
                                     ignore_case=False, whole_word=False)
        changes = text.plan_replace(self.files(), pattern, r"v\1.\2", regex=True)
        self.assertEqual(changes[0].after, "버전 v1.2")

    def test_replace_backslash_is_literal_in_plain_mode(self):
        self.make("a.txt", "경로")
        pattern = text.build_pattern("경로", regex=False, ignore_case=False, whole_word=False)
        changes = text.plan_replace(self.files(), pattern, r"C:\\새폴더")
        self.assertEqual(changes[0].after, r"C:\\새폴더")

    def test_whole_word_option(self):
        self.make("a.txt", "id and idx")
        pattern = text.build_pattern("id", regex=False, ignore_case=False, whole_word=True)
        self.assertEqual(text.plan_replace(self.files(), pattern, "KEY")[0].after,
                         "KEY and idx")

    def test_bad_regex_raises(self):
        with self.assertRaises(text.TextError):
            text.build_pattern("(unclosed", regex=True, ignore_case=False, whole_word=False)

    def test_eol_and_trim(self):
        self.make("a.txt", "one\r\ntwo\r\n")
        self.assertEqual(text.plan_eol(self.files(), "lf")[0].after, "one\ntwo\n")

        self.make("b.txt", "line   \n\ttab\t\n")
        change = text.plan_trim(self.files(glob=["b.txt"]))[0]
        self.assertEqual(change.after, "line\n\ttab\n")

    def test_trim_expands_tabs_when_asked(self):
        self.make("a.txt", "\tx\n")
        self.assertEqual(text.plan_trim(self.files(), tabs=2)[0].after, "  x\n")

    def test_encoding_plan_skips_already_utf8(self):
        self.make("utf.txt", "한글")
        self.make("legacy.txt", "한글", encoding="cp949")
        changes = text.plan_encoding(self.files())
        self.assertEqual([c.path.name for c in changes], ["legacy.txt"])

    def test_apply_and_undo_roundtrip(self):
        target = self.make("a.txt", "before")
        journal = self.root / "j" / "journal.jsonl"
        pattern = text.build_pattern("before", regex=False, ignore_case=False,
                                     whole_word=False)
        changes = text.plan_replace(self.files(glob=["a.txt"]), pattern, "after")
        text.apply_changes(changes, journal=journal)
        self.assertEqual(target.read_text(encoding="utf-8"), "after")

        restored, errors = text.undo(journal)
        self.assertEqual((restored, errors), (1, []))
        self.assertEqual(target.read_text(encoding="utf-8"), "before")

    def test_apply_recodes_to_utf8(self):
        target = self.make("a.txt", "한글", encoding="cp949")
        changes = text.plan_encoding(self.files())
        text.apply_changes(changes, target_encoding="utf-8",
                           journal=self.root / "j" / "journal.jsonl")
        self.assertEqual(target.read_bytes(), "한글".encode("utf-8"))

    def test_read_lines_strips_and_drops_blanks(self):
        p = self.make("a.txt", "  홍길동  \n\n김철수\n")
        self.assertEqual(text.read_lines(p), ["홍길동", "김철수"])
        self.assertEqual(text.read_lines(p, keep_blank=True), ["홍길동", "", "김철수"])

    def test_line_stats(self):
        stats = text.line_stats(["가", "나", "가", "", "다"])
        self.assertEqual((stats.total, stats.unique, stats.blank), (5, 3, 1))
        self.assertEqual(stats.duplicated, 1)
        self.assertEqual(stats.extra, 1)

    def test_unique_keeps_order(self):
        self.assertEqual(text.unique_lines(["나", "가", "나", "다"]), ["나", "가", "다"])
        self.assertEqual(text.unique_lines(["A", "a"], ignore_case=True), ["A"])

    def test_compare_lines(self):
        result = text.compare_lines(["홍길동", "김철수"], ["김철수", "박민수"])
        self.assertEqual(result["공통"], ["김철수"])
        self.assertEqual(result["왼쪽만"], ["홍길동"])
        self.assertEqual(result["오른쪽만"], ["박민수"])

    def test_compare_lines_ignore_case(self):
        result = text.compare_lines(["Kim"], ["kim"], ignore_case=True)
        self.assertEqual(result["공통"], ["Kim"])
        self.assertEqual(result["오른쪽만"], [])

    def test_sort_lines_numeric_puts_text_last(self):
        self.assertEqual(text.sort_lines(["10 개", "2 개", "가나다"], numeric=True),
                         ["2 개", "10 개", "가나다"])
        self.assertEqual(text.sort_lines(["나", "가"]), ["가", "나"])

    def test_extract_named_groups_become_columns(self):
        import re

        lines = ["2026-09-01 INFO 시작", "2026-09-02 ERROR 실패", "쓰레기"]
        pattern = re.compile(r"(?P<날짜>\S+) (?P<레벨>\w+) (?P<메시지>.+)")
        result = text.extract(lines, pattern)

        self.assertEqual(result.headers, ["날짜", "레벨", "메시지"])
        self.assertEqual(result.rows[0], ["2026-09-01", "INFO", "시작"])
        self.assertEqual(result.matched_lines, 2)
        self.assertEqual(result.missed, 1)
        self.assertEqual(result.samples_missed[0], (3, "쓰레기"))

    def test_extract_numbered_groups(self):
        import re

        result = text.extract(["a=1"], re.compile(r"(\w+)=(\d+)"))
        self.assertEqual(result.headers, ["1", "2"])
        self.assertEqual(result.rows, [["a", "1"]])

    def test_extract_without_groups_keeps_whole_match(self):
        import re

        result = text.extract(["가나다", "라마바"], re.compile(r"나."))
        self.assertEqual(result.headers, ["전체"])
        self.assertEqual(result.rows, [["나다"]])

    def test_extract_optional_group_becomes_blank(self):
        import re

        pattern = re.compile(r"(?P<이름>\w+)(?: (?P<값>\d+))?")
        result = text.extract(["가 1", "나"], pattern)
        self.assertEqual(result.rows, [["가", "1"], ["나", ""]])

    def test_diff_preview(self):
        change = text.Change(Path("a.txt"), "a\nb\n", "a\nc\n", "utf-8", 1)
        lines = change.diff()
        self.assertTrue(any(l.startswith("-b") for l in lines))
        self.assertTrue(any(l.startswith("+c") for l in lines))

    def test_diff_units_pairs_similar_lines_as_edit(self):
        r = text.diff_units("첫 문장이다.\n그대로.\n", "첫 문장이었다.\n그대로.\n")
        self.assertEqual(r.same, 1)
        self.assertEqual(r.counts, {"수정": 1, "추가": 0, "삭제": 0})
        self.assertEqual(r.edits[0].old_no, 1)
        self.assertEqual(r.edits[0].new_no, 1)

    def test_diff_units_splits_unlike_pair_into_delete_and_add(self):
        r = text.diff_units("고양이가 담을 넘었다.\n", "회의는 목요일로 미룬다.\n")
        self.assertEqual([e.kind for e in r.edits], ["삭제", "추가"])

    def test_diff_units_similar_threshold_is_adjustable(self):
        old, new = "고양이가 담을 넘었다.\n", "회의는 목요일로 미룬다.\n"
        r = text.diff_units(old, new, similar=0.0)
        self.assertEqual([e.kind for e in r.edits], ["수정"])

    def test_diff_units_ratio_and_totals(self):
        r = text.diff_units("가\n나\n다\n", "가\n나\n")
        self.assertEqual((r.old_total, r.new_total, r.same), (3, 2, 2))
        self.assertAlmostEqual(r.ratio, 0.8)
        self.assertEqual(text.diff_units("", "").ratio, 1.0)

    def test_split_units_sentence_and_para(self):
        doc = "한 문장이다. 두 번째다!\n\n다른 문단."
        self.assertEqual(text.split_units(doc, "sentence"),
                         ["한 문장이다.", "두 번째다!", "다른 문단."])
        self.assertEqual(text.split_units(doc, "para"),
                         ["한 문장이다. 두 번째다!", "다른 문단."])
        with self.assertRaises(text.TextError):
            text.split_units(doc, "글자")

    def test_word_marks_shows_only_changed_words(self):
        marked = text.word_marks("첫 문장이다 그리고 끝", "첫 문장이었다 그리고 진짜 끝")
        self.assertIn("[-문장이다-]", marked)
        self.assertIn("{+문장이었다+}", marked)
        self.assertIn("{+진짜+}", marked)
        self.assertTrue(marked.startswith("첫 "))


class WrapTest(unittest.TestCase):
    LONG = "한국어 문장이 아주 길게 이어지는 경우에 줄을 접어야 읽기 좋다."

    def test_width_counts_hangul_as_two(self):
        self.assertEqual(text.display_width("가나"), 4)
        lines = text.wrap_line(self.LONG, 20)
        self.assertTrue(all(text.display_width(l) <= 20 for l in lines), lines)

    def test_breaks_only_at_spaces(self):
        for line in text.wrap_line(self.LONG, 20):
            self.assertNotIn("  ", line)
            self.assertTrue(line.strip())
        self.assertEqual(" ".join(text.wrap_line(self.LONG, 20)), self.LONG)

    def test_keeps_indent_of_the_first_line(self):
        lines = text.wrap_line("    " + self.LONG, 24)
        self.assertTrue(all(l.startswith("    ") for l in lines), lines)

    def test_code_fence_is_untouched(self):
        body = "```\n" + self.LONG + "\n```\n"
        self.assertEqual(text.wrap_text(body, width=10), body)

    def test_tables_lists_and_quotes_are_untouched(self):
        for line in (f"| {self.LONG} |", f"- {self.LONG}", f"> {self.LONG}",
                     f"# {self.LONG}", f"1. {self.LONG}"):
            self.assertEqual(text.wrap_text(line, width=10), line)

    def test_all_option_wraps_everything_outside_code(self):
        line = f"- {self.LONG}"
        self.assertNotEqual(text.wrap_text(line, width=20, skip_marked=False), line)

    def test_short_lines_and_trailing_newline_stay(self):
        self.assertEqual(text.wrap_text("짧다\n", width=80), "짧다\n")
        self.assertEqual(text.wrap_text("짧다", width=80), "짧다")

    def test_wrapping_is_idempotent(self):
        once = text.wrap_text(self.LONG + "\n", width=20)
        self.assertEqual(text.wrap_text(once, width=20), once)


class RepeatTest(unittest.TestCase):
    DOCS = [("a.md", "같은 설명을 여기서 한 번 한다.\n다른 문장이다.\n"
                     "같은 설명을 여기서 한 번 한다."),
            ("b.md", "같은 설명을 여기서 한 번 한다!\n짧다.\n짧다.")]

    def test_finds_repeats_across_files(self):
        found = text.repeated_sentences(self.DOCS)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].count, 3)
        self.assertEqual([n for n, _ in found[0].places], ["a.md", "a.md", "b.md"])

    def test_punctuation_and_case_do_not_matter(self):
        found = text.repeated_sentences([("a", "충분히 긴 문장을 여기에 쓴다."),
                                         ("b", "충분히  긴 문장을 여기에 쓴다!")])
        self.assertEqual(len(found), 1)

    def test_short_sentences_are_ignored(self):
        self.assertEqual(text.repeated_sentences([("a", "짧다.\n짧다.")]), [])

    def test_same_file_flag(self):
        found = text.repeated_sentences(self.DOCS)
        self.assertFalse(found[0].same_file)
        only_a = text.repeated_sentences([self.DOCS[0]])
        self.assertTrue(only_a[0].same_file)

    def test_code_blocks_and_table_rows_are_skipped(self):
        body = ("```\n같은 코드 줄을 여기 쓴다\n같은 코드 줄을 여기 쓴다\n```\n"
                "| 같은 표의 머리글이다 |\n| 같은 표의 머리글이다 |\n")
        self.assertEqual(text.repeated_sentences([("a.md", body)]), [])

    def test_min_count_can_be_raised(self):
        found = text.repeated_sentences(self.DOCS, min_count=4)
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
