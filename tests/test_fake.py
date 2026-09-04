"""시험용 가짜 자료 만들기 시험."""

import unittest
from datetime import date
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import fakedata, sheet


class FakeDataTest(unittest.TestCase):
    def test_seed_repeats_the_same_rows(self):
        fields = [fakedata.parse_field("이름"), fakedata.parse_field("금액=금액:1000:2000")]
        first = fakedata.make_rows(fields, 5, seed=42)
        second = fakedata.make_rows(fields, 5, seed=42)
        self.assertEqual(first, second)

    def test_generated_bizno_passes_the_checker(self):
        _, rows = fakedata.make_rows([fakedata.parse_field("사업자번호")], 20, seed=1)
        self.assertTrue(all(sheet.check_bizno(r[0]) for r in rows))

    def test_generated_phone_and_email_pass_format_checks(self):
        fields = [fakedata.parse_field("전화"), fakedata.parse_field("이메일")]
        _, rows = fakedata.make_rows(fields, 20, seed=2)
        self.assertTrue(all(sheet.FORMAT_CHECKS["휴대폰"](r[0]) for r in rows))
        self.assertTrue(all(sheet.FORMAT_CHECKS["이메일"](r[1]) for r in rows))

    def test_column_name_defaults_to_kind(self):
        self.assertEqual(fakedata.parse_field("이름").label, "이름")
        self.assertEqual(fakedata.parse_field("연락처=전화").label, "연락처")

    def test_ranges_are_respected(self):
        field = fakedata.parse_field("금액=정수:5:9")
        _, rows = fakedata.make_rows([field], 30, seed=3)
        self.assertTrue(all(5 <= r[0] <= 9 for r in rows))

    def test_date_range_counts_back_from_today(self):
        field = fakedata.parse_field("가입일=날짜:10")
        today = date(2026, 9, 4)
        _, rows = fakedata.make_rows([field], 20, seed=4, today=today)
        self.assertTrue(all(date(2026, 8, 25) <= r[0] <= today for r in rows))

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(fakedata.FakeError):
            fakedata.parse_field("주민번호")          # 만들 생각이 없는 것도 조용히 안 만든다

    def test_broken_range_is_refused(self):
        with self.assertRaises(fakedata.FakeError):
            fakedata.parse_field("금액=정수:abc")
        with self.assertRaises(fakedata.FakeError):
            fakedata.parse_field("금액=정수:9:1")

    def test_needs_fields_and_rows(self):
        with self.assertRaises(fakedata.FakeError):
            fakedata.make_rows([], 3)
        with self.assertRaises(fakedata.FakeError):
            fakedata.make_rows([fakedata.parse_field("이름")], 0)


if __name__ == "__main__":
    unittest.main()
