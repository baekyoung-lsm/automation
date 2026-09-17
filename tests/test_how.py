"""«이럴 땐 이렇게»(at how) 시험.

여기서 제일 중요한 것은 «적어 둔 명령이 진짜로 되는가» 다. 안내만
그럴듯하고 안 되는 명령이면 없느니만 못하다.
"""

from __future__ import annotations

import contextlib
import io
import shlex
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import cli, recipes


class RecipeDataTest(unittest.TestCase):
    def test_every_command_really_parses(self):
        """진짜 파서에 걸어 본다. 옵션 이름이 하나만 틀려도 여기서 걸린다."""
        parser = cli.build_parser()
        for line in recipes.commands():
            parts = shlex.split(line)
            self.assertEqual(parts[0], "at", line)
            with contextlib.redirect_stderr(io.StringIO()):
                try:
                    parser.parse_args(parts[1:])
                except SystemExit:
                    self.fail(f"되지 않는 명령입니다: {line}")

    def test_every_recipe_has_a_title_and_a_step(self):
        for one in recipes.RECIPES:
            self.assertTrue(one.title.strip(), one)
            self.assertTrue(one.steps, one.title)

    def test_every_recipe_sits_in_a_known_topic(self):
        self.assertEqual({one.topic for one in recipes.RECIPES} - set(recipes.TOPICS),
                         set())

    def test_no_two_recipes_have_the_same_title(self):
        titles = [one.title for one in recipes.RECIPES]
        self.assertEqual(len(titles), len(set(titles)))

    def test_every_topic_has_recipes(self):
        for topic in recipes.topics():
            self.assertTrue(recipes.by_topic(topic), topic)

    def test_search_looks_at_titles_commands_and_other_words(self):
        self.assertTrue(recipes.search("개인정보"))        # 딴 이름
        self.assertTrue(recipes.search("pdfjoin"))         # 명령
        self.assertTrue(recipes.search("합치기"))          # 제목
        self.assertEqual(recipes.search("없는말입니다"), [])

    def test_search_ignores_spacing(self):
        self.assertTrue(recipes.search("주민 번호"))

    def test_topics_are_case_insensitive(self):
        self.assertTrue(recipes.by_topic("pdf"))
        self.assertTrue(recipes.by_topic("PDF"))


class HowCommandTest(unittest.TestCase):
    def run_cli(self, *args, expect: int = 0) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(list(args))
        self.assertEqual(code, expect, out.getvalue())
        return out.getvalue()

    def test_bare_how_lists_the_topics(self):
        got = self.run_cli("how")
        for topic in recipes.topics():
            self.assertIn(topic, got)
        self.assertIn("at how 취합", got)

    def test_a_topic_shows_every_recipe_in_it(self):
        got = self.run_cli("how", "취합")
        for one in recipes.by_topic("취합"):
            self.assertIn(one.title, got)
        self.assertNotIn("가지 더", got)       # 주제는 잘라 보이지 않는다

    def test_a_word_searches(self):
        got = self.run_cli("how", "개인정보")
        self.assertIn("at text privacy", got)

    def test_an_unknown_word_says_what_to_try(self):
        got = self.run_cli("how", "없는말입니다", expect=1)
        self.assertIn("at find", got)
        self.assertIn("취합", got)             # 주제 목록을 알려 준다

    def test_all_shows_everything(self):
        got = self.run_cli("how", "--all")
        self.assertNotIn("가지 더", got)
        for one in recipes.RECIPES:
            self.assertIn(one.title, got)

    def test_limit_cuts_the_search(self):
        got = self.run_cli("how", "표", "--limit", "2")
        self.assertIn("가지 더", got)


if __name__ == "__main__":
    unittest.main()
