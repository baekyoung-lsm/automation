"""한글 정규화·조사·표기 오류 시험."""

import unicodedata
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import hangul
class HangulTest(unittest.TestCase):
    def test_nfd_detected_and_composed(self):
        decomposed = unicodedata.normalize("NFD", "한글파일.txt")
        self.assertTrue(hangul.is_decomposed(decomposed))
        self.assertFalse(hangul.is_decomposed("한글파일.txt"))
        self.assertEqual(hangul.to_nfc(decomposed), "한글파일.txt")

    def test_sanitize(self):
        self.assertEqual(hangul.sanitize_filename("  제목: 초안<v2>.TXT  "), "제목- 초안-v2.txt")
        self.assertEqual(hangul.sanitize_filename(".bashrc"), ".bashrc")
        self.assertEqual(hangul.sanitize_filename("CON.txt"), "_CON.txt")
        self.assertEqual(hangul.sanitize_filename("a b.md", space="underscore"), "a_b.md")

    def test_josa(self):
        self.assertEqual(hangul.josa("책", "이/가"), "책이")
        self.assertEqual(hangul.josa("노트", "이/가"), "노트가")
        self.assertEqual(hangul.josa("원고", "은/는"), "원고는")

    def test_josa_riul_takes_ro(self):
        self.assertEqual(hangul.josa("서울", "으로/로"), "서울로")
        self.assertEqual(hangul.josa("부산", "으로/로"), "부산으로")
        self.assertEqual(hangul.josa("책", "으로/로"), "책으로")

    def test_josa_reads_trailing_digit_aloud(self):
        self.assertEqual(hangul.josa("2", "을/를"), "2를")     # 이
        self.assertEqual(hangul.josa("3", "을/를"), "3을")     # 삼
        self.assertEqual(hangul.josa("10", "으로/로"), "10으로")

    def test_josa_unknown_word_keeps_first_form(self):
        self.assertEqual(hangul.josa("Kim", "은/는"), "Kim은")


    def test_find_typos_reports_place_and_fix(self):
        found = hangul.find_typos("몇일 전에\n문을 잠궈 놨다.")
        self.assertEqual([(t.line, t.wrong, t.right) for t in found],
                         [(1, "몇일", "며칠"), (2, "잠궈", "잠가")])
        self.assertEqual(found[0].column, 1)
        self.assertEqual(found[1].column, 4)

    def test_riul_kke_only_after_riul_batchim(self):
        found = hangul.find_typos("금방 갈께. 선생님께 드렸다.")
        self.assertEqual([t.wrong for t in found], ["갈께"])

    def test_typo_rules_skip_words_with_other_meanings(self):
        # '찌게'(살이 찌게), '일부로'(일부로 나뉘다)는 규칙에 넣지 않았다
        self.assertEqual(hangul.find_typos("살이 찌게 두면 일부로 나뉜다."), [])

    def test_narrowed_rules_still_catch_real_typos(self):
        self.assertEqual(hangul.fix_typos("김치찌게에 베게를 뒀다")[0],
                         "김치찌개에 베개를 뒀다")

    def test_fix_typos_counts_and_keeps_rest(self):
        body, count = hangul.fix_typos("역활이 됬다. 그대로 둘 말.")
        self.assertEqual(body, "역할이 됐다. 그대로 둘 말.")
        self.assertEqual(count, 2)

    def test_fix_typos_leaves_clean_text_alone(self):
        self.assertEqual(hangul.fix_typos("며칠 전에 문을 잠갔다."),
                         ("며칠 전에 문을 잠갔다.", 0))


if __name__ == "__main__":
    unittest.main()
