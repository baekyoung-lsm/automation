"""git 정리·검사·통계 시험."""

import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import files, gitkit, names, text, todo


class GitkitTest(unittest.TestCase):
    def test_detects_real_secrets(self):
        text = (
            'gh = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"\n'      # attools: ignore
            'db = "postgres://app:s3cret@db:5432/app"\n'              # attools: ignore
            'password = "Real!Pass99"\n')                             # attools: ignore
        kinds = {f.kind for f in gitkit.scan_text(text, "a.py")}
        self.assertEqual(kinds, {"GitHub 토큰", "접속 문자열 비밀번호", "하드코딩된 비밀값"})

    def test_ignores_placeholders(self):
        text = ('API_KEY = "your-key-here"\n'
                'SECRET = "${VAULT_SECRET}"\n'
                'TOKEN = "changeme"\n'
                'PW = os.environ["DB_PASSWORD"]\n')
        self.assertEqual(gitkit.scan_text(text, "a.py"), [])

    def test_ignore_marker(self):
        text = 'password = "Real!Pass99"  # attools: ignore\n'  # noqa: secret
        self.assertEqual(gitkit.scan_text(text, "a.py"), [])

    def test_entropy(self):
        low = gitkit.shannon_entropy("aaaaaaaaaaaaaaaaaaaaaaaa")
        high = gitkit.shannon_entropy("kJ8sQ2mZ4vX9pL1nR7tB3wY6")
        self.assertLess(low, 1.0)
        self.assertGreater(high, 4.0)


class GitStatsTest(unittest.TestCase):
    def setUp(self):
        import subprocess

        self.root = Path(tempfile.mkdtemp())
        self.run = lambda *args: subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True)
        self.run("init", "-q")
        self.run("config", "user.email", "t@e.c")
        self.run("config", "user.name", "테스터")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def commit(self, name, content, message, author="테스터"):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        self.run("add", "-A")
        self.run("-c", f"user.name={author}", "commit", "-q", "-m", message)

    def test_read_log_collects_numstat(self):
        self.commit("a.py", "one\ntwo\n", "첫 커밋")
        self.commit("a.py", "one\ntwo\nthree\n", "줄 추가")

        commits = gitkit.read_log(self.root)
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[0].subject, "줄 추가")
        self.assertEqual(commits[0].files["a.py"], (1, 0))
        self.assertEqual(commits[0].added, 1)

    def test_churn_ranks_frequently_touched_files(self):
        self.commit("hot.py", "1\n", "a")
        self.commit("hot.py", "1\n2\n", "b")
        self.commit("cold.py", "1\n", "c")

        churn = gitkit.churn_by_file(gitkit.read_log(self.root))
        self.assertEqual(churn[0].path, "hot.py")
        self.assertEqual(churn[0].commits, 2)
        self.assertEqual(churn[0].authors, {"테스터"})

    def test_by_author(self):
        self.commit("a.py", "1\n", "a", author="가")
        self.commit("a.py", "1\n2\n", "b", author="나")
        self.commit("a.py", "1\n2\n3\n", "c", author="나")

        rows = gitkit.by_author(gitkit.read_log(self.root))
        self.assertEqual(rows[0][0], "나")
        self.assertEqual(rows[0][1], 2)

    def test_by_period_and_weekday(self):
        self.commit("a.py", "1\n", "a")
        commits = gitkit.read_log(self.root)

        self.assertEqual(sum(n for _, n in gitkit.by_period(commits, unit="day")), 1)
        self.assertEqual(len(gitkit.by_weekday(commits)), 7)
        self.assertEqual(sum(n for _, n in gitkit.by_weekday(commits)), 1)
        with self.assertRaises(ValueError):
            gitkit.by_period(commits, unit="분기")

    def test_collect_changes_parses_conventional_prefixes(self):
        self.commit("a.py", "1\n", "feat(api): 검색 추가")
        self.commit("a.py", "1\n2\n", "fix: 널 참조 고침")
        self.commit("a.py", "1\n2\n3\n", "feat!: 응답 형식 변경")

        changes = gitkit.collect_changes(self.root)
        self.assertEqual([c.kind for c in changes], ["feat", "fix", "feat"])
        self.assertEqual(changes[2].scope, "api")
        self.assertEqual(changes[2].title, "검색 추가")
        self.assertTrue(changes[0].breaking)

    def test_collect_changes_keeps_custom_prefix(self):
        self.commit("a.py", "1\n", "attools: 새 명령 추가")
        change = gitkit.collect_changes(self.root)[0]
        self.assertEqual(change.kind, "attools")
        self.assertEqual(change.title, "새 명령 추가")

    def test_changes_without_prefix_group_by_directory(self):
        self.commit("src/deep/a.py", "1\n", "접두사 없는 커밋")
        changes = gitkit.collect_changes(self.root)
        self.assertEqual(changes[0].kind, "")
        groups = gitkit.group_changes(changes)
        self.assertEqual(list(groups), ["src"])

    def test_group_changes_orders_conventional_first(self):
        self.commit("a.py", "1\n", "chore: 정리")
        self.commit("a.py", "1\n2\n", "feat: 기능")
        self.commit("a.py", "1\n2\n3\n", "fix: 버그")
        groups = gitkit.group_changes(gitkit.collect_changes(self.root))
        self.assertEqual(list(groups), ["새 기능", "고침", "잡일"])

    def test_render_changelog(self):
        self.commit("a.py", "1\n", "feat: 기능 하나")
        self.commit("a.py", "1\n2\n", "fix!: 깨지는 변경")
        text = gitkit.render_changelog(
            gitkit.group_changes(gitkit.collect_changes(self.root)),
            title="1.0.0", link_prefix="https://x/commit/")
        self.assertIn("## 1.0.0", text)
        self.assertIn("### 새 기능", text)
        self.assertIn("**[호환성 주의]**", text)
        self.assertIn("https://x/commit/", text)

    def test_since_tag_limits_range(self):
        self.commit("a.py", "1\n", "첫 커밋")
        self.run("tag", "v0.1")
        self.commit("a.py", "1\n2\n", "태그 뒤 커밋")

        self.assertEqual(gitkit.latest_tag(self.root), "v0.1")
        changes = gitkit.collect_changes(self.root, since="v0.1")
        self.assertEqual([c.title for c in changes], ["태그 뒤 커밋"])

    def test_latest_tag_without_tags(self):
        self.commit("a.py", "1\n", "커밋")
        self.assertEqual(gitkit.latest_tag(self.root), "")

    def test_top_directory(self):
        self.assertEqual(gitkit.top_directory(["src/a.py", "src/b.py"]), "src")
        self.assertEqual(gitkit.top_directory(["src/a.py", "docs/b.md"]), "여러 곳")
        self.assertEqual(gitkit.top_directory([]), "기타")

    def test_list_branches_reports_age_and_tracking(self):
        self.commit("a.py", "1\n", "첫 커밋")
        self.run("branch", "기능/새것")
        branches = gitkit.list_branches(self.root)

        names = {b.name for b in branches}
        self.assertIn("기능/새것", names)
        current = [b for b in branches if b.current]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].author, "테스터")
        self.assertEqual(current[0].subject, "첫 커밋")
        self.assertEqual(current[0].age_days, 0)
        self.assertEqual(current[0].upstream, "")   # 원격 없음

    def test_list_branches_sorted_by_recency(self):
        self.commit("a.py", "1\n", "커밋")
        self.run("branch", "오래된것")
        self.commit("a.py", "1\n2\n", "나중 커밋")
        branches = gitkit.list_branches(self.root)
        self.assertTrue(branches[0].when >= branches[-1].when)

    def test_list_branches_on_empty_repo(self):
        self.assertEqual(gitkit.list_branches(self.root), [])

    def test_tracked_count_distinguishes_empty_index(self):
        self.assertEqual(gitkit.tracked_count(self.root), 0)   # 저장소지만 add 전
        self.commit("a.py", "1\n", "첫 커밋")
        self.assertEqual(gitkit.tracked_count(self.root), 1)

    def test_tracked_count_outside_repo(self):
        outside = Path(tempfile.mkdtemp())
        try:
            self.assertEqual(gitkit.tracked_count(outside), -1)
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_korean_filenames_are_not_escaped(self):
        # git 은 기본으로 비ASCII 파일명을 8진수로 이스케이프한다. 꺼야 한다.
        self.commit("한글 파일.py", "# TODO 한글 주석\n", "한글 파일 추가")

        names = [n for n in gitkit.run(["ls-files"], self.root).splitlines() if n]
        self.assertEqual(names, ["한글 파일.py"])

        found = todo.collect(self.root)
        self.assertEqual([t.path for t in found], ["한글 파일.py"])

    def test_read_log_on_empty_repo(self):
        with self.assertRaises(RuntimeError):
            gitkit.read_log(self.root)


class TodoTest(unittest.TestCase):
    def test_finds_markers_in_comments(self):
        src = ("# TODO(홍길동): 캐시 붙이기\n"
               "    pass  # FIXME 예외 처리 없음\n"
               "// XXX: 임시\n"
               " * HACK - 나중에 지울 것\n"
               "- TODO: 마크다운 목록\n")
        found = todo.scan_text(src, "a.py")
        self.assertEqual([t.marker for t in found],
                         ["TODO", "FIXME", "XXX", "HACK", "TODO"])
        self.assertEqual(found[0].owner, "홍길동")
        self.assertEqual(found[0].text, "캐시 붙이기")

    def test_ignores_markers_inside_strings(self):
        src = ('_p("TODO 가 없습니다")\n'
               'help="-m FIXME -m BUG"\n'
               'x = "TODOLIST"\n'
               'name = TODOS\n')
        self.assertEqual(todo.scan_text(src, "a.py"), [])

    def test_owner_forms(self):
        found = todo.scan_text("# TODO @kim 로그 정리\n# TODO\n", "a.py")
        self.assertEqual(found[0].owner, "kim")
        self.assertEqual(found[0].text, "로그 정리")
        self.assertEqual(found[1].text, "(내용 없음)")

    def test_marker_filter(self):
        src = "# TODO 하나\n# FIXME 둘\n"
        self.assertEqual([t.marker for t in todo.scan_text(src, "a.py", markers=["FIXME"])],
                         ["FIXME"])

    def test_sort_by_severity_and_age(self):
        from datetime import datetime, timedelta

        old = todo.Todo("a.py", 1, "TODO", "오래됨", when=datetime.now() - timedelta(days=400))
        new = todo.Todo("b.py", 1, "BUG", "새것", when=datetime.now())
        self.assertEqual([t.marker for t in todo.sort_todos([new, old], "age")],
                         ["TODO", "BUG"])
        self.assertEqual([t.marker for t in todo.sort_todos([old, new], "severity")],
                         ["BUG", "TODO"])
        with self.assertRaises(ValueError):
            todo.sort_todos([], "없는정렬")

    def test_summarize_orders_by_severity(self):
        items = [todo.Todo("a", 1, "TODO", "x"), todo.Todo("a", 2, "BUG", "y"),
                 todo.Todo("a", 3, "TODO", "z")]
        self.assertEqual(list(todo.summarize(items)), ["BUG", "TODO"])

    def test_parse_blame_output(self):
        blob = ("a" * 40 + " 1 3 1\n"
                "author 홍길동\n"
                "author-time 1700000000\n"
                "\t# TODO 무언가\n")
        parsed = todo._parse_blame(blob)
        self.assertEqual(parsed[3][0], "홍길동")


class ConflictTest(unittest.TestCase):
    TEXT = ("보통 줄\n"
            "<<<<<<< HEAD\n우리 것 1\n우리 것 2\n"
            "=======\n저쪽 것\n"
            ">>>>>>> feature\n"
            "끝\n"
            "<<<<<<< HEAD\n=======\n새로 들어온 줄\n>>>>>>> other\n")

    def test_finds_each_conflict_with_side_sizes(self):
        found = gitkit.find_conflicts(self.TEXT, "a.py")
        self.assertEqual([(c.line, c.ours, c.theirs) for c in found],
                         [(2, 2, 1), (9, 0, 1)])
        self.assertEqual(found[0].label_ours, "HEAD")
        self.assertEqual(found[0].label_theirs, "feature")

    def test_one_sided_conflict_is_marked(self):
        found = gitkit.find_conflicts(self.TEXT)
        self.assertFalse(found[0].one_sided)
        self.assertTrue(found[1].one_sided)      # 지운 쪽과 남긴 쪽의 다툼

    def test_diff3_base_section_is_not_counted(self):
        text = ("<<<<<<< HEAD\n우리\n"
                "||||||| 공통 조상\n원래\n원래2\n"
                "=======\n저쪽\n>>>>>>> other\n")
        c = gitkit.find_conflicts(text)[0]
        self.assertEqual((c.ours, c.theirs), (1, 1))

    def test_plain_text_has_no_conflicts(self):
        self.assertEqual(gitkit.find_conflicts("보통 글\n===\n제목\n"), [])

    def test_unclosed_marker_is_not_reported(self):
        # 끝 표시가 없으면 충돌로 세지 않는다. 문서 안의 예시일 수 있다.
        self.assertEqual(gitkit.find_conflicts("<<<<<<< HEAD\n우리\n"), [])


class ReadyTest(unittest.TestCase):
    def test_debug_marks_only_flag_real_leftovers(self):
        added = {"a.js": ["console.log(x)", "const y = 1", "debugger;"],
                 "b.py": ["breakpoint()", "print('보통 코드')"],
                 "c.go": ['fmt.Println("이건 코드다")']}
        found = gitkit.find_debug_marks(added)
        self.assertEqual({(m.path, m.kind) for m in found},
                         {("a.js", "console.log"), ("a.js", "debugger"),
                          ("b.py", "breakpoint()")})

    def test_focused_and_skipped_tests_are_caught(self):
        found = gitkit.find_debug_marks({"t.js": ['it.only("하나", () => {})',
                                                  'describe.skip("건너뜀", fn)']})
        self.assertEqual(len(found), 2)

    def test_ignore_mark_silences_a_line(self):
        found = gitkit.find_debug_marks(
            {"a.js": ["console.log(1)  // attools:ignore"]})
        self.assertEqual(found, [])

    def test_staged_added_lines_parses_diff_paths(self):
        import subprocess
        import tempfile

        root = Path(tempfile.mkdtemp())
        try:
            def git(*args):
                subprocess.run(["git", "-C", str(root), *args], check=True,
                               capture_output=True)

            git("init", "-q")
            (root / "a.js").write_text("const x = 1;\n", encoding="utf-8")
            git("add", ".")
            git("-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "시작")
            (root / "a.js").write_text("const x = 1;\nconsole.log(x);\n",
                                       encoding="utf-8")
            git("add", ".")
            added = gitkit.staged_added_lines(root)
            self.assertEqual(added, {"a.js": ["console.log(x);"]})
            self.assertEqual(len(gitkit.find_debug_marks(added)), 1)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
