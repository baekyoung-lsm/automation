"""일상 계산: D-day, 대출, 세금, 적금 시험."""

import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import life


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


class TaxSavingTest(unittest.TestCase):
    def test_vat_add(self):
        v = life.vat_add(1_000_000)
        self.assertEqual((v.supply, v.vat, v.total), (1_000_000, 100_000, 1_100_000))

    def test_vat_extract_is_exact_for_round_amounts(self):
        v = life.vat_extract(1_100_000)
        self.assertEqual((v.supply, v.vat), (1_000_000, 100_000))

    def test_vat_extract_parts_always_sum_to_total(self):
        for amount in (1000, 1234567, 33333, 999, 11000):
            v = life.vat_extract(amount)
            self.assertEqual(v.supply + v.vat, amount, amount)

    def test_vat_rate_can_change(self):
        self.assertEqual(life.vat_add(1000, rate=0).vat, 0)

    def test_withhold_takes_local_tax_from_income_tax(self):
        w = life.withhold(3_000_000)
        self.assertEqual((w.income_tax, w.local_tax), (90_000, 9_000))
        self.assertEqual(w.net, 2_901_000)
        self.assertAlmostEqual(w.rate, 3.3)

    def test_withhold_other_income_rate(self):
        w = life.withhold(1_000_000, rate=8)
        self.assertEqual((w.income_tax, w.local_tax, w.net), (80_000, 8_000, 912_000))

    def test_saving_monthly_uses_declining_periods(self):
        s = life.saving_plan(monthly=500_000, months=24, annual_rate=3.5)
        self.assertEqual(s.kind, "적금")
        self.assertEqual(s.principal, 12_000_000)
        self.assertEqual(s.interest, 437_500)      # 월이자 x 24x25/2
        self.assertEqual(s.tax, 67_375)
        self.assertEqual(s.total, 12_370_125)

    def test_saving_deposit_is_simple_interest(self):
        s = life.saving_plan(deposit=10_000_000, months=12, annual_rate=3.5, tax_rate=0)
        self.assertEqual((s.kind, s.interest, s.tax), ("예금", 350_000, 0))
        self.assertAlmostEqual(s.effective, 3.5, places=2)

    def test_saving_effective_rate_is_lower_than_nominal(self):
        s = life.saving_plan(monthly=100_000, months=12, annual_rate=4, tax_rate=0)
        self.assertLess(s.effective, 4)

    def test_saving_needs_exactly_one_kind(self):
        with self.assertRaises(ValueError):
            life.saving_plan(months=12, annual_rate=3)
        with self.assertRaises(ValueError):
            life.saving_plan(monthly=1, deposit=1, months=12, annual_rate=3)
        with self.assertRaises(ValueError):
            life.saving_plan(deposit=1000, months=0, annual_rate=3)


if __name__ == "__main__":
    unittest.main()
