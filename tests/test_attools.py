import shutil
import tempfile
import unicodedata
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import devkit, files, gitkit, hangul, keyhtml, keys, life, manuscript, sheet, xlsx
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

    def test_html_export_is_self_contained(self):
        html = keyhtml.build(self.groups, self.sources)
        self.assertNotIn("__DATA__", html)
        self.assertNotIn("<script src", html)   # 외부 의존 없음
        self.assertIn("서식 없이 붙여넣기", html)
        self.assertIn("localStorage", html)
        # 탭은 JS 가 그리므로 이름은 심어 둔 JSON 안에 있어야 한다
        for g in self.groups:
            self.assertIn(g.name, html)


if __name__ == "__main__":
    unittest.main()
