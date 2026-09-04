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


if __name__ == "__main__":
    unittest.main()
