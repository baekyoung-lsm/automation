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


class TimezoneTest(unittest.TestCase):
    def test_alias_and_iana_names_both_work(self):
        self.assertEqual(str(life.zone_of("서울")), "Asia/Seoul")
        self.assertEqual(str(life.zone_of("Asia/Tokyo")), "Asia/Tokyo")

    def test_unknown_zone_is_reported(self):
        with self.assertRaises(life.ZoneError):
            life.zone_of("어딘가")

    def test_zone_times_sorted_by_offset(self):
        from datetime import datetime

        moment = datetime(2026, 9, 4, 14, 0, tzinfo=life.zone_of("서울"))
        times = life.zone_times(moment, ["서울", "뉴욕", "런던"])
        self.assertEqual([z.name for z in times], ["뉴욕", "런던", "서울"])
        seoul = times[-1]
        self.assertEqual(seoul.offset, "UTC+9")
        self.assertTrue(seoul.is_work)                 # 금요일 14시

    def test_zone_times_needs_a_zone_on_the_moment(self):
        from datetime import datetime

        with self.assertRaises(life.ZoneError):
            life.zone_times(datetime(2026, 9, 4, 14, 0), ["서울"])

    def test_parse_when_accepts_date_and_bare_time(self):
        seoul = life.zone_of("서울")
        parsed = life.parse_when("2026-09-05 14:00", seoul)
        self.assertEqual((parsed.year, parsed.hour), (2026, 14))
        self.assertEqual(life.parse_when("09:30", seoul).minute, 30)
        with self.assertRaises(life.ZoneError):
            life.parse_when("내일 낮", seoul)

    def test_work_overlap_marks_shared_hours(self):
        from datetime import date

        rows = life.work_overlap("서울", "싱가포르", day=date(2026, 9, 4))
        both = [(mine, yours) for mine, yours, ok in rows if ok]
        self.assertEqual(both[0], (10, 9))             # 시차 1시간
        self.assertEqual(len(both), 8)

    def test_work_overlap_can_be_empty(self):
        from datetime import date

        rows = life.work_overlap("서울", "뉴욕", day=date(2026, 9, 4))
        self.assertEqual([r for r in rows if r[2]], [])

    def test_weekend_is_not_work_time(self):
        from datetime import date

        rows = life.work_overlap("서울", "도쿄", day=date(2026, 9, 5))   # 토요일
        self.assertEqual([r for r in rows if r[2]], [])

    def test_hour_ranges_wrap_around_midnight(self):
        self.assertEqual(life.hour_ranges([22, 23, 0, 1]), [(22, 1)])
        self.assertEqual(life.hour_ranges([9, 10, 11]), [(9, 11)])
        self.assertEqual(life.hour_ranges([1, 5]), [(1, 1), (5, 5)])
        self.assertEqual(life.hour_ranges([]), [])
        self.assertEqual(life.hour_ranges(list(range(24))), [(0, 23)])


class RentTest(unittest.TestCase):
    def test_deposit_to_monthly(self):
        plan = life.to_monthly(500_000_000, 100_000_000, 5.5)
        self.assertEqual(plan.moved, 400_000_000)
        self.assertEqual(plan.monthly, 1_833_333)     # 4억 x 5.5% / 12
        self.assertEqual(plan.deposit, 100_000_000)

    def test_monthly_to_deposit_is_the_inverse(self):
        plan = life.to_deposit(1_833_333, 100_000_000, 5.5)
        self.assertAlmostEqual(plan.moved, 400_000_000, delta=100)
        self.assertAlmostEqual(plan.deposit, 500_000_000, delta=100)

    def test_yearly_is_twelve_months(self):
        self.assertEqual(life.to_monthly(120_000_000, 0, 10).yearly,
                         life.to_monthly(120_000_000, 0, 10).monthly * 12)

    def test_zero_rate_is_refused(self):
        with self.assertRaises(ValueError):
            life.to_monthly(100_000_000, 0, 0)
        with self.assertRaises(ValueError):
            life.to_deposit(500_000, 0, 0)

    def test_keeping_more_than_the_deposit_is_refused(self):
        with self.assertRaises(ValueError):
            life.to_monthly(100_000_000, 200_000_000, 5)


class KoreanAmountTest(unittest.TestCase):
    def test_reading_form(self):
        self.assertEqual(life.korean_amount(0), "영")
        self.assertEqual(life.korean_amount(101), "백일")
        self.assertEqual(life.korean_amount(10_000), "만")        # '일만'이 아니다
        self.assertEqual(life.korean_amount(12_345), "만 이천삼백사십오")
        self.assertEqual(life.korean_amount(500_000), "오십만")
        self.assertEqual(life.korean_amount(100_000_000), "억")

    def test_formal_form_keeps_leading_one(self):
        self.assertEqual(life.korean_amount(1_000, formal=True), "일천")
        self.assertEqual(life.korean_amount(10_000, formal=True), "일만")
        self.assertEqual(life.formal_amount(1_250_000), "일금 일백이십오만원정")

    def test_formal_form_has_no_spaces(self):
        self.assertNotIn(" ", life.korean_amount(1_234_567, formal=True))

    def test_rounds_to_won(self):
        self.assertEqual(life.korean_amount(1000.4), "천")

    def test_negative_is_marked(self):
        self.assertTrue(life.korean_amount(-5_000).startswith("마이너스"))

    def test_huge_number_falls_back_to_digits(self):
        # 경보다 크면 한글로 적지 않고 숫자로 둔다
        self.assertIn(",", life.korean_amount(10 ** 21))

    def test_unit_can_change(self):
        self.assertTrue(life.formal_amount(1000, unit="달러").endswith("달러정"))


class TimeCalcTest(unittest.TestCase):
    def test_parse_clock_forms(self):
        self.assertEqual(life.parse_clock("09:30"), 570)
        self.assertEqual(life.parse_clock("9시 30분"), 570)
        self.assertEqual(life.parse_clock("18시"), 1080)
        with self.assertRaises(life.TimeError):
            life.parse_clock("아침")
        with self.assertRaises(life.TimeError):
            life.parse_clock("09:99")

    def test_parse_duration_forms(self):
        self.assertEqual(life.parse_duration("3h20m"), 200)
        self.assertEqual(life.parse_duration("3시간 20분"), 200)
        self.assertEqual(life.parse_duration("90분"), 90)
        self.assertEqual(life.parse_duration("1.5시간"), 90)
        with self.assertRaises(life.TimeError):
            life.parse_duration("조금")

    def test_span_over_midnight(self):
        night = life.parse_span("22:00~06:00")
        self.assertEqual(night.minutes, 480)          # 야간 근무
        self.assertEqual(life.parse_span("09:00-18:30").minutes, 570)

    def test_span_needs_two_times(self):
        with self.assertRaises(life.TimeError):
            life.parse_span("09:00")

    def test_work_minutes_subtracts_break(self):
        spans = [life.parse_span("09:00-12:00"), life.parse_span("13:00-18:00")]
        self.assertEqual(life.work_minutes(spans), 480)
        self.assertEqual(life.work_minutes(spans, rest=60), 420)

    def test_work_minutes_can_go_negative(self):
        # 휴게가 더 길면 0 으로 가리지 않는다. 입력이 잘못됐다는 신호다
        self.assertLess(life.work_minutes([life.parse_span("09:00-10:00")], rest=120), 0)

    def test_format_minutes(self):
        self.assertEqual(life.format_minutes(510), "8시간 30분")
        self.assertEqual(life.format_minutes(480), "8시간")
        self.assertEqual(life.format_minutes(45), "45분")
        self.assertEqual(life.format_minutes(510, clock=True), "08:30")
        self.assertEqual(life.format_minutes(-30), "-30분")


class HolidaysBetweenTest(unittest.TestCase):
    """여러 해에 걸친 공휴일. 사이의 해가 빠지면 영업일을 더 많이 세게 된다."""

    def test_every_year_is_included(self):
        table = life.holidays_between(2026, 2030)
        self.assertEqual(sorted({d.year for d in table}),
                         [2026, 2027, 2028, 2029, 2030])

    def test_reversed_range(self):
        self.assertEqual(life.holidays_between(2030, 2026),
                         life.holidays_between(2026, 2030))

    def test_single_year(self):
        table = life.holidays_between(2026, 2026)
        self.assertEqual(table, life.holidays_for(2026))

    def test_long_jump_counts_middle_years(self):
        """3년 넘게 건너뛰면 사이 해의 공휴일이 반드시 반영돼야 한다."""
        from datetime import date

        start = date(2026, 1, 2)
        full = life.add_workdays(start, 1000, life.holidays_between(2025, 2031))
        short = life.add_workdays(start, 1000,
                                  life.holidays_between(2026, 2026))
        self.assertLess(short, full)      # 공휴일을 빼먹으면 날짜가 앞당겨진다


class AnnualLeaveTest(unittest.TestCase):
    """연차. 다른 시험처럼 date 는 안에서 들여온다."""

    def setUp(self):
        from datetime import date

        self.date = date

    def test_first_year_gives_one_day_per_full_month(self):
        got = life.annual_leave(self.date(2026, 3, 1), self.date(2026, 9, 7))
        self.assertEqual((got.years, got.months, got.days), (0, 6, 6))
        self.assertEqual(got.next_date, self.date(2026, 10, 1))

    def test_first_month_is_not_yet_a_day(self):
        got = life.annual_leave(self.date(2026, 3, 1), self.date(2026, 3, 31))
        self.assertEqual(got.days, 0)

    def test_first_year_stops_at_eleven(self):
        got = life.annual_leave(self.date(2026, 3, 1), self.date(2027, 2, 28))
        self.assertEqual(got.days, life.MAX_MONTHLY)
        self.assertEqual(got.next_date, self.date(2027, 3, 1))   # 1년이 되는 날

    def test_one_year_gives_fifteen(self):
        got = life.annual_leave(self.date(2026, 3, 1), self.date(2027, 3, 1))
        self.assertEqual((got.years, got.days), (1, 15))

    def test_two_years_still_fifteen(self):
        self.assertEqual(life.annual_days(2), 15)

    def test_third_year_adds_one(self):
        self.assertEqual(life.annual_days(3), 16)
        self.assertEqual(life.annual_days(4), 16)
        self.assertEqual(life.annual_days(5), 17)

    def test_capped_at_twenty_five(self):
        self.assertEqual(life.annual_days(21), 25)
        self.assertEqual(life.annual_days(40), life.MAX_ANNUAL)

    def test_under_one_year_has_no_annual_days(self):
        self.assertEqual(life.annual_days(0), 0)

    def test_leap_day_joiner_moves_to_march_first(self):
        # 2월 29일이 없는 해에는 3월 1일로 본다
        self.assertEqual(life.add_years(self.date(2024, 2, 29), 1), self.date(2025, 3, 1))
        self.assertEqual(life.add_years(self.date(2024, 2, 29), 4), self.date(2028, 2, 29))

    def test_before_joining_is_an_error(self):
        with self.assertRaises(ValueError):
            life.annual_leave(self.date(2026, 3, 1), self.date(2026, 2, 28))


if __name__ == "__main__":
    unittest.main()
