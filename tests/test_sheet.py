"""표 모델과 csv/xlsx 입출력 시험."""

import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import report, sheet, text, xlsx


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


if __name__ == "__main__":
    unittest.main()
