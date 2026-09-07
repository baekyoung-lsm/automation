"""줄 수 세기 시험 - 코드·주석·빈 줄 가르기."""

import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools.code import loc


class CountTextTest(unittest.TestCase):
    def test_line_comments_and_blanks(self):
        body = "# 주석\n\nx = 1\n"
        self.assertEqual(loc.count_text(body, ("#",), ()), (1, 1, 1))

    def test_trailing_comment_is_still_code(self):
        # 코드 뒤에 붙은 주석까지 주석으로 세면 코드 줄이 사라진다
        body = "x = 1  # 설명\n"
        self.assertEqual(loc.count_text(body, ("#",), ()), (1, 0, 0))

    def test_block_comment_spans_lines(self):
        body = "/* 여는\n   이어짐 */\nconst a = 1;\n"
        self.assertEqual(loc.count_text(body, ("//",), (("/*", "*/"),)),
                         (1, 2, 0))

    def test_block_opened_and_closed_on_one_line(self):
        body = "/* 한 줄 */\nconst a = 1;\n"
        self.assertEqual(loc.count_text(body, ("//",), (("/*", "*/"),)),
                         (1, 1, 0))

    def test_block_marker_after_code_does_not_open_a_comment(self):
        body = "const a = 1; /* 뒤 */\nconst b = 2;\n"
        self.assertEqual(loc.count_text(body, ("//",), (("/*", "*/"),)),
                         (2, 0, 0))

    def test_python_docstring_counts_as_comment(self):
        body = 'def f():\n    """설명\n    이어짐\n    """\n    return 1\n'
        self.assertEqual(loc.count_text(body, ("#",), (('"""', '"""'),)),
                         (2, 3, 0))

    def test_multiline_string_value_counts_as_code(self):
        # x = """... 는 주석이 아니다. 여는 기호로 시작하는 줄만 주석으로 센다
        body = 'x = """값\n이어짐"""\n'
        self.assertEqual(loc.count_text(body, ("#",), (('"""', '"""'),)),
                         (2, 0, 0))

    def test_language_without_block_rules(self):
        body = "/* 셸에는 블록 주석이 없다 */\necho hi\n"
        self.assertEqual(loc.count_text(body, ("#",), ()), (2, 0, 0))


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, name, body):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def test_groups_by_language(self):
        self.make("가.py", "# 설명\nx = 1\n")
        self.make("나.py", "y = 2\n\n")
        self.make("다.js", "// 설명\nconst a = 1;\n")
        report = loc.scan([self.root])
        names = {l.language: l for l in report.languages}
        self.assertEqual(names["파이썬"].files, 2)
        self.assertEqual(names["파이썬"].code, 2)
        self.assertEqual(names["파이썬"].comment, 1)
        self.assertEqual(names["자바스크립트"].code, 1)
        self.assertEqual(report.code, 3)

    def test_unknown_suffix_does_not_guess_comments(self):
        self.make("메모.xyz", "# 이게 주석인지 알 수 없다\n값\n")
        report = loc.scan([self.root])
        lang = report.languages[0]
        self.assertFalse(lang.known)
        self.assertEqual(lang.comment, 0)
        self.assertEqual(lang.code, 2)      # 모르면 코드로 센다

    def test_json_has_no_comments_and_that_is_known(self):
        self.make("자료.json", '{\n  "가": 1\n}\n')
        lang = loc.scan([self.root]).languages[0]
        self.assertTrue(lang.known)         # «주석이 없다» 와 «모른다» 는 다르다
        self.assertEqual(lang.comment, 0)

    def test_skips_build_folders(self):
        self.make("node_modules/큰것.js", "const a = 1;\n")
        self.make("가.py", "x = 1\n")
        report = loc.scan([self.root])
        self.assertEqual([l.language for l in report.languages], ["파이썬"])

    def test_missing_path_is_reported(self):
        report = loc.scan([self.root / "없음"])
        self.assertEqual(len(report.skipped), 1)
        self.assertEqual(report.languages, [])

    def test_glob_narrows_the_scan(self):
        self.make("가.py", "x = 1\n")
        self.make("나.js", "const a = 1;\n")
        report = loc.scan([self.root], glob="*.py")
        self.assertEqual([l.language for l in report.languages], ["파이썬"])

    def test_files_are_sorted_by_code(self):
        self.make("작은.py", "x = 1\n")
        self.make("큰.py", "x = 1\ny = 2\nz = 3\n")
        report = loc.scan([self.root])
        self.assertEqual(Path(report.files[0].path).name, "큰.py")

    def test_single_file_path_works(self):
        path = self.make("하나.py", "# 설명\nx = 1\n")
        report = loc.scan([path])
        self.assertEqual(report.languages[0].files, 1)


if __name__ == "__main__":
    unittest.main()
