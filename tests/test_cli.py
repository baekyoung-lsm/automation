"""모든 하위 명령의 배선 시험."""

import argparse
import contextlib
import io
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import text
class CliWiringTest(unittest.TestCase):
    """모든 하위 명령이 제대로 연결돼 있는지 훑는다.

    argparse 배선 실수(위치 인자 순서, 빠진 func, 중복 이름)는 단위 테스트로는
    안 잡히고 실제로 쳐 봐야 드러난다.
    """

    def setUp(self):
        from attools import cli

        self.cli = cli
        self.parser = cli.build_parser()

    def walk(self):
        """(경로, 파서) 를 모두 돌려준다."""
        stack = [((), self.parser)]
        while stack:
            path, parser = stack.pop()
            yield path, parser
            for action in parser._actions:
                if isinstance(action, argparse._SubParsersAction):
                    for name, sub in action.choices.items():
                        stack.append((path + (name,), sub))

    def test_every_leaf_command_has_a_handler(self):
        leaves = [(path, p) for path, p in self.walk()
                  if not any(isinstance(a, argparse._SubParsersAction)
                             for a in p._actions)]
        self.assertGreater(len(leaves), 30)
        for path, parser in leaves:
            with self.subTest(command=" ".join(path)):
                self.assertTrue(callable(parser.get_default("func")),
                                f"at {' '.join(path)} 에 func 이 없습니다")

    def test_help_works_everywhere(self):
        for path, parser in self.walk():
            with self.subTest(command=" ".join(path)):
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit) as cm:
                        parser.parse_args(["--help"])
                self.assertEqual(cm.exception.code, 0)

    def test_no_duplicate_group_names(self):
        groups = [path[0] for path, _ in self.walk() if len(path) == 1]
        self.assertEqual(len(groups), len(set(groups)))

    def test_positional_order_of_two_argument_commands(self):
        # at text replace <찾을것> <바꿀것> [경로...] 처럼 순서가 뒤집히면 안 된다
        parsed = self.parser.parse_args(["text", "replace", "옛것", "새것", "some/dir"])
        self.assertEqual((parsed.find, parsed.replace, parsed.paths),
                         ("옛것", "새것", ["some/dir"]))

    def test_double_dash_tail_goes_to_command(self):
        # at file watch src -- pytest -q 에서 -q 가 watch 옵션으로 먹히면 안 된다
        with contextlib.redirect_stdout(io.StringIO()):
            code = self.cli.main(["file", "watch", "없는디렉터리", "--", "pytest", "-q"])
        self.assertEqual(code, 1)      # 디렉터리가 없어 1, 파싱 자체는 통과

    def test_version_flag(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["--version"])
        self.assertIn("attools", out.getvalue())


class FindCommandTest(unittest.TestCase):
    """at find 가 명령 목록을 실제 파서에서 가져오는지."""

    def setUp(self):
        from attools import cli

        self.cli = cli

    def run_find(self, *args) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = self.cli.main(["find", *args])
        return code, out.getvalue()

    def test_finds_by_help_text(self):
        code, out = self.run_find("중복")
        self.assertEqual(code, 0)
        self.assertIn("at file dupes", out)

    def test_finds_by_command_name(self):
        _, out = self.run_find("unzip")
        self.assertIn("at file unzip", out)

    def test_groups_are_not_listed_as_commands(self):
        _, out = self.run_find("파일")
        self.assertNotIn("at file\n", out)      # 그룹 자체는 실행할 명령이 아니다

    def test_no_match_returns_one(self):
        code, out = self.run_find("없는말123")
        self.assertEqual(code, 1)
        self.assertIn("걸리는 명령이 없습니다", out)

    def test_deep_searches_option_help(self):
        code, _ = self.run_find("--deep", "pre-commit")
        self.assertEqual(code, 0)

    def test_empty_query_asks_for_one(self):
        code, out = self.run_find()
        self.assertEqual(code, 1)
        self.assertIn("찾을 말", out)

    def test_walk_reaches_every_leaf(self):
        leaves = [path for path, _, parser in
                  self.cli.walk_commands(self.cli.build_parser())
                  if not any(isinstance(a, argparse._SubParsersAction)
                             for a in parser._actions)]
        self.assertGreater(len(leaves), 80)


class CompletionTest(unittest.TestCase):
    def setUp(self):
        from attools import cli

        self.cli = cli

    def output(self, *args) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.cli.main(["completion", *args])
        self.assertEqual(code, 0)
        return out.getvalue()

    def test_bash_script_is_valid_shell(self):
        import shutil
        import subprocess
        import tempfile

        script = self.output("bash")
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash 가 없습니다")
        with tempfile.NamedTemporaryFile("w", suffix=".bash", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(script)
            path = fh.name
        done = subprocess.run([bash, "-n", path], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_every_group_appears(self):
        script = self.output("bash")
        for group in ("file", "dev", "git", "life", "sheet", "text", "doc",
                      "json", "keys", "novel"):
            self.assertIn(f"{group})", script)

    def test_new_commands_are_included_automatically(self):
        # 목록을 손으로 적지 않고 파서에서 뽑는지
        script = self.output("bash")
        self.assertIn("conflicts", script)
        self.assertIn("--columns", script)

    def test_leaf_group_completes_its_options(self):
        self.assertIn("--gaps", self.output("bash"))

    def test_zsh_script_mentions_compdef(self):
        self.assertIn("compdef _at_complete at", self.output("zsh"))


class InputErrorTest(unittest.TestCase):
    """파일 하나를 받는 명령에 디렉터리를 주면 한국어로 알려야 한다."""

    def setUp(self):
        from attools import cli

        self.cli = cli

    def test_directory_instead_of_file(self):
        import tempfile

        root = tempfile.mkdtemp()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = self.cli.main(["novel", "check", root])
        self.assertEqual(code, 1)
        self.assertIn("디렉터리입니다", out.getvalue())

    def test_missing_file(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = self.cli.main(["novel", "check", "없는파일.md"])
        self.assertEqual(code, 1)
        self.assertIn("파일이 없습니다", out.getvalue())


class DocLintTest(unittest.TestCase):
    """문서 점검 묶음이 오류와 판단거리를 갈라 놓는지."""

    def setUp(self):
        import shutil
        import tempfile

        from attools import cli

        self.cli = cli
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def run_lint(self, *args) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = self.cli.main(["doc", "lint", *args])
        return code, out.getvalue()

    def test_broken_link_is_an_error(self):
        doc = self.root / "a.md"
        doc.write_text("# 제목\n\n[없는 문서](없는파일.md)\n", encoding="utf-8")
        code, out = self.run_lint(str(doc))
        self.assertEqual(code, 1)
        self.assertIn("깨진 링크", out)

    def test_table_alignment_is_not_an_error(self):
        doc = self.root / "b.md"
        doc.write_text("# 제목\n\n| 가 | 나 |\n|---|---|\n| 가나다 | 1 |\n",
                       encoding="utf-8")
        code, out = self.run_lint(str(doc))
        self.assertEqual(code, 0)          # 판단이 필요한 것은 종료 코드에 넣지 않는다
        self.assertIn("칸이 안 맞는 표", out)

    def test_only_errors_hides_judgement_items(self):
        doc = self.root / "c.md"
        doc.write_text("# 제목\n\n| 가 | 나 |\n|---|---|\n| 가나다 | 1 |\n",
                       encoding="utf-8")
        _, out = self.run_lint(str(doc), "--only-errors")
        self.assertNotIn("칸이 안 맞는 표", out)

    def test_clean_document_passes(self):
        doc = self.root / "d.md"
        doc.write_text("# 제목\n\n## 하나\n\n글.\n", encoding="utf-8")
        code, out = self.run_lint(str(doc))
        self.assertEqual(code, 0)
        self.assertIn("문제가 없습니다", out)


if __name__ == "__main__":
    unittest.main()
