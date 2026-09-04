"""파일 분류·개명·중복·감시·압축 시험."""

import shutil
import tempfile
import unicodedata
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import files, names, report, text


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

    def test_digest_is_stable_and_content_sensitive(self):
        a = self.make("a.txt", "같은 내용")
        b = self.make("b.txt", "같은 내용")
        c = self.make("c.txt", "다른 내용")
        self.assertEqual(files.digest(a), files.digest(b))
        self.assertNotEqual(files.digest(a), files.digest(c))
        self.assertEqual(len(files.digest(a)), 64)          # sha256
        with self.assertRaises(ValueError):
            files.digest(a, "없는방식")

    def test_write_sums_format_matches_sha256sum(self):
        self.make("a.txt", "내용")
        self.make("sub/b.txt", "내용")
        targets = sorted(files.iter_targets(self.root, recursive=True,
                                            include_hidden=False))
        lines = files.write_sums(self.root, targets)
        self.assertEqual(len(lines), 2)
        for line in lines:
            digest, sep, name = line.partition("  ")   # 표준 도구와 같은 두 칸
            self.assertEqual(len(digest), 64)
            self.assertTrue(sep)
            self.assertIn(name, ("a.txt", "sub/b.txt"))

    def test_check_sums_detects_change_and_missing(self):
        self.make("같음.txt", "그대로")
        self.make("바뀜.txt", "처음")
        self.make("사라짐.txt", "있음")
        targets = sorted(files.iter_targets(self.root, recursive=True,
                                            include_hidden=False))
        lines = files.write_sums(self.root, targets)

        (self.root / "바뀜.txt").write_text("나중", encoding="utf-8")
        (self.root / "사라짐.txt").unlink()

        result = files.check_sums(self.root, lines)
        self.assertEqual(result.ok, ["같음.txt"])
        self.assertEqual(result.changed, ["바뀜.txt"])
        self.assertEqual(result.missing, ["사라짐.txt"])
        self.assertEqual(result.failed, 2)

    def test_check_sums_reports_malformed_lines(self):
        result = files.check_sums(self.root, ["# 주석", "", "이상한줄"])
        self.assertEqual(result.malformed, [(3, "이상한줄")])

    def test_recent_files_filters_by_age(self):
        import os
        import time

        fresh = self.make("새것.txt", "x")
        old = self.make("옛것.txt", "x")
        os.utime(old, (time.time() - 10 * 86400,) * 2)

        found = files.recent_files(self.root, days=1)
        self.assertEqual([p.name for p, _, _ in found], ["새것.txt"])

        both = files.recent_files(self.root, days=30)
        self.assertEqual(len(both), 2)

    def test_recent_files_newest_first(self):
        import os
        import time

        a = self.make("a.txt", "x")
        b = self.make("b.txt", "x")
        os.utime(a, (time.time() - 3600,) * 2)
        found = files.recent_files(self.root, days=1)
        self.assertEqual([p.name for p, _, _ in found], ["b.txt", "a.txt"])

    def test_recent_files_glob_and_limit(self):
        self.make("a.py", "x")
        self.make("b.txt", "x")
        self.assertEqual(
            [p.name for p, _, _ in files.recent_files(self.root, glob=["*.py"])],
            ["a.py"])
        self.assertEqual(len(files.recent_files(self.root, limit=1)), 1)

    def test_day_label(self):
        from datetime import datetime, timedelta

        today = datetime(2026, 9, 4, 12, 0)
        self.assertEqual(files.day_label(today.timestamp(), today=today), "오늘")
        self.assertEqual(
            files.day_label((today - timedelta(days=1)).timestamp(), today=today), "어제")
        self.assertEqual(
            files.day_label((today - timedelta(days=2)).timestamp(), today=today), "그저께")
        self.assertEqual(
            files.day_label((today - timedelta(days=9)).timestamp(), today=today),
            "2026-08-26")

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


    def _cp949_zip(self, names: dict) -> Path:
        """윈도우에서 만든 것처럼 cp949 이름으로 zip 을 만든다."""
        import zipfile

        class Cp949Info(zipfile.ZipInfo):
            def _encodeFilenameFlags(self):
                return self.filename.encode("cp949"), 0

        path = self.root / "윈도우.zip"
        with zipfile.ZipFile(path, "w") as z:
            for name, body in names.items():
                z.writestr(Cp949Info(name), body)
            info = zipfile.ZipInfo("정상.txt")
            info.flag_bits |= files.ZIP_UTF8_FLAG
            z.writestr(info, "utf-8 표시가 있는 항목")
        return path

    def test_list_zip_repairs_cp949_names(self):
        path = self._cp949_zip({"보고서/1분기 결과.txt": "내용", "사진.jpg": "x"})
        entries = {e.name: e for e in files.list_zip(path)}
        self.assertIn("보고서/1분기 결과.txt", entries)
        self.assertTrue(entries["보고서/1분기 결과.txt"].fixed)
        self.assertFalse(entries["정상.txt"].fixed)      # 이미 UTF-8 이면 두 번 고치지 않는다

    def test_fix_zip_name_leaves_utf8_flagged_alone(self):
        self.assertEqual(files.fix_zip_name("한글.txt", files.ZIP_UTF8_FLAG),
                         ("한글.txt", False))

    def test_fix_zip_name_leaves_ascii_alone(self):
        self.assertEqual(files.fix_zip_name("report.txt", 0), ("report.txt", False))

    def test_unsafe_reason_catches_escapes(self):
        self.assertEqual(files.unsafe_reason("../바깥.txt"), "상위 디렉터리(..)")
        self.assertEqual(files.unsafe_reason("/etc/passwd"), "절대 경로")
        self.assertEqual(files.unsafe_reason("C:/윈도우"), "드라이브 경로")
        self.assertEqual(files.unsafe_reason("안/전.txt"), "")

    def test_extract_zip_writes_fixed_names_and_skips_escapes(self):
        path = self._cp949_zip({"보고서/결과.txt": "내용", "../바깥.txt": "위험"})
        dest = self.root / "풀기"
        written, skipped = files.extract_zip(path, dest, files.list_zip(path))
        names = sorted(p.relative_to(dest).as_posix() for p in written)
        self.assertEqual(names, ["보고서/결과.txt", "정상.txt"])
        self.assertTrue(any("상위 디렉터리" in s for s in skipped))
        self.assertEqual((dest / "보고서" / "결과.txt").read_text(encoding="utf-8"),
                         "내용")

    def test_extract_zip_keeps_existing_files_unless_told(self):
        path = self._cp949_zip({"결과.txt": "새 내용"})
        dest = self.root / "풀기"
        dest.mkdir()
        (dest / "결과.txt").write_text("원래 내용", encoding="utf-8")
        written, skipped = files.extract_zip(path, dest, files.list_zip(path))
        self.assertTrue(any("이미 있음" in s for s in skipped))
        self.assertEqual((dest / "결과.txt").read_text(encoding="utf-8"), "원래 내용")
        files.extract_zip(path, dest, files.list_zip(path), overwrite=True)
        self.assertEqual((dest / "결과.txt").read_text(encoding="utf-8"), "새 내용")


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


if __name__ == "__main__":
    unittest.main()
