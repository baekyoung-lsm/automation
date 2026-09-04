import argparse
import contextlib
import io
import shutil
import tempfile
import unicodedata
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import (devkit, files, gitkit, hangul, jsonkit, keyhtml, keys, life,
                     logkit, manuscript, mdkit, names, sheet, text, todo, xlsx)
from attools.schedule import Cron, CronError


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


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, name, content="x"):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_organize_roundtrip(self):
        self.make("보고서.pdf")
        self.make("사진.jpg")
        self.make("메모")
        moves = files.plan_organize(self.root)
        self.assertEqual(len(moves), 3)
        self.assertTrue(all(Path(m.src).exists() for m in moves))  # 계획만으로는 안 옮긴다

        journal = files.apply_moves(moves)
        self.assertTrue((self.root / "문서" / "보고서.pdf").exists())
        self.assertTrue((self.root / "기타" / "메모").exists())

        restored, errors = files.undo(journal)
        self.assertEqual((restored, errors), (3, []))
        self.assertTrue((self.root / "보고서.pdf").exists())

    def test_organize_skips_already_sorted(self):
        self.make("문서/이미 정리됨.pdf")
        self.assertEqual(files.plan_organize(self.root, recursive=True), [])

    def test_name_collision_gets_suffix(self):
        self.make("문서/보고서.pdf", "먼저")
        self.make("보고서.pdf", "나중")
        files.apply_moves(files.plan_organize(self.root))
        self.assertTrue((self.root / "문서" / "보고서 (1).pdf").exists())
        self.assertEqual((self.root / "문서" / "보고서.pdf").read_text(encoding="utf-8"), "먼저")

    def test_archive_selects_by_age_and_glob(self):
        import os
        import time

        old = self.make("logs/old.log")
        self.make("logs/new.log")
        self.make("keep.txt")
        os.utime(old, (time.time() - 400 * 86400,) * 2)

        picked = files.plan_archive(self.root, glob=["*.log"], older_days=365)
        self.assertEqual([p.name for p in picked], ["old.log"])

    def test_archive_packs_and_removes_after_verifying(self):
        self.make("a.log", "내용" * 500)
        self.make("sub/b.log", "내용" * 500)
        targets = files.plan_archive(self.root, glob=["*.log"])

        result = files.make_archive(self.root, targets, self.root / "보관.zip",
                                    remove=True)
        self.assertEqual(len(result.stored), 2)
        self.assertEqual(len(result.removed), 2)
        self.assertEqual(result.failed, [])
        self.assertFalse((self.root / "a.log").exists())
        self.assertTrue((self.root / "보관.zip").exists())
        self.assertLess(result.packed_size, result.raw_size)

    def test_archive_keeps_originals_without_remove(self):
        self.make("a.log")
        targets = files.plan_archive(self.root, glob=["*.log"])
        result = files.make_archive(self.root, targets, self.root / "z.zip")
        self.assertEqual(result.removed, [])
        self.assertTrue((self.root / "a.log").exists())

    def test_archive_refuses_to_overwrite(self):
        self.make("a.log")
        targets = files.plan_archive(self.root, glob=["*.log"])
        files.make_archive(self.root, targets, self.root / "z.zip")
        with self.assertRaises(RuntimeError):
            files.make_archive(self.root, targets, self.root / "z.zip")

    def test_archive_preserves_relative_paths(self):
        import zipfile

        self.make("sub/deep/c.log")
        targets = files.plan_archive(self.root, glob=["*.log"])
        files.make_archive(self.root, targets, self.root / "z.zip")
        with zipfile.ZipFile(self.root / "z.zip") as z:
            self.assertEqual(z.namelist(), ["sub/deep/c.log"])

    def test_tree_structure_and_counts(self):
        self.make("src/a.py", "1\n2\n3\n")
        self.make("src/deep/b.py", "1\n")
        self.make("README.md", "x")

        tree = files.build_tree(self.root, use_git=False, with_lines=True)
        self.assertEqual(tree.file_count, 3)
        names = [c.name for c in tree.children]
        self.assertEqual(names, ["src", "README.md"])   # 디렉터리가 먼저
        self.assertEqual(tree.total_lines, 4)

    def test_tree_depth_folds(self):
        self.make("a/b/c/d.py", "1\n")
        tree = files.build_tree(self.root, use_git=False, depth=2)
        rows = files.render_tree(tree)
        self.assertEqual(len(rows), 3)          # 루트 + a/ + b/

    def test_tree_respects_gitignore(self):
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=self.root, capture_output=True)
        self.make(".gitignore", "무시할것/\n*.log\n")
        self.make("보일것.py", "1\n")
        self.make("무시할것/숨김.py", "1\n")
        self.make("app.log", "x")

        tracked = files.tracked_paths(self.root)
        self.assertIsNotNone(tracked)
        names = {p.name for p in tracked}
        self.assertIn("보일것.py", names)
        self.assertNotIn("숨김.py", names)
        self.assertNotIn("app.log", names)

    def test_tracked_paths_outside_git(self):
        self.assertIsNone(files.tracked_paths(self.root))

    def test_count_lines_skips_binary(self):
        text = self.make("a.py", "1\n2\n")
        binary = self.root / "b.bin"
        binary.write_bytes(b"\x00\x01\x02")
        self.assertEqual(files.count_lines(text), 2)
        self.assertIsNone(files.count_lines(binary))

    def test_render_tree_uses_box_drawing(self):
        self.make("a.py", "1\n")
        self.make("b.py", "1\n")
        rows = files.render_tree(files.build_tree(self.root, use_git=False))
        self.assertTrue(rows[1].startswith("├─ "))
        self.assertTrue(rows[2].startswith("└─ "))

    def test_language_summary(self):
        self.make("a.py", "1\n2\n")
        self.make("b.py", "1\n")
        self.make("c.md", "x")
        summary = files.language_summary(
            files.build_tree(self.root, use_git=False, with_lines=True))
        self.assertEqual(summary[0], (".py", 2, 3))

    def test_dir_diff_finds_all_three_kinds(self):
        self.make("a/same.txt", "같음")
        self.make("b/same.txt", "같음")
        self.make("a/only-left.txt", "x")
        self.make("b/only-right.txt", "y")
        self.make("a/sub/changed.txt", "AAA")
        self.make("b/sub/changed.txt", "BBB")     # 크기는 같고 내용만 다르다

        d = files.diff_dirs(self.root / "a", self.root / "b")
        self.assertEqual(d.only_left, ["only-left.txt"])
        self.assertEqual(d.only_right, ["only-right.txt"])
        self.assertEqual([n for n, _, _ in d.changed], ["sub/changed.txt"])
        self.assertEqual(d.same, 1)
        self.assertFalse(d.empty)

    def test_dir_diff_quick_misses_same_size_changes(self):
        self.make("a/x.txt", "AAA")
        self.make("b/x.txt", "BBB")
        quick = files.diff_dirs(self.root / "a", self.root / "b", quick=True)
        self.assertEqual(quick.changed, [])       # 크기만 보면 같아 보인다
        self.assertEqual(quick.same, 1)

    def test_dir_diff_identical(self):
        self.make("a/x.txt", "같음")
        self.make("b/x.txt", "같음")
        self.assertTrue(files.diff_dirs(self.root / "a", self.root / "b").empty)

    def test_dir_diff_glob_filter(self):
        self.make("a/x.py", "1")
        self.make("a/x.txt", "1")
        d = files.diff_dirs(self.root / "a", self.root / "b", glob=["*.py"])
        self.assertEqual(d.only_left, ["x.py"])

    def test_duplicates(self):
        self.make("a.txt", "같은 내용" * 100)
        self.make("sub/b.txt", "같은 내용" * 100)
        self.make("c.txt", "다른 내용" * 100)
        groups = files.find_duplicates(self.root, min_size=1)
        self.assertEqual(len(groups), 1)
        self.assertEqual({p.name for p in groups[0]}, {"a.txt", "b.txt"})

    def test_rename_template_fields(self):
        self.make("b.txt")
        self.make("a.txt")
        moves = files.plan_rename(self.root, "{seq:03d}-{stem}{ext}")
        self.assertEqual([Path(m.dst).name for m in moves],
                         ["001-a.txt", "002-b.txt"])   # 기본은 이름 순

    def test_rename_sorts_by_date(self):
        import os
        import time

        old = self.make("z.txt")
        new = self.make("a.txt")
        os.utime(old, (time.time() - 9999, time.time() - 9999))
        moves = files.plan_rename(self.root, "{seq}{ext}", sort="date")
        self.assertEqual(Path(moves[0].src).name, "z.txt")

    def test_rename_unknown_field_raises(self):
        self.make("a.txt")
        with self.assertRaises(ValueError) as cm:
            files.plan_rename(self.root, "{없는것}")
        self.assertIn("쓸 수 있는 것", str(cm.exception))

    def test_rename_replacements_and_case(self):
        self.make("보고서 최종(수정).TXT")
        moves = files.plan_rename(self.root, "{name}",
                                  replacements=[("최종(수정)", "v2")])
        self.assertEqual(Path(moves[0].dst).name, "보고서 v2.txt")

    def test_rename_regex_replacement(self):
        self.make("IMG_0021.jpg")
        moves = files.plan_rename(self.root, "{name}", regex=True,
                                  replacements=[(r"IMG_0*(\d+)", r"사진\1")])
        self.assertEqual(Path(moves[0].dst).name, "사진21.jpg")

    def test_rename_glob_filter(self):
        self.make("a.jpg")
        self.make("b.txt")
        moves = files.plan_rename(self.root, "x-{name}", glob=["*.jpg"])
        self.assertEqual([Path(m.src).name for m in moves], ["a.jpg"])

    def test_rename_avoids_collisions(self):
        self.make("a.txt")
        self.make("b.txt")
        moves = files.plan_rename(self.root, "같은이름.txt")
        self.assertEqual(sorted(Path(m.dst).name for m in moves),
                         ["같은이름 (1).txt", "같은이름.txt"])

    def test_fixname_plan(self):
        self.make(unicodedata.normalize("NFD", "한글.txt"))
        moves = files.plan_fixname(self.root)
        self.assertEqual([Path(m.dst).name for m in moves], ["한글.txt"])


class DevkitTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_env_diff(self):
        (self.root / ".env.example").write_text(
            'DB_HOST=localhost\nAPI_KEY=your-key-here\nDEBUG=true\n', encoding="utf-8")
        (self.root / ".env").write_text(
            'DB_HOST="127.0.0.1"\nAPI_KEY=your-key-here\nDEBUG=\nEXTRA=1\n', encoding="utf-8")
        d = devkit.env_diff(self.root / ".env.example", self.root / ".env")
        self.assertEqual(d.missing, [])
        self.assertEqual(d.empty, ["DEBUG"])
        self.assertEqual(d.placeholder, ["API_KEY"])
        self.assertEqual(d.extra, ["EXTRA"])
        self.assertFalse(d.ok)

    def test_parse_env_quotes_and_comments(self):
        (self.root / ".env").write_text(
            "export A='1' # 주석\nB=\"두 단어\"\n# 통째 주석\nC=3\n", encoding="utf-8")
        self.assertEqual(devkit.parse_env(self.root / ".env"),
                         {"A": "1", "B": "두 단어", "C": "3"})

    def test_build_example_never_leaks_secrets(self):
        (self.root / ".env").write_text(
            "DB_HOST=10.0.0.5\nDB_PASSWORD=s3cr3t!\nAPI_KEY=sk_live_x\n"
            "DB_PORT=5432\nDEBUG=true\n", encoding="utf-8")

        text, added = devkit.build_example(self.root / ".env")
        self.assertNotIn("s3cr3t", text)
        self.assertNotIn("sk_live", text)
        self.assertIn("DB_PASSWORD=<db_password>", text)
        self.assertIn("DB_PORT=5432", text)      # 숫자·불리언은 그대로 둔다
        self.assertIn("DEBUG=true", text)
        self.assertEqual(len(added), 5)

    def test_build_example_keeps_comments_and_marks_removed(self):
        (self.root / ".env").write_text("A=1\nNEW=x\n", encoding="utf-8")
        (self.root / ".env.example").write_text(
            "# 주석\nA=<a>\nOLD=<old>\n", encoding="utf-8")

        text, added = devkit.build_example(self.root / ".env",
                                           existing=self.root / ".env.example")
        self.assertIn("# 주석", text)
        self.assertIn("# (지워진 키) OLD=<old>", text)
        self.assertIn("NEW=<new>", text)
        self.assertEqual(added, ["NEW"])

    def test_build_example_keep_values_still_hides_secrets(self):
        (self.root / ".env").write_text("URL=https://a.b\nTOKEN=abcdef\n",
                                        encoding="utf-8")
        text, _ = devkit.build_example(self.root / ".env", keep_values=True)
        self.assertIn("URL=https://a.b", text)
        self.assertNotIn("abcdef", text)

    def test_time_roundtrip(self):
        dt = devkit.parse_when("1700000000")
        self.assertEqual(devkit.when_report(dt)["epoch"], "1700000000")
        self.assertEqual(devkit.parse_when("1700000000000"), dt)

    def test_jwt(self):
        import base64
        import json
        import time

        def seg(obj):
            return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

        token = f"{seg({'alg': 'HS256'})}.{seg({'exp': int(time.time()) - 10})}.sig"
        info = devkit.decode_jwt(token)
        self.assertTrue(info["expired"])
        self.assertTrue(info["signed"])

    def test_bench_statistics(self):
        r = devkit.BenchResult("x", times=[0.10, 0.20, 0.30, 0.40])
        self.assertEqual(r.runs, 4)
        self.assertAlmostEqual(r.mean, 0.25)
        self.assertAlmostEqual(r.median, 0.25)
        self.assertAlmostEqual(r.fastest, 0.10)
        self.assertAlmostEqual(r.slowest, 0.40)
        self.assertGreater(r.stdev, 0)

    def test_bench_empty_and_single(self):
        self.assertEqual(devkit.BenchResult("x").mean, 0.0)
        self.assertEqual(devkit.BenchResult("x").median, 0.0)
        self.assertEqual(devkit.BenchResult("x", times=[0.5]).stdev, 0.0)
        self.assertEqual(devkit.BenchResult("x", times=[1, 2, 3]).median, 2)

    def test_bench_runs_and_skips_warmup(self):
        r = devkit.run_bench(["python3", "-c", "pass"], runs=3, warmup=1)
        self.assertEqual(r.runs, 3)          # 예열은 결과에 넣지 않는다
        self.assertEqual(r.failures, 0)
        self.assertTrue(all(t > 0 for t in r.times))

    def test_bench_counts_failures(self):
        r = devkit.run_bench(["python3", "-c", "raise SystemExit(1)"],
                             runs=2, warmup=0)
        self.assertEqual(r.failures, 2)

    def test_format_seconds(self):
        self.assertEqual(devkit.format_seconds(0.0123), "12.3ms")
        self.assertEqual(devkit.format_seconds(2.5), "2.50초")
        self.assertTrue(devkit.format_seconds(75).startswith("1분"))

    def test_mask(self):
        text = "주민 900101-1234567 폰 010-1234-5678 pw=hunter22 메일 hong@ex.com"  # attools: ignore
        masked, counts = devkit.mask_text(text)
        self.assertNotIn("1234567", masked)
        self.assertNotIn("hunter22", masked)
        self.assertIn("010-****-5678", masked)
        self.assertEqual(counts["주민등록번호"], 1)


class ManuscriptTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_stats_excludes_heading(self):
        p = self.root / "1화.txt"
        p.write_text("# 제목\n\n가나다 라마바.\n", encoding="utf-8")
        s = manuscript.analyze(p)
        self.assertEqual(s.chars_no_space, 7)   # 가나다라마바.
        self.assertEqual(s.sentences, 1)

    def test_dialogue_ratio(self):
        s = manuscript.analyze(Path("x.txt"), '"안녕" 그가 말했다.')
        self.assertGreater(s.dialogue_ratio, 0)

    def test_inspect_runs(self):
        f = manuscript.inspect("그는 갔다. 그는 왔다. 그는 섰다.", run_threshold=3)
        self.assertEqual(f.start_runs, [("그는", 3, 1)])

    def test_inspect_cliche_and_long(self):
        f = manuscript.inspect("그는 미소를 지었다. " + "가" * 150 + ".", long_limit=100)
        self.assertIn(("미소를 지었다", 1), f.cliches)
        self.assertEqual(len(f.long_sentences), 1)

    def test_split_scenes_by_breaks_and_headings(self):
        text = ("# 1화\n\n" + "가" * 60 + "\n\n***\n\n" + "나" * 60 + "\n\n"
                "## 2화\n\n" + "다" * 60 + "\n")
        scenes = manuscript.split_scenes(text, min_chars=10)
        self.assertEqual(len(scenes), 3)
        self.assertEqual([s.title for s in scenes], ["1화", "", "2화"])
        self.assertEqual(scenes[0].number, 1)

    def test_split_scenes_drops_short_fragments(self):
        text = "짧음\n\n***\n\n" + "가" * 60
        scenes = manuscript.split_scenes(text, min_chars=30)
        self.assertEqual(len(scenes), 1)

    def test_split_scenes_on_blank_run(self):
        text = "가" * 40 + "\n\n\n\n" + "나" * 40
        self.assertEqual(len(manuscript.split_scenes(text, min_chars=10)), 2)

    def test_scene_metrics(self):
        scene = manuscript.Scene(1, "", 1, '리안이 웃었다.\n"안녕." 카일이 답했다.')
        self.assertEqual(scene.opening, "리안이 웃었다.")
        self.assertGreater(scene.dialogue_ratio, 0)
        # 공백만 뺀 글자 수라 따옴표도 센다
        self.assertEqual(scene.chars, len('리안이웃었다."안녕."카일이답했다.'))

    def test_tag_people_orders_by_frequency(self):
        scenes = [manuscript.Scene(1, "", 1, "리안 리안 카일")]
        manuscript.tag_people(scenes, ["카일", "리안", "세드릭"])
        self.assertEqual(scenes[0].people, ["리안", "카일"])

    def test_find_mentions_with_context(self):
        import re

        text = ("리안은 상자를 열었다. 안에는 붉은 열쇠가 있었다. 그는 넣었다.\n"
                "다른 이야기였다. 붉은 열쇠는 잊혔다.\n")
        found = manuscript.find_mentions(text, re.compile("붉은 열쇠"), path="1화.txt")
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0].hit, "안에는 붉은 열쇠가 있었다.")
        self.assertIn("리안은 상자를 열었다.", found[0].before)
        self.assertIn("그는 넣었다.", found[0].after)
        self.assertIn("**붉은 열쇠", found[0].context().replace("안에는 ", ""))

    def test_find_mentions_tags_scene_number(self):
        import re

        text = ("# 1화\n\n" + "가" * 60 + " 열쇠가 있었다.\n\n***\n\n"
                + "나" * 60 + " 열쇠를 꺼냈다.\n")
        scenes = manuscript.split_scenes(text, min_chars=10)
        found = manuscript.find_mentions(text, re.compile("열쇠"), scenes=scenes)
        self.assertEqual([m.scene for m in found], [1, 2])

    def test_find_mentions_none(self):
        import re

        self.assertEqual(manuscript.find_mentions("아무것도 없다.", re.compile("열쇠")), [])

    def test_strip_headings_keeps_scene_breaks(self):
        text = "# 1화\n\n본문\n\n***\n\n다음\n"
        stripped = manuscript.strip_headings(text)
        self.assertNotIn("1화", stripped)
        self.assertIn("***", stripped)          # 장면 구분선은 남아야 한다
        self.assertEqual(text.count("\n"), stripped.count("\n"))   # 행 번호 유지

        self.assertNotIn("***", manuscript.strip_markup(text))

    def test_find_context_skips_separator_lines(self):
        import re

        text = "***\n열쇠가 있었다.\n***\n"
        found = manuscript.find_mentions(text, re.compile("열쇠"))
        self.assertEqual(found[0].before, "")
        self.assertEqual(found[0].after, "")

    def test_time_marks_extract_kinds(self):
        text = "2026년 3월 5일 아침, 봄이었다. 사흘 뒤 오후 3시에 다시 왔다."
        kinds = {m.kind for m in manuscript.find_time_marks(text)}
        self.assertEqual(kinds, {"날짜", "시간대", "계절", "기간", "시각"})

    def test_time_marks_prefer_longest_overlap(self):
        marks = manuscript.find_time_marks("2026년 3월 5일에 만났다.")
        self.assertEqual([m.text for m in marks if m.kind == "날짜"], ["2026년 3월 5일"])

    def test_time_conflict_within_one_scene(self):
        text = ("# 1화\n\n" + "가" * 50 + " 아침이었다. " + "나" * 50 + " 한밤중이었다.\n"
                "\n***\n\n" + "다" * 50 + " 저녁이었다.\n")
        scenes = manuscript.split_scenes(text, min_chars=10)
        marks = manuscript.find_time_marks(manuscript.strip_headings(text), scenes=scenes)
        conflicts = manuscript.time_conflicts(marks)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].scene, 1)
        self.assertEqual(sorted(conflicts[0].values), ["밤", "아침"])

    def test_no_conflict_across_scenes(self):
        text = ("아침이었다. " + "가" * 60 + "\n\n***\n\n한밤중이었다. " + "나" * 60 + "\n")
        scenes = manuscript.split_scenes(text, min_chars=10)
        marks = manuscript.find_time_marks(text, scenes=scenes)
        self.assertEqual(manuscript.time_conflicts(marks), [])

    def test_style_metrics(self):
        text = '짧다. 이것은 조금 더 긴 문장이다. "대사." 그가 말했다.'
        st = manuscript.style_metrics(text, "1화")
        self.assertEqual(st.name, "1화")
        self.assertEqual(st.sentences, 4)
        self.assertGreater(st.avg_sentence, 0)
        self.assertGreater(st.dialogue_ratio, 0)
        self.assertGreater(st.vocabulary, 0)
        self.assertLessEqual(st.vocabulary, 1)

    def test_style_metrics_empty(self):
        st = manuscript.style_metrics("", "빈것")
        self.assertEqual(st.sentences, 0)
        self.assertEqual(st.avg_sentence, 0.0)

    def test_style_long_ratio(self):
        text = "짧다. " + "가" * 100 + "."
        st = manuscript.style_metrics(text, long_limit=50)
        self.assertAlmostEqual(st.long_ratio, 0.5)

    def test_style_outliers_needs_three(self):
        rows = [manuscript.style_metrics("가나다. 라마바.", f"{i}") for i in range(2)]
        self.assertEqual(manuscript.style_outliers(rows), {})

    def test_style_outliers_flags_the_odd_one(self):
        rows = []
        for i in range(5):
            body = ("그는 걸었다. " * 10 if i != 2
                    else "그는 오래도록 걸었고 그 길은 끝없이 이어졌으며 결국 아무 데도 "
                         "닿지 못했다. " * 10)
            rows.append(manuscript.style_metrics(body, f"{i}화"))
        found = manuscript.style_outliers(rows)
        self.assertIn("2화", found)
        self.assertTrue(any("평균 문장 길이" in r for r in found["2화"]))

    def test_normalize_body_one_line_one_paragraph(self):
        text = "# 1화\n\n첫 줄이다.\n둘째 줄이다.\n\n***\n\n다음 문단.\n"
        body = manuscript.normalize_body(text)
        self.assertNotIn("1화", body)                    # 제목은 뺀다
        self.assertEqual(body.split("\n\n"),
                         ["첫 줄이다.", "둘째 줄이다.", "***", "다음 문단."])

    def test_normalize_body_join_and_indent(self):
        text = "접힌 문단의\n뒷부분이다.\n"
        joined = manuscript.normalize_body(text, join_lines=True)
        self.assertEqual(joined, "접힌 문단의 뒷부분이다.")

        indented = manuscript.normalize_body(text, indent=True)
        self.assertTrue(indented.startswith("\u3000"))

    def test_normalize_body_scene_mark(self):
        body = manuscript.normalize_body("가.\n\n***\n\n나.\n", scene_mark="＊")
        self.assertIn("＊", body)
        self.assertNotIn("***", body)

    def test_chapter_title_prefers_heading(self):
        self.assertEqual(manuscript.chapter_title(Path("01.txt"), "# 1화 겨울\n\n본문"),
                         "1화 겨울")
        self.assertEqual(manuscript.chapter_title(Path("01화.txt"), "제목 없는 본문"),
                         "01화")

    def test_export_html_structure(self):
        html = manuscript.export_html([("1화", "가.\n\n***\n\n나.")],
                                      title="제목", author="필명", note="메모")
        self.assertIn("<h2 id=\"장1\">1화</h2>", html)
        self.assertIn("<p>가.</p>", html)
        self.assertIn('class="break"', html)
        self.assertIn("제목", html)
        self.assertNotIn("text-indent", html)

    def test_export_html_indent_uses_css(self):
        html = manuscript.export_html([("1화", "가.")], indent=True)
        self.assertIn("text-indent", html)

    def test_export_html_escapes(self):
        html = manuscript.export_html([("<script>", "a & b")])
        self.assertNotIn("<script>", html.split("<style>")[0] + html.split("</style>")[1])
        self.assertIn("a &amp; b", html)

    def test_export_text_formats(self):
        plain = manuscript.export_text([("1화", "본문")], title="제목")
        self.assertIn("[ 1화 ]", plain)

        markdown = manuscript.export_text([("1화", "본문")], title="제목", markdown=True)
        self.assertIn("# 제목", markdown)
        self.assertIn("## 1화", markdown)

    def test_snapshot_growth(self):
        (self.root / "1화.txt").write_text("가나다", encoding="utf-8")
        manuscript.snapshot(self.root, note="초고")
        (self.root / "1화.txt").write_text("가나다라마", encoding="utf-8")
        manuscript.snapshot(self.root, note="퇴고")
        snaps = manuscript.list_snapshots(self.root)
        self.assertEqual([s["total"] for s in snaps], [3, 5])
        self.assertEqual(snaps[0]["note"], "초고")


class CronTest(unittest.TestCase):
    def runs(self, expr, start, n=3):
        from datetime import datetime
        return [d.strftime("%Y-%m-%d %H:%M") for d in Cron(expr).next_runs(start, n)]

    def test_weekday_schedule(self):
        from datetime import datetime
        self.assertEqual(
            self.runs("0 9 * * 1-5", datetime(2026, 9, 4, 10, 0), 3),
            ["2026-09-07 09:00", "2026-09-08 09:00", "2026-09-09 09:00"])

    def test_step_and_macro(self):
        from datetime import datetime
        self.assertEqual(self.runs("*/15 * * * *", datetime(2026, 1, 1, 0, 1), 2),
                         ["2026-01-01 00:15", "2026-01-01 00:30"])
        self.assertEqual(self.runs("@monthly", datetime(2026, 1, 5, 0, 0), 1),
                         ["2026-02-01 00:00"])

    def test_dom_or_dow(self):
        # 일/요일이 둘 다 지정되면 cron 은 OR 로 본다
        from datetime import datetime
        got = self.runs("0 0 13 * 5", datetime(2026, 3, 1, 0, 0), 3)
        self.assertEqual(got, ["2026-03-06 00:00", "2026-03-13 00:00", "2026-03-20 00:00"])

    def test_named_month_and_dow(self):
        from datetime import datetime
        self.assertEqual(self.runs("0 0 * JAN MON", datetime(2025, 12, 1), 1),
                         ["2026-01-05 00:00"])

    def test_invalid(self):
        for bad in ("0 9 * *", "99 * * * *", "0 9 * * 9", "*/0 * * * *"):
            with self.assertRaises(CronError):
                Cron(bad)


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


class LifeTest(unittest.TestCase):
    def test_parse_amount(self):
        self.assertEqual(life.parse_amount("3억5000만"), 350_000_000)
        self.assertEqual(life.parse_amount("1.5억"), 150_000_000)
        self.assertEqual(life.parse_amount("350,000,000원"), 350_000_000)
        with self.assertRaises(ValueError):
            life.parse_amount("삼억")

    def test_dday_and_age(self):
        from datetime import date
        d = life.DDay(date(2024, 3, 15), date(2024, 6, 22))
        self.assertEqual(d.delta, -99)
        self.assertEqual(d.nth_day, 100)          # 당일을 1일로 세면 100일째
        self.assertEqual(life.korean_age(date(1995, 12, 1), date(2026, 9, 3)), 30)
        self.assertEqual(life.korean_age(date(1995, 9, 3), date(2026, 9, 3)), 31)

    def test_settle_balances_to_zero(self):
        share, balance, transfers = life.settle({"A": 45000, "B": 12000}, extra=["C"])
        self.assertEqual(share, 19000)
        self.assertEqual(sum(balance.values()), 0)
        self.assertEqual(sum(t.amount for t in transfers), 26000)  # A가 받을 돈
        self.assertEqual(len(transfers), 2)
        self.assertTrue(all(t.payee == "A" for t in transfers))

    def test_amortize_pays_off(self):
        rows = life.amortize(100_000_000, 5.0, 120)
        self.assertEqual(len(rows), 120)
        self.assertAlmostEqual(rows[-1].balance, 0.0, places=6)
        self.assertAlmostEqual(sum(r.principal for r in rows), 100_000_000, places=2)
        self.assertAlmostEqual(rows[0].payment, rows[50].payment, places=2)

    def test_amortize_grace(self):
        rows = life.amortize(100_000_000, 6.0, 12, grace=3)
        self.assertEqual([r.principal for r in rows[:3]], [0.0, 0.0, 0.0])
        self.assertAlmostEqual(rows[-1].balance, 0.0, places=6)

    def test_solar_holidays_and_substitutes(self):
        from datetime import date

        table = life.solar_holidays(2026)
        # 2026년: 삼일절(일)·광복절(토)·개천절(토)이 주말과 겹쳐 대체공휴일이 붙는다
        self.assertEqual(table[date(2026, 3, 2)], "삼일절 대체공휴일")
        self.assertEqual(table[date(2026, 8, 17)], "광복절 대체공휴일")
        self.assertEqual(table[date(2026, 10, 5)], "개천절 대체공휴일")
        # 현충일은 토요일이어도 대체공휴일이 없다
        self.assertEqual(table[date(2026, 6, 6)], "현충일")
        self.assertNotIn(date(2026, 6, 8), table)

    def test_count_and_add_workdays(self):
        from datetime import date

        holidays = life.solar_holidays(2026)
        # 2026-08-14(금) + 5영업일: 17일은 광복절 대체공휴일이라 건너뛴다
        self.assertEqual(life.add_workdays(date(2026, 8, 14), 5, holidays),
                         date(2026, 8, 24))
        self.assertEqual(life.add_workdays(date(2026, 8, 14), 0, holidays),
                         date(2026, 8, 14))
        self.assertEqual(life.count_workdays(date(2026, 3, 1), date(2026, 3, 31),
                                             holidays), 21)

    def test_add_workdays_backwards(self):
        from datetime import date

        holidays = life.solar_holidays(2026)
        self.assertEqual(life.add_workdays(date(2026, 8, 18), -1, holidays),
                         date(2026, 8, 14))   # 17일이 대체공휴일이라 금요일로

    def test_is_workday(self):
        from datetime import date

        holidays = life.solar_holidays(2026)
        self.assertFalse(life.is_workday(date(2026, 8, 15), holidays))  # 광복절(토)
        self.assertFalse(life.is_workday(date(2026, 8, 16), holidays))  # 일요일
        self.assertTrue(life.is_workday(date(2026, 8, 18), holidays))

    def test_user_holidays_merge_and_warning(self):
        from datetime import date

        root = Path(tempfile.mkdtemp())
        try:
            path = root / "holidays.txt"
            path.write_text("# 주석\n2026-02-17 설날\n2026-09-25 추석\n"
                            "2026-05-24 부처님오신날\n엉터리줄\n", encoding="utf-8")
            extra = life.load_user_holidays(path)
            self.assertEqual(extra[date(2026, 2, 17)], "설날")
            self.assertEqual(len(extra), 3)

            merged = life.holidays_for(2026, extra)
            self.assertIn(date(2026, 2, 17), merged)
            self.assertEqual(life.missing_lunar_warning(merged, [2026]), [])

            # 음력 명절이 없으면 반드시 경고한다
            self.assertTrue(life.missing_lunar_warning(life.solar_holidays(2026), [2026]))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_unit_convert(self):
        group, value, unit, results = life.convert("84㎡")
        self.assertEqual(group, "넓이")
        self.assertAlmostEqual(dict(results)["평"], 25.41, places=2)
        self.assertAlmostEqual(dict(life.convert("30평")[3])["㎡"], 99.17, places=2)
        self.assertAlmostEqual(dict(life.convert("100F")[3])["℃"], 37.78, places=2)
        with self.assertRaises(ValueError):
            life.convert("5광년")


class WatchTest(unittest.TestCase):
    def test_mtime_diff(self):
        root = Path(tempfile.mkdtemp())
        try:
            (root / "a.py").write_text("1", encoding="utf-8")
            before = files.snapshot_mtimes(root, ["*.py"])
            (root / "b.py").write_text("2", encoding="utf-8")
            after = files.snapshot_mtimes(root, ["*.py"])
            self.assertEqual([Path(c).name for c in files.diff_mtimes(before, after)], ["b.py"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class XlsxTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_roundtrip_preserves_types(self):
        from datetime import date, datetime

        path = self.root / "x.xlsx"
        rows = [["이름", "입사일", "시각", "연봉", "재직"],
                ["홍길동", date(2021, 3, 2), datetime(2023, 7, 15, 9, 30), 52000000, True],
                ["김 철수", None, None, 47500000.5, False]]
        xlsx.write_sheets(path, {"직원": rows})

        self.assertEqual(xlsx.sheet_names(path), ["직원"])
        got = xlsx.read_sheet(path)
        self.assertEqual(got[0], rows[0])
        self.assertEqual(got[1], rows[1])
        self.assertEqual(got[2], rows[2])

    def test_multiple_sheets_and_name_sanitizing(self):
        path = self.root / "x.xlsx"
        xlsx.write_sheets(path, {"1분기[초안]": [["a", 1]], "2분기": [["b", 2]]})
        self.assertEqual(xlsx.sheet_names(path), ["1분기_초안_", "2분기"])
        self.assertEqual(xlsx.read_sheet(path, "2분기"), [["b", 2]])
        with self.assertRaises(xlsx.XlsxError):
            xlsx.read_sheet(path, "3분기")

    def test_column_helpers(self):
        self.assertEqual(xlsx.col_to_index("A1"), 0)
        self.assertEqual(xlsx.col_to_index("AB7"), 27)
        self.assertEqual(xlsx.index_to_col(0), "A")
        self.assertEqual(xlsx.index_to_col(27), "AB")

    def test_escapes_xml_and_control_chars(self):
        path = self.root / "x.xlsx"
        xlsx.write_sheets(path, {"s": [["a & b <c>", "탭\t유지"]]})
        self.assertEqual(xlsx.read_sheet(path)[0][0], "a & b <c>")


class SheetTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def csv(self, name, text, encoding="utf-8"):
        p = self.root / name
        p.write_bytes(text.encode(encoding))
        return p

    def test_parse_number_korean_formats(self):
        self.assertEqual(sheet.parse_number("1,234원"), 1234)
        self.assertEqual(sheet.parse_number("(1,234)"), -1234)
        self.assertEqual(sheet.parse_number("12.5%"), 0.125)
        self.assertIsNone(sheet.parse_number("06234"))          # 우편번호는 그대로
        self.assertIsNone(sheet.parse_number("1234567890123456789"))
        self.assertIsNone(sheet.parse_number("abc"))

    def test_parse_date_formats(self):
        from datetime import date

        for text in ("2024-01-05", "2024.01.05", "2024/1/5", "20240105"):
            self.assertEqual(sheet.parse_date(text), date(2024, 1, 5), text)
        self.assertIsNone(sheet.parse_date("2024-13-05"))
        self.assertIsNone(sheet.parse_date("010-1234-5678"))

    def test_load_cp949_and_parse(self):
        from datetime import date

        p = self.csv("a.csv", "사번,이름,입사일,연봉\nE001, 홍길동 ,2021-03-02,\"52,000,000\"\n",
                     encoding="cp949")
        t = sheet.load(p)
        self.assertEqual(t.headers, ["사번", "이름", "입사일", "연봉"])
        self.assertEqual(t.rows[0][2], date(2021, 3, 2))
        self.assertEqual(t.rows[0][3], 52000000)

    def test_duplicate_headers_get_suffix(self):
        p = self.csv("a.csv", "값,값,\n1,2,3\n")
        self.assertEqual(sheet.load(p).headers, ["값", "값_2", "열3"])

    def test_clean_removes_noise(self):
        p = self.csv("a.csv", "이름,메모,빈열\n 홍길동 ,,\n김　철수,x,\n김　철수,x,\n,,\n")
        t = sheet.load(p)
        cleaned, rep = sheet.clean(t, drop_duplicates=True)
        self.assertEqual(cleaned.headers, ["이름", "메모"])
        self.assertEqual([r[0] for r in cleaned.rows], ["홍길동", "김 철수"])
        self.assertEqual(rep.duplicate_rows, 1)
        self.assertEqual(rep.dropped_cols, ["빈열"])

    def test_validate_finds_duplicate_key(self):
        p = self.csv("a.csv", "사번,이름\nE1,가\nE1,나\n,다\n")
        issues = sheet.validate(sheet.load(p), key="사번")
        kinds = {i.kind for i in issues}
        self.assertIn("중복 키", kinds)
        self.assertIn("키 결측", kinds)

    def test_validate_flags_text_numbers(self):
        # 숫자가 문자로 저장돼 있으면 엑셀에서 정렬·합계가 틀어진다
        p = self.csv("a.csv", "금액\n100\n200\n")
        t = sheet.load(p, raw=True)
        self.assertTrue(any(i.kind == "문자로 저장된 숫자/날짜" for i in sheet.validate(t)))

    def test_merge_aligns_columns(self):
        a = self.csv("a.csv", "사번,이름\nE1,가\n")
        b = self.csv("b.csv", "사번,부서\nE2,개발\n")
        merged, warnings = sheet.merge([sheet.load(a), sheet.load(b)])
        self.assertEqual(merged.headers, ["출처", "사번", "이름", "부서"])
        self.assertEqual(merged.rows[0], ["a", "E1", "가", None])
        self.assertEqual(merged.rows[1], ["b", "E2", None, "개발"])
        self.assertTrue(warnings)

    def test_diff_by_key(self):
        a = self.csv("a.csv", "사번,연봉,부서\nE1,100,영업\nE2,200,개발\n")
        b = self.csv("b.csv", "사번,연봉,부서\nE1,150,영업\nE3,300,인사\n")
        d = sheet.diff(sheet.load(a), sheet.load(b), "사번")
        self.assertEqual([r[0] for r in d.added], ["E3"])
        self.assertEqual([r[0] for r in d.removed], ["E2"])
        self.assertEqual(d.changed, [("E1", "연봉", 100, 150)])

    def test_pivot_sum_and_cross(self):
        p = self.csv("a.csv", "부서,분기,금액\n영업,1Q,100\n영업,2Q,50\n개발,1Q,300\n")
        t = sheet.load(p)
        flat = sheet.pivot(t, rows=["부서"], values="금액", agg="sum")
        self.assertEqual(flat.rows, [["개발", 300], ["영업", 150]])

        cross = sheet.pivot(t, rows=["부서"], cols="분기", values="금액", agg="sum")
        self.assertEqual(cross.headers, ["부서", "1Q", "2Q", "합계"])
        self.assertEqual(cross.rows, [["개발", 300, None, 300], ["영업", 100, 50, 150]])

    def table(self):
        return sheet.Table(
            ["사번", "이름", "부서", "연봉"],
            [["E1", "홍길동", "영업", 52000000],
             ["E2", "김철수", "개발", 47000000],
             ["E3", "이영희", "개발", 61000000],
             ["E4", "최수진", "영업", None]])

    def test_cut_picks_and_orders_columns(self):
        result = sheet.cut(self.table(), ["연봉", "이름"])
        self.assertEqual(result.headers, ["연봉", "이름"])
        self.assertEqual(result.rows[0], [52000000, "홍길동"])
        with self.assertRaises(sheet.SheetError):
            sheet.cut(self.table(), ["없는열"])

    def test_cut_drop_mode(self):
        result = sheet.cut(self.table(), ["사번", "부서"], drop=True)
        self.assertEqual(result.headers, ["이름", "연봉"])

    def test_where_and_or(self):
        t = self.table()
        eq = [sheet.Condition("부서", "eq", "개발")]
        self.assertEqual(len(sheet.where(t, eq).rows), 2)

        both = eq + [sheet.Condition("연봉", "gte", "5000만")]
        self.assertEqual([r[1] for r in sheet.where(t, both).rows], ["이영희"])
        self.assertEqual(len(sheet.where(t, both, any_match=True).rows), 3)

    def test_where_compares_numbers_as_numbers(self):
        t = self.table()
        rows = sheet.where(t, [sheet.Condition("연봉", "gt", "50,000,000")]).rows
        self.assertEqual({r[1] for r in rows}, {"홍길동", "이영희"})

    def test_where_has_is_case_insensitive_substring(self):
        rows = sheet.where(self.table(), [sheet.Condition("이름", "has", "영")]).rows
        self.assertEqual([r[1] for r in rows], ["이영희"])

    def test_condition_parse_requires_equals(self):
        self.assertEqual(sheet.Condition.parse("eq", "부서=영업").value, "영업")
        with self.assertRaises(sheet.SheetError):
            sheet.Condition.parse("eq", "부서")

    def test_sort_puts_blanks_last(self):
        result = sheet.sort_rows(self.table(), ["연봉"])
        self.assertEqual([r[1] for r in result.rows],
                         ["김철수", "홍길동", "이영희", "최수진"])
        desc = sheet.sort_rows(self.table(), ["연봉"], descending=True)
        self.assertEqual(desc.rows[0][1], "최수진")   # 내림차순이면 빈 칸이 먼저

    def test_sample_is_reproducible_with_seed(self):
        t = self.table()
        a = sheet.sample(t, 2, seed=7)
        b = sheet.sample(t, 2, seed=7)
        self.assertEqual(a.rows, b.rows)
        self.assertEqual(sheet.sample(t, 2, head=True).rows, t.rows[:2])
        self.assertEqual(len(sheet.sample(t, 99).rows), 4)

    def test_split_rows_and_by_column(self):
        t = self.table()
        parts = sheet.split_rows(t, 3)
        self.assertEqual([len(p.rows) for p in parts], [3, 1])
        with self.assertRaises(sheet.SheetError):
            sheet.split_rows(t, 0)

        groups = sheet.split_by(t, "부서")
        self.assertEqual(sorted(groups), ["개발", "영업"])
        self.assertEqual(len(groups["개발"].rows), 2)
        self.assertEqual(groups["개발"].sheet, "개발")

    def test_split_by_labels_blank_values(self):
        t = sheet.Table(["a", "b"], [["", 1], [None, 2]])
        self.assertEqual(list(sheet.split_by(t, "a")), ["(빈칸)"])

    def test_placeholders_and_render(self):
        tpl = "{이름} 님 {부서} {번호:03d} {{그대로}} {없는열}"
        self.assertEqual(sheet.placeholders(tpl), ["이름", "부서", "번호", "없는열"])

        missing = set()
        out = sheet.render(tpl, {"이름": "홍길동", "부서": "영업", "번호": 7},
                           missing=missing)
        self.assertEqual(out, "홍길동 님 영업 007 {그대로} ")
        self.assertEqual(missing, {"없는열"})

    def test_render_falls_back_on_bad_format_spec(self):
        self.assertEqual(sheet.render("{이름:03d}", {"이름": "홍길동"}), "홍길동")

    def test_fill_makes_one_result_per_row(self):
        t = sheet.Table(["사번", "이름"], [["E1", "홍길동"], ["E2", "김철수"]])
        results, missing = sheet.fill(t, "{이름}({사번})",
                                      name_template="{번호:03d}-{사번}.txt")
        self.assertEqual(missing, set())
        self.assertEqual([r.text for r in results], ["홍길동(E1)", "김철수(E2)"])
        self.assertEqual([r.name for r in results], ["001-E1.txt", "002-E2.txt"])

    def test_fill_reports_missing_columns(self):
        t = sheet.Table(["이름"], [["홍길동"]])
        _, missing = sheet.fill(t, "{이름} {연차}")
        self.assertEqual(missing, {"연차"})

    def test_save_csv_has_bom_for_excel(self):
        p = self.csv("a.csv", "이름\n홍길동\n")
        out = sheet.save(sheet.load(p), self.root / "out.csv")
        self.assertTrue(out.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_save_xlsx_roundtrip(self):
        p = self.csv("a.csv", "이름,입사일\n홍길동,2021-03-02\n")
        out = sheet.save(sheet.load(p), self.root / "out.xlsx", sheet_name="직원")
        back = sheet.load(out)
        self.assertEqual(back.sheet, "직원")
        self.assertEqual(back.rows[0][0], "홍길동")

    def test_unsupported_format(self):
        p = self.root / "a.pdf"
        p.write_bytes(b"%PDF")
        with self.assertRaises(sheet.SheetError):
            sheet.load(p)


class KeysTest(unittest.TestCase):
    def setUp(self):
        self.groups, self.sources = keys.load_groups()
        self.state = keys.State()
        self.doc = keys.find_group(self.groups, "doc")

    def test_data_is_well_formed(self):
        self.assertTrue(self.groups)
        ids = [g.id for g in self.groups]
        self.assertEqual(len(ids), len(set(ids)))
        for g in self.groups:
            self.assertTrue(g.apps, g.id)
            names = [i.name for i in g.items]
            self.assertEqual(len(names), len(set(names)), f"{g.id} 항목 이름 중복")
            for item in g.items:
                self.assertTrue(item.cat, item.name)
                # 키 딕셔너리는 선언된 앱 id 만 쓴다
                self.assertLessEqual(set(item.keys), set(g.app_ids), item.name)
                self.assertTrue(any(item.keys.values()), f"{item.name}: 단축키가 하나도 없음")

    def test_three_cell_states(self):
        item = keys.Item("테스트", "편집", 3,
                         {"hwp": "Ctrl+K", "word": keys.NO_SHORTCUT, "gdocs": None},
                         group="doc")
        self.assertEqual(item.status("hwp"), "key")
        self.assertEqual(item.status("word"), "none")
        self.assertEqual(item.status("gdocs"), "unknown")
        self.assertEqual(item.status("없는앱"), "unknown")
        self.assertEqual(item.shortcut("hwp"), "Ctrl+K")
        self.assertEqual(item.shortcut("word"), keys.MARK_NONE)
        self.assertEqual(item.shortcut("gdocs"), keys.MARK_UNKNOWN)
        self.assertEqual(item.unknown_apps(["hwp", "word", "gdocs"]), ["gdocs"])

    def test_none_marker_is_not_searchable(self):
        # '없음'은 표시용 값이지 단축키가 아니므로 검색에 걸리면 안 된다
        group = keys.Group("t", "테스트", "", [{"id": "a", "name": "A"}])
        group.items = [keys.Item("기능", "편집", 3, {"a": keys.NO_SHORTCUT}, group="t")]
        self.assertEqual(keys.search(group, "없음"), [])
        self.assertEqual(len(keys.search(group, "기능")), 1)

    def test_gaps_lists_unknown_cells_only(self):
        group = keys.Group("t", "테스트", "", [{"id": "a", "name": "A"},
                                               {"id": "b", "name": "B"}])
        group.items = [
            keys.Item("있음", "편집", 3, {"a": "Ctrl+A", "b": keys.NO_SHORTCUT}, group="t"),
            keys.Item("모름", "편집", 3, {"a": "Ctrl+B", "b": None}, group="t"),
        ]
        rows = keys.gaps([group])
        self.assertEqual([(i.name, m) for _, i, m in rows], [("모름", ["b"])])

    def test_data_cell_values_are_valid(self):
        for g in self.groups:
            for item in g.items:
                for app, value in item.keys.items():
                    self.assertTrue(value is None or isinstance(value, str),
                                    f"{g.id}/{item.name}/{app}")
                    if isinstance(value, str):
                        self.assertTrue(value.strip(), f"{g.id}/{item.name}/{app} 빈 문자열")

    def test_search_by_function_name(self):
        found = [i.name for i in keys.search(self.doc, "붙여넣기")]
        self.assertIn("서식 없이 붙여넣기", found)

    def test_search_by_key_combo_ignores_separators(self):
        for query in ("Ctrl+Shift+V", "ctrl shift v", "ctrlshiftv"):
            found = [i.name for i in keys.search(self.doc, query)]
            self.assertIn("서식 없이 붙여넣기", found, query)

    def test_search_across_groups(self):
        hits = keys.search_all(self.groups, "Ctrl+K")
        self.assertGreater(len(hits), 1)
        self.assertTrue(all(isinstance(g, keys.Group) for g, _ in hits))

    def test_sort_abc_and_cat(self):
        names = [i.name for i in keys.sort_items(self.doc, self.state, "abc")]
        self.assertEqual(names, sorted(names))
        cats = [i.cat for i in keys.sort_items(self.doc, self.state, "cat")]
        self.assertEqual(cats, sorted(cats))
        with self.assertRaises(keys.KeysError):
            keys.sort_items(self.doc, self.state, "없는정렬")

    def test_hits_reorder_freq(self):
        target = self.doc.items[-1]
        self.assertNotEqual(keys.sort_items(self.doc, self.state, "freq")[0].name, target.name)
        self.state.hit(target.uid, 99)
        self.assertEqual(keys.sort_items(self.doc, self.state, "freq")[0].name, target.name)

    def test_pins_float_to_top(self):
        target = self.doc.items[-1]
        self.assertTrue(self.state.toggle_pin(target.uid))
        self.assertEqual(keys.sort_items(self.doc, self.state, "abc")[0].name, target.name)
        self.assertFalse(self.state.toggle_pin(target.uid))
        self.assertNotEqual(keys.sort_items(self.doc, self.state, "abc")[0].name, target.name)

    def test_custom_order_move(self):
        item = keys.sort_items(self.doc, self.state, "freq")[2]
        self.state.move(self.doc, item, -2)
        self.assertEqual(keys.sort_items(self.doc, self.state, "custom")[0].name, item.name)
        self.state.move(self.doc, item, 1)
        self.assertEqual(keys.sort_items(self.doc, self.state, "custom")[1].name, item.name)

    def test_sort_cycle_covers_every_mode(self):
        mode, seen = "freq", []
        for _ in range(len(keys.SORTS)):
            seen.append(mode)
            mode = keys.next_sort(mode)
        self.assertEqual(sorted(seen), sorted(keys.SORTS))
        self.assertEqual(mode, "freq")

    def test_unknown_group(self):
        with self.assertRaises(keys.KeysError):
            keys.find_group(self.groups, "없는그룹")

    def test_set_shortcut_writes_user_file(self):
        root = Path(tempfile.mkdtemp())
        original = keys.USER_DATA
        keys.USER_DATA = root / "shortcuts.json"
        try:
            path, is_new = keys.set_shortcut(self.doc, "표 만들기", "word", "Alt+N,T")
            self.assertTrue(path.is_file())
            self.assertFalse(is_new)          # 기본 데이터에 있는 항목

            groups, _ = keys.load_groups()
            item = next(i for i in keys.find_group(groups, "doc").items
                        if i.name == "표 만들기")
            self.assertEqual(item.shortcut("word"), "Alt+N,T")
            # 기본 데이터의 다른 칸이 사용자 항목에 덮여 사라지면 안 된다
            self.assertEqual(item.shortcut("hwp"), "Ctrl+N,T")
        finally:
            keys.USER_DATA = original
            shutil.rmtree(root, ignore_errors=True)

    def test_set_shortcut_none_marks_no_shortcut(self):
        root = Path(tempfile.mkdtemp())
        original = keys.USER_DATA
        keys.USER_DATA = root / "shortcuts.json"
        try:
            keys.set_shortcut(self.doc, "편집 용지", "gdocs", None)
            groups, _ = keys.load_groups()
            item = next(i for i in keys.find_group(groups, "doc").items
                        if i.name == "편집 용지")
            self.assertEqual(item.status("gdocs"), "none")
            self.assertEqual(item.shortcut("gdocs"), keys.MARK_NONE)
        finally:
            keys.USER_DATA = original
            shutil.rmtree(root, ignore_errors=True)

    def test_set_shortcut_new_item(self):
        root = Path(tempfile.mkdtemp())
        original = keys.USER_DATA
        keys.USER_DATA = root / "shortcuts.json"
        try:
            _, is_new = keys.set_shortcut(self.doc, "내가 만든 기능", "hwp", "Ctrl+Q")
            self.assertTrue(is_new)
            groups, _ = keys.load_groups()
            names_ = [i.name for i in keys.find_group(groups, "doc").items]
            self.assertIn("내가 만든 기능", names_)
        finally:
            keys.USER_DATA = original
            shutil.rmtree(root, ignore_errors=True)

    def test_set_shortcut_rejects_unknown_app(self):
        with self.assertRaises(keys.KeysError):
            keys.set_shortcut(self.doc, "표 만들기", "없는앱", "x")

    def test_html_export_is_self_contained(self):
        html = keyhtml.build(self.groups, self.sources)
        self.assertNotIn("__DATA__", html)
        self.assertNotIn("<script src", html)   # 외부 의존 없음
        self.assertIn("서식 없이 붙여넣기", html)
        self.assertIn("localStorage", html)
        # 탭은 JS 가 그리므로 이름은 심어 둔 JSON 안에 있어야 한다
        for g in self.groups:
            self.assertIn(g.name, html)


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

    def test_diff_preview(self):
        change = text.Change(Path("a.txt"), "a\nb\n", "a\nc\n", "utf-8", 1)
        lines = change.diff()
        self.assertTrue(any(l.startswith("-b") for l in lines))
        self.assertTrue(any(l.startswith("+c") for l in lines))


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


class NamesTest(unittest.TestCase):
    SAMPLE = ("리안은 문을 열었다. 카일이 뒤따랐다.\n"
              "리안는 대답하지 않았다. 리언이 웃었다.\n"
              "카일을 바라보던 리안이 고개를 저었다.\n"
              "세드릭과 리안은 걸었다. 세드릭를 믿을 수 없었다.\n"
              "카알이 문득 돌아보았다. 세드릭은 검을 뽑았다.\n")

    def test_strip_particle_takes_longest(self):
        self.assertEqual(names.strip_particle("리안에게서"), ("리안", "에게서"))
        self.assertEqual(names.strip_particle("리안은"), ("리안", "은"))
        self.assertEqual(names.strip_particle("문득"), ("문득", ""))

    def test_extract_needs_repetition_and_variety(self):
        found = names.extract(self.SAMPLE, min_count=2, min_variety=2)
        # 횟수가 같으면 이름 순으로 고정된다
        self.assertEqual([n.text for n in found], ["리안", "세드릭", "카일"])
        self.assertEqual(found[0].count, 4)

    def test_extract_skips_stopwords(self):
        text = "그녀는 갔다. 그녀가 왔다. 그녀를 봤다. " * 3
        self.assertEqual(names.extract(text, min_count=2), [])

    def test_variants_flags_rare_lookalikes(self):
        found = names.extract(self.SAMPLE, min_count=2, min_variety=2)
        pairs = names.variants(found, names.all_stems(self.SAMPLE))
        self.assertIn(("리안", "리언"), [(a.text, b.text) for a, b, _ in pairs])
        self.assertIn(("카일", "카알"), [(a.text, b.text) for a, b, _ in pairs])
        # 확정된 이름끼리는 흔들림으로 보지 않는다
        self.assertNotIn("세드릭", [b.text for _, b, _ in pairs])

    def test_edit_distance_cutoff(self):
        self.assertEqual(names.edit_distance("리안", "리언"), 1)
        self.assertEqual(names.edit_distance("리안", "리안"), 0)
        self.assertGreater(names.edit_distance("리안", "세드릭", 1), 1)

    def test_josa_batchim_rules(self):
        errors = names.check_josa("카일가 왔다. 카일는 갔다.", ["카일"])
        self.assertEqual([(e.wrong, e.right) for e in errors], [("가", "이"), ("는", "은")])

        errors = names.check_josa("미아이 왔다. 미아으로 갔다.", ["미아"])
        self.assertEqual([(e.wrong, e.right) for e in errors], [("이", "가"), ("으로", "로")])

    def test_josa_riul_takes_ro(self):
        # 받침이 ㄹ 이면 '서울로'가 맞고 '서울으로'는 틀리다
        self.assertEqual(names.check_josa("서울로 갔다.", ["서울"]), [])
        errors = names.check_josa("서울으로 갔다.", ["서울"])
        self.assertEqual((errors[0].wrong, errors[0].right), ("으로", "로"))

    def test_josa_ignores_longer_words(self):
        # '리안나는'은 리안+는이 아니다
        self.assertEqual(names.check_josa("리안나는 다른 사람이다.", ["리안"]), [])

    def test_josa_correct_forms_pass(self):
        clean = "리안이 웃었다. 리안은 갔다. 리안을 봤다. 리안과 함께."
        self.assertEqual(names.check_josa(clean, ["리안"]), [])

    SPEECH = ('"늦었어." 카일이 말했다.\n'
              '리안이 고개를 저었다. "괜찮습니다."\n'
              '"그럴 수 없어." 카일이 다시 말했다.\n'
              '"모르겠어."\n')

    def test_extract_speech_finds_speaker_after_quote(self):
        found = names.extract_speech(self.SPEECH, ["리안", "카일"])
        self.assertEqual([s.speaker for s in found], ["카일", "리안", "카일", ""])

    def test_extract_speech_does_not_cross_lines(self):
        # 다음 줄의 이름을 화자로 집으면 안 된다
        text = '"대사."\n카일이 다음 줄에서 말했다.\n'
        self.assertEqual(names.extract_speech(text, ["카일"])[0].speaker, "")

    def test_extract_speech_detects_politeness(self):
        found = names.extract_speech(self.SPEECH, ["리안", "카일"])
        self.assertEqual([s.polite for s in found], [False, True, False, False])

    def test_extract_speech_line_numbers(self):
        found = names.extract_speech(self.SPEECH, ["리안", "카일"])
        self.assertEqual([s.line for s in found], [1, 2, 3, 4])

    def test_voice_profiles(self):
        profiles, unknown = names.voice_profiles(
            names.extract_speech(self.SPEECH, ["리안", "카일"]))
        self.assertEqual(unknown, 1)
        self.assertEqual(profiles[0].name, "카일")
        self.assertEqual(profiles[0].count, 2)
        self.assertEqual(profiles[0].polite_ratio, 0.0)

        polite = [p for p in profiles if p.name == "리안"][0]
        self.assertEqual(polite.polite_ratio, 1.0)
        self.assertEqual(polite.top_endings[0][0], "니다")

    def test_voice_profiles_empty(self):
        self.assertEqual(names.voice_profiles([]), ([], 0))

    def test_dialogue_speakers(self):
        text = '"늦었어." 카일이 말했다.\n"응." 리안이 답했다.\n'
        counts = names.dialogue_speakers(text, ["카일", "리안"])
        self.assertEqual(counts["카일"], 1)
        self.assertEqual(counts["리안"], 1)


class JsonkitTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, name, content):
        p = self.root / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_load_reports_position_on_bad_json(self):
        p = self.write("bad.json", '{"a": }')
        with self.assertRaises(jsonkit.JsonError) as cm:
            jsonkit.load(p)
        self.assertIn("행", str(cm.exception))

    def test_load_falls_back_to_json_lines(self):
        p = self.write("a.jsonl", '{"a":1}\n{"a":2}\n')
        self.assertEqual(jsonkit.load(p), [{"a": 1}, {"a": 2}])

    def test_load_missing_file(self):
        with self.assertRaises(jsonkit.JsonError):
            jsonkit.load(self.root / "없음.json")

    def test_walk_paths(self):
        paths = [p for p, _ in jsonkit.walk({"a": {"b": [1, 2]}})]
        self.assertEqual(paths, ["a.b[0]", "a.b[1]"])

    def test_schema_collapses_arrays_and_marks_optional(self):
        data = {"users": [{"id": 1, "name": "가"}, {"id": 2, "name": "나", "nick": "x"}]}
        fields = {f.path: f for f in jsonkit.schema(data)}
        self.assertEqual(fields["users[].id"].types, {"int"})
        self.assertFalse(fields["users[].id"].optional)
        self.assertTrue(fields["users[].nick"].optional)

    def test_schema_records_mixed_types(self):
        fields = {f.path: f for f in jsonkit.schema({"a": [1, "x"]})}
        self.assertEqual(fields["a[]"].types, {"int", "string"})

    def test_diff_categories(self):
        d = jsonkit.diff({"keep": 1, "gone": 2, "t": 1, "v": "a"},
                         {"keep": 1, "new": 3, "t": "1", "v": "b"})
        self.assertEqual([p for p, _ in d.added], ["new"])
        self.assertEqual([p for p, _ in d.removed], ["gone"])
        self.assertEqual(d.type_changed, [("t", "int", "string")])
        self.assertEqual(d.value_changed, [("v", "a", "b")])
        self.assertFalse(d.empty)

    def test_diff_identical_is_empty(self):
        self.assertTrue(jsonkit.diff({"a": [1, {"b": 2}]}, {"a": [1, {"b": 2}]}).empty)

    def test_diff_by_key_ignores_array_order(self):
        before = {"u": [{"id": 1, "n": "가"}, {"id": 2, "n": "나"}]}
        after = {"u": [{"id": 2, "n": "나"}, {"id": 1, "n": "가"}]}
        self.assertFalse(jsonkit.diff(before, after).empty)          # 인덱스 기준이면 다르게 보이고
        self.assertTrue(jsonkit.diff(before, after, key="id").empty)  # id 로 짝지으면 같다

    def test_diff_by_key_finds_added_and_removed_items(self):
        d = jsonkit.diff({"u": [{"id": 1}]}, {"u": [{"id": 2}]}, key="id")
        self.assertEqual([p for p, _ in d.removed], ["u[id=1]"])
        self.assertEqual([p for p, _ in d.added], ["u[id=2]"])

    def test_breaking_covers_removed_and_type_changes(self):
        d = jsonkit.diff({"gone": 1, "t": 1, "v": 1}, {"t": "1", "v": 2})
        self.assertEqual(len(d.breaking), 2)

    def test_type_names(self):
        self.assertEqual(jsonkit.type_name(True), "bool")   # bool 이 int 로 잡히면 안 된다
        self.assertEqual(jsonkit.type_name(1), "int")
        self.assertEqual(jsonkit.type_name(None), "null")

    def test_preview_truncates(self):
        self.assertTrue(jsonkit.preview("가" * 100, 10).endswith("…"))


class LogkitTest(unittest.TestCase):
    SAMPLE = [
        "2026-09-03 10:00:01 INFO  요청 시작 user=1234",
        "2026-09-03 10:00:02 ERROR 결제 실패 order=8821 amount=15,000",
        "  at com.app.Pay.run(Pay.java:42)",
        "2026-09-03 10:00:05 ERROR 결제 실패 order=8822 amount=7,500",
        "2026-09-03 11:30:00 WARNING 응답 지연 1200ms",
        "2026-09-03 11:30:10 ERROR DB 연결 실패 10.0.0.5:5432",
    ]

    def test_parse_attaches_stack_traces(self):
        entries = logkit.parse(self.SAMPLE)
        self.assertEqual(len(entries), 5)          # 트레이스 줄은 앞 항목에 붙는다
        self.assertIn("Pay.java", entries[1].raw)

    def test_level_and_time_parsing(self):
        entries = logkit.parse(self.SAMPLE)
        self.assertEqual(entries[0].level, "INFO")
        self.assertEqual(entries[3].level, "WARN")   # WARNING 은 WARN 으로 통일
        self.assertEqual(entries[0].when.hour, 10)

    def test_level_counts_ordered_by_severity(self):
        counts = logkit.level_counts(logkit.parse(self.SAMPLE))
        self.assertEqual(list(counts), ["ERROR", "WARN", "INFO"])
        self.assertEqual(counts["ERROR"], 3)

    def test_normalize_collapses_varying_values(self):
        a = logkit.normalize("결제 실패 order=8821 amount=15,000")
        b = logkit.normalize("결제 실패 order=8822 amount=7,500")
        self.assertEqual(a, b)
        self.assertIn("<ip>", logkit.normalize("연결 실패 10.0.0.5:5432"))
        self.assertIn("<uuid>", logkit.normalize(
            "id=550e8400-e29b-41d4-a716-446655440000"))

    def test_group_messages_merges_same_incident(self):
        groups = logkit.group_messages(logkit.parse(self.SAMPLE), levels={"ERROR"})
        self.assertEqual(groups[0].count, 2)
        self.assertEqual(groups[0].lines, [2, 4])
        self.assertEqual(groups[0].level, "ERROR")

    def test_histogram_buckets(self):
        series = logkit.histogram(logkit.parse(self.SAMPLE), bucket="1h")
        self.assertEqual([c for _, c in series], [3, 2])
        with self.assertRaises(ValueError):
            logkit.histogram([], bucket="7초")

    def test_histogram_respects_level_filter(self):
        series = logkit.histogram(logkit.parse(self.SAMPLE), bucket="1h",
                                  levels={"ERROR"})
        self.assertEqual([c for _, c in series], [2, 1])

    def test_spikes_need_a_real_jump(self):
        from datetime import datetime, timedelta

        base = datetime(2026, 9, 3, 8)
        flat = [(base + timedelta(hours=i), 2) for i in range(6)]
        self.assertEqual(logkit.spikes(flat), [])

        flat[3] = (flat[3][0], 40)
        found = logkit.spikes(flat)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][1], 40)

    def test_strip_prefix_leaves_message(self):
        self.assertEqual(
            logkit.strip_prefix("2026-09-03 10:00:02 ERROR 결제 실패"), "결제 실패")

    def test_span(self):
        first, last = logkit.span(logkit.parse(self.SAMPLE))
        self.assertEqual((first.hour, last.hour), (10, 11))
        self.assertEqual(logkit.span([]), (None, None))


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
