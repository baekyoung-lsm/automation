"""모든 하위 명령의 배선 시험."""

import argparse
import contextlib
import io
import re
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

    def test_spacing_does_not_matter(self):
        # 도움말에는 «글자 수», 사람은 «글자수» 라고 친다
        _, out = self.run_find("글자수")
        self.assertIn("at text count", out)

    def test_common_words_find_the_right_command(self):
        # 사람이 치는 말과 도움말에 적힌 말이 다른 자리들
        for word, command in (("압축", "at file archive"),
                              ("맞춤법", "at text typo"),
                              ("연락처", "at sheet vcard"),
                              ("백업", "at file sync")):
            _, out = self.run_find(word)
            self.assertIn(command, out, word)

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


class KoreanHelpTest(unittest.TestCase):
    """도움말은 한국어다. 규칙을 적어만 두면 언젠가 영어가 섞인다."""

    @staticmethod
    def hangul(text: str) -> bool:
        return bool(re.search(r"[가-힣]", text or ""))

    def walk(self):
        from attools import cli

        for path, help_text, parser in cli.walk_commands(cli.build_parser()):
            if any(isinstance(a, argparse._SubParsersAction)
                   for a in parser._actions):
                continue
            yield path, help_text, parser

    def test_every_command_explains_itself_in_korean(self):
        bad = [" ".join(path) for path, help_text, _p in self.walk()
               if not self.hangul(help_text)]
        self.assertEqual(bad, [], f"한국어 설명이 없는 명령: {bad}")

    def test_option_help_is_korean(self):
        bad = []
        for path, _help, parser in self.walk():
            for action in parser._actions:
                if action.dest in ("help", "version") or action.help is None:
                    continue
                if not self.hangul(action.help):
                    bad.append(f"at {' '.join(path)} "
                               f"{action.option_strings or action.dest}: "
                               f"{action.help}")
        self.assertEqual(bad, [], f"한국어가 아닌 옵션 설명: {bad}")


class DumpTest(unittest.TestCase):
    """긴 결과를 화면에 쏟지 않는지. 관(|)으로 넘길 때는 다 나와야 한다."""

    def run_dump(self, text, tty: bool):
        import io
        from unittest import mock

        from attools.cli import common

        buffer = io.StringIO()
        buffer.isatty = lambda: tty          # StringIO 는 언제나 False 를 준다
        with mock.patch("sys.stdout", buffer):
            common._dump(text, hint="-o 로 저장")
        return buffer.getvalue()

    def test_pipe_gets_everything(self):
        body = "\n".join(f"{i}" for i in range(500))
        self.assertEqual(len(self.run_dump(body, tty=False).splitlines()), 500)

    def test_screen_gets_the_head_and_a_note(self):
        body = "\n".join(f"{i}" for i in range(500))
        shown = self.run_dump(body, tty=True).splitlines()
        self.assertEqual(len(shown), 21)
        self.assertIn("480줄 더", shown[-1])
        self.assertIn("-o 로 저장", shown[-1])

    def test_short_output_is_untouched(self):
        body = "가\n나\n다"
        self.assertEqual(self.run_dump(body, tty=True), "가\n나\n다\n")


class EpilogExampleTest(unittest.TestCase):
    """도움말 아래에 적어 둔 예시가 진짜 되는 명령이어야 한다.

    안내만 그럴듯하고 그대로 쳤을 때 안 되면, 없느니만 못하다.
    """

    def setUp(self):
        from attools import cli

        self.cli = cli

    def parses(self, line: str) -> None:
        import shlex

        parts = shlex.split(line)[1:]         # 맨 앞의 «at» 은 뗀다
        if "--" in parts:                     # main 과 같이 «--» 뒤는 넘긴다
            parts = parts[:parts.index("--")]
        self.cli.build_parser().parse_args(parts)

    def examples(self, parser, path=""):
        out = []
        for raw in (getattr(parser, "epilog", None) or "").splitlines():
            one = raw.strip()
            for head in ("예:", "예)"):
                one = one.removeprefix(head).strip()
            one = one.split("#")[0].strip()
            if one.startswith("at "):
                out.append((path, one))
        for action in parser._actions:
            if isinstance(getattr(action, "choices", None), dict):
                for name, sub in action.choices.items():
                    out += self.examples(sub, f"{path} {name}".strip())
        return out

    def test_every_example_parses(self):
        found = self.examples(self.cli.build_parser())
        self.assertGreater(len(found), 10)    # 예시가 사라지면 이 시험이 조용해진다
        for path, line in found:
            with self.subTest(command=path, example=line):
                self.parses(line)


class HouseRulesTest(unittest.TestCase):
    """저장소 규칙을 시험이 지킨다. 적어만 두면 언젠가 어긋난다."""

    # 정규식을 글자 그대로 적으면 이 파일이 스스로 걸린다. 코드 번호로 적는다.
    EMOJI = re.compile("[\U0001F300-\U0001FAFF\U0001F000-\U0001F2FF]"
                       "|[\u2600-\u27bf]|\ufe0f|[\U0001F1E6-\U0001F1FF]")
    # 고정 표시로 쓰는 기호는 이모지가 아니다 (별표, 화살표).
    ALLOWED = {"\u2605", "\u2606", "\u2610", "\u2611"}

    def sources(self):
        root = Path(__file__).resolve().parents[1]
        return (sorted((root / "attools").rglob("*.py"))
                + sorted((root / "tests").glob("*.py"))
                + [root / "README.md", root / "CLAUDE.md"])

    def test_no_emoji_anywhere(self):
        bad = []
        for path in self.sources():
            for number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1):
                for found in self.EMOJI.finditer(line):
                    if found.group(0) in self.ALLOWED:
                        continue
                    bad.append(f"{path.name}:{number} {found.group(0)!r}")
        self.assertEqual(bad, [], f"이모지가 들어갔습니다: {bad[:5]}")

    def test_writing_commands_have_a_safety_net(self):
        """파일을 내는 명령은 «미리보기(--apply)» 나 «덮어쓰기 막기(--overwrite)»
        둘 중 하나는 있어야 한다. 말없이 덮어쓰면 되돌릴 방법이 없다.
        """
        import argparse

        from attools import cli

        bad = []
        for path, _help, parser in cli.walk_commands(cli.build_parser()):
            if any(isinstance(a, argparse._SubParsersAction)
                   for a in parser._actions):
                continue
            options = {o for a in parser._actions for o in a.option_strings}
            if not ({"-o", "--out"} & options):
                continue
            if not ({"--overwrite", "--apply"} & options):
                bad.append("at " + " ".join(path))
        self.assertEqual(bad, [], f"안전장치가 없는 명령: {bad}")

    def test_readme_lists_each_command_once(self):
        """README 표에 같은 명령이 두 번 들어가면 한쪽만 고치게 된다."""
        from collections import Counter

        readme = Path(__file__).resolve().parents[1] / "README.md"
        names = []
        for line in readme.read_text(encoding="utf-8").splitlines():
            if not line.startswith("| `at "):
                continue
            command = line.split("`")[1].split()
            names.append(" ".join(command[:3] if len(command) > 2
                                  else command[:2]))
        twice = [name for name, count in Counter(names).items() if count > 1]
        self.assertEqual(twice, [], f"표에 두 번 나온 명령: {twice}")

    def test_logic_modules_do_not_print(self):
        """출력은 cli 에서만 한다. 로직이 찍기 시작하면 시험이 지저분해진다."""
        import ast

        root = Path(__file__).resolve().parents[1] / "attools"
        bad = []
        for path in sorted(root.rglob("*.py")):
            if path.relative_to(root).parts[0] == "cli":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "print"):
                    bad.append(f"{path.name}:{node.lineno}")
        self.assertEqual(bad, [], f"로직 모듈에서 print 를 씁니다: {bad}")

    def test_home_is_not_frozen_at_import_time(self):
        """Path.home() 을 모듈 최상단에서 굳히면 시험이 진짜 홈을 건드린다."""
        import ast

        root = Path(__file__).resolve().parents[1] / "attools"
        bad = []
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                for sub in ast.walk(node):
                    if (isinstance(sub, ast.Call)
                            and isinstance(sub.func, ast.Attribute)
                            and sub.func.attr == "home"):
                        bad.append(f"{path.name}:{node.lineno}")
        self.assertEqual(bad, [], f"홈 경로를 굳혔습니다: {bad}")


if __name__ == "__main__":
    unittest.main()
