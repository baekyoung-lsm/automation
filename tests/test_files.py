"""파일 분류·개명·중복·감시·압축 시험."""

import os
import shutil
import tempfile
import unicodedata
import unittest
from datetime import datetime
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import files, text
from attools.write import names


def exif_jpeg(*, make="Samsung", model="SM-G991N", orientation=6,
              lat=(37, 33, 36.0), lon=(126, 58, 40.0), lat_ref="N",
              lon_ref="E", taken="2026:03:04 14:30:00", order="MM") -> bytes:
    """위치·기기·방향이 든 최소 JPEG. EXIF 읽기·지우기를 시험하는 데 쓴다.

    order 는 바이트 순서다. 파일마다 «MM»(빅)과 «II»(리틀)이 섞여 있고,
    폰·카메라는 대개 II 로 적는다.
    """
    import struct

    mark = ">" if order == "MM" else "<"

    def ascii_entry(tag, text, pool, base):
        raw = text.encode() + b"\x00"
        if len(raw) <= 4:
            return struct.pack(mark + "HHI4s", tag, 2, len(raw), raw.ljust(4, b"\x00")), pool
        offset = base + len(pool)
        pool += raw
        return struct.pack(mark + "HHII", tag, 2, len(raw), offset), pool

    def rationals(tag, values, pool, base):
        raw = b"".join(struct.pack(mark + "II", int(v * 1000), 1000) for v in values)
        offset = base + len(pool)
        pool += raw
        return struct.pack(mark + "HHII", tag, 5, len(values), offset), pool

    # TIFF 머리말: MM 00 2a, 첫 IFD 는 8
    header = ((b"MM\x00\x2a" if order == "MM" else b"II\x2a\x00")
              + struct.pack(mark + "I", 8))
    # 항목 자리를 먼저 잡아야 offset 을 계산할 수 있다
    entries0 = 5          # Make, Model, Orientation, ExifIFD, GPSIFD
    ifd0_size = 2 + entries0 * 12 + 4
    gps_entries = 4
    gps_size = 2 + gps_entries * 12 + 4
    exif_entries = 1      # DateTimeOriginal
    exif_size = 2 + exif_entries * 12 + 4

    ifd0_at = 8
    gps_at = ifd0_at + ifd0_size
    exif_at = gps_at + gps_size
    pool_at = exif_at + exif_size

    pool = b""
    make_e, pool = ascii_entry(0x010F, make, pool, pool_at)
    model_e, pool = ascii_entry(0x0110, model, pool, pool_at)
    orient_e = struct.pack(mark + "HHI4s", 0x0112, 3, 1,
                           struct.pack(mark + "HH", orientation, 0))
    exif_ptr = struct.pack(mark + "HHII", 0x8769, 4, 1, exif_at)
    gps_ptr = struct.pack(mark + "HHII", 0x8825, 4, 1, gps_at)
    ifd0 = (struct.pack(mark + "H", entries0) + make_e + model_e + orient_e
            + exif_ptr + gps_ptr + struct.pack(mark + "I", 0))

    lat_ref_e, pool = ascii_entry(0x0001, lat_ref, pool, pool_at)
    lat_e, pool = rationals(0x0002, lat, pool, pool_at)
    lon_ref_e, pool = ascii_entry(0x0003, lon_ref, pool, pool_at)
    lon_e, pool = rationals(0x0004, lon, pool, pool_at)
    gps = (struct.pack(mark + "H", gps_entries) + lat_ref_e + lat_e + lon_ref_e
           + lon_e + struct.pack(mark + "I", 0))

    taken_e, pool = ascii_entry(0x9003, taken, pool, pool_at)
    exif_ifd = struct.pack(mark + "H", exif_entries) + taken_e + struct.pack(mark + "I", 0)

    tiff = header + ifd0 + gps + exif_ifd + pool
    app1 = b"Exif\x00\x00" + tiff
    out = b"\xff\xd8"
    out += b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1
    out += b"\xff\xfe" + struct.pack(">H", 2 + 5) + b"memo\x00"   # 주석
    # 최소 SOF0 + SOS + EOI (그림 자료는 없다시피)
    out += b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, 4, 4, 1) + bytes([1, 0x11, 0])
    out += b"\xff\xda" + struct.pack(">H", 8) + bytes([1, 1, 0, 0, 63, 0])
    out += b"\x00" * 8 + b"\xff\xd9"
    return out


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        # 저널을 안 주면 files 는 홈에 쓴다. 홈을 임시 폴더로 돌려 두지 않으면
        # 시험을 돌릴 때마다 진짜 ~/.attools/journal 에 파일이 쌓인다.
        self.home = Path(tempfile.mkdtemp())
        self.prev_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)

    def tearDown(self):
        if self.prev_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.prev_home
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

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
        self.assertEqual(journal.parent, self.home / ".attools" / "journal")
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


class ImageTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _png(self, width, height):
        import struct
        import zlib

        def chunk(tag, body):
            return (struct.pack(">I", len(body)) + tag + body
                    + struct.pack(">I", zlib.crc32(tag + body)))

        head = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        path = self.root / "a.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head)
                         + chunk(b"IEND", b""))
        return path

    def test_png_size(self):
        info = files.image_info(self._png(1920, 1080))
        self.assertEqual((info.kind, info.width, info.height), ("PNG", 1920, 1080))
        self.assertEqual(info.ratio, "16:9")

    def test_gif_and_bmp_are_little_endian(self):
        import struct

        gif = self.root / "b.gif"
        gif.write_bytes(b"GIF89a" + struct.pack("<HH", 640, 480) + b"\x00" * 8)
        self.assertEqual((files.image_info(gif).width, files.image_info(gif).height),
                         (640, 480))
        bmp = self.root / "c.bmp"
        # 높이가 음수면 위에서 아래로 그리는 그림이다. 크기는 절댓값이다.
        bmp.write_bytes(b"BM" + b"\x00" * 16 + struct.pack("<ii", 300, -200)
                        + b"\x00" * 8)
        info = files.image_info(bmp)
        self.assertEqual((info.width, info.height), (300, 200))

    def test_jpeg_reads_frame_header(self):
        import struct

        path = self.root / "d.jpg"
        path.write_bytes(b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16)
                         + b"\x00" * 14 + b"\xff\xc0" + struct.pack(">H", 17)
                         + b"\x08" + struct.pack(">HH", 768, 1024) + b"\x00" * 10)
        info = files.image_info(path)
        self.assertEqual((info.kind, info.width, info.height), ("JPEG", 1024, 768))

    def test_webp_vp8x_size(self):
        path = self.root / "e.webp"
        path.write_bytes(b"RIFF" + b"\x00" * 4 + b"WEBPVP8X" + b"\x00" * 8
                         + (799).to_bytes(3, "little") + (599).to_bytes(3, "little"))
        info = files.image_info(path)
        self.assertEqual((info.kind, info.width, info.height), ("WebP", 800, 600))

    def test_unknown_or_broken_file_returns_none(self):
        broken = self.root / "f.png"
        broken.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        self.assertIsNone(files.image_info(broken))
        self.assertIsNone(files.image_info(self.root / "없는파일.png"))

    def test_scan_separates_unreadable_files(self):
        self._png(10, 20)
        (self.root / "g.jpg").write_text("이건 그림이 아니다", encoding="utf-8")
        found, unknown = files.scan_images(self.root)
        self.assertEqual([i.kind for i in found], ["PNG"])
        self.assertEqual([p.name for p in unknown], ["g.jpg"])


class RouteTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        for name in ("세금계산서_2026-03.pdf", "회의록.docx", "IMG_0001.jpg"):
            (self.root / name).write_text("x", encoding="utf-8")
        self.rules = files.load_rules([
            {"이름": "세금계산서", "패턴": "세금계산서*.pdf",
             "정규식": r"(?P<연>\d{4})-(?P<달>\d{2})", "폴더": "회계/{연}/{달}"},
            {"패턴": "*.jpg", "폴더": "사진/{년}"},
        ])

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_rules_accept_korean_and_english_keys(self):
        rules = files.load_rules({"rules": [{"pattern": "*.txt", "folder": "글"}]})
        self.assertEqual((rules[0].pattern, rules[0].folder), ("*.txt", "글"))

    def test_rules_need_a_folder(self):
        with self.assertRaises(ValueError):
            files.load_rules([{"패턴": "*.txt"}])
        with self.assertRaises(ValueError):
            files.load_rules([])

    def test_route_uses_regex_groups_in_folder_name(self):
        routed, missed = files.plan_route(self.root, self.rules)
        by_name = {Path(r.move.src).name: Path(r.move.dst) for r in routed}
        self.assertEqual(
            by_name["세금계산서_2026-03.pdf"].relative_to(self.root).as_posix(),
            "회계/2026/03/세금계산서_2026-03.pdf")
        self.assertEqual([p.name for p in missed], ["회의록.docx"])

    def test_first_matching_rule_wins(self):
        rules = files.load_rules([{"패턴": "*.jpg", "폴더": "먼저"},
                                  {"패턴": "*", "폴더": "나중"}])
        routed, _ = files.plan_route(self.root, rules)
        jpg = next(r for r in routed if r.move.src.endswith(".jpg"))
        self.assertIn("먼저", jpg.move.dst)

    def test_rule_with_unmatched_regex_falls_through(self):
        rules = files.load_rules([
            {"패턴": "*.pdf", "정규식": r"없는패턴(?P<x>\d+)", "폴더": "안됨/{x}"},
            {"패턴": "*.pdf", "폴더": "문서"}])
        routed, _ = files.plan_route(self.root, rules)
        self.assertTrue(routed[0].move.dst.endswith("문서/세금계산서_2026-03.pdf"))

    def test_unknown_placeholder_is_reported(self):
        rules = files.load_rules([{"패턴": "*.jpg", "폴더": "{없는것}"}])
        with self.assertRaises(ValueError):
            files.plan_route(self.root, rules)

    def test_route_plan_does_not_touch_files(self):
        files.plan_route(self.root, self.rules)
        self.assertTrue((self.root / "IMG_0001.jpg").is_file())


class FlattenTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        for rel in ("2026/1분기/보고서.pdf", "2026/2분기/보고서.pdf", "메모.txt"):
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_top_level_files_stay(self):
        moves = files.plan_flatten(self.root)
        self.assertNotIn("메모.txt", [Path(m.src).name for m in moves])

    def test_name_clash_gets_a_number(self):
        moves = files.plan_flatten(self.root)
        names = sorted(Path(m.dst).name for m in moves)
        self.assertEqual(names, ["보고서 (1).pdf", "보고서.pdf"])

    def test_keep_path_prefixes_folders(self):
        moves = files.plan_flatten(self.root, keep_path=True)
        names = sorted(Path(m.dst).name for m in moves)
        self.assertEqual(names, ["2026_1분기_보고서.pdf", "2026_2분기_보고서.pdf"])

    def test_dest_directory_can_differ(self):
        dest = self.root / "모음"
        moves = files.plan_flatten(self.root, dest=dest)
        self.assertTrue(all(Path(m.dst).parent == dest.resolve() for m in moves))
        self.assertIn("메모.txt", [Path(m.src).name for m in moves])   # 다른 곳이면 옮긴다

    def test_plan_does_not_move_anything(self):
        files.plan_flatten(self.root)
        self.assertTrue((self.root / "2026" / "1분기" / "보고서.pdf").is_file())

    def test_empty_dirs_are_listed_deepest_first(self):
        (self.root / "빈것" / "안쪽").mkdir(parents=True)
        found = files.empty_dirs(self.root)
        self.assertEqual(found[0].name, "안쪽")


class PhotoTest(unittest.TestCase):
    """촬영 시각(EXIF)으로 사진 묶기."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    @staticmethod
    def jpeg(taken: bytes | None) -> bytes:
        """EXIF DateTimeOriginal 만 든 최소 JPEG."""
        import struct

        body = b"\xff\xd8"
        if taken is not None:
            tiff = b"II" + struct.pack("<HI", 42, 8)          # 리틀엔디언, IFD0 은 8
            ifd0 = (struct.pack("<H", 1)
                    + struct.pack("<HHII", 0x8769, 4, 1, 26)  # ExifIFD 는 26
                    + struct.pack("<I", 0))
            sub = (struct.pack("<H", 1)
                   + struct.pack("<HHII", 0x9003, 2, 20, 44)  # 글자는 44부터
                   + struct.pack("<I", 0))
            exif = b"Exif\x00\x00" + tiff + ifd0 + sub + taken
            body += b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif
        return body + b"\xff\xd9"

    def make(self, name, taken=b"2024:03:15 14:30:00\x00"):
        path = self.root / name
        path.write_bytes(self.jpeg(taken))
        return path

    def test_reads_exif(self):
        path = self.make("가.jpg")
        self.assertEqual(files.exif_datetime(path),
                         datetime(2024, 3, 15, 14, 30, 0))

    def test_no_exif_is_none(self):
        self.assertIsNone(files.exif_datetime(self.make("나.jpg", None)))

    def test_not_a_jpeg_is_none(self):
        path = self.root / "메모.txt"
        path.write_text("사진이 아님", encoding="utf-8")
        self.assertIsNone(files.exif_datetime(path))

    def test_broken_exif_is_none(self):
        """망가진 EXIF 에 무엇을 지어내지 않는다."""
        path = self.root / "깨짐.jpg"
        path.write_bytes(b"\xff\xd8" + b"Exif\x00\x00" + b"\x00" * 40 + b"\xff\xd9")
        self.assertIsNone(files.exif_datetime(path))

    def test_plan_uses_taken_date(self):
        self.make("가.jpg")
        self.make("나.jpg", b"2024:04:02 09:00:00\x00")
        plan = files.plan_photos(self.root)
        buckets = sorted(Path(m.dst).parent.name for m in plan.moves)
        self.assertEqual(buckets, ["2024-03", "2024-04"])
        self.assertEqual(plan.from_exif, 2)

    def test_leaves_unknown_alone_by_default(self):
        """촬영 시각을 모르면 건드리지 않는다. 수정 시각은 복사한 날일 수 있다."""
        self.make("가.jpg")
        self.make("모름.jpg", None)
        plan = files.plan_photos(self.root)
        self.assertEqual(len(plan.moves), 1)
        self.assertEqual([p.name for p in plan.left], ["모름.jpg"])

    def test_mtime_fallback_is_reported(self):
        self.make("모름.jpg", None)
        plan = files.plan_photos(self.root, use_mtime=True)
        self.assertEqual(len(plan.moves), 1)
        self.assertEqual([p.name for p in plan.from_mtime], ["모름.jpg"])
        self.assertEqual(plan.left, [])

    def test_already_in_place_is_skipped(self):
        folder = self.root / "2024-03"
        folder.mkdir()
        (folder / "가.jpg").write_bytes(self.jpeg(b"2024:03:15 14:30:00\x00"))
        self.assertEqual(files.plan_photos(self.root).moves, [])

    def test_rename_with_taken(self):
        self.make("IMG_0001.jpg")
        self.make("IMG_0002.jpg", b"2024:04:02 09:00:00\x00")
        plan = files.plan_rename_report(self.root, "{taken}-{taken_time}{ext}")
        self.assertEqual(sorted(Path(m.dst).name for m in plan.moves),
                         ["20240315-143000.jpg", "20240402-090000.jpg"])
        self.assertEqual(plan.skipped, [])

    def test_rename_skips_photos_without_exif(self):
        """수정 시각으로 몰래 대신하면 촬영일이라 적힌 틀린 이름이 남는다."""
        self.make("있음.jpg")
        self.make("없음.jpg", None)
        plan = files.plan_rename_report(self.root, "{taken}{ext}")
        self.assertEqual(len(plan.moves), 1)
        self.assertEqual([p.name for p in plan.skipped], ["없음.jpg"])

    def test_rename_without_taken_reads_no_exif(self):
        self.make("없음.jpg", None)
        plan = files.plan_rename_report(self.root, "{seq:02d}{ext}")
        self.assertEqual(len(plan.moves), 1)
        self.assertEqual(plan.skipped, [])

    def test_render_name_says_what_is_missing(self):
        path = self.make("없음.jpg", None)
        with self.assertRaises(ValueError) as ctx:
            files.render_name(path, "{taken}{ext}", seq=1)
        self.assertIn("EXIF", str(ctx.exception))

    def test_unknown_bucket(self):
        with self.assertRaises(ValueError):
            files.plan_photos(self.root, by="시간")

    def test_non_photos_are_ignored(self):
        (self.root / "메모.txt").write_text("x", encoding="utf-8")
        self.assertEqual(files.plan_photos(self.root).moves, [])


class CollectDupesTest(unittest.TestCase):
    """중복을 지우지 않고 모으기. 무리마다 하나는 반드시 남아야 한다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "깊은" / "더깊은").mkdir(parents=True)
        body = "같은 내용" * 200
        for name in ("원본.txt", "깊은/사본1.txt", "깊은/더깊은/사본2.txt"):
            (self.root / name).write_text(body, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def groups(self):
        return files.find_duplicates(self.root, min_size=1)

    def test_keeps_shortest_path(self):
        keeper = files.pick_keeper(self.groups()[0], "shortest")
        self.assertEqual(keeper.name, "원본.txt")

    def test_keep_modes(self):
        group = self.groups()[0]
        self.assertEqual(files.pick_keeper(group, "first"), sorted(group)[0])
        self.assertIn(files.pick_keeper(group, "oldest"), group)
        with self.assertRaises(ValueError):
            files.pick_keeper(group, "제일큰것")

    def test_plan_leaves_one_behind(self):
        moves = files.plan_collect_dupes(self.root, self.groups(),
                                         self.root / "_중복")
        self.assertEqual(len(moves), 2)
        self.assertNotIn(str(self.root / "원본.txt"), [m.src for m in moves])

    def test_plan_keeps_relative_path(self):
        moves = files.plan_collect_dupes(self.root, self.groups(),
                                         self.root / "_중복")
        targets = sorted(str(Path(m.dst).relative_to(self.root / "_중복"))
                         for m in moves)
        self.assertEqual(targets, ["깊은/더깊은/사본2.txt", "깊은/사본1.txt"])

    def test_round_trip(self):
        dest = self.root / "_중복"
        journal = self.root / "기록.jsonl"
        moves = files.plan_collect_dupes(self.root, self.groups(), dest)
        files.apply_moves(moves, journal=journal)
        self.assertFalse((self.root / "깊은" / "사본1.txt").exists())
        self.assertTrue((self.root / "원본.txt").exists())

        restored, errors = files.undo(journal)
        self.assertEqual((restored, errors), (2, []))
        self.assertTrue((self.root / "깊은" / "사본1.txt").exists())

    def test_files_already_in_dest_are_skipped(self):
        """모아 둔 폴더를 다시 훑어도 같은 파일을 또 옮기지 않는다."""
        dest = self.root / "_중복"
        dest.mkdir()
        (dest / "사본3.txt").write_text("같은 내용" * 200, encoding="utf-8")
        moves = files.plan_collect_dupes(self.root, self.groups(), dest)
        self.assertNotIn(str(dest / "사본3.txt"), [m.src for m in moves])


class ListFilesTest(unittest.TestCase):
    """파일 목록 뽑기. 엑셀에 붙일 자료 목록을 손으로 안 적게."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "안쪽").mkdir()
        (self.root / "가.txt").write_text("작다", encoding="utf-8")
        (self.root / "나.pdf").write_text("조금 더 크다" * 10, encoding="utf-8")
        (self.root / "안쪽" / "다.txt").write_text("셋", encoding="utf-8")
        (self.root / ".숨김").write_text("x", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_walks_into_folders_and_skips_hidden(self):
        rows = files.list_files(self.root)
        self.assertEqual(sorted(r.name for r in rows), ["가.txt", "나.pdf", "다.txt"])
        inner = [r for r in rows if r.name == "다.txt"][0]
        self.assertEqual(inner.folder, "안쪽")
        self.assertEqual(inner.relative, str(Path("안쪽") / "다.txt"))

    def test_hidden_on_request(self):
        rows = files.list_files(self.root, include_hidden=True)
        self.assertIn(".숨김", [r.name for r in rows])

    def test_flat_stays_on_top(self):
        rows = files.list_files(self.root, recursive=False)
        self.assertNotIn("다.txt", [r.name for r in rows])

    def test_glob_filters(self):
        rows = files.list_files(self.root, glob=["*.txt"])   # 하위까지 본다
        self.assertEqual(sorted(r.name for r in rows), ["가.txt", "다.txt"])
        top = files.list_files(self.root, glob=["*.txt"], recursive=False)
        self.assertEqual([r.name for r in top], ["가.txt"])

    def test_sorts(self):
        by_size = files.list_files(self.root, sort="size")
        self.assertEqual(by_size[0].name, "나.pdf")     # 큰 것부터
        by_ext = files.list_files(self.root, sort="ext")
        self.assertEqual(by_ext[0].suffix, "pdf")

    def test_unknown_sort(self):
        with self.assertRaises(ValueError):
            files.list_files(self.root, sort="아무거나")

    def test_suffix_has_no_dot(self):
        rows = files.list_files(self.root, glob=["*.pdf"])
        self.assertEqual(rows[0].suffix, "pdf")


class PackTest(unittest.TestCase):
    """첨부용 나눠 담기. 만들어진 zip 이 한도를 넘지 않는지까지 본다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, name, size):
        path = self.root / name
        path.write_bytes(os.urandom(size))      # 안 눌리는 자료로 재야 한다
        return path

    def test_parse_size_units(self):
        self.assertEqual(files.parse_size("1B"), 1)
        self.assertEqual(files.parse_size("2K"), 2048)
        self.assertEqual(files.parse_size("25MB"), 25 * 1024 ** 2)
        self.assertEqual(files.parse_size("1.5GiB"), int(1.5 * 1024 ** 3))

    def test_bare_number_means_megabytes(self):
        # 사람은 «25» 라고 적고 25MB 를 뜻한다. 25바이트로 읽으면 안 된다
        self.assertEqual(files.parse_size("25"), 25 * 1024 ** 2)

    def test_bad_size(self):
        for bad in ("크게", "", "-3MB", "0"):
            with self.assertRaises(ValueError):
                files.parse_size(bad)

    def test_groups_under_the_limit(self):
        made = [self.make("가.bin", 40_000), self.make("나.bin", 40_000),
                self.make("다.bin", 30_000)]
        packs, too_big = files.plan_packs(made, max_bytes=100_000)
        self.assertEqual(too_big, [])
        self.assertEqual(len(packs), 2)
        for pack in packs:
            self.assertLessEqual(pack.size, 100_000)

    def test_file_bigger_than_the_limit_is_left_out_and_named(self):
        big = self.make("큰것.bin", 200_000)
        small = self.make("작은것.bin", 1_000)
        packs, too_big = files.plan_packs([big, small], max_bytes=100_000)
        self.assertEqual([p for p, _s in too_big], [big])
        self.assertEqual(packs[0].files, [small])

    def test_the_zip_actually_fits(self):
        import zipfile

        made = [self.make(f"파일{i}.bin", 9_000) for i in range(12)]
        limit = 50_000
        packs, _too_big = files.plan_packs(made, max_bytes=limit)
        for pack in packs:
            target = self.root / f"묶음{pack.index}.zip"
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
                for path in pack.files:
                    z.write(path, path.name)
            self.assertLessEqual(target.stat().st_size, limit)

    def test_too_small_a_limit_is_an_error(self):
        with self.assertRaises(ValueError):
            files.plan_packs([], max_bytes=100)

    def test_unreadable_file_is_skipped(self):
        packs, too_big = files.plan_packs([self.root / "없는것.bin"],
                                          max_bytes=100_000)
        self.assertEqual((packs, too_big), ([], []))


class RenameByMapTest(unittest.TestCase):
    """목록대로 이름 바꾸기. 무엇이 안 바뀌었는지 다 알려 주는지 본다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.home = Path(tempfile.mkdtemp())
        self.prev_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        for name in ("가.pdf", "나.pdf", "라.pdf"):
            (self.root / name).write_text("x", encoding="utf-8")

    def tearDown(self):
        if self.prev_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.prev_home
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_renames_and_reports_the_rest(self):
        plan = files.plan_rename_map(self.root, [
            ("가.pdf", "제출-001.pdf"), ("없음.pdf", "제출-003.pdf")])
        self.assertEqual([Path(m.dst).name for m in plan.moves], ["제출-001.pdf"])
        self.assertEqual(plan.missing, ["없음.pdf"])
        self.assertEqual(plan.untouched, ["나.pdf", "라.pdf"])

    def test_missing_extension_is_kept(self):
        plan = files.plan_rename_map(self.root, [("가.pdf", "제출-001")])
        self.assertEqual(Path(plan.moves[0].dst).name, "제출-001.pdf")

    def test_same_name_is_not_a_move(self):
        plan = files.plan_rename_map(self.root, [("가.pdf", "가.pdf")])
        self.assertEqual(plan.moves, [])
        self.assertEqual(plan.same, ["가.pdf"])

    def test_two_files_to_one_name_get_numbered(self):
        plan = files.plan_rename_map(self.root, [
            ("가.pdf", "제출.pdf"), ("나.pdf", "제출.pdf")])
        names = [Path(m.dst).name for m in plan.moves]
        self.assertEqual(names, ["제출.pdf", "제출 (1).pdf"])

    def test_dangerous_names_are_cleaned(self):
        plan = files.plan_rename_map(self.root, [("가.pdf", "../밖으로.pdf")])
        self.assertNotIn("..", Path(plan.moves[0].dst).name)

    def test_apply_is_undoable(self):
        plan = files.plan_rename_map(self.root, [("가.pdf", "제출-001.pdf")])
        journal = files.apply_moves(plan.moves)
        self.assertTrue((self.root / "제출-001.pdf").exists())
        restored, errors = files.undo(journal)
        self.assertEqual((restored, errors), (1, []))
        self.assertTrue((self.root / "가.pdf").exists())


class FolderAuditTest(unittest.TestCase):
    """받은 폴더 훑기. 무엇을 봤는지도 함께 내는지 본다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def kinds(self, **kwargs):
        return {n.kind: n for n in files.audit_folder(self.root, **kwargs).notes}

    def test_empty_folder(self):
        rep = files.audit_folder(self.root)
        self.assertEqual(rep.files, 0)
        self.assertTrue(rep.skipped)

    def test_composition_is_always_there(self):
        (self.root / "가.txt").write_text("내용", encoding="utf-8")
        self.assertIn("구성", self.kinds())

    def test_duplicate_files(self):
        (self.root / "가.txt").write_text("같은 내용", encoding="utf-8")
        (self.root / "나.txt").write_text("같은 내용", encoding="utf-8")
        self.assertIn("중복", self.kinds())

    def test_no_dupes_flag_says_it_skipped(self):
        (self.root / "가.txt").write_text("같은 내용", encoding="utf-8")
        (self.root / "나.txt").write_text("같은 내용", encoding="utf-8")
        rep = files.audit_folder(self.root, dupes=False)
        self.assertNotIn("중복", {n.kind for n in rep.notes})
        self.assertTrue(any("보지 않았습니다" in line for line in rep.skipped))

    def test_decomposed_hangul_name(self):
        import unicodedata

        name = unicodedata.normalize("NFD", "한글.txt")
        (self.root / name).write_text("x", encoding="utf-8")
        note = self.kinds()["이름"]
        self.assertIn("자모가 분리된", note.samples[0])

    def test_double_space_in_a_name(self):
        (self.root / "가운데  공백.txt").write_text("x", encoding="utf-8")
        self.assertIn("이름", self.kinds())

    def test_junk_files_are_not_name_problems(self):
        (self.root / ".DS_Store").write_text("junk", encoding="utf-8")
        kinds = self.kinds(include_hidden=True)
        self.assertIn("찌꺼기", kinds)
        self.assertNotIn("이름", kinds)

    def test_empty_file(self):
        (self.root / "빈것.txt").write_text("", encoding="utf-8")
        self.assertIn("빈 파일", self.kinds())

    def test_office_temp_file(self):
        (self.root / "~$문서.xlsx").write_text("temp", encoding="utf-8")
        self.assertIn("찌꺼기", self.kinds())

    def test_clean_folder_has_only_composition_and_size(self):
        (self.root / "보고서.pdf").write_text("가", encoding="utf-8")
        (self.root / "명단.csv").write_text("나", encoding="utf-8")
        self.assertEqual(set(self.kinds()), {"구성", "큰 파일"})


class UndoInputTest(unittest.TestCase):
    """되돌리기에 엉뚱한 것을 줬을 때. 역추적 대신 사람 말이어야 한다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_broken_journal_is_reported(self):
        journal = self.root / "가짜.jsonl"
        journal.write_text("{이건 JSON 이 아니다\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            files.undo(journal)


class DocumentMetaTest(unittest.TestCase):
    CORE = ("<?xml version='1.0' encoding='UTF-8'?>"
            "<cp:coreProperties"
            " xmlns:cp='http://schemas.openxmlformats.org/package/2006/"
            "metadata/core-properties'"
            " xmlns:dc='http://purl.org/dc/elements/1.1/'"
            " xmlns:dcterms='http://purl.org/dc/terms/'>"
            "<dc:title>2026 사업계획</dc:title>"
            "<dc:creator>김철수</dc:creator>"
            "<cp:lastModifiedBy>박영희</cp:lastModifiedBy>"
            "<cp:revision>7</cp:revision>"
            "<dcterms:modified>2026-02-11T18:20:00Z</dcterms:modified>"
            "</cp:coreProperties>")
    APP = ("<?xml version='1.0'?><Properties xmlns='http://schemas."
           "openxmlformats.org/officeDocument/2006/extended-properties'>"
           "<Application>Microsoft Office Word</Application>"
           "<Pages>12</Pages><Words>3400</Words>"
           "<Company>가나상사</Company></Properties>")

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, name="계획서.docx", *, core=True, app=True) -> Path:
        import zipfile

        path = self.root / name
        with zipfile.ZipFile(path, "w") as z:
            if core:
                z.writestr("docProps/core.xml", self.CORE)
            if app:
                z.writestr("docProps/app.xml", self.APP)
            z.writestr("word/document.xml", "<x/>")
        return path

    def test_reads_core_and_app(self):
        meta = files.document_meta(self.make())
        self.assertEqual(meta.kind, "워드")
        self.assertEqual(meta.title, "2026 사업계획")
        self.assertEqual(meta.author, "김철수")
        self.assertEqual(meta.last_by, "박영희")
        self.assertEqual(meta.revision, "7")
        self.assertEqual(meta.modified, "2026-02-11T18:20:00Z")
        self.assertEqual(meta.pages, 12)
        self.assertEqual(meta.words, 3400)
        self.assertEqual(meta.company, "가나상사")
        self.assertEqual(meta.error, "")

    def test_personal_lists_names_left_behind(self):
        meta = files.document_meta(self.make())
        self.assertEqual(meta.personal, ["김철수", "박영희", "가나상사"])

    def test_document_without_properties(self):
        meta = files.document_meta(self.make(core=False, app=False))
        self.assertEqual(meta.error, "문서 속성이 없습니다")
        self.assertEqual(meta.personal, [])

    def test_broken_file_says_why(self):
        path = self.root / "가짜.xlsx"
        path.write_bytes("이건 zip 이 아니다".encode("utf-8"))
        meta = files.document_meta(path)
        # 빈 칸으로 두면 «속성이 없다» 로 읽힌다. 못 읽은 것은 못 읽었다고 적는다
        self.assertIn("열지 못했습니다", meta.error)

    def test_scan_skips_other_files_and_temp_files(self):
        self.make()
        self.make("보고.pptx")
        (self.root / "메모.txt").write_text("가", encoding="utf-8")
        (self.root / "~$계획서.docx").write_bytes(b"tmp")
        found = files.scan_documents(self.root)
        self.assertEqual([m.path.name for m in found],
                         ["계획서.docx", "보고.pptx"])
        self.assertEqual(found[1].kind, "슬라이드")

    def test_scan_can_take_one_file(self):
        path = self.make()
        self.assertEqual(len(files.scan_documents(path)), 1)


class ScrubTest(DocumentMetaTest):
    """속성 지우기. 만드는 방법은 DocumentMetaTest 것을 그대로 쓴다."""

    def test_plan_lists_what_would_go(self):
        plan = files.plan_scrub(self.make())
        self.assertEqual([label for label, _v in plan.removed],
                         ["만든 사람", "마지막 저장한 사람", "회사"])
        self.assertEqual([v for _l, v in plan.removed],
                         ["김철수", "박영희", "가나상사"])
        self.assertTrue(plan.ok)

    def test_plan_does_not_touch_the_file(self):
        path = self.make()
        before = path.read_bytes()
        files.plan_scrub(path)
        self.assertEqual(path.read_bytes(), before)

    def test_apply_keeps_the_original_and_the_rest(self):
        path = self.make()
        before = path.read_bytes()
        out = files.apply_scrub(path, self.root / "사본.docx")
        self.assertEqual(path.read_bytes(), before)
        meta = files.document_meta(out)
        self.assertEqual(meta.author, "")
        self.assertEqual(meta.last_by, "")
        self.assertEqual(meta.company, "")
        self.assertEqual(meta.title, "2026 사업계획")   # 내용은 그대로다
        self.assertEqual(meta.pages, 12)

    def test_scrubbed_copy_has_nothing_left_to_scrub(self):
        out = files.apply_scrub(self.make(), self.root / "사본.docx")
        self.assertFalse(files.plan_scrub(out).ok)

    def test_all_parts_survive(self):
        import zipfile

        out = files.apply_scrub(self.make(), self.root / "사본.docx")
        with zipfile.ZipFile(out) as z:
            self.assertIn("word/document.xml", z.namelist())

    def test_comments_are_reported_not_touched(self):
        import zipfile

        path = self.make()
        with zipfile.ZipFile(path, "a") as z:
            z.writestr("word/comments.xml", "<c>김철수</c>")
        plan = files.plan_scrub(path)
        self.assertEqual(plan.others, ["word/comments.xml"])
        out = files.apply_scrub(path, self.root / "사본.docx")
        with zipfile.ZipFile(out) as z:
            self.assertIn("김철수", z.read("word/comments.xml").decode("utf-8"))

    def test_broken_file_is_not_scrubbed(self):
        path = self.root / "가짜.docx"
        path.write_bytes(b"not a zip")
        plan = files.plan_scrub(path)
        self.assertFalse(plan.ok)
        self.assertIn("열지 못했습니다", plan.error)

    def test_blank_tag_leaves_other_text_alone(self):
        xml = "<a><dc:creator>김</dc:creator><dc:title>가</dc:title></a>"
        got, gone = files._blank_tag(xml, "creator")
        self.assertEqual(gone, "김")
        self.assertEqual(got, "<a><dc:creator></dc:creator>"
                              "<dc:title>가</dc:title></a>")


class PdfMetaTest(unittest.TestCase):
    """PDF 속성 읽기. 속성만 보고 본문 글자는 꺼내지 않는다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, body: bytes, name: str = "문서.pdf") -> Path:
        path = self.root / name
        path.write_bytes(b"%PDF-1.4\n" + body + b"\n%%EOF\n")
        return path

    def test_counts_page_objects(self):
        body = (b"1 0 obj<</Type/Pages/Kids[2 0 R 3 0 R]/Count 2>>endobj\n"
                b"2 0 obj<</Type/Page/Parent 1 0 R>>endobj\n"
                b"3 0 obj<</Type/Page/Parent 1 0 R>>endobj\n")
        self.assertEqual(files.pdf_meta(self.make(body)).pages, 2)

    def test_falls_back_to_count_when_no_page_objects(self):
        body = b"1 0 obj<</Type/Pages/Count 7>>endobj\n"
        self.assertEqual(files.pdf_meta(self.make(body)).pages, 7)

    def test_reads_plain_info(self):
        body = (b"1 0 obj<</Type/Page>>endobj\n"
                b"2 0 obj<</Title (2026 \\(1\\) plan)/Author (Hong)"
                b"/Producer (attools)/CreationDate (D:20260304120500+09'00')>>"
                b"endobj\n")
        meta = files.pdf_meta(self.make(body))
        self.assertEqual(meta.title, "2026 (1) plan")
        self.assertEqual(meta.author, "Hong")
        self.assertEqual(meta.created, "2026-03-04 12:05")

    def test_reads_utf16_hex_info(self):
        raw = "홍길동".encode("utf-16-be").hex()
        body = (b"1 0 obj<</Type/Page>>endobj\n2 0 obj<</Author <FEFF"
                + raw.encode() + b">>>endobj\n")
        self.assertEqual(files.pdf_meta(self.make(body)).author, "홍길동")

    def test_encrypted_file_is_not_opened(self):
        body = b"trailer<</Encrypt 9 0 R>>"
        meta = files.pdf_meta(self.make(body))
        self.assertIn("암호", meta.error)
        self.assertIsNone(meta.pages)

    def test_not_a_pdf(self):
        path = self.root / "가짜.pdf"
        path.write_bytes("이건 PDF 가 아니다".encode("utf-8"))
        self.assertIn("PDF 가 아닙니다", files.pdf_meta(path).error)

    def test_unknown_page_count_says_so(self):
        meta = files.pdf_meta(self.make(b"1 0 obj<</Title (x)>>endobj"))
        self.assertIsNone(meta.pages)
        self.assertIn("쪽 수를 읽지 못했습니다", meta.error)

    def test_reads_pages_inside_a_compressed_object_stream(self):
        import zlib

        inner = (b"1 0 obj<</Type/Page>>endobj 2 0 obj<</Type/Page>>endobj")
        packed = zlib.compress(inner)
        body = (b"5 0 obj<</Type/ObjStm/N 2/Filter/FlateDecode>>stream\n"
                + packed + b"\nendstream endobj\n")
        self.assertEqual(files.pdf_meta(self.make(body)).pages, 2)

    def test_scan_includes_pdf_and_can_skip_it(self):
        self.make(b"1 0 obj<</Type/Page>>endobj", "보고서.pdf")
        found = files.scan_documents(self.root)
        self.assertEqual([m.kind for m in found], ["PDF"])
        self.assertEqual(files.scan_documents(self.root, pdf=False), [])


class HwpxMetaTest(unittest.TestCase):
    """한글 문서 속성. 워드와 담는 자리가 달라 따로 본다."""

    HPF = ("<opf:package xmlns:opf='o' xmlns:dc='d'><opf:metadata>"
           "<dc:title>2026 예산안</dc:title><dc:creator>김철수</dc:creator>"
           "</opf:metadata></opf:package>")

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, name="예산안.hwpx", meta=True) -> Path:
        import zipfile

        path = self.root / name
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("mimetype", "application/hwp+zip")
            if meta:
                z.writestr("Contents/content.hpf", self.HPF)
            z.writestr("Contents/section0.xml", "<x/>")
        return path

    def test_reads_title_and_creator(self):
        meta = files.document_meta(self.make())
        self.assertEqual(meta.kind, "한글")
        self.assertEqual(meta.title, "2026 예산안")
        self.assertEqual(meta.author, "김철수")
        self.assertEqual(meta.personal, ["김철수"])

    def test_without_properties(self):
        self.assertEqual(files.document_meta(self.make(meta=False)).error,
                         "문서 속성이 없습니다")

    def test_scrub_clears_the_name_but_keeps_the_title(self):
        out = files.apply_scrub(self.make(), self.root / "사본.hwpx")
        meta = files.document_meta(out)
        self.assertEqual(meta.author, "")
        self.assertEqual(meta.title, "2026 예산안")


class ExifTest(unittest.TestCase):
    """사진에 남은 촬영 정보. 시험용 JPEG 을 손으로 만들어 본다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, name="사진.jpg", **kw) -> Path:
        path = self.root / name
        path.write_bytes(exif_jpeg(**kw))
        return path

    def test_reads_place_device_and_time(self):
        meta = files.photo_info(self.write())
        self.assertEqual((meta.make, meta.model), ("Samsung", "SM-G991N"))
        self.assertEqual(meta.orientation, 6)
        self.assertAlmostEqual(meta.latitude, 37.56, places=4)
        self.assertAlmostEqual(meta.longitude, 126.97778, places=4)
        self.assertEqual(meta.taken.strftime("%Y-%m-%d %H:%M"),
                         "2026-03-04 14:30")

    def test_little_endian_exif(self):
        # 폰·카메라는 대개 II(리틀엔디언)로 적는다. 이쪽이 오히려 흔하다
        meta = files.photo_info(self.write("아이폰.jpg", order="II",
                                           make="Apple", model="iPhone"))
        self.assertEqual((meta.make, meta.model), ("Apple", "iPhone"))
        self.assertAlmostEqual(meta.latitude, 37.56, places=4)
        self.assertEqual(meta.orientation, 6)
        self.assertEqual(meta.taken.strftime("%H:%M"), "14:30")

    def test_little_endian_strip(self):
        src = self.write("아이폰.jpg", order="II")
        out, _removed = files.strip_exif(src, self.root / "사본.jpg")
        after = files.photo_info(out)
        self.assertEqual(after.where, "")
        self.assertEqual(after.orientation, 6)

    def test_south_and_west_are_negative(self):
        meta = files.photo_info(self.write(lat_ref="S", lon_ref="W"))
        self.assertLess(meta.latitude, 0)
        self.assertLess(meta.longitude, 0)

    def test_personal_lists_what_leaks(self):
        meta = files.photo_info(self.write())
        self.assertEqual(meta.personal[0], "위치 37.56000, 126.97778")
        self.assertIn("기기 Samsung SM-G991N", meta.personal)

    def test_photo_without_exif(self):
        path = self.root / "민.jpg"
        path.write_bytes(b"\xff\xd8\xff\xd9")
        self.assertIn("EXIF", files.photo_info(path).error)

    def test_not_a_jpeg(self):
        path = self.root / "그림.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        self.assertIn("JPEG 이 아닙니다", files.photo_info(path).error)

    # ---- 지우기

    def test_strip_removes_place_and_device(self):
        src = self.write()
        out, removed = files.strip_exif(src, self.root / "사본.jpg")
        self.assertIn("Exif/XMP", removed)
        after = files.photo_info(out)
        self.assertEqual(after.where, "")
        self.assertEqual(after.make, "")
        self.assertIsNone(after.taken)

    def test_strip_keeps_orientation_by_default(self):
        # 방향까지 지우면 폰으로 찍은 사진이 눕혀 보인다
        out, _removed = files.strip_exif(self.write(orientation=6),
                                         self.root / "사본.jpg")
        self.assertEqual(files.photo_info(out).orientation, 6)

    def test_strip_all_drops_orientation_too(self):
        out, _removed = files.strip_exif(self.write(orientation=6),
                                         self.root / "사본.jpg",
                                         keep_orientation=False)
        self.assertIsNone(files.photo_info(out).orientation)

    def test_stripped_file_is_still_a_jpeg(self):
        src = self.write()
        out, _removed = files.strip_exif(src, self.root / "사본.jpg")
        raw = out.read_bytes()
        self.assertTrue(raw.startswith(b"\xff\xd8"))
        self.assertTrue(raw.endswith(b"\xff\xd9"))
        before = files.image_info(src)
        after = files.image_info(out)
        self.assertEqual((after.width, after.height),
                         (before.width, before.height))
        self.assertLess(out.stat().st_size, src.stat().st_size)

    def test_original_is_untouched(self):
        src = self.write()
        before = src.read_bytes()
        files.strip_exif(src, self.root / "사본.jpg")
        self.assertEqual(src.read_bytes(), before)

    def test_strip_refuses_other_formats(self):
        path = self.root / "그림.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        with self.assertRaises(ValueError):
            files.strip_exif(path, self.root / "사본.png")

    def test_scan_only_looks_at_jpegs(self):
        self.write("가.jpg")
        (self.root / "메모.txt").write_text("가", encoding="utf-8")
        found = files.scan_photos(self.root)
        self.assertEqual([m.path.name for m in found], ["가.jpg"])


class SyncTest(unittest.TestCase):
    """백업 폴더에 맞춰 넣기. 지우는 일이 섞여 있어 자세히 본다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.source = self.root / "원본"
        self.backup = self.root / "백업"
        self.source.mkdir()
        self.backup.mkdir()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, where: Path, name: str, body: str) -> Path:
        path = where / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def plan(self, **kw):
        return files.plan_sync(self.source, self.backup, **kw)

    def test_counts_new_changed_and_extra(self):
        self.write(self.source, "가.txt", "새것")
        self.write(self.source, "나.txt", "바뀐 것")
        self.write(self.backup, "나.txt", "옛것")
        self.write(self.source, "다.txt", "같음")
        self.write(self.backup, "다.txt", "같음")
        self.write(self.backup, "라.txt", "백업에만")

        plan = self.plan()
        self.assertEqual(plan.new, ["가.txt"])
        self.assertEqual(plan.changed, ["나.txt"])
        self.assertEqual(plan.extra, ["라.txt"])
        self.assertEqual(plan.same, 1)

    def test_plan_touches_nothing(self):
        self.write(self.source, "가.txt", "새것")
        self.plan()
        self.assertFalse((self.backup / "가.txt").exists())

    def test_apply_copies_new_and_changed(self):
        self.write(self.source, "가운데/가.txt", "새것")
        self.write(self.source, "나.txt", "바뀐 것")
        self.write(self.backup, "나.txt", "옛것")
        plan = self.plan()
        copied, removed, failed = files.apply_sync(self.source, self.backup,
                                                   plan)
        self.assertEqual((copied, removed, failed), (2, 0, []))
        self.assertEqual((self.backup / "가운데" / "가.txt").read_text("utf-8"),
                         "새것")
        self.assertEqual((self.backup / "나.txt").read_text("utf-8"), "바뀐 것")

    def test_old_version_is_kept_before_overwriting(self):
        # 백업이 원본을 덮는 순간 예전 판이 사라진다. 사람이 찾는 건 대개 그쪽이다
        self.write(self.source, "나.txt", "바뀐 것")
        self.write(self.backup, "나.txt", "옛것")
        files.apply_sync(self.source, self.backup, self.plan(),
                         stamp="20260308-000000")
        old = (self.backup / files.OLD_VERSIONS_DIR / "20260308-000000"
               / "나.txt")
        self.assertEqual(old.read_text("utf-8"), "옛것")

    def test_no_keep_drops_the_old_version(self):
        self.write(self.source, "나.txt", "바뀐 것")
        self.write(self.backup, "나.txt", "옛것")
        files.apply_sync(self.source, self.backup, self.plan(), keep_old=False)
        self.assertFalse((self.backup / files.OLD_VERSIONS_DIR).exists())

    def test_extra_files_stay_by_default(self):
        self.write(self.backup, "라.txt", "백업에만")
        files.apply_sync(self.source, self.backup, self.plan())
        self.assertTrue((self.backup / "라.txt").is_file())

    def test_remove_extra_moves_it_aside_first(self):
        self.write(self.backup, "라.txt", "백업에만")
        _copied, removed, _failed = files.apply_sync(
            self.source, self.backup, self.plan(), remove_extra=True,
            stamp="20260308-000000")
        self.assertEqual(removed, 1)
        self.assertFalse((self.backup / "라.txt").exists())
        kept = (self.backup / files.OLD_VERSIONS_DIR / "20260308-000000"
                / "라.txt")
        self.assertEqual(kept.read_text("utf-8"), "백업에만")

    def test_kept_versions_are_not_counted_as_extra(self):
        self.write(self.source, "나.txt", "바뀐 것")
        self.write(self.backup, "나.txt", "옛것")
        files.apply_sync(self.source, self.backup, self.plan(),
                         stamp="20260308-000000")
        # 두 번째로 셀 때 «백업에만 있는 파일» 로 잡히면 지우자고 들 것이다
        self.assertEqual(self.plan().extra, [])

    def test_missing_backup_folder_is_all_new(self):
        self.write(self.source, "가.txt", "새것")
        plan = files.plan_sync(self.source, self.root / "아직없음")
        self.assertEqual(plan.new, ["가.txt"])


if __name__ == "__main__":
    unittest.main()
