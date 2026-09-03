import shutil
import tempfile
import unicodedata
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import devkit, files, gitkit, hangul, life, manuscript
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
            'gh = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"\n'
            'db = "postgres://app:s3cret@db:5432/app"\n'
            'password = "Real!Pass99"\n')
        kinds = {f.kind for f in gitkit.scan_text(text, "a.py")}
        self.assertEqual(kinds, {"GitHub 토큰", "접속 문자열 비밀번호", "하드코딩된 비밀값"})

    def test_ignores_placeholders(self):
        text = ('API_KEY = "your-key-here"\n'
                'SECRET = "${VAULT_SECRET}"\n'
                'TOKEN = "changeme"\n'
                'PW = os.environ["DB_PASSWORD"]\n')
        self.assertEqual(gitkit.scan_text(text, "a.py"), [])

    def test_ignore_marker(self):
        text = 'password = "Real!Pass99"  # attools: ignore\n'
        self.assertEqual(gitkit.scan_text(text, "a.py"), [])

    def test_entropy(self):
        low = gitkit.shannon_entropy("aaaaaaaaaaaaaaaaaaaaaaaa")
        high = gitkit.shannon_entropy("kJ8sQ2mZ4vX9pL1nR7tB3wY6")
        self.assertLess(low, 1.0)
        self.assertGreater(high, 4.0)


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


if __name__ == "__main__":
    unittest.main()
