"""표 모델과 csv/xlsx 입출력 시험."""

import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import sheet, text, xlsx
from attools.docs import report
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

    def _bare_xlsx(self, sheet_xml: str) -> Path:
        """다른 도구가 낸 것처럼 손으로 만든 xlsx. 우리 라이터를 거치지 않는다."""
        import zipfile

        path = self.root / "남이만든.xlsx"
        book = ('<?xml version="1.0"?><workbook xmlns="http://schemas.'
                'openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://'
                'schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="시트" sheetId="1" r:id="rId1"/></sheets>'
                "</workbook>")
        rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.'
                'openxmlformats.org/package/2006/relationships"><Relationship '
                'Id="rId1" Type="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships/worksheet" '
                'Target="worksheets/sheet1.xml"/></Relationships>')
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("xl/workbook.xml", book)
            z.writestr("xl/_rels/workbook.xml.rels", rels)
            z.writestr("xl/worksheets/sheet1.xml",
                       '<?xml version="1.0"?><worksheet xmlns="http://schemas.'
                       'openxmlformats.org/spreadsheetml/2006/main">'
                       "<sheetData>" + sheet_xml + "</sheetData></worksheet>")
        return path

    def test_cells_without_an_address_keep_their_order(self):
        # 칸 주소(r)를 안 적는 도구가 있다. A 열로 몰면 앞 칸이 조용히 사라진다
        path = self._bare_xlsx(
            "<row><c t='inlineStr'><is><t>가</t></is></c>"
            "<c t='inlineStr'><is><t>나</t></is></c></row>"
            "<row><c t='inlineStr'><is><t>1</t></is></c>"
            "<c t='inlineStr'><is><t>2</t></is></c></row>")
        self.assertEqual(xlsx.read_sheet(path), [["가", "나"], ["1", "2"]])

    def test_skipped_columns_stay_empty(self):
        path = self._bare_xlsx(
            "<row><c r='A1' t='inlineStr'><is><t>가</t></is></c>"
            "<c r='C1' t='inlineStr'><is><t>다</t></is></c></row>")
        self.assertEqual(xlsx.read_sheet(path), [["가", None, "다"]])

    def test_inline_rich_text_is_joined(self):
        path = self._bare_xlsx(
            "<row><c r='A1' t='inlineStr'><is><r><t>영업</t></r>"
            "<r><t>1팀</t></r></is></c></row>")
        self.assertEqual(xlsx.read_sheet(path), [["영업1팀"]])

    def test_semicolon_csv_is_read_as_columns(self):
        # 엑셀은 나라 설정에 따라 세미콜론으로 내보낸다. 쉼표로만 읽으면
        # 한 줄이 통째로 한 칸이 되는데, 표는 «열리기» 때문에 틀린 줄도 모른다
        path = self.root / "세미콜론.csv"
        path.write_text("이름;부서;연봉\n홍길동;영업;5000\n", encoding="utf-8")
        table = sheet.load(path)
        self.assertEqual(table.headers, ["이름", "부서", "연봉"])
        self.assertEqual(table.rows, [["홍길동", "영업", 5000]])

    def test_comma_wins_when_both_appear(self):
        path = self.root / "쉼표.csv"
        path.write_text("이름,메모\n홍길동,\"영업; 개발\"\n", encoding="utf-8")
        self.assertEqual(sheet.load(path).headers, ["이름", "메모"])

    def test_pipe_csv(self):
        path = self.root / "막대.csv"
        path.write_text("가|나\n1|2\n", encoding="utf-8")
        self.assertEqual(sheet.load(path).headers, ["가", "나"])

    def test_one_column_csv_stays_one_column(self):
        path = self.root / "한열.csv"
        path.write_text("이름\n홍길동\n김철수\n", encoding="utf-8")
        self.assertEqual(sheet.load(path).headers, ["이름"])

    def test_mac_1904_workbook_dates(self):
        """옛 맥 엑셀 파일. 기준일을 모르면 모든 날짜가 4년 앞당겨진다."""
        import zipfile

        def make(name: str, pr: str) -> Path:
            path = self.root / name
            book = ('<?xml version="1.0"?><workbook xmlns="http://schemas.'
                    'openxmlformats.org/spreadsheetml/2006/main" xmlns:r='
                    '"http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships">' + pr + '<sheets><sheet name="시트" '
                    'sheetId="1" r:id="rId1"/></sheets></workbook>')
            rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.'
                    'openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.'
                    'openxmlformats.org/officeDocument/2006/relationships/'
                    'worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
            styles = ('<?xml version="1.0"?><styleSheet xmlns="http://schemas.'
                      'openxmlformats.org/spreadsheetml/2006/main"><cellXfs '
                      'count="2"><xf numFmtId="0"/><xf numFmtId="14" '
                      'applyNumberFormat="1"/></cellXfs></styleSheet>')
            body = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.'
                    'openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                    '<row r="1"><c r="A1" s="1"><v>44621</v></c></row>'
                    "</sheetData></worksheet>")
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("xl/workbook.xml", book)
                z.writestr("xl/_rels/workbook.xml.rels", rels)
                z.writestr("xl/styles.xml", styles)
                z.writestr("xl/worksheets/sheet1.xml", body)
            return path

        from datetime import date

        old_mac = xlsx.read_sheet(make("맥.xlsx", '<workbookPr date1904="1"/>'))
        normal = xlsx.read_sheet(make("보통.xlsx", ""))
        self.assertEqual(normal[0][0], date(2022, 3, 1))
        self.assertEqual(old_mac[0][0], date(2026, 3, 2))

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
        # 내림차순에서도 빈 칸은 맨 뒤다. 연봉 높은 순으로 볼 때 값이 없는
        # 행이 맨 위를 차지하면 표를 못 읽는다.
        self.assertEqual(desc.rows[-1][1], "최수진")

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

    def test_flatten_record(self):
        row = sheet.flatten_record({"id": 1, "meta": {"부서": "영업"},
                                    "태그": ["a"], "깊음": {"안": {"더": 1}}})
        self.assertEqual(row["meta.부서"], "영업")
        self.assertEqual(row["깊음.안.더"], 1)
        self.assertEqual(row["태그"], '["a"]')      # 배열은 JSON 글자로

    def test_flatten_record_depth_limit(self):
        row = sheet.flatten_record({"a": {"b": {"c": 1}}}, depth=1)
        self.assertIn("a.b", row)
        self.assertEqual(row["a.b"], '{"c": 1}')

    def test_from_records_union_of_keys(self):
        table, info = sheet.from_records(
            [{"id": 1, "name": "가"}, {"id": 2, "비고": "x"}])
        self.assertEqual(table.headers, ["id", "name", "비고"])
        self.assertEqual(table.rows, [[1, "가", None], [2, None, "x"]])
        self.assertEqual((info.rows, info.columns), (2, 3))

    def test_from_records_skips_non_objects(self):
        table, info = sheet.from_records([{"a": 1}, 3, "글자"])
        self.assertEqual(len(table.rows), 1)
        self.assertEqual(info.skipped, 2)

    def test_from_records_needs_objects(self):
        with self.assertRaises(sheet.SheetError):
            sheet.from_records([1, 2, 3])

    def test_find_records_picks_largest_array(self):
        data = {"작음": [{"a": 1}], "큼": [{"a": 1}, {"a": 2}], "숫자": [1, 2, 3]}
        self.assertEqual(len(sheet.find_records(data)), 2)

    def test_find_records_by_path(self):
        data = {"data": {"users": [{"id": 1}]}}
        self.assertEqual(sheet.find_records(data, "data.users"), [{"id": 1}])
        with self.assertRaises(sheet.SheetError):
            sheet.find_records(data, "data")        # 배열이 아니다

    def test_find_records_root_array(self):
        self.assertEqual(sheet.find_records([{"a": 1}]), [{"a": 1}])
        with self.assertRaises(sheet.SheetError):
            sheet.find_records({"a": 1})

    def test_unflatten(self):
        self.assertEqual(sheet.unflatten({"a.b": 1, "a.c": 2, "d": 3}),
                         {"a": {"b": 1, "c": 2}, "d": 3})

    def test_unflatten_overwrites_scalar_parent(self):
        # 'a' 와 'a.b' 가 함께 오면 중첩 쪽을 살린다
        self.assertEqual(sheet.unflatten({"a": 1, "a.b": 2}), {"a": {"b": 2}})

    def test_to_records_skips_blanks_by_default(self):
        t = sheet.Table(["a", "b"], [[1, None], [2, ""]])
        self.assertEqual(sheet.to_records(t), [{"a": 1}, {"a": 2}])
        self.assertEqual(sheet.to_records(t, skip_blank=False),
                         [{"a": 1, "b": None}, {"a": 2, "b": ""}])

    def test_to_records_dates_become_iso(self):
        from datetime import date, datetime

        t = sheet.Table(["날", "때"], [[date(2026, 3, 2), datetime(2026, 3, 2, 9, 30)]])
        record = sheet.to_records(t)[0]
        self.assertEqual(record["날"], "2026-03-02")
        self.assertEqual(record["때"], "2026-03-02 09:30:00")

    def test_json_table_round_trip(self):
        original = [{"id": 1, "name": "홍길동", "meta": {"부서": "영업"},
                     "태그": ["a", "b"]},
                    {"id": 2, "name": "김철수", "meta": {"부서": "개발"}}]
        table, _ = sheet.from_records(original)
        back = sheet.to_records(table, nest=True, parse_json=True)
        self.assertEqual(back, original)

    def rule_table(self):
        from datetime import date

        return sheet.Table(
            ["사번", "이름", "부서", "연봉", "입사일"],
            [["E001", "홍길동", "영업", 52000000, date(2021, 3, 2)],
             ["E002", "", "개발", 47000000, date(2023, 7, 15)],
             ["E002", "이영희", "기획", -100, "2020-01-06"],
             ["잘못", "최수진", "인사", 61000000, date(2020, 1, 6)]])

    def test_validate_required_and_unique(self):
        found = {v.rule.kind: v for v in sheet.validate_rules(
            self.rule_table(),
            [sheet.parse_rule("required", "이름"),
             sheet.parse_rule("unique", "사번")])}
        self.assertEqual(found["required"].rows, [3])
        self.assertEqual(found["unique"].rows, [4])
        self.assertEqual(found["unique"].samples, ["E002"])

    def test_validate_match_range_type_oneof(self):
        rules = [sheet.parse_rule("match", r"사번=^E\d{3}$"),
                 sheet.parse_rule("range", "연봉=0:"),
                 sheet.parse_rule("type", "입사일=날짜"),
                 sheet.parse_rule("oneof", "부서=영업,개발,인사")]
        found = {v.rule.kind: v for v in sheet.validate_rules(self.rule_table(), rules)}
        self.assertEqual(found["match"].rows, [5])
        self.assertEqual(found["range"].rows, [4])
        self.assertEqual(found["type"].rows, [4])
        self.assertEqual(found["oneof"].rows, [4])

    def test_validate_blank_only_caught_by_required(self):
        # 빈 칸을 규칙마다 다시 잡으면 같은 행이 여러 번 나와 시끄럽다
        t = sheet.Table(["a"], [[None]])
        self.assertEqual(sheet.validate_rules(t, [sheet.parse_rule("type", "a=숫자")]), [])
        self.assertEqual(len(sheet.validate_rules(
            t, [sheet.parse_rule("required", "a")])), 1)

    def test_validate_passes_clean_table(self):
        t = sheet.Table(["사번", "이름"], [["E001", "가"], ["E002", "나"]])
        self.assertEqual(sheet.validate_rules(
            t, [sheet.parse_rule("required", "이름"),
                sheet.parse_rule("unique", "사번")]), [])

    def test_validate_range_bounds(self):
        t = sheet.Table(["나이"], [[17], [30], [70]])
        found = sheet.validate_rules(t, [sheet.parse_rule("range", "나이=18:65")])
        self.assertEqual(found[0].rows, [2, 4])

    def test_parse_rule_errors(self):
        with self.assertRaises(sheet.SheetError):
            sheet.parse_rule("match", "정규식만있음")
        with self.assertRaises(sheet.SheetError):
            sheet.validate_rules(sheet.Table(["a"], [[1]]),
                                 [sheet.parse_rule("type", "a=없는종류")])
        with self.assertRaises(sheet.SheetError):
            sheet.validate_rules(sheet.Table(["a"], [["x"]]),
                                 [sheet.parse_rule("match", "a=(열린괄호")])

    def test_fx_adds_computed_column(self):
        t = sheet.Table(["이름", "연봉"], [["가", 1200], ["나", 2400]])
        out, report = sheet.add_column(t, "월급", "연봉/12", digits=0)
        self.assertEqual(out.headers, ["이름", "연봉", "월급"])
        self.assertEqual([r[2] for r in out.rows], [100, 200])
        self.assertEqual((report.computed, report.failed), (2, 0))

    def test_fx_replaces_existing_column(self):
        t = sheet.Table(["a", "b"], [[1, 2]])
        out, _ = sheet.add_column(t, "b", "a * 10")
        self.assertEqual(out.headers, ["a", "b"])
        self.assertEqual(out.rows[0], [1, 10])

    def test_fx_blanks_failing_rows_and_reports_why(self):
        t = sheet.Table(["a", "b"], [[10, 2], [10, 0], [10, None]])
        out, report = sheet.add_column(t, "몫", "a / b")
        self.assertEqual([r[2] for r in out.rows], [5.0, None, None])
        self.assertEqual(report.failed, 2)
        self.assertIn("0으로 나눔", report.reasons)

    def test_fx_rejects_dangerous_expressions(self):
        t = sheet.Table(["a"], [[1]])
        for bad in ("__import__('os')", "open('x')", "a.__class__",
                    "[x for x in a]", "a 1"):
            with self.assertRaises(sheet.SheetError, msg=bad):
                sheet.add_column(t, "x", bad)

    def test_fx_rejects_unknown_column(self):
        t = sheet.Table(["a"], [[1]])
        with self.assertRaises(sheet.SheetError):
            sheet.add_column(t, "x", "a + 없는열")

    def test_fx_allows_whitelisted_functions_and_conditions(self):
        t = sheet.Table(["a"], [[-3], [5]])
        out, _ = sheet.add_column(t, "절댓값", "abs(a)")
        self.assertEqual([r[1] for r in out.rows], [3, 5])

        out2, _ = sheet.add_column(t, "등급", '"큼" if a > 0 else "작음"')
        self.assertEqual([r[1] for r in out2.rows], ["작음", "큼"])

    def test_fx_column_name_with_space(self):
        t = sheet.Table(["매출 합계", "건수"], [[100, 4]])
        out, _ = sheet.add_column(t, "평균", "{매출 합계} / 건수")
        self.assertEqual(out.rows[0][2], 25.0)

    def test_fx_chained_columns(self):
        t = sheet.Table(["a"], [[12]])
        step1, _ = sheet.add_column(t, "b", "a / 2")
        step2, _ = sheet.add_column(step1, "c", "b + 1")
        self.assertEqual(step2.rows[0], [12, 6.0, 7.0])

    def test_dedupe_keep_first_and_last(self):
        t = sheet.Table(["k", "v"], [["1", "가"], ["1", "나"], ["2", "다"]])
        first, info = sheet.dedupe(t, ["k"], keep="first")
        self.assertEqual([r[1] for r in first.rows], ["가", "다"])
        self.assertEqual((info.kept, info.removed), (2, 1))
        self.assertEqual(info.duplicate_keys, [("1", 2)])

        last, _ = sheet.dedupe(t, ["k"], keep="last")
        self.assertEqual([r[1] for r in last.rows], ["나", "다"])

    def test_dedupe_keep_latest_by_date(self):
        from datetime import date

        t = sheet.Table(["사번", "부서", "수정일"],
                        [["E1", "영업", date(2026, 1, 5)],
                         ["E1", "영업2팀", date(2026, 3, 2)],
                         ["E2", "개발", date(2026, 2, 1)]])
        result, _ = sheet.dedupe(t, ["사번"], keep="max", by="수정일")
        self.assertEqual([r[1] for r in result.rows], ["영업2팀", "개발"])

        oldest, _ = sheet.dedupe(t, ["사번"], keep="min", by="수정일")
        self.assertEqual(oldest.rows[0][1], "영업")

    def test_dedupe_multiple_keys(self):
        t = sheet.Table(["a", "b", "v"], [["1", "x", "가"], ["1", "y", "나"],
                                          ["1", "x", "다"]])
        result, info = sheet.dedupe(t, ["a", "b"])
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(info.removed, 1)

    def test_dedupe_requires_by_for_max(self):
        t = sheet.Table(["k"], [["1"]])
        with self.assertRaises(sheet.SheetError):
            sheet.dedupe(t, ["k"], keep="max")
        with self.assertRaises(sheet.SheetError):
            sheet.dedupe(t, ["k"], keep="아무거나")

    def test_dedupe_counts_blank_keys(self):
        t = sheet.Table(["k", "v"], [["", "가"], ["", "나"], ["1", "다"]])
        result, info = sheet.dedupe(t, ["k"])
        self.assertEqual(info.blank_keys, 2)
        self.assertEqual(len(result.rows), 2)

    def test_join_left_keeps_unmatched(self):
        left = sheet.Table(["사번", "이름"], [["E1", "홍길동"], ["E3", "이영희"]])
        right = sheet.Table(["사번", "연봉"], [["E1", 100], ["E9", 200]])

        merged, info = sheet.join(left, right, on="사번")
        self.assertEqual(merged.headers, ["사번", "이름", "연봉"])
        self.assertEqual(merged.rows, [["E1", "홍길동", 100], ["E3", "이영희", None]])
        self.assertEqual((info.matched, info.left_only), (1, 1))

    def test_join_inner_and_outer(self):
        left = sheet.Table(["k", "a"], [["1", "x"], ["2", "y"]])
        right = sheet.Table(["k", "b"], [["1", "p"], ["3", "q"]])

        inner, _ = sheet.join(left, right, on="k", how="inner")
        self.assertEqual([r[0] for r in inner.rows], ["1"])

        outer, info = sheet.join(left, right, on="k", how="outer")
        self.assertEqual(sorted(r[0] for r in outer.rows), ["1", "2", "3"])
        self.assertEqual(info.right_only, 1)

    def test_join_reports_row_multiplication(self):
        # VLOOKUP 은 첫 짝만 가져와서 조용히 틀린다. 여기서는 늘어난 걸 알려야 한다
        left = sheet.Table(["k"], [["1"]])
        right = sheet.Table(["k", "v"], [["1", "a"], ["1", "b"]])

        merged, info = sheet.join(left, right, on="k")
        self.assertEqual(len(merged.rows), 2)
        self.assertEqual(info.multiplied, 1)
        self.assertEqual(info.duplicate_keys, ["1"])

    def test_join_renames_colliding_columns(self):
        left = sheet.Table(["k", "이름"], [["1", "가"]])
        right = sheet.Table(["k", "이름"], [["1", "나"]])

        merged, info = sheet.join(left, right, on="k")
        self.assertEqual(merged.headers, ["k", "이름", "이름_2"])
        self.assertEqual(info.renamed, [("이름", "이름_2")])
        self.assertEqual(merged.rows[0], ["1", "가", "나"])

    def test_join_different_key_names(self):
        left = sheet.Table(["사번"], [["E1"]])
        right = sheet.Table(["사원번호", "연봉"], [["E1", 100]])
        merged, _ = sheet.join(left, right, on="사번", right_on="사원번호")
        self.assertEqual(merged.headers, ["사번", "연봉"])
        self.assertEqual(merged.rows[0], ["E1", 100])

    def test_join_skips_blank_right_keys(self):
        left = sheet.Table(["k"], [["1"]])
        right = sheet.Table(["k", "v"], [["", "버릴것"], ["1", "쓸것"]])
        merged, info = sheet.join(left, right, on="k")
        self.assertEqual(info.blank_keys, 1)
        self.assertEqual(merged.rows[0][1], "쓸것")

    def test_join_rejects_unknown_how(self):
        t = sheet.Table(["k"], [["1"]])
        with self.assertRaises(sheet.SheetError):
            sheet.join(t, t, on="k", how="cross")

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


    def test_melt_widens_rows_and_skips_blanks(self):
        t = sheet.Table(["부서", "이름", "1월", "2월"],
                        [["영업", "가", 10, None], ["개발", "나", 5, 7]])
        m = sheet.melt(t, keep=["부서", "이름"])
        self.assertEqual(m.headers, ["부서", "이름", "항목", "값"])
        self.assertEqual(m.rows, [["영업", "가", "1월", 10],
                                  ["개발", "나", "1월", 5],
                                  ["개발", "나", "2월", 7]])

    def test_melt_can_keep_blanks(self):
        t = sheet.Table(["이름", "1월", "2월"], [["가", 10, None]])
        self.assertEqual(len(sheet.melt(t, keep=["이름"], skip_blank=False).rows), 2)

    def test_melt_picks_named_value_columns_only(self):
        t = sheet.Table(["이름", "1월", "2월"], [["가", 1, 2]])
        m = sheet.melt(t, keep=["이름"], value_cols=["2월"], name="달", value="매출")
        self.assertEqual(m.headers, ["이름", "달", "매출"])
        self.assertEqual(m.rows, [["가", "2월", 2]])

    def test_melt_needs_a_column_to_unfold(self):
        t = sheet.Table(["이름"], [["가"]])
        with self.assertRaises(sheet.SheetError):
            sheet.melt(t, keep=["이름"])

    def test_transpose_uses_first_column_as_headers(self):
        t = sheet.Table(["부서", "1월", "2월"], [["영업", 10, 20], ["개발", 5, 7]])
        r = sheet.transpose(t)
        self.assertEqual(r.headers, ["항목", "영업", "개발"])
        self.assertEqual(r.rows, [["1월", 10, 5], ["2월", 20, 7]])

    def test_transpose_numbers_duplicate_headers(self):
        t = sheet.Table(["부서", "값"], [["영업", 1], ["영업", 2]])
        self.assertEqual(sheet.transpose(t).headers, ["항목", "영업", "영업-2"])

    def test_transpose_needs_rows(self):
        with self.assertRaises(sheet.SheetError):
            sheet.transpose(sheet.Table(["가"], []))


    def test_render_attaches_josa_by_batchim(self):
        out = sheet.render("{이름:은/는} {도시:으로/로} 간다.",
                           {"이름": "민수", "도시": "서울"})
        self.assertEqual(out, "민수는 서울로 간다.")
        out = sheet.render("{이름:은/는} {도시:으로/로} 간다.",
                           {"이름": "지현", "도시": "부산"})
        self.assertEqual(out, "지현은 부산으로 간다.")

    def test_render_josa_on_number(self):
        self.assertEqual(sheet.render("{수량:을/를}", {"수량": 3}), "3을")

    def test_render_writes_amounts_in_hangul(self):
        self.assertEqual(sheet.render("{금액:한글}", {"금액": 12345}),
                         "만 이천삼백사십오")
        self.assertEqual(sheet.render("{금액:계약서}", {"금액": 1250000}),
                         "일금 일백이십오만원정")

    def test_hangul_spec_only_applies_to_numbers(self):
        self.assertEqual(sheet.render("{값:한글}", {"값": "글자"}), "글자")

    def test_render_keeps_format_spec(self):
        self.assertEqual(sheet.render("{번호:03d}", {"번호": 7}), "007")


    def test_bizno_checksum_accepts_real_numbers(self):
        self.assertTrue(sheet.check_bizno("124-81-00998"))
        self.assertTrue(sheet.check_bizno("2208162517"))

    def test_bizno_checksum_rejects_wrong_check_digit(self):
        self.assertFalse(sheet.check_bizno("124-81-00997"))
        self.assertFalse(sheet.check_bizno("123-45-67890"))

    def test_bizno_needs_ten_digits(self):
        self.assertFalse(sheet.check_bizno("124-81-0099"))
        self.assertFalse(sheet.check_bizno(""))

    def test_format_checks_for_korean_fields(self):
        checks = sheet.FORMAT_CHECKS
        self.assertTrue(checks["휴대폰"]("010-1234-5678"))
        self.assertTrue(checks["휴대폰"]("01012345678"))
        self.assertFalse(checks["휴대폰"]("02-1234-5678"))
        self.assertTrue(checks["전화번호"]("02-123-4567"))
        self.assertTrue(checks["우편번호"]("06236"))
        self.assertFalse(checks["우편번호"]("123-456"))     # 옛 6자리는 안 받는다
        self.assertTrue(checks["이메일"]("a.b@example.co.kr"))
        self.assertFalse(checks["이메일"]("a@b"))

    def test_validate_format_rule_finds_bad_rows(self):
        t = sheet.Table(["이름", "번호"],
                        [["가게", "124-81-00998"], ["나게", "123-45-67890"]])
        bad = sheet.validate_rules(t, [sheet.Rule("format", "번호", "사업자번호")])
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0].rows, [3])

    def test_validate_unknown_format_is_reported(self):
        t = sheet.Table(["번호"], [["1"]])
        with self.assertRaises(sheet.SheetError):
            sheet.validate_rules(t, [sheet.Rule("format", "번호", "주민번호")])


class ExpandTest(unittest.TestCase):
    TABLE = sheet.Table(["이름", "주소", "비고"],
                        [["가", "서울시 강남구 역삼동", "A"],
                         ["나", "부산시 해운대구", "B"],
                         ["다", "", "C"]])

    def test_expand_widens_to_the_longest_row(self):
        new, report = sheet.expand_column(self.TABLE, "주소", sep=" ")
        self.assertEqual(new.headers, ["이름", "주소1", "주소2", "주소3", "비고"])
        self.assertEqual(new.rows[1], ["나", "부산시", "해운대구", "", "B"])
        self.assertEqual(report.widest, 3)
        self.assertTrue(report.uneven)
        self.assertEqual(report.blanks, 1)

    def test_expand_keeps_original_column_when_asked(self):
        new, _ = sheet.expand_column(self.TABLE, "주소", sep=" ",
                                     names=["시", "구", "동"], keep=True)
        self.assertEqual(new.headers, ["이름", "주소", "시", "구", "동", "비고"])
        self.assertEqual(new.rows[0][1], "서울시 강남구 역삼동")

    def test_expand_needs_enough_names(self):
        with self.assertRaises(sheet.SheetError):
            sheet.expand_column(self.TABLE, "주소", sep=" ", names=["시", "구"])

    def test_expand_limit_leaves_rest_in_last_cell(self):
        new, _ = sheet.expand_column(self.TABLE, "주소", sep=" ", limit=2)
        self.assertEqual(new.rows[0][1:3], ["서울시", "강남구 역삼동"])

    def test_expand_by_regex(self):
        table = sheet.Table(["값"], [["가1나22다"]])
        new, _ = sheet.expand_column(table, "값", sep=r"\d+", regex=True)
        self.assertEqual(new.rows[0], ["가", "나", "다"])

    def test_expand_rejects_empty_separator(self):
        with self.assertRaises(sheet.SheetError):
            sheet.expand_column(self.TABLE, "주소", sep="")

    def test_expand_even_split_is_not_flagged(self):
        table = sheet.Table(["값"], [["가,나"], ["다,라"]])
        _, report = sheet.expand_column(table, "값")
        self.assertFalse(report.uneven)


class CombineTest(unittest.TestCase):
    TABLE = sheet.Table(["시", "구", "동", "비고"],
                        [["서울시", "강남구", "역삼동", "A"],
                         ["부산시", "", "해운대", "B"]])

    def test_combine_replaces_source_columns_in_place(self):
        new = sheet.combine_columns(self.TABLE, ["시", "구", "동"], into="주소")
        self.assertEqual(new.headers, ["주소", "비고"])
        self.assertEqual(new.rows[0], ["서울시 강남구 역삼동", "A"])

    def test_combine_skips_blank_cells(self):
        new = sheet.combine_columns(self.TABLE, ["시", "구", "동"], into="주소")
        self.assertEqual(new.rows[1][0], "부산시 해운대")     # 구분자가 겹치지 않는다

    def test_combine_can_keep_blanks(self):
        new = sheet.combine_columns(self.TABLE, ["시", "구", "동"], into="주소",
                                    skip_blank=False)
        self.assertEqual(new.rows[1][0], "부산시  해운대")

    def test_combine_keep_puts_new_column_at_the_end(self):
        new = sheet.combine_columns(self.TABLE, ["시", "구"], into="주소", keep=True)
        self.assertEqual(new.headers, ["시", "구", "동", "비고", "주소"])
        self.assertEqual(new.rows[0][-1], "서울시 강남구")

    def test_combine_round_trips_with_expand(self):
        joined = sheet.combine_columns(self.TABLE, ["시", "구", "동"], into="주소",
                                       skip_blank=False)
        back, _ = sheet.expand_column(joined, "주소", sep=" ",
                                      names=["시", "구", "동"])
        self.assertEqual(back.rows[0][:3], ["서울시", "강남구", "역삼동"])

    def test_combine_needs_columns(self):
        with self.assertRaises(sheet.SheetError):
            sheet.combine_columns(self.TABLE, [], into="주소")


class ColumnStatTest(unittest.TestCase):
    TABLE = sheet.Table(["부서", "연봉"],
                        [["영업", 100], ["개발", 200], ["개발", None], ["영업", 900]])

    def test_numbers_get_total_mean_median(self):
        stat = {s.name: s for s in sheet.column_stats(self.TABLE)}["연봉"]
        self.assertEqual((stat.count, stat.total), (3, 1200))
        self.assertEqual(stat.median, 200)          # 평균 400 과 다르다
        self.assertEqual((stat.low, stat.high), (100, 900))

    def test_median_of_even_count_is_the_middle_average(self):
        table = sheet.Table(["값"], [[1], [2], [3], [4]])
        self.assertEqual(sheet.column_stats(table)[0].median, 2.5)

    def test_text_column_gets_top_value(self):
        stat = {s.name: s for s in sheet.column_stats(self.TABLE)}["부서"]
        self.assertEqual((stat.top, stat.top_count), ("영업", 2))
        self.assertAlmostEqual(stat.top_ratio, 0.5)

    def test_mostly_text_column_is_not_treated_as_numeric(self):
        table = sheet.Table(["값"], [["가"], ["나"], [3]])
        self.assertNotEqual(sheet.column_stats(table)[0].kind, "숫자")

    def test_date_column_keeps_range(self):
        from datetime import date as _date

        table = sheet.Table(["날"], [[_date(2026, 1, 1)], [_date(2026, 5, 1)]])
        stat = sheet.column_stats(table)[0]
        self.assertEqual((stat.kind, stat.low, stat.high),
                         ("날짜", _date(2026, 1, 1), _date(2026, 5, 1)))

    def test_empty_column_is_safe(self):
        stat = sheet.column_stats(sheet.Table(["값"], [[None], [""]]))[0]
        self.assertEqual((stat.count, stat.top_ratio), (0, 0.0))


class ColumnDiffTest(unittest.TestCase):
    BEFORE = sheet.Table(["사번", "이름", "부서", "연봉"],
                         [["E001", "가", "영업", 5000]])
    AFTER = sheet.Table(["사번", "이름", "연봉", "입사일", "부서"],
                        [["E001", "가", "5천만", "2024-01-05", "영업"]])

    def test_added_and_removed_columns(self):
        d = sheet.column_diff(self.BEFORE, self.AFTER)
        self.assertEqual(d.added, ["입사일"])
        self.assertEqual(d.removed, [])

    def test_moved_columns_report_both_positions(self):
        d = sheet.column_diff(self.BEFORE, self.AFTER)
        self.assertIn(("연봉", 4, 3), d.moved)
        self.assertIn(("부서", 3, 5), d.moved)

    def test_type_change_is_reported(self):
        d = sheet.column_diff(self.BEFORE, self.AFTER)
        self.assertEqual([n for n, _, _ in d.retyped], ["연봉"])

    def test_same_structure_is_empty(self):
        self.assertTrue(sheet.column_diff(self.BEFORE, self.BEFORE).empty)

    def test_renamed_column_shows_as_removed_and_added(self):
        after = sheet.Table(["사번", "성명", "부서", "연봉"], [["E001", "가", "영업", 5000]])
        d = sheet.column_diff(self.BEFORE, after)
        self.assertEqual((d.added, d.removed), (["성명"], ["이름"]))


class SaveSheetsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def tables(self) -> dict:
        return {"영업": sheet.Table(["이름", "연봉"], [["가", 5000]]),
                "개발": sheet.Table(["이름", "연봉"], [["나", 6000], ["다", 5500]])}

    def test_each_table_becomes_a_sheet(self):
        path = sheet.save_sheets(self.tables(), self.root / "부서별.xlsx")
        self.assertEqual(sheet.xlsx.sheet_names(path), ["영업", "개발"])
        loaded = sheet.load(path, sheet="개발")
        self.assertEqual(len(loaded.rows), 2)

    def test_sheet_name_is_cleaned_for_excel(self):
        tables = {"영업/1분기 [초안] 아주 긴 이름을 넣어 서른한 자를 넘겨 봅니다":
                  sheet.Table(["가"], [["1"]])}
        path = sheet.save_sheets(tables, self.root / "정리.xlsx")
        name = sheet.xlsx.sheet_names(path)[0]
        self.assertLessEqual(len(name), 31)
        self.assertNotIn("/", name)
        self.assertNotIn("[", name)

    def test_csv_is_refused(self):
        with self.assertRaises(sheet.SheetError):
            sheet.save_sheets(self.tables(), self.root / "안됨.csv")

    def test_empty_input_is_refused(self):
        with self.assertRaises(sheet.SheetError):
            sheet.save_sheets({}, self.root / "빈것.xlsx")


class SortDirectionTest(unittest.TestCase):
    TABLE = sheet.Table(["부서", "이름", "연봉"],
                        [["영업", "가", 5000], ["개발", "나", 6000],
                         ["개발", "다", 7000], ["영업", "라", 4000]])

    def test_single_direction(self):
        rows = sheet.sort_rows(self.TABLE, ["연봉"], descending=True).rows
        self.assertEqual([r[2] for r in rows], [7000, 6000, 5000, 4000])

    def test_per_column_direction(self):
        rows = sheet.sort_rows(self.TABLE, ["부서", "연봉"],
                               order=[False, True]).rows
        self.assertEqual([(r[0], r[2]) for r in rows],
                         [("개발", 7000), ("개발", 6000),
                          ("영업", 5000), ("영업", 4000)])

    def test_blank_cells_go_last_in_both_directions(self):
        table = sheet.Table(["값"], [[3], [None], [1]])
        self.assertEqual([r[0] for r in sheet.sort_rows(table, ["값"]).rows],
                         [1, 3, None])
        # 내림차순에서도 빈 칸이 맨 앞으로 올라오지 않아야 자료가 읽힌다
        rows = sheet.sort_rows(table, ["값"], order=[True]).rows
        self.assertEqual(rows[-1][0], None)

    def test_order_shorter_than_columns_falls_back(self):
        rows = sheet.sort_rows(self.TABLE, ["부서", "연봉"], order=[True]).rows
        self.assertEqual(rows[0][0], "영업")


class WhereBlankTest(unittest.TestCase):
    TABLE = sheet.Table(["이름", "연봉"],
                        [["가", 5000], ["나", None], ["다", ""], ["라", "  "]])

    def pick(self, op: str) -> list:
        cond = sheet.Condition.parse(op, "연봉")
        return [r[0] for r in sheet.where(self.TABLE, [cond]).rows]

    def test_empty_catches_none_and_blank_strings(self):
        self.assertEqual(self.pick("empty"), ["나", "다", "라"])

    def test_filled_is_the_opposite(self):
        self.assertEqual(self.pick("filled"), ["가"])

    def test_parse_needs_no_value(self):
        cond = sheet.Condition.parse("empty", " 연봉 ")
        self.assertEqual((cond.column, cond.value), ("연봉", ""))

    def test_other_ops_still_need_a_value(self):
        with self.assertRaises(sheet.SheetError):
            sheet.Condition.parse("eq", "연봉")


class RenameColumnTest(unittest.TestCase):
    TABLE = sheet.Table([" 수량 ", "금액", "비고"], [[1, 100, "x"]])

    def test_renames_and_reports_missing(self):
        new, missing = sheet.rename_columns(self.TABLE, {"수량": "개수",
                                                         "없는열": "무엇"})
        self.assertEqual(new.headers[0], "개수")
        self.assertEqual(missing, ["없는열"])

    def test_matches_ignoring_spaces_and_case(self):
        new, missing = sheet.rename_columns(sheet.Table(["Qty"], [[1]]),
                                            {"qty": "개수"})
        self.assertEqual(new.headers, ["개수"])
        self.assertEqual(missing, [])

    def test_strip_cleans_untouched_headers(self):
        new, _ = sheet.rename_columns(self.TABLE, {}, strip=True)
        self.assertEqual(new.headers[0], "수량")

    def test_clash_gets_a_number(self):
        new, _ = sheet.rename_columns(self.TABLE, {"금액": "비고"})
        self.assertEqual(new.headers, [" 수량 ", "비고", "비고-2"])

    def test_rows_are_untouched(self):
        new, _ = sheet.rename_columns(self.TABLE, {"수량": "개수"})
        self.assertEqual(new.rows, self.TABLE.rows)


class SaveDocxTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_table_becomes_a_word_table(self):
        import xml.etree.ElementTree as ET
        import zipfile

        table = sheet.Table(["이름", "연봉"], [["가", 5000], ["나", None]])
        path = sheet.save(table, self.root / "표.docx")
        with zipfile.ZipFile(path) as z:
            body = z.read("word/document.xml").decode("utf-8")
        ET.fromstring(body)
        self.assertEqual(body.count("<w:tr>"), 3)      # 머리글 + 두 행
        self.assertIn("이름", body)

    def test_values_become_text(self):
        import zipfile

        table = sheet.Table(["값"], [[1234]])
        path = sheet.save(table, self.root / "표.docx")
        with zipfile.ZipFile(path) as z:
            self.assertIn("1234", z.read("word/document.xml").decode("utf-8"))


class FormatColumnTest(unittest.TestCase):
    """열 표기 통일. 모르는 값을 억지로 고치지 않는지가 핵심이다."""

    def test_phone_shapes(self):
        cases = {
            "01012345678": "010-1234-5678",
            "010-1234-5678": "010-1234-5678",
            "+82-10-1234-5678": "010-1234-5678",
            "021234567": "02-123-4567",
            "0212345678": "02-1234-5678",
            "0311234567": "031-123-4567",
            "07012345678": "070-1234-5678",
            "15881588": "1588-1588",
        }
        for raw, want in cases.items():
            self.assertEqual(sheet.format_phone(raw), want, raw)

    def test_phone_leaves_unknown_alone(self):
        """규칙을 모르는 번호는 None. 억지로 자르면 조용히 틀린 번호가 된다."""
        for raw in ("0100000", "12345", "abc", "099-1234-5678", ""):
            self.assertIsNone(sheet.format_phone(raw), raw)

    def test_bizno_and_postcode(self):
        self.assertEqual(sheet.format_bizno("1234567890"), "123-45-67890")
        self.assertIsNone(sheet.format_bizno("12345"))
        self.assertEqual(sheet.format_postcode("06236"), "06236")
        self.assertIsNone(sheet.format_postcode("135-080"))   # 옛 여섯 자리

    def test_date_and_number(self):
        self.assertEqual(sheet.format_date_cell("2026.1.2"), "2026-01-02")
        self.assertIsNone(sheet.format_date_cell("2026/2/29"))  # 없는 날짜
        self.assertEqual(sheet.format_number_cell("1,234원"), 1234)
        self.assertIsNone(sheet.format_number_cell("없음"))

    def test_column_report(self):
        table = sheet.Table(["연락처"],
                            [["01012345678"], ["010-1111-2222"], [""], ["0100"]])
        new, rep = sheet.format_column(table, "연락처", "전화")
        self.assertEqual(new.rows[0][0], "010-1234-5678")
        self.assertEqual(rep.changed, 1)
        self.assertEqual(rep.already, 1)
        self.assertEqual(rep.blank, 1)
        self.assertEqual(rep.failed, [(5, "0100")])           # 머리글이 1행

    def test_original_table_is_untouched(self):
        table = sheet.Table(["연락처"], [["01012345678"]])
        sheet.format_column(table, "연락처", "전화")
        self.assertEqual(table.rows[0][0], "01012345678")

    def test_bizno_checksum_is_reported_separately(self):
        """꼴을 맞추는 것과 옳은 번호인지는 다른 문제다."""
        table = sheet.Table(["사업자"], [["1234567890"], ["1208147521"]])
        _new, rep = sheet.format_column(table, "사업자", "사업자번호")
        self.assertEqual(rep.changed, 2)
        self.assertEqual([line for line, _v in rep.invalid], [2])

    def test_unknown_kind(self):
        table = sheet.Table(["값"], [["1"]])
        with self.assertRaises(sheet.SheetError):
            sheet.format_column(table, "값", "주민번호")


class MarkdownTableTest(unittest.TestCase):
    """표를 마크다운으로. 칸 맞춤은 at doc table 이 한다."""

    def test_basic(self):
        table = sheet.Table(["이름", "부서"], [["홍길동", "영업"]])
        self.assertEqual(sheet.to_markdown(table),
                         "| 이름 | 부서 |\n| --- | --- |\n| 홍길동 | 영업 |\n")

    def test_pipe_is_escaped(self):
        """세로줄은 칸 구분자라 그대로 두면 표가 깨진다."""
        table = sheet.Table(["값"], [["a|b"]])
        self.assertIn("a\\|b", sheet.to_markdown(table))

    def test_newline_becomes_space(self):
        table = sheet.Table(["값"], [["줄1\n줄2"]])
        self.assertNotIn("줄1\n줄2", sheet.to_markdown(table))
        self.assertIn("줄1 줄2", sheet.to_markdown(table))

    def test_blank_cells_keep_the_shape(self):
        table = sheet.Table(["a", "b"], [["1"], [None, None]])
        lines = sheet.to_markdown(table).splitlines()
        self.assertTrue(all(line.count("|") == 3 for line in lines), lines)

    def test_save_writes_markdown(self):
        root = Path(tempfile.mkdtemp())
        try:
            table = sheet.Table(["이름"], [["홍길동"]])
            path = sheet.save(table, root / "표.md")
            self.assertIn("| 이름 |", path.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TableFromGridTest(unittest.TestCase):
    """붙여넣은 격자에도 파일과 같은 규칙을 쓴다."""

    def test_duplicate_headers_are_numbered(self):
        table = sheet.table_from_grid([["이름", "이름"], ["가", "나"]])
        self.assertEqual(table.headers, ["이름", "이름_2"])

    def test_short_rows_are_padded(self):
        table = sheet.table_from_grid([["a", "b", "c"], ["1"]])
        self.assertEqual(table.rows, [["1", None, None]])

    def test_blank_rows_are_dropped(self):
        table = sheet.table_from_grid([["a"], [""], ["1"]])
        self.assertEqual(table.rows, [["1"]])

    def test_empty_grid(self):
        with self.assertRaises(sheet.SheetError):
            sheet.table_from_grid([])


class DescribeSheetsTest(unittest.TestCase):
    """엑셀 한 파일 안의 시트 훑기."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.path = self.root / "여러장.xlsx"
        xlsx.write_sheets(self.path, {
            "직원": [["사번", "이름"], ["E1", "홍길동"]],
            "빈시트": [],
            "급여": [["사번", "금액"], ["E1", 5000], ["E2", 4700]],
        })

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_lists_every_sheet(self):
        found = sheet.describe_sheets(self.path)
        self.assertEqual([i.name for i in found], ["직원", "빈시트", "급여"])

    def test_counts_rows_without_header(self):
        found = {i.name: i for i in sheet.describe_sheets(self.path)}
        self.assertEqual(found["급여"].rows, 2)
        self.assertEqual(found["급여"].headers, ["사번", "금액"])

    def test_empty_sheet_is_not_an_error(self):
        """빈 시트도 목록에서 빼지 않는다. 없는 것과 빈 것은 다르다."""
        found = {i.name: i for i in sheet.describe_sheets(self.path)}
        self.assertEqual(found["빈시트"].rows, 0)
        self.assertEqual(found["빈시트"].error, "비어 있음")

    def test_csv_is_refused(self):
        path = self.root / "명단.csv"
        path.write_text("이름\n홍길동\n", encoding="utf-8")
        with self.assertRaises(sheet.SheetError):
            sheet.describe_sheets(path)


class SheetNameTest(unittest.TestCase):
    """시트 이름 규칙. 겹치면 시트 하나가 조용히 사라지던 자리다."""

    def test_duplicates_get_numbers(self):
        self.assertEqual(sheet.unique_sheet_names(["영업", "영업", "영업"]),
                         ["영업", "영업_2", "영업_3"])

    def test_long_names_are_cut_but_stay_apart(self):
        long_a = "가" * 40 + "A"
        long_b = "가" * 40 + "B"
        made = sheet.unique_sheet_names([long_a, long_b])
        self.assertEqual(len(made), 2)
        self.assertNotEqual(made[0], made[1])
        self.assertTrue(all(len(name) <= 31 for name in made))

    def test_forbidden_characters(self):
        self.assertEqual(sheet.unique_sheet_names(["가:나*다"]), ["가_나_다"])

    def test_save_sheets_keeps_every_sheet(self):
        root = Path(tempfile.mkdtemp())
        try:
            tables = {("가" * 40 + "A"): sheet.Table(["a"], [["1"]]),
                      ("가" * 40 + "B"): sheet.Table(["a"], [["2"]])}
            path = sheet.save_sheets(tables, root / "책.xlsx")
            self.assertEqual(len(xlsx.sheet_names(path)), 2)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class FindInFilesTest(unittest.TestCase):
    """여러 파일에서 값 찾기. «이 사번이 어느 파일에 있나»."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "명단.csv").write_text(
            "사번,이름,부서\nE1,홍길동,영업\nE2,김철수,개발\n", encoding="utf-8")
        (self.root / "평가.csv").write_text("사번,평가\nE2,A\n", encoding="utf-8")
        xlsx.write_sheets(self.root / "급여.xlsx",
                          {"1월": [["사번", "금액"], ["E2", 1000]],
                           "2월": [["사번", "금액"], ["E1", 2000]]})

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def files(self):
        return sorted(self.root.iterdir())

    def test_finds_across_files_and_sheets(self):
        found, skipped = sheet.find_in_files(self.files(), "E2")
        self.assertEqual(skipped, [])
        self.assertEqual({Path(h.path).name for h in found},
                         {"명단.csv", "평가.csv", "급여.xlsx"})
        self.assertIn("1월", {h.sheet for h in found})

    def test_row_number_counts_the_header(self):
        found, _ = sheet.find_in_files(self.files(), "김철수")
        self.assertEqual(found[0].row, 3)      # 머리글 1행, 홍길동 2행

    def test_column_narrows_the_search(self):
        found, skipped = sheet.find_in_files(self.files(), "홍길동", column="이름")
        self.assertEqual([h.column for h in found], ["이름"])
        # 그 열이 없는 파일은 «못 읽음»으로 알린다. 조용히 빼면 다 봤다고 여긴다.
        self.assertTrue(any("이름" in why for _name, why in skipped))

    def test_partial_by_default_exact_on_request(self):
        loose, _ = sheet.find_in_files(self.files(), "홍길")
        self.assertEqual(len(loose), 1)
        strict, _ = sheet.find_in_files(self.files(), "홍길", exact=True)
        self.assertEqual(strict, [])

    def test_case_can_be_ignored_or_not(self):
        found, _ = sheet.find_in_files(self.files(), "e2")
        self.assertTrue(found)
        strict, _ = sheet.find_in_files(self.files(), "e2", ignore_case=False)
        self.assertEqual(strict, [])

    def test_unreadable_files_are_reported(self):
        (self.root / "메모.pdf").write_text("x", encoding="utf-8")
        _found, skipped = sheet.find_in_files(self.files(), "E2")
        self.assertEqual(len(skipped), 1)
        self.assertIn("메모.pdf", skipped[0][0])


class FillDownTest(unittest.TestCase):
    def table(self):
        return sheet.Table(["부서", "이름", "연봉"],
                           [["영업", "홍길동", 5200],
                            [None, "김철수", 4700],
                            ["", "이영희", None],
                            ["개발", "박민수", 6100]])

    def test_fills_only_named_columns(self):
        filled, count = sheet.fill_down(self.table(), ["부서"])
        self.assertEqual([r[0] for r in filled.rows],
                         ["영업", "영업", "영업", "개발"])
        self.assertEqual(count, 2)
        self.assertIsNone(filled.rows[2][2])      # 연봉은 건드리지 않는다

    def test_fills_every_column_by_default(self):
        filled, count = sheet.fill_down(self.table())
        self.assertEqual(filled.rows[2][2], 4700)
        self.assertEqual(count, 3)

    def test_leading_blank_stays_blank(self):
        t = sheet.Table(["부서", "이름"], [[None, "홍길동"], ["영업", "김철수"]])
        filled, count = sheet.fill_down(t, ["부서"])
        self.assertIsNone(filled.rows[0][0])      # 위에 채울 값이 없다
        self.assertEqual(count, 0)

    def test_unknown_column_is_an_error(self):
        with self.assertRaises(sheet.SheetError):
            sheet.fill_down(self.table(), ["없는열"])


class TotalRowTest(unittest.TestCase):
    def table(self):
        return sheet.Table(["부서", "이름", "연봉"],
                           [["영업", "홍길동", 5200],
                            ["영업", "김철수", 4700],
                            ["개발", "이영희", None],
                            ["개발", "박민수", 6100]])

    def test_sum_skips_text_columns(self):
        line, counted = sheet.total_row(self.table())
        self.assertEqual(counted, ["연봉"])
        self.assertEqual(line[2], 16000)
        self.assertIsNone(line[1])                # 이름 칸에 0 을 넣지 않는다
        self.assertEqual(line[0], "합계")

    def test_average_rounds_to_two_places(self):
        line, _ = sheet.total_row(self.table(), ["연봉"], kind="avg")
        self.assertEqual(line[2], 5333.33)

    def test_count_counts_filled_cells(self):
        line, counted = sheet.total_row(self.table(), ["연봉"], kind="count")
        self.assertEqual(counted, ["연봉"])
        self.assertEqual(line[2], 3)              # 빈 칸 하나는 빼고 센다

    def test_label_replaces_the_first_cell(self):
        line, _ = sheet.total_row(self.table(), ["연봉"], label="총계")
        self.assertEqual(line[0], "총계")

    def test_unknown_kind_is_an_error(self):
        with self.assertRaises(sheet.SheetError):
            sheet.total_row(self.table(), kind="median")

    def test_with_total_appends_one_row(self):
        t = self.table()
        result, _ = sheet.with_total(t, ["연봉"])
        self.assertEqual(len(result.rows), len(t.rows) + 1)
        self.assertEqual(result.headers, t.headers)
        self.assertEqual(len(t.rows), 4)          # 원본은 그대로다


class MaskTest(unittest.TestCase):
    def test_name_keeps_the_ends(self):
        self.assertEqual(sheet.mask_name("홍길동"), "홍*동")
        self.assertEqual(sheet.mask_name("남궁민수"), "남**수")
        self.assertEqual(sheet.mask_name("김철"), "김*")
        self.assertEqual(sheet.mask_name("가"), "*")

    def test_name_with_spaces_masks_each_word(self):
        self.assertEqual(sheet.mask_name("Hong Gil"), "H*** G**")

    def test_phone_hides_the_middle(self):
        self.assertEqual(sheet.mask_phone("01012345678"), "010-****-5678")
        self.assertEqual(sheet.mask_phone("02-123-4567"), "02-***-4567")
        self.assertEqual(sheet.mask_phone("1588-1234"), "1588-****")

    def test_phone_refuses_what_it_cannot_read(self):
        # 아무 숫자나 잘라 «전화처럼» 만들면 전화가 아닌 값이 전화인 척한다
        self.assertIsNone(sheet.mask_phone("주문 12345"))

    def test_email_keeps_the_domain(self):
        self.assertEqual(sheet.mask_email("hong@example.com"), "ho**@example.com")
        self.assertIsNone(sheet.mask_email("골뱅이가 없다"))

    def test_short_email_id_is_hidden_whole(self):
        self.assertEqual(sheet.mask_email("ab@b.co"), "**@b.co")
        self.assertEqual(sheet.mask_email("a@b.co"), "*@b.co")

    def test_rrn_keeps_only_the_gender_digit(self):
        # 시험용 가짜 번호다. at git scan 이 진짜로 오해하지 않게 표시해 둔다
        self.assertEqual(sheet.mask_rrn("900101-1234567"),   # attools: ignore
                         "900101-1******")
        self.assertEqual(sheet.mask_rrn("9001011234567"), "900101-1******")
        self.assertIsNone(sheet.mask_rrn("900101-123456"))

    def test_account_keeps_the_last_four(self):
        self.assertEqual(sheet.mask_account("123-456-789012"), "***-***-**9012")
        self.assertEqual(sheet.mask_account("1234 5678 9012 3456"),
                         "**** **** **** 3456")
        self.assertIsNone(sheet.mask_account("1234567"))      # 너무 짧다
        self.assertIsNone(sheet.mask_account("계좌 없음"))

    def test_address_keeps_the_district(self):
        self.assertEqual(sheet.mask_address("서울특별시 강남구 테헤란로 123 4층"),
                         "서울특별시 강남구 ****")
        self.assertEqual(sheet.mask_address("경기도 성남시 분당구 정자동 178"),
                         "경기도 성남시 분당구 ****")
        self.assertIsNone(sheet.mask_address("우리집"))

    def table(self):
        return sheet.Table(["이름", "연락처"],
                           [["홍길동", "010-1234-5678"],
                            ["김철수", None],
                            ["이영희", "연락처 없음"]])

    def test_mask_column_reports_what_it_could_not_read(self):
        masked, rep = sheet.mask_column(self.table(), "연락처", "전화")
        self.assertEqual(masked.rows[0][1], "010-****-5678")
        self.assertIsNone(masked.rows[1][1])           # 빈 칸은 그대로 둔다
        self.assertEqual(rep.blank, 1)
        # 모르는 값은 남기지 않고 통째로 가린다. 대신 몇 행인지 알려 준다
        self.assertEqual(masked.rows[2][1], sheet.HIDDEN)
        self.assertEqual(rep.unclear, [(4, "연락처 없음")])
        self.assertEqual(rep.masked, 2)

    def test_mask_column_leaves_other_columns_alone(self):
        masked, _ = sheet.mask_column(self.table(), "연락처", "전화")
        self.assertEqual([r[0] for r in masked.rows], ["홍길동", "김철수", "이영희"])

    def test_unknown_kind_is_an_error(self):
        with self.assertRaises(sheet.SheetError):
            sheet.mask_column(self.table(), "이름", "지문")

    def test_unknown_column_is_an_error(self):
        with self.assertRaises(sheet.SheetError):
            sheet.mask_column(self.table(), "없는열", "이름")


class FindRowsTest(unittest.TestCase):
    def table(self):
        return sheet.Table(["사번", "이름", "부서"],
                           [["E1", "홍길동", "영업"],
                            ["E2", "김철수", None],
                            ["E3", "이영희", "인사"]])

    def test_line_numbers_count_the_header_as_row_one(self):
        found = sheet.find_rows(self.table(), number=3)
        self.assertEqual(found, [(3, ["E2", "김철수", None])])

    def test_condition_keeps_the_line_number(self):
        found = sheet.find_rows(self.table(),
                                [sheet.Condition.parse("eq", "부서=인사")])
        self.assertEqual([line for line, _row in found], [4])

    def test_no_condition_returns_every_row(self):
        self.assertEqual(len(sheet.find_rows(self.table())), 3)

    def test_short_rows_are_padded_to_the_headers(self):
        t = sheet.Table(["가", "나", "다"], [["1"]])
        _line, row = sheet.find_rows(t)[0]
        self.assertEqual(row, ["1", None, None])

    def test_unknown_column_is_an_error(self):
        with self.assertRaises(sheet.SheetError):
            sheet.find_rows(self.table(),
                            [sheet.Condition.parse("eq", "없는열=값")])

    def test_where_still_works_after_sharing_the_test(self):
        # where 와 find_rows 가 같은 판정을 쓴다
        kept = sheet.where(self.table(),
                           [sheet.Condition.parse("has", "이름=철")])
        self.assertEqual(len(kept.rows), 1)


class ReadCellsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def form(self, name="양식.xlsx", who="홍길동", amount=1250000):
        path = self.root / name
        xlsx.write_sheets(path, {"요약": [["제목", "3월 보고"], [],
                                          ["담당자", who, "부서", "영업"],
                                          [], [], [], ["금액", amount]]},
                          header=False)
        return path

    def test_reads_by_excel_address(self):
        found = xlsx.read_cells(self.form(), ["B3", "D3", "B7"])
        self.assertEqual(found["B3"], "홍길동")
        self.assertEqual(found["D3"], "영업")
        self.assertEqual(found["B7"], 1250000)

    def test_missing_cell_is_none_not_an_error(self):
        self.assertIsNone(xlsx.read_cells(self.form(), ["Z99"])["Z99"])

    def test_bad_address(self):
        with self.assertRaises(xlsx.XlsxError):
            xlsx.split_ref("3B")
        with self.assertRaises(xlsx.XlsxError):
            xlsx.split_ref("B")

    def test_split_ref(self):
        self.assertEqual(xlsx.split_ref("A1"), (1, 0))
        self.assertEqual(xlsx.split_ref("AB12"), (12, 27))
        self.assertEqual(xlsx.split_ref("$B$3"), (3, 1))


class CollectCellsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def form(self, name, who, amount):
        path = self.root / name
        xlsx.write_sheets(path, {"요약": [["제목", "3월 보고"], [],
                                          ["담당자", who], [], [], [],
                                          ["금액", amount]]}, header=False)
        return path

    def specs(self):
        return [sheet.parse_cell("B3=담당자"), sheet.parse_cell("B7=금액")]

    def test_one_row_per_file(self):
        paths = [self.form("영업.xlsx", "홍길동", 100),
                 self.form("개발.xlsx", "김철수", 200)]
        table, skipped = sheet.collect_cells(paths, self.specs())
        self.assertEqual(table.headers, ["파일", "담당자", "금액"])
        self.assertEqual(table.rows[0], ["영업.xlsx", "홍길동", 100])
        self.assertEqual(skipped, [])

    def test_csv_uses_the_same_addresses(self):
        path = self.root / "인사.csv"
        path.write_text("제목,3월 보고\n\n담당자,이영희\n\n\n\n금액,300\n",
                        encoding="utf-8")
        table, _ = sheet.collect_cells([path], self.specs())
        self.assertEqual(table.rows[0], ["인사.csv", "이영희", 300])

    def test_file_with_a_different_form_stays_in_the_table(self):
        # 빠뜨린 파일이 조용히 사라지면 무엇이 안 왔는지 알 수 없다
        odd = self.root / "다른양식.csv"
        odd.write_text("아무것도 없음\n", encoding="utf-8")
        table, skipped = sheet.collect_cells([odd], self.specs())
        self.assertEqual(len(table.rows), 1)
        self.assertEqual(table.rows[0][1:], [None, None])
        self.assertEqual(skipped, [])

    def test_unreadable_file_is_reported_not_dropped_silently(self):
        bad = self.root / "메모.pdf"
        bad.write_text("x", encoding="utf-8")
        table, skipped = sheet.collect_cells([bad], self.specs())
        self.assertEqual(table.rows, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("지원하지 않는", skipped[0][1])

    def test_folder_is_reported(self):
        _table, skipped = sheet.collect_cells([self.root], self.specs())
        self.assertEqual(skipped[0][1], "폴더입니다")

    def test_parse_cell(self):
        self.assertEqual(sheet.parse_cell("b3=담당자"),
                         sheet.CellSpec("B3", "담당자"))
        self.assertEqual(sheet.parse_cell("C7").name, "C7")
        with self.assertRaises(sheet.SheetError):
            sheet.parse_cell("담당자")

    def test_no_specs_is_an_error(self):
        with self.assertRaises(sheet.SheetError):
            sheet.collect_cells([], [])


class TablesFromDocxTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, tables, name="보고서.docx"):
        from attools import docx

        parts = [docx.paragraph("보고")]
        for rows in tables:
            parts.append(docx.table(rows))
        path = self.root / name
        docx.write_document(path, parts)
        return path

    def test_first_row_becomes_the_headers(self):
        path = self.make([[["이름", "부서"], ["홍길동", "영업"]]])
        table = sheet.tables_from_docx(path)[0]
        self.assertEqual(table.headers, ["이름", "부서"])
        self.assertEqual(table.rows, [["홍길동", "영업"]])

    def test_numbers_are_read_as_numbers(self):
        path = self.make([[["이름", "금액"], ["홍길동", "1,200"]]])
        self.assertEqual(sheet.tables_from_docx(path)[0].rows[0][1], 1200)

    def test_blank_first_cell_keeps_the_row_as_data(self):
        # 병합 때문에 첫 줄이 비면 머리글을 지어내지 않고 자리만 만든다
        path = self.make([[["", "1월", "2월"], ["매출", "10", "20"]]])
        table = sheet.tables_from_docx(path)[0]
        self.assertEqual(table.headers, ["열1", "열2", "열3"])
        self.assertEqual(len(table.rows), 2)

    def test_duplicate_header_row_is_not_used_as_headers(self):
        path = self.make([[["값", "값"], ["1", "2"]]])
        self.assertEqual(sheet.tables_from_docx(path)[0].headers,
                         ["열1", "열2"])

    def test_every_table_in_order(self):
        path = self.make([[["가"], ["1"]], [["나"], ["2"]]])
        tables = sheet.tables_from_docx(path)
        self.assertEqual([t.sheet for t in tables], ["표1", "표2"])

    def test_document_without_tables(self):
        from attools import docx

        path = self.root / "글만.docx"
        docx.write_document(path, [docx.paragraph("표가 없다")])
        self.assertEqual(sheet.tables_from_docx(path), [])

    def test_not_a_word_file(self):
        bad = self.root / "가짜.docx"
        bad.write_text("zip 이 아니다", encoding="utf-8")
        with self.assertRaises(sheet.SheetError):
            sheet.tables_from_docx(bad)


class SimilarTest(unittest.TestCase):
    def test_normalize_strips_company_words(self):
        for name in ("(주)가나상사", "주식회사 가나상사", "㈜ 가나-상사", "가나 상사"):
            self.assertEqual(sheet.normalize_name(name), "가나상사")

    def test_english_tail_is_stripped_only_at_the_end(self):
        self.assertEqual(sheet.normalize_name("Gana Co.,Ltd"), "gana")
        # 이름 가운데서 떼면 딴 이름이 된다
        self.assertEqual(sheet.normalize_name("Incheon"), "incheon")

    def test_same_after_cleaning(self):
        t = sheet.Table(["상호"], [["(주)가나"], ["주식회사 가나"]])
        pairs, _cut = sheet.find_similar(t, "상호")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].reason, "표기만 다름")
        self.assertEqual((pairs[0].left_row, pairs[0].right_row), (2, 3))

    def test_one_character_typo_in_a_short_name(self):
        t = sheet.Table(["상호"], [["다라테크"], ["다라테그"]])
        pairs, _cut = sheet.find_similar(t, "상호")
        self.assertEqual(pairs[0].reason, "비슷함")

    def test_two_letter_names_are_left_alone(self):
        # 두 글자짜리는 한 글자만 달라도 딴 곳이다. 짐작하지 않는다
        t = sheet.Table(["상호"], [["마바"], ["마사"]])
        pairs, _cut = sheet.find_similar(t, "상호")
        self.assertEqual(pairs, [])

    def test_exactly_equal_values_are_not_pairs(self):
        # 똑같은 값은 at sheet dedupe 가 할 일이다
        t = sheet.Table(["상호"], [["가나"], ["가나"]])
        pairs, _cut = sheet.find_similar(t, "상호")
        self.assertEqual(pairs, [])

    def test_different_names_are_not_paired(self):
        t = sheet.Table(["상호"], [["가나상사"], ["마바무역"]])
        pairs, _cut = sheet.find_similar(t, "상호")
        self.assertEqual(pairs, [])

    def test_blank_cells_are_skipped(self):
        t = sheet.Table(["상호"], [[None], [""], ["가나"]])
        pairs, _cut = sheet.find_similar(t, "상호")
        self.assertEqual(pairs, [])

    def test_limit_reports_that_it_stopped(self):
        rows = [[f"가나상사{i}"] for i in range(10)]
        _pairs, cut = sheet.find_similar(sheet.Table(["상호"], rows), limit=3,
                                         column="상호")
        self.assertTrue(cut)

    def test_unknown_column(self):
        with self.assertRaises(sheet.SheetError):
            sheet.find_similar(sheet.Table(["상호"], [["가나"]]), "없는열")


class ToSqlTest(unittest.TestCase):
    def table(self):
        from datetime import date

        return sheet.Table(["사번", "이름", "입사일", "연봉", "재직"],
                           [["E1", "홍길동", date(2021, 3, 2), 52000000, True],
                            ["E2", "김'철수", None, 47000000, False]])

    def test_it_actually_runs_in_sqlite(self):
        import sqlite3

        body = sheet.to_sql(self.table(), "users", create=True)
        con = sqlite3.connect(":memory:")
        con.executescript(body)
        rows = con.execute("select 사번, 이름, 연봉 from users order by 사번").fetchall()
        self.assertEqual(rows, [("E1", "홍길동", 52000000),
                                ("E2", "김'철수", 47000000)])

    def test_blank_becomes_null_not_empty_text(self):
        import sqlite3

        con = sqlite3.connect(":memory:")
        con.executescript(sheet.to_sql(self.table(), "users", create=True))
        got = con.execute("select count(*) from users where 입사일 is null").fetchone()
        self.assertEqual(got[0], 1)

    def test_quote_in_a_value_is_doubled(self):
        self.assertIn("'김''철수'", sheet.to_sql(self.table(), "users"))

    def test_mysql_uses_backticks(self):
        body = sheet.to_sql(self.table(), "users", dialect="mysql")
        self.assertIn("INSERT INTO `users` (`사번`", body)

    def test_postgres_writes_true_and_false(self):
        body = sheet.to_sql(self.table(), "users", dialect="postgres")
        self.assertIn("TRUE", body)
        self.assertNotIn(", 1,", body)

    def test_batch_splits_the_statements(self):
        body = sheet.to_sql(self.table(), "users", batch=1)
        self.assertEqual(body.count("INSERT INTO"), 2)

    def test_column_type_falls_back_to_text_when_mixed(self):
        t = sheet.Table(["값"], [[1], ["글자"]])
        self.assertIn('"값" TEXT', sheet.to_sql(t, "t", create=True))

    def test_int_and_float_mix_becomes_a_float_type(self):
        t = sheet.Table(["값"], [[1], [1.5]])
        self.assertIn('"값" REAL', sheet.to_sql(t, "t", create=True))

    def test_identifier_quotes_inside_a_name_are_escaped(self):
        t = sheet.Table(['이"름'], [["가"]])
        self.assertIn('"이""름"', sheet.to_sql(t, "t"))

    def test_errors(self):
        for kwargs in ({"dialect": "oracle"}, {"batch": 0}):
            with self.assertRaises(sheet.SheetError):
                sheet.to_sql(self.table(), "users", **kwargs)
        with self.assertRaises(sheet.SheetError):
            sheet.to_sql(self.table(), "  ")
        with self.assertRaises(sheet.SheetError):
            sheet.to_sql(sheet.Table(["가"], []), "users")


class DatePartsTest(unittest.TestCase):
    def table(self):
        from datetime import date

        return sheet.Table(["주문일", "금액"],
                           [["2026-03-02", 100],
                            [date(2026, 12, 31), 200],
                            ["날짜아님", 300],
                            [None, 400]])

    def test_adds_columns_named_after_the_source(self):
        new, _failed = sheet.add_date_parts(self.table(), "주문일", ["요일", "연월"])
        self.assertEqual(new.headers[-2:], ["주문일 요일", "주문일 연월"])

    def test_values(self):
        new, _failed = sheet.add_date_parts(
            self.table(), "주문일", ["연도", "월", "일", "요일", "연월", "분기", "주차"])
        self.assertEqual(new.rows[0][2:],
                         [2026, 3, 2, "월", "2026-03", "2026 Q1", "2026-W10"])

    def test_week_number_carries_its_own_year(self):
        # 연말·연초의 주는 해가 넘어간다. 그래서 그 해를 붙여 둔다
        from datetime import date

        self.assertEqual(sheet.date_part(date(2027, 1, 1), "주차"), "2026-W53")

    def test_unreadable_cell_is_left_blank_and_reported(self):
        new, failed = sheet.add_date_parts(self.table(), "주문일", ["요일"])
        self.assertIsNone(new.rows[2][2])
        self.assertEqual(failed, [(4, "날짜아님")])

    def test_blank_cell_is_not_an_error(self):
        _new, failed = sheet.add_date_parts(self.table(), "주문일", ["요일"])
        self.assertNotIn(5, [line for line, _v in failed])

    def test_unknown_part(self):
        with self.assertRaises(sheet.SheetError):
            sheet.add_date_parts(self.table(), "주문일", ["별자리"])

    def test_no_parts(self):
        with self.assertRaises(sheet.SheetError):
            sheet.add_date_parts(self.table(), "주문일", [])

    def test_duplicate_header_gets_a_number(self):
        t = sheet.Table(["주문일", "주문일 요일"], [["2026-03-02", "월"]])
        new, _failed = sheet.add_date_parts(t, "주문일", ["요일"])
        self.assertEqual(len(set(new.headers)), len(new.headers))


class ReplaceValuesTest(unittest.TestCase):
    def table(self):
        from datetime import date

        return sheet.Table(["부서", "이름", "금액", "날짜"],
                           [["영업1팀", "홍길동", 1000, date(2026, 3, 2)],
                            ["영업2팀", "김철수", 2000, None],
                            ["개발팀", "영업1팀 지원", 3000, None]])

    def test_partial_match_by_default(self):
        new, rep = sheet.replace_values(self.table(), "영업1팀", "세일즈1팀")
        self.assertEqual(new.rows[0][0], "세일즈1팀")
        self.assertEqual(new.rows[2][1], "세일즈1팀 지원")
        self.assertEqual((rep.changed, rep.rows), (2, 2))
        self.assertEqual(rep.columns, ["부서", "이름"])

    def test_exact_only_matches_the_whole_cell(self):
        new, rep = sheet.replace_values(self.table(), "영업1팀", "세일즈1팀",
                                        exact=True)
        self.assertEqual(new.rows[2][1], "영업1팀 지원")   # 그대로
        self.assertEqual(rep.changed, 1)

    def test_column_scope(self):
        _new, rep = sheet.replace_values(self.table(), "영업1팀", "세일즈1팀",
                                         columns=["부서"])
        self.assertEqual(rep.columns, ["부서"])

    def test_numbers_are_left_alone_and_counted(self):
        # 글자로 바꿔 넣으면 그 열이 통째로 글자가 되어 합계가 어긋난다
        new, rep = sheet.replace_values(self.table(), "1000", "X")
        self.assertEqual(new.rows[0][2], 1000)
        self.assertEqual((rep.changed, rep.skipped_typed), (0, 1))

    def test_ignore_case(self):
        t = sheet.Table(["값"], [["Hello"], ["HELLO"]])
        new, rep = sheet.replace_values(t, "hello", "안녕", ignore_case=True)
        self.assertEqual([r[0] for r in new.rows], ["안녕", "안녕"])
        self.assertEqual(rep.changed, 2)

    def test_blank_cells_are_skipped(self):
        t = sheet.Table(["값"], [[None], [""]])
        _new, rep = sheet.replace_values(t, "가", "나")
        self.assertEqual(rep.changed, 0)

    def test_original_table_is_untouched(self):
        t = self.table()
        sheet.replace_values(t, "영업1팀", "세일즈1팀")
        self.assertEqual(t.rows[0][0], "영업1팀")

    def test_empty_needle_is_an_error(self):
        with self.assertRaises(sheet.SheetError):
            sheet.replace_values(self.table(), "", "가")

    def test_unknown_column(self):
        with self.assertRaises(sheet.SheetError):
            sheet.replace_values(self.table(), "가", "나", columns=["없는열"])


class OutlierTest(unittest.TestCase):
    def table(self, values):
        return sheet.Table(["금액"], [[v] for v in values])

    def steady(self):
        return [100, 105, 98, 102, 99, 101, 103, 97]

    def test_finds_both_ends(self):
        rep = sheet.find_outliers(self.table(self.steady() + [0, 100000]), "금액")
        sides = {o.side for o in rep.found}
        self.assertEqual(sides, {"높음", "낮음"})
        self.assertEqual({o.row for o in rep.found}, {10, 11})

    def test_nothing_when_values_are_alike(self):
        rep = sheet.find_outliers(self.table(self.steady()), "금액")
        self.assertEqual(rep.found, [])

    def test_too_few_numbers_says_so(self):
        rep = sheet.find_outliers(self.table([1, 2, 3]), "금액")
        self.assertIn("말할 수 없습니다", rep.note)
        self.assertEqual(rep.found, [])

    def test_all_same_value(self):
        rep = sheet.find_outliers(self.table([5] * 10), "금액")
        self.assertIn("모두 같아", rep.note)

    def test_sigma_is_dragged_by_the_outlier(self):
        # 그래서 기본을 iqr 로 두었다
        rows = self.steady() + [100000]
        iqr = sheet.find_outliers(self.table(rows), "금액")
        sigma = sheet.find_outliers(self.table(rows), "금액", method="sigma",
                                    factor=3)
        self.assertTrue(iqr.found)
        self.assertEqual(sigma.found, [])

    def test_text_numbers_are_read(self):
        rep = sheet.find_outliers(
            self.table(["100", "105", "98", "102", "99", "101", "103", "97",
                        "1,000,000"]), "금액")
        self.assertEqual(rep.counted, 9)
        self.assertEqual(len(rep.found), 1)

    def test_blank_and_text_are_skipped(self):
        rep = sheet.find_outliers(self.table(self.steady() + [None, "글자"]),
                                  "금액")
        self.assertEqual(rep.counted, 8)

    def test_bad_arguments(self):
        with self.assertRaises(sheet.SheetError):
            sheet.find_outliers(self.table([1]), "금액", method="마법")
        with self.assertRaises(sheet.SheetError):
            sheet.find_outliers(self.table([1]), "금액", factor=0)
        with self.assertRaises(sheet.SheetError):
            sheet.find_outliers(self.table([1]), "없는열")

    def test_quantile(self):
        values = [1, 2, 3, 4]
        self.assertEqual(sheet._quantile(values, 0.5), 2.5)
        self.assertEqual(sheet._quantile(values, 0.0), 1)
        self.assertEqual(sheet._quantile([], 0.5), 0.0)


class ExcelFormulaTest(unittest.TestCase):
    def headers(self):
        return ["이름", "수량", "단가"]

    def test_arithmetic_uses_a1_references(self):
        self.assertEqual(sheet.excel_formula("수량*단가", self.headers(), 2),
                         "(B2 * C2)")

    def test_row_number_follows(self):
        self.assertEqual(sheet.excel_formula("수량+1", self.headers(), 7),
                         "(B7 + 1)")

    def test_condition_becomes_if(self):
        got = sheet.excel_formula('"A" if 수량 > 3 else "B"', self.headers(), 2)
        self.assertEqual(got, 'IF((B2 > 3), "A", "B")')

    def test_functions_are_renamed(self):
        self.assertEqual(sheet.excel_formula("min(수량, 단가)", self.headers(), 2),
                         "MIN(B2, C2)")
        # 엑셀 ROUND 는 자릿수를 꼭 받는다
        self.assertEqual(sheet.excel_formula("round(수량)", self.headers(), 2),
                         "ROUND(B2, 0)")

    def test_modulo_and_power(self):
        self.assertEqual(sheet.excel_formula("수량 % 2", self.headers(), 2),
                         "MOD(B2, 2)")
        self.assertEqual(sheet.excel_formula("수량 ** 2", self.headers(), 2),
                         "(B2 ^ 2)")

    def test_quotes_in_text_are_doubled(self):
        self.assertEqual(sheet.excel_formula('\'큰"따옴표\'', self.headers(), 2),
                         '"큰""따옴표"')

    def test_column_with_spaces_uses_braces(self):
        headers = ["매출 합계", "수량"]
        self.assertEqual(sheet.excel_formula("{매출 합계}/수량", headers, 3),
                         "(A3 / B3)")

    def test_things_excel_cannot_do_are_refused(self):
        for bad in ("수량//2", "[1,2]", "sum(수량)", "1 < 수량 < 3"):
            with self.assertRaises(sheet.SheetError):
                sheet.excel_formula(bad, self.headers(), 2)

    def test_unknown_column(self):
        with self.assertRaises(sheet.SheetError):
            sheet.excel_formula("없는열*2", self.headers(), 2)


class FormulaColumnTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def table(self):
        return sheet.Table(["수량", "단가"], [[3, 1000], [5, 2000]])

    def test_cells_hold_formula_and_value(self):
        new, _rep = sheet.add_formula_column(self.table(), "금액", "수량*단가")
        cell = new.rows[0][2]
        self.assertIsInstance(cell, xlsx.Formula)
        self.assertEqual(cell.body, "(A2 * B2)")
        self.assertEqual(cell.cached, 3000)

    def test_xlsx_holds_both(self):
        import zipfile

        new, _rep = sheet.add_formula_column(self.table(), "금액", "수량*단가")
        path = self.root / "견적.xlsx"
        sheet.save(new, path)
        with zipfile.ZipFile(path) as z:
            body = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("<f>(A2 * B2)</f>", body)
        self.assertIn("<v>3000</v>", body)
        # 캐시된 값이 있어 우리 리더도 숫자로 읽는다
        self.assertEqual(xlsx.read_sheet(path)[1], [3, 1000, 3000])

    def test_csv_writes_the_formula_text(self):
        new, _rep = sheet.add_formula_column(self.table(), "금액", "수량*단가")
        path = self.root / "견적.csv"
        sheet.save(new, path)
        self.assertIn("=(A2 * B2)", path.read_text(encoding="utf-8-sig"))


class BadFileTest(unittest.TestCase):
    """잘못된 파일에 파이썬 역추적이 아니라 사람 말이 나오는지."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.fake = self.root / "가짜.xlsx"
        self.fake.write_text("zip 이 아니다", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_not_a_zip_is_a_sheet_error(self):
        with self.assertRaises(sheet.SheetError) as ctx:
            sheet.load(self.fake)
        self.assertIn("엑셀 파일이 아닙니다", str(ctx.exception))

    def test_describe_sheets_too(self):
        with self.assertRaises(sheet.SheetError):
            sheet.describe_sheets(self.fake)

    def test_xlsx_layer_says_what_to_do(self):
        with self.assertRaises(xlsx.XlsxError) as ctx:
            xlsx.sheet_names(self.fake)
        self.assertIn("xls", str(ctx.exception))

    def test_wrong_sheet_name_is_a_sheet_error(self):
        path = self.root / "진짜.xlsx"
        xlsx.write_sheets(path, {"8월": [["가"], ["1"]]})
        with self.assertRaises(sheet.SheetError) as ctx:
            sheet.load(path, sheet="10월")
        self.assertIn("있는 시트", str(ctx.exception))

    def test_missing_file(self):
        with self.assertRaises(sheet.SheetError):
            sheet.load(self.root / "없는것.xlsx")


class AuditTest(unittest.TestCase):
    def kinds(self, report):
        return {n.kind for n in report.notes}

    def test_empty_table_says_it_saw_nothing(self):
        rep = sheet.audit(sheet.Table(["가"], []))
        self.assertEqual(rep.notes, [])
        self.assertTrue(rep.skipped)

    def test_formula_looking_cells_are_reported(self):
        # 남이 보낸 표를 엑셀로 열면 = 로 시작하는 칸이 수식으로 실행된다
        table = sheet.Table(["이름", "메모"],
                            [["홍길동", '=cmd|" /C calc"!A0'],
                             ["김철수", "보통 메모"],
                             ["이영희", "+1234-보임"]])
        report = sheet.audit(table)
        self.assertIn("수식으로 읽힘", self.kinds(report))
        note = [n for n in report.notes if n.kind == "수식으로 읽힘"][0]
        self.assertEqual(note.column, "메모")
        self.assertIn("2개", note.detail)

    def test_numbers_are_not_formula_warnings(self):
        # 숫자로 읽힌 -5 는 글자가 아니라 수라 위험하지 않다
        table = sheet.Table(["값"], [[-5], [3], ["보통"]])
        self.assertNotIn("수식으로 읽힘", self.kinds(sheet.audit(table)))

    def test_missing_heavy_column(self):
        t = sheet.Table(["가"], [[None], [None], ["값"], ["값2"]])
        self.assertIn("빈 칸", self.kinds(sheet.audit(t)))

    def test_mixed_types(self):
        t = sheet.Table(["금액"], [[1], [2], ["글자"]])
        self.assertIn("타입 섞임", self.kinds(sheet.audit(t)))

    def test_duplicate_rows(self):
        t = sheet.Table(["가"], [["값"], ["값"]])
        self.assertIn("중복 행", self.kinds(sheet.audit(t)))

    def test_outlier_column(self):
        rows = [[v] for v in [100, 105, 98, 102, 99, 101, 103, 97, 100000]]
        self.assertIn("드문 값", self.kinds(sheet.audit(sheet.Table(["금액"], rows))))

    def test_private_columns(self):
        t = sheet.Table(["메일", "전화"],
                        [["a@a.com", "010-1111-2222"]] * 3)
        notes = [n for n in sheet.audit(t).notes if n.kind == "개인정보"]
        self.assertEqual({n.column for n in notes}, {"메일", "전화"})
        # 조사는 받침에 맞춰 붙인다
        self.assertTrue(any("이메일로" in n.detail for n in notes))

    def test_shaky_names(self):
        t = sheet.Table(["상호"], [["(주)가나"], ["주식회사 가나"], ["다라"]])
        self.assertIn("표기 흔들림", self.kinds(sheet.audit(t)))

    def test_clean_table_has_no_notes(self):
        t = sheet.Table(["사번", "이름"],
                        [["E1", "홍길동"], ["E2", "김철수"], ["E3", "이영희"]])
        self.assertEqual(sheet.audit(t).notes, [])

    def test_it_says_what_it_looked_at(self):
        # «문제 없음» 이 «다 봤다» 로 읽히면 안 된다
        rep = sheet.audit(sheet.Table(["가"], [["1"]]))
        self.assertTrue(rep.looked)


class DdayTest(unittest.TestCase):
    def table(self):
        return sheet.Table(["일감", "마감일"],
                           [["가", "2026-09-01"], ["나", "2026-09-07"],
                            ["다", "2026-12-25"], ["라", "언젠가"], ["마", None]])

    def today(self):
        from datetime import date

        return date(2026, 9, 7)

    def test_counts_days_and_states(self):
        new, _failed = sheet.add_dday(self.table(), "마감일", today=self.today())
        self.assertEqual([r[2] for r in new.rows[:3]], [-6, 0, 109])
        self.assertEqual([r[3] for r in new.rows[:3]], ["지남", "오늘", "남음"])

    def test_unreadable_cell_is_blank_and_reported(self):
        new, failed = sheet.add_dday(self.table(), "마감일", today=self.today())
        self.assertEqual(new.rows[3][2:], [None, None])
        self.assertEqual(failed, [(5, "언젠가")])

    def test_blank_cell_is_not_a_failure(self):
        _new, failed = sheet.add_dday(self.table(), "마감일", today=self.today())
        self.assertNotIn(6, [line for line, _v in failed])

    def test_headers_are_named_after_the_column(self):
        new, _failed = sheet.add_dday(self.table(), "마감일", today=self.today())
        self.assertEqual(new.headers[-2:], ["마감일 남은 일수", "마감일 상태"])

    def test_unknown_column(self):
        with self.assertRaises(sheet.SheetError):
            sheet.add_dday(self.table(), "없는열")


class OverwriteGuardTest(unittest.TestCase):
    """이미 있는 파일을 말없이 덮지 않는지. 되돌릴 방법이 없는 자리다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.source = self.root / "직원.csv"
        self.source.write_text("사번,이름\nE1,홍길동\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_cli(self, *args):
        import contextlib
        import io

        from attools import cli

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(list(args))
        return code, out.getvalue()

    def test_second_run_is_refused(self):
        target = self.root / "이름만.csv"
        code, _out = self.run_cli("sheet", "cut", str(self.source), "-c", "이름",
                                  "-o", str(target))
        self.assertEqual(code, 0)
        before = target.read_text(encoding="utf-8")

        code, out = self.run_cli("sheet", "cut", str(self.source), "-c", "사번",
                                 "-o", str(target))
        self.assertEqual(code, 1)
        self.assertIn("이미 있는 파일", out)
        self.assertEqual(target.read_text(encoding="utf-8"), before)   # 그대로다

    def test_overwrite_flag_writes(self):
        target = self.root / "이름만.csv"
        self.run_cli("sheet", "cut", str(self.source), "-c", "이름",
                     "-o", str(target))
        code, _out = self.run_cli("sheet", "cut", str(self.source), "-c", "사번",
                                  "-o", str(target), "--overwrite")
        self.assertEqual(code, 0)
        self.assertIn("사번", target.read_text(encoding="utf-8"))

    def test_new_file_is_fine(self):
        code, _out = self.run_cli("sheet", "cut", str(self.source), "-c", "이름",
                                  "-o", str(self.root / "처음.csv"))
        self.assertEqual(code, 0)


class IcsTest(unittest.TestCase):
    def setUp(self):
        from datetime import date, datetime, time
        self.date, self.datetime, self.time = date, datetime, time
        self.table = sheet.Table(
            ["일정", "시작", "끝", "장소", "비고"],
            [["킥오프", "2026-03-04 14:30", "2026-03-04 16:00", "회의실", "가, 나"],
             ["워크숍", "2026-03-10", "2026-03-12", "양평", ""],
             ["", "2026-03-11", "", "", ""],
             ["미정", "언젠가", "", "", ""]])

    def build(self, **kw):
        return sheet.events_from_table(self.table, summary="일정",
                                       start="시작", end="끝", **kw)

    # ---- 날짜·시각 읽기

    def test_reads_date_with_clock(self):
        self.assertEqual(sheet.parse_when("2026-03-04 14:30"),
                         (self.date(2026, 3, 4), self.time(14, 30)))

    def test_reads_korean_afternoon(self):
        self.assertEqual(sheet.parse_when("2026.3.4 오후 2시"),
                         (self.date(2026, 3, 4), self.time(14, 0)))

    def test_date_only_has_no_clock(self):
        self.assertEqual(sheet.parse_when("2026-03-04"),
                         (self.date(2026, 3, 4), None))

    def test_impossible_clock_is_not_guessed(self):
        self.assertIsNone(sheet.parse_when("2026-03-04 12:70"))

    def test_no_date_at_all(self):
        self.assertIsNone(sheet.parse_when("언젠가"))
        self.assertIsNone(sheet.parse_when(""))

    def test_datetime_cell(self):
        got = sheet.parse_when(self.datetime(2026, 3, 4, 9, 5))
        self.assertEqual(got, (self.date(2026, 3, 4), self.time(9, 5)))

    # ---- 표 -> 일정

    def test_bad_rows_are_skipped_not_filled(self):
        events, skipped = self.build()
        self.assertEqual([e.summary for e in events], ["킥오프", "워크숍"])
        self.assertEqual([line for line, _why in skipped], [4, 5])

    def test_all_day_when_no_clock(self):
        events, _skipped = self.build()
        self.assertTrue(events[1].all_day)
        self.assertFalse(events[0].all_day)

    def test_end_before_start_is_skipped(self):
        table = sheet.Table(["일정", "시작", "끝"],
                            [["거꾸로", "2026-03-10", "2026-03-01"]])
        events, skipped = sheet.events_from_table(table, summary="일정",
                                                  start="시작", end="끝")
        self.assertEqual(events, [])
        self.assertIn("앞섭니다", skipped[0][1])

    # ---- ics 만들기

    def body(self, **kw):
        events, _skipped = self.build()
        kw.setdefault("now", self.datetime(2026, 1, 1, 0, 0))
        return sheet.to_ics(events, **kw)

    def test_all_day_end_gets_one_more_day(self):
        # ics 의 DTEND 는 «그 다음 날» 이라 12일까지 쉬면 13일로 적어야 한다
        self.assertIn("DTEND;VALUE=DATE:20260313", self.body())

    def test_timed_event_carries_seoul_zone(self):
        out = self.body()
        self.assertIn("DTSTART;TZID=Asia/Seoul:20260304T143000", out)
        self.assertIn("TZID:Asia/Seoul", out)

    def test_lines_end_with_crlf(self):
        self.assertTrue(self.body().endswith("END:VCALENDAR\r\n"))

    def test_alarm_is_optional(self):
        self.assertNotIn("VALARM", self.body())
        self.assertIn("TRIGGER:-PT30M", self.body(alarm=30))

    def test_default_length_when_no_end_time(self):
        table = sheet.Table(["일정", "시작"], [["회의", "2026-03-04 09:00"]])
        events, _skipped = sheet.events_from_table(table, summary="일정",
                                                   start="시작")
        out = sheet.to_ics(events, minutes=30)
        self.assertIn("DTEND;TZID=Asia/Seoul:20260304T093000", out)

    def test_same_event_keeps_same_uid(self):
        first = sheet.Event("회의", self.date(2026, 3, 4))
        second = sheet.Event("회의", self.date(2026, 3, 4))
        other = sheet.Event("회식", self.date(2026, 3, 4))
        self.assertEqual(sheet._event_uid(first), sheet._event_uid(second))
        self.assertNotEqual(sheet._event_uid(first), sheet._event_uid(other))

    # ---- 형식

    def test_escapes_comma_and_newline(self):
        self.assertEqual(sheet.ics_escape("가, 나; 다"), "가\\, 나\\; 다")
        self.assertEqual(sheet.ics_escape("한\n줄"), "한\\n줄")

    def test_folds_long_lines_without_cutting_hangul(self):
        line = "SUMMARY:" + "가" * 60
        folded = sheet.fold_line(line)
        self.assertGreater(len(folded), 1)
        for piece in folded:
            self.assertLessEqual(len(piece.encode("utf-8")), 75)
        self.assertTrue(all(p.startswith(" ") for p in folded[1:]))
        self.assertEqual("".join([folded[0]] + [p[1:] for p in folded[1:]]),
                         line)

    def test_folded_output_can_be_unfolded_back(self):
        table = sheet.Table(["일정", "시작"], [["아주 긴 " + "회의" * 40,
                                               "2026-03-04"]])
        events, _skipped = sheet.events_from_table(table, summary="일정",
                                                   start="시작")
        out = sheet.to_ics(events).replace("\r\n ", "")
        self.assertIn("SUMMARY:아주 긴 " + "회의" * 40, out)


class AgeTest(unittest.TestCase):
    def setUp(self):
        from datetime import date, datetime
        self.date, self.datetime = date, datetime
        self.table = sheet.Table(
            ["이름", "생년월일"],
            [["가", "1990-05-06"], ["나", "900101-2345678"],   # attools: ignore
             ["다", "몰라"], ["라", ""], ["마", "051231-4000000"]])   # attools: ignore

    def build(self, **kw):
        kw.setdefault("on", self.date(2026, 3, 1))
        return sheet.add_age(self.table, "생년월일", **kw)

    def test_reads_plain_birthday(self):
        self.assertEqual(sheet.parse_birth("1990-05-06"),
                         (self.date(1990, 5, 6), ""))

    def test_reads_rrn_century_and_sex(self):
        self.assertEqual(sheet.parse_birth("900101-2345678"),   # attools: ignore
                         (self.date(1990, 1, 1), "여"))
        self.assertEqual(sheet.parse_birth("051231-4000000"),   # attools: ignore
                         (self.date(2005, 12, 31), "여"))
        self.assertEqual(sheet.parse_birth("051231-3000000"),   # attools: ignore
                         (self.date(2005, 12, 31), "남"))

    def test_six_digits_alone_are_not_guessed(self):
        # 900101 이 1990년인지 2090년인지 정할 근거가 없다
        self.assertIsNone(sheet.parse_birth("900101"))

    def test_impossible_birthday_is_not_read(self):
        self.assertIsNone(sheet.parse_birth("901301-1234567"))   # attools: ignore
        self.assertIsNone(sheet.parse_birth("몰라"))

    def test_age_is_korean_age(self):
        result, _report = self.build()
        self.assertEqual(result.rows[0][2], 35)      # 생일 전이라 한 살 적다
        self.assertEqual(result.rows[1][2], 36)

    def test_unreadable_cells_stay_empty(self):
        result, report = self.build()
        self.assertIsNone(result.rows[2][2])
        self.assertIsNone(result.rows[3][2])
        self.assertEqual([line for line, _raw in report.failed], [4])
        self.assertEqual(report.read, 3)

    def test_group_column_is_optional(self):
        plain, _r = self.build()
        self.assertEqual(plain.headers, ["이름", "생년월일", "생년월일 만나이"])
        grouped, _r = self.build(group=True)
        self.assertEqual(grouped.rows[0][3], "30대")

    def test_sex_only_from_rrn(self):
        result, report = self.build(sex=True)
        self.assertIsNone(result.rows[0][3])
        self.assertEqual(result.rows[1][3], "여")
        self.assertEqual(report.sexed, 2)

    def test_bucket_edges(self):
        self.assertEqual(sheet.age_bucket(0), "10세 미만")
        self.assertEqual(sheet.age_bucket(9), "10세 미만")
        self.assertEqual(sheet.age_bucket(10), "10대")
        self.assertEqual(sheet.age_bucket(39), "30대")
        self.assertEqual(sheet.age_bucket(101), "100세 이상")


class VcardTest(unittest.TestCase):
    def setUp(self):
        self.table = sheet.Table(
            ["이름", "회사", "직함", "휴대전화", "전화", "메일", "주소"],
            [["홍길동", "(주)가나", "팀장", "010-1234-5678", "02-100-2000",
              "a@b.com", "서울시 중구 세종대로 1, 2층"],
             ["", "다라", "", "", "", "", ""]])

    def build(self, **kw):
        kw.setdefault("company", "회사")
        kw.setdefault("mobile", "휴대전화")
        return sheet.contacts_from_table(self.table, name="이름", **kw)

    def test_rows_without_a_name_are_skipped(self):
        people, skipped = self.build()
        self.assertEqual([p.name for p in people], ["홍길동"])
        self.assertEqual(skipped, [(3, "이름이 비었습니다")])

    def test_phone_kinds(self):
        people, _skipped = self.build(phone="전화")
        self.assertEqual(people[0].phones,
                         [("CELL", "010-1234-5678"), ("WORK", "02-100-2000")])

    def test_name_is_not_split(self):
        # 남궁·제갈 같은 두 자 성을 잘못 자르느니 통째로 넣는다
        out = sheet.to_vcard([sheet.Contact("남궁민수")])
        self.assertIn("N:남궁민수;;;;", out)
        self.assertIn("FN:남궁민수", out)

    def test_optional_fields_are_left_out(self):
        out = sheet.to_vcard([sheet.Contact("가")])
        self.assertNotIn("ORG:", out)
        self.assertNotIn("EMAIL", out)
        self.assertNotIn("ADR", out)

    def test_full_card(self):
        people, _skipped = self.build(title="직함", email="메일",
                                      address="주소")
        out = sheet.to_vcard(people)
        self.assertIn("ORG:(주)가나", out)
        self.assertIn("TITLE:팀장", out)
        self.assertIn("EMAIL;TYPE=INTERNET:a@b.com", out)
        self.assertIn("ADR;TYPE=WORK:;;서울시 중구 세종대로 1\\, 2층;;;;", out)
        self.assertTrue(out.endswith("END:VCARD\r\n"))

    def test_empty_list_makes_empty_text(self):
        self.assertEqual(sheet.to_vcard([]), "")

    def test_long_line_is_folded(self):
        out = sheet.to_vcard([sheet.Contact("가" * 60)])
        for line in out.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75)


class ReadCardTest(unittest.TestCase):
    VCF = ("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:홍길동\r\nORG:(주)가나;영업\r\n"
           "TITLE:팀장\r\nTEL;TYPE=CELL:010-1234-5678\r\n"
           "TEL;TYPE=WORK:02-100-2000\r\nEMAIL;TYPE=INTERNET:a@b.com\r\n"
           "ADR;TYPE=WORK:;;서울시 중구 1\\, 2층;;;;\r\nEND:VCARD\r\n")

    def test_reads_one_card(self):
        table = sheet.read_vcards(self.VCF)
        row = dict(zip(table.headers, table.rows[0]))
        self.assertEqual(row["이름"], "홍길동")
        self.assertEqual(row["회사"], "(주)가나 영업")
        self.assertEqual(row["직함"], "팀장")
        self.assertEqual(row["휴대전화"], "010-1234-5678")
        self.assertEqual(row["전화"], "02-100-2000")
        self.assertEqual(row["주소"], "서울시 중구 1, 2층")

    def test_unfolds_long_lines(self):
        text = "BEGIN:VCARD\r\nFN:홍길\r\n 동\r\nEND:VCARD\r\n"
        self.assertEqual(sheet.read_vcards(text).rows[0][0], "홍길동")

    def test_name_falls_back_to_n(self):
        text = "BEGIN:VCARD\r\nN:남궁;민수;;;\r\nEND:VCARD\r\n"
        self.assertEqual(sheet.read_vcards(text).rows[0][0], "남궁 민수")

    def test_quoted_printable_from_old_phones(self):
        text = ("BEGIN:VCARD\r\nFN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:"
                "=ED=99=8D=EA=B8=B8=EB=8F=99\r\nEND:VCARD\r\n")
        self.assertEqual(sheet.read_vcards(text).rows[0][0], "홍길동")

    def test_round_trip(self):
        people = [sheet.Contact("가나다", company="회사", email="a@b.com",
                                phones=[("CELL", "010-1")])]
        table = sheet.read_vcards(sheet.to_vcard(people))
        row = dict(zip(table.headers, table.rows[0]))
        self.assertEqual(row["이름"], "가나다")
        self.assertEqual(row["휴대전화"], "010-1")

    # ---- ics

    ICS = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:워크숍\r\n"
           "DTSTART;VALUE=DATE:20260310\r\nDTEND;VALUE=DATE:20260313\r\n"
           "LOCATION:양평\r\nBEGIN:VALARM\r\nDESCRIPTION:워크숍\r\n"
           "END:VALARM\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")

    def test_all_day_end_comes_back_inclusive(self):
        row = dict(zip(sheet.ICS_HEADERS, sheet.read_ics(self.ICS).rows[0]))
        self.assertEqual(row["시작"], "2026-03-10")
        self.assertEqual(row["끝"], "2026-03-12")     # 파일에는 13일로 들어 있다
        self.assertEqual(row["종일"], "예")

    def test_alarm_description_is_not_the_event_description(self):
        row = dict(zip(sheet.ICS_HEADERS, sheet.read_ics(self.ICS).rows[0]))
        self.assertEqual(row["설명"], "")

    def test_timed_event(self):
        text = ("BEGIN:VEVENT\r\nSUMMARY:회의\r\n"
                "DTSTART;TZID=Asia/Seoul:20260304T143000\r\n"
                "DTEND;TZID=Asia/Seoul:20260304T160000\r\nEND:VEVENT\r\n")
        row = dict(zip(sheet.ICS_HEADERS, sheet.read_ics(text).rows[0]))
        self.assertEqual(row["시작"], "2026-03-04 14:30")
        self.assertEqual(row["종일"], "")

    def test_unreadable_moment_is_kept_as_is(self):
        text = "BEGIN:VEVENT\r\nSUMMARY:가\r\nDTSTART:언제나\r\nEND:VEVENT\r\n"
        row = dict(zip(sheet.ICS_HEADERS, sheet.read_ics(text).rows[0]))
        self.assertEqual(row["시작"], "언제나")

    def test_nothing_to_read(self):
        self.assertEqual(sheet.read_ics("아무것도 아님").rows, [])
        self.assertEqual(sheet.read_vcards("").rows, [])


class MailDraftTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.attach = self.root / "명세서.pdf"
        self.attach.write_bytes(b"%PDF-1.4 fake")
        self.table = sheet.Table(
            ["이름", "메일", "금액", "첨부"],
            [["홍길동", "a@b.com", 120000, str(self.attach)],
             ["김철수", "없음", 5000, ""],
             ["박영희", "c@d.com", 7000, str(self.root / "없다.pdf")]])

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def build(self, **kw):
        kw.setdefault("template", "{이름}님, {금액:,}원입니다.\n")
        kw.setdefault("subject", "{이름}님 정산")
        kw.setdefault("to", "메일")
        return sheet.build_mails(self.table, **kw)

    def test_fills_subject_and_body(self):
        drafts, _missing = self.build()
        self.assertEqual(drafts[0].subject, "홍길동님 정산")
        self.assertIn("120,000원", drafts[0].body)

    def test_bad_address_is_a_problem_not_a_guess(self):
        drafts, _missing = self.build()
        self.assertFalse(drafts[1].ok)
        self.assertIn("메일 주소", drafts[1].problem)

    def test_missing_attachment_stops_that_row(self):
        drafts, _missing = self.build(attach="첨부")
        self.assertEqual([p.name for p in drafts[0].attachments],
                         ["명세서.pdf"])
        self.assertFalse(drafts[2].ok)
        self.assertIn("첨부를 찾지 못했습니다", drafts[2].problem)

    def test_missing_placeholder_is_reported(self):
        _drafts, missing = self.build(template="{부서} 앞")
        self.assertEqual(missing, {"부서"})

    def test_split_addresses(self):
        good, bad = sheet.split_addresses("a@b.com; c@d.com, 없음")
        self.assertEqual(good, ["a@b.com", "c@d.com"])
        self.assertEqual(bad, ["없음"])

    def test_eml_has_korean_subject_and_body(self):
        drafts, _missing = self.build(attach="첨부")
        raw = sheet.to_eml(drafts[0], sender="me@corp.com")
        import email

        message = email.message_from_bytes(raw)
        self.assertEqual(message["To"], "a@b.com")
        self.assertEqual(message["From"], "me@corp.com")
        self.assertEqual(str(email.header.make_header(
            email.header.decode_header(message["Subject"]))), "홍길동님 정산")
        # 아웃룩이 초안으로 열게 하는 표시
        self.assertEqual(message["X-Unsent"], "1")
        parts = list(message.walk())
        self.assertIn("명세서.pdf",
                      [p.get_filename() for p in parts])
        body = [p for p in parts if p.get_content_type() == "text/plain"][0]
        self.assertIn("120,000원",
                      body.get_payload(decode=True).decode("utf-8"))

    def test_empty_subject_is_a_problem(self):
        drafts, _missing = self.build(subject="{없는열}")
        self.assertIn("제목이 비었습니다", drafts[0].problem)


class CellDiffTest(unittest.TestCase):
    def setUp(self):
        self.before = sheet.Table(["이름", "금액"], [["가", 100], ["나", 200]])

    def test_no_change(self):
        got = sheet.diff_cells(self.before, self.before)
        self.assertTrue(got.empty)
        self.assertEqual(got.changes, [])

    def test_changed_cell_has_excel_address(self):
        after = sheet.Table(["이름", "금액"], [["가", 150], ["나", 200]])
        change = sheet.diff_cells(self.before, after).changes[0]
        self.assertEqual(change.ref, "B2")     # 머리글이 1행이다
        self.assertEqual(change.column, "금액")
        self.assertEqual((change.before, change.after), ("100", "150"))

    def test_added_row_and_column(self):
        after = sheet.Table(["이름", "금액", "비고"],
                            [["가", 100], ["나", 200], ["다", 300]])
        got = sheet.diff_cells(self.before, after)
        self.assertEqual(got.rows_after, 3)
        self.assertEqual(got.columns_after, 3)
        self.assertEqual([c.ref for c in got.changes], ["A4", "B4"])

    def test_limit_marks_that_it_was_cut(self):
        big = sheet.Table(["가"], [[str(n)] for n in range(50)])
        other = sheet.Table(["가"], [[str(n + 1)] for n in range(50)])
        got = sheet.diff_cells(big, other, limit=10)
        self.assertTrue(got.cut)
        self.assertEqual(len(got.changes), 10)

    def test_shifted_row_shows_everything_below(self):
        # 자리로만 견주므로 한 줄 밀리면 아래가 다 달라 보인다. 그래서 안내를 단다
        after = sheet.Table(["이름", "금액"],
                            [["새로", 1], ["가", 100], ["나", 200]])
        self.assertEqual(len(sheet.diff_cells(self.before, after).changes), 6)


class CompareFormsTest(unittest.TestCase):
    """받은 파일들의 서식 견주기. 합치기 전에 보는 자리다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, name: str, body: str) -> Path:
        path = self.root / name
        path.write_text(body, encoding="utf-8")
        return path

    def build(self):
        self.write("영업.csv", "사번,이름,금액\nE1,홍길동,100\n")
        self.write("개발.csv", "사번,이름,금액\nE2,김철수,200\n")
        self.write("인사.csv", "사번,이름,금액,비고\nE3,이영희,300,추가\n")
        self.write("총무.csv", "이름,사번,금액\n박영희,E4,400\n")
        return sheet.compare_forms(sorted(self.root.iterdir()))

    def test_standard_is_the_most_common_shape(self):
        report = self.build()
        self.assertEqual(report.standard, ["사번", "이름", "금액"])
        self.assertEqual(report.common, 2)

    def test_extra_column_is_named(self):
        found = {c.path.name: c for c in self.build().checks}
        self.assertEqual(found["인사.csv"].extra, ["비고"])
        self.assertFalse(found["인사.csv"].same)

    def test_reordered_columns_are_reported(self):
        # 열 이름은 같은데 순서가 다른 파일. 자리로 합치면 값이 엇갈린다
        found = {c.path.name: c for c in self.build().checks}
        self.assertTrue(found["총무.csv"].reordered)
        self.assertEqual(found["총무.csv"].missing, [])

    def test_same_files_are_marked_same(self):
        found = {c.path.name: c for c in self.build().checks}
        self.assertTrue(found["영업.csv"].same)
        self.assertTrue(found["개발.csv"].same)

    def test_missing_column(self):
        self.write("가.csv", "사번,이름,금액\nE1,가,1\n")
        self.write("나.csv", "사번,이름,금액\nE2,나,2\n")
        self.write("다.csv", "사번,이름\nE3,다\n")
        found = {c.path.name: c for c in
                 sheet.compare_forms(sorted(self.root.iterdir())).checks}
        self.assertEqual(found["다.csv"].missing, ["금액"])

    def test_unreadable_file_is_kept_with_a_reason(self):
        self.write("가.csv", "사번\nE1\n")
        (self.root / "깨짐.xlsx").write_bytes(b"not a zip")
        report = sheet.compare_forms(sorted(self.root.iterdir()))
        broken = [c for c in report.checks if c.path.name == "깨짐.xlsx"][0]
        self.assertTrue(broken.error)
        self.assertFalse(broken.same)

    def test_nothing_readable(self):
        (self.root / "깨짐.xlsx").write_bytes(b"not a zip")
        report = sheet.compare_forms([self.root / "깨짐.xlsx"])
        self.assertEqual(report.standard, [])
        self.assertEqual(report.odd, report.checks)


class WorkTimeTest(unittest.TestCase):
    """근무 시간 셈. 휴게와 자정 넘김을 어떻게 봤는지가 중요하다."""

    def setUp(self):
        self.table = sheet.Table(
            ["날짜", "출근", "퇴근"],
            [["2026-03-02", "09:00", "18:00"],
             ["2026-03-03", "09:00", "21:30"],
             ["2026-03-04", "22:00", "06:00"],
             ["2026-03-05", "", ""],
             ["2026-03-06", "아홉시", "18:00"]])

    def days(self, **kw):
        kw.setdefault("start", "출근")
        kw.setdefault("end", "퇴근")
        kw.setdefault("date", "날짜")
        return sheet.work_days(self.table, **kw)

    def test_legal_break_is_taken_out(self):
        days, _table = self.days()
        self.assertEqual(days[0].minutes, 540)      # 아홉 시간 자리에 있었고
        self.assertEqual(days[0].rest, 60)          # 여덟 시간 넘으면 한 시간
        self.assertEqual(days[0].worked, 480)

    def test_break_can_be_given(self):
        days, _table = self.days(rest=30)
        self.assertEqual(days[0].worked, 510)

    def test_short_day_gets_thirty_minutes(self):
        table = sheet.Table(["출근", "퇴근"], [["09:00", "14:00"]])
        days, _t = sheet.work_days(table, start="출근", end="퇴근")
        self.assertEqual((days[0].minutes, days[0].rest), (300, 30))

    def test_overnight_shift(self):
        days, _table = self.days()
        night = days[2]
        self.assertTrue(night.overnight)
        self.assertEqual(night.minutes, 480)        # 22시 -> 다음 날 6시

    def test_blank_row_is_a_day_off(self):
        days, _table = self.days()
        self.assertEqual(days[3].problem, "빈 칸")
        self.assertEqual(days[3].worked, 0)

    def test_unreadable_time_is_reported_not_guessed(self):
        days, table = self.days()
        self.assertIn("읽지 못했습니다", days[4].problem)
        self.assertIsNone(table.rows[4][-2])        # 실근무 칸을 비워 둔다

    def test_added_columns(self):
        _days, table = self.days()
        self.assertEqual(table.headers[-4:],
                         ["체류(시간)", "휴게(분)", "실근무(시간)", "자정 넘김"])

    def test_weekly_totals_start_on_monday(self):
        from datetime import date

        days, _table = self.days()
        weeks = sheet.work_weeks(days)
        self.assertEqual(weeks[0][0], date(2026, 3, 2))   # 월요일
        self.assertEqual(weeks[0][1], 480 + 690 + 420)

    def test_clock_formats(self):
        from datetime import datetime, time

        self.assertEqual(sheet.parse_clock("9:05"), time(9, 5))
        self.assertEqual(sheet.parse_clock("9시"), time(9, 0))
        self.assertEqual(sheet.parse_clock("18시 30"), time(18, 30))
        self.assertEqual(sheet.parse_clock(datetime(1899, 12, 30, 9, 0)),
                         time(9, 0))
        self.assertEqual(sheet.parse_clock("0.375"), time(9, 0))
        self.assertIsNone(sheet.parse_clock("25:00"))
        self.assertIsNone(sheet.parse_clock(""))


if __name__ == "__main__":
    unittest.main()
