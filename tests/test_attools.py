import shutil
import tempfile
import unicodedata
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import devkit, files, hangul, manuscript


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

    def test_duplicates(self):
        self.make("a.txt", "같은 내용" * 100)
        self.make("sub/b.txt", "같은 내용" * 100)
        self.make("c.txt", "다른 내용" * 100)
        groups = files.find_duplicates(self.root, min_size=1)
        self.assertEqual(len(groups), 1)
        self.assertEqual({p.name for p in groups[0]}, {"a.txt", "b.txt"})

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

    def test_mask(self):
        text = "주민 900101-1234567 폰 010-1234-5678 pw=hunter22 메일 hong@ex.com"
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

    def test_snapshot_growth(self):
        (self.root / "1화.txt").write_text("가나다", encoding="utf-8")
        manuscript.snapshot(self.root, note="초고")
        (self.root / "1화.txt").write_text("가나다라마", encoding="utf-8")
        manuscript.snapshot(self.root, note="퇴고")
        snaps = manuscript.list_snapshots(self.root)
        self.assertEqual([s["total"] for s in snaps], [3, 5])
        self.assertEqual(snaps[0]["note"], "초고")


if __name__ == "__main__":
    unittest.main()
