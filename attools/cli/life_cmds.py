"""at life - 일상 계산."""

from __future__ import annotations

from .. import life, text
from .common import _pad, _p, _grid


def cmd_life_dday(a) -> int:
    from datetime import date as _date

    today = life.parse_date(a.today) if a.today else _date.today()
    for text in a.dates:
        try:
            target = life.parse_date(text)
        except ValueError:
            _p(f"날짜를 해석하지 못했습니다: {text} (예: 2024-03-15, 20240315)")
            return 1

        d = life.DDay(target, today)
        _p(f"{target:%Y-%m-%d}({life.weekday_ko(target)})")
        if d.delta > 0:
            _p(f"  D-{d.delta}  ({d.delta}일 남음)")
        elif d.delta == 0:
            _p("  D-Day  오늘입니다")
        else:
            _p(f"  D+{-d.delta}  (지난 지 {-d.delta}일, 당일 포함 {d.nth_day}일째)")
            _p(f"  만 {life.korean_age(target, today)}년 경과 (생일이면 만 나이)")

        if not a.no_milestones:
            _p("  다가올 기념일")
            for name, when, left in d.milestones()[:a.count]:
                _p(f"    {name:>6}  {when:%Y-%m-%d}({life.weekday_ko(when)})  D-{left}")
        _p("")
    return 0


def cmd_life_split(a) -> int:
    paid: dict[str, float] = {}
    for item in a.paid:
        name, _, amount = item.partition("=")
        if not amount:
            _p(f"'이름=금액' 형태로 적으세요: {item}")
            return 1
        try:
            paid[name] = paid.get(name, 0.0) + life.parse_amount(amount)
        except ValueError as e:
            _p(str(e))
            return 1

    try:
        share, balance, transfers = life.settle(paid, extra=a.extra)
    except ValueError as e:
        _p(str(e))
        return 1

    total = sum(paid.values())
    _p(f"총액 {life.format_won(total)}, {len(balance)}명")
    _p(f"1인당 {life.format_won(share)}\n")

    for name in sorted(balance, key=lambda n: -balance[n]):
        v = balance[name]
        state = "받을 돈" if v > 0 else ("낼 돈" if v < 0 else "정산 완료")
        _p(f"  {_pad(name, 12)}낸 돈 {paid.get(name, 0):>12,.0f}   "
           f"{_pad(state, 8)}{abs(v):>10,.0f}")

    _p("\n송금")
    if not transfers:
        _p("  주고받을 것이 없습니다.")
    for t in transfers:
        _p(f"  {t.payer} -> {t.payee}  {t.amount:,.0f}원")
    return 0


def cmd_life_loan(a) -> int:
    try:
        principal = life.parse_amount(a.principal)
    except ValueError as e:
        _p(str(e))
        return 1

    months = int(round(a.years * 12)) if a.years else a.months
    if not months:
        _p("기간을 --years 또는 --months 로 지정하세요.")
        return 1

    try:
        rows = life.amortize(principal, a.rate, months, kind=a.kind, grace=a.grace)
    except ValueError as e:
        _p(str(e))
        return 1

    interest = sum(r.interest for r in rows)
    _p(f"{life.format_won(principal)}  연 {a.rate}%  {months}개월({months / 12:.1f}년)  {a.kind}"
       + (f"  거치 {a.grace}개월" if a.grace else ""))
    _p("")
    first, last = rows[a.grace], rows[-1]
    if a.kind == "원리금균등":
        _p(f"  매달 상환액   {life.format_won(first.payment)}")
    else:
        _p(f"  첫 달 상환액  {life.format_won(first.payment)}")
        _p(f"  마지막 상환액 {life.format_won(last.payment)}")
    _p(f"  총 이자       {life.format_won(interest)}")
    _p(f"  총 상환액     {life.format_won(principal + interest)}")
    _p(f"  이자 비율     {interest / principal:.1%}")

    if a.table:
        _p(f"\n  회차  {'상환액':>14}{'이자':>14}{'원금':>14}{'잔액':>16}")
        shown = rows if a.table < 0 else rows[:a.table]
        for r in shown:
            _p(f"  {r.no:>4}  {r.payment:>14,.0f}{r.interest:>14,.0f}"
               f"{r.principal:>14,.0f}{r.balance:>16,.0f}")
        if len(shown) < len(rows):
            _p(f"  ... 총 {len(rows)}회차 (--table -1 로 전체 출력)")
    return 0


def cmd_life_unit(a) -> int:
    try:
        group, value, unit, results = life.convert(" ".join(a.value))
    except ValueError as e:
        _p(str(e))
        return 1

    _p(f"[{group}] {value:g}{unit}")
    for name, converted in results:
        _p(f"  {_pad(name, 8)}{converted:,.4g}")
    return 0


def cmd_life_tax(a) -> int:
    try:
        amount = life.parse_amount(" ".join(a.amount))
    except ValueError as e:
        _p(str(e))
        return 1
    if amount <= 0:
        _p("금액은 0보다 커야 합니다.")
        return 1

    added = life.vat_add(amount, rate=a.vat_rate)
    taken = life.vat_extract(amount, rate=a.vat_rate)
    _p(f"{life.format_won(amount)}")
    _p(f"\n부가세 {a.vat_rate:g}%")
    _p(f"  이 금액이 공급가액이면   부가세 {added.vat:,}원, 합계 {added.total:,}원")
    _p(f"  이 금액이 합계(세금포함)면  공급가액 {taken.supply:,}원, "
       f"부가세 {taken.vat:,}원")

    w = life.withhold(amount, rate=a.withhold_rate)
    _p(f"\n원천징수 (소득세 {a.withhold_rate:g}% + 지방소득세 그 10%)")
    _p(f"  소득세 {w.income_tax:,}원 + 지방소득세 {w.local_tax:,}원 "
       f"= {w.tax:,}원 ({w.rate:.2f}%)")
    _p(f"  실수령액 {life.format_won(w.net)}")
    _p("\n원 미만은 버립니다. 소득 종류마다 세율이 다릅니다 - 사업소득은 소득세 3%"
       "(합계 3.3%), 기타소득은 8%(합계 8.8%). --withhold-rate 로 바꾸세요.")
    return 0


def cmd_life_save(a) -> int:
    try:
        monthly = life.parse_amount(a.monthly) if a.monthly else 0
        deposit = life.parse_amount(a.deposit) if a.deposit else 0
        plan = life.saving_plan(monthly=monthly, deposit=deposit,
                                months=a.months, annual_rate=a.rate,
                                tax_rate=a.tax)
    except ValueError as e:
        _p(str(e))
        return 1

    _p(f"{plan.kind}  연 {plan.annual_rate:g}%  {plan.months}개월  (단리)")
    if monthly:
        _p(f"  매달 {int(monthly):,}원 x {plan.months}회")
    _p(f"  원금        {plan.principal:,}원")
    _p(f"  세전 이자   {plan.interest:,}원")
    _p(f"  이자소득세  -{plan.tax:,}원 ({plan.tax_rate:g}%)")
    _p(f"  세후 이자   {plan.net_interest:,}원")
    _p(f"  만기 수령   {life.format_won(plan.total)}")
    _p(f"\n원금 대비 세후 수익률 연 {plan.effective:.2f}%")
    if plan.kind == "적금":
        _p("적금은 먼저 넣은 돈만 오래 이자가 붙어서, 같은 금리인 예금보다 "
           "실제 수익률이 절반쯤입니다. 금리만 보고 비교하면 안 됩니다.")
    _p("은행이 표시하는 단리 기준입니다. 월복리 상품이나 중도해지 이율은 다릅니다.")
    return 0


def cmd_life_tz(a) -> int:
    from datetime import datetime

    if a.list:
        _p("별칭")
        names = sorted(set(life.ZONE_ALIASES))
        for i in range(0, len(names), 4):
            _p("  " + "  ".join(_pad(n, 14) for n in names[i:i + 4]).rstrip())
        _p("\n별칭에 없으면 Asia/Seoul 처럼 IANA 이름을 그대로 적으면 됩니다.")
        return 0

    try:
        home = life.zone_of(a.zone)
        moment = life.parse_when(" ".join(a.when), home) if a.when else datetime.now(home)
        names = list(a.to or []) or [n for n in life.DEFAULT_ZONES]
        if a.zone not in names:
            names = [a.zone, *names]
        times = life.zone_times(moment, names)
    except life.ZoneError as e:
        _p(str(e))
        return 1

    _p(f"{a.zone} {moment:%Y-%m-%d %H:%M}({life.weekday_ko(moment.date())}) 기준")
    _grid(["곳", "시간대", "현지 시각", "요일", "시차", "근무 시간"],
          [[z.name, z.zone, f"{z.when:%m-%d %H:%M}", life.weekday_ko(z.when.date()),
            z.offset, "예" if z.is_work else "아니오"] for z in times])

    if a.overlap:
        try:
            rows = life.work_overlap(a.zone, a.overlap, day=moment.date())
        except life.ZoneError as e:
            _p(str(e))
            return 1
        both = [(mine, yours) for mine, yours, ok in rows if ok]
        _p(f"\n{a.zone} ↔ {a.overlap}  (양쪽 09~18시 기준)")
        if both:
            _p(f"  겹치는 시간 {len(both)}시간: " +
               ", ".join(f"{m:02d}시(상대 {y:02d}시)" for m, y in both))
        else:
            near = [m for m, y, _ in rows if life.WORK_START <= y < life.WORK_END]
            _p("  겹치는 근무 시간이 없습니다.")
            for begin, end in life.hour_ranges(near):
                _p(f"  상대 근무 시간은 내 {begin:02d}시~{end:02d}시입니다"
                   + ("(자정을 넘습니다)." if end < begin else "."))
    _p("\n서머타임은 시간대 자료(IANA)를 그대로 따릅니다.")
    return 0


def cmd_life_rent(a) -> int:
    try:
        rate = a.rate
        if a.monthly:
            monthly = life.parse_amount(a.monthly)
            base = life.parse_amount(a.deposit) if a.deposit else 0
            plan = life.to_deposit(monthly, base, rate)
            _p(f"월세 {life.format_won(monthly)} -> 보증금 (연 {rate:g}%)")
            _p(f"  보증금에 더할 금액   {life.format_won(plan.moved)}")
            _p(f"  바꾼 뒤 보증금       {life.format_won(plan.deposit)}")
            _p(f"  한 해 월세 {life.format_won(monthly * 12)} 만큼 안 냅니다.")
        else:
            if not a.deposit:
                _p("전세보증금을 주세요. 예: at life rent --deposit 5억 --keep 1억")
                return 1
            full = life.parse_amount(a.deposit)
            keep = life.parse_amount(a.keep) if a.keep else 0
            plan = life.to_monthly(full, keep, rate)
            _p(f"전세 {life.format_won(full)} 중 "
               f"{life.format_won(plan.deposit)} 만 남기기 (연 {rate:g}%)")
            _p(f"  월세로 돌리는 금액   {life.format_won(plan.moved)}")
            _p(f"  월세                 {life.format_won(plan.monthly)}")
            _p(f"  한 해                {life.format_won(plan.yearly)}")
    except ValueError as e:
        _p(str(e))
        return 1

    _p("\n전환율은 계약마다 다릅니다. 주택임대차보호법에는 상한(기준금리 + 일정 %)이 "
       "있으니 지금 기준금리를 확인해 넣으세요.")
    _p("여기서는 준 전환율로만 계산하고, 세금이나 관리비는 보지 않습니다.")
    return 0


def cmd_life_won(a) -> int:
    try:
        amount = life.parse_amount(" ".join(a.amount))
    except ValueError as e:
        _p(str(e))
        return 1

    _p(f"{life.format_won(amount)}")
    _p(f"  읽기      {life.korean_amount(amount)}")
    _p(f"  계약서    {life.formal_amount(amount, unit=a.unit)}")
    if amount != int(amount):
        _p("소수점 아래는 반올림했습니다.")
    _p("계약서 표기는 자리를 붙여 쓰고 '일천'처럼 앞의 일을 살립니다. "
       "숫자를 덧붙여 고치기 어렵게 하려는 표기입니다.")
    return 0


def cmd_life_cal(a) -> int:
    import calendar
    from datetime import date as _date

    today = _date.today()
    year, month = today.year, today.month
    if a.month:
        body = a.month.strip().replace("/", "-").replace(".", "-")
        parts = [p for p in body.split("-") if p]
        try:
            year = int(parts[0])
            month = int(parts[1]) if len(parts) > 1 else 1
            if not 1 <= month <= 12:
                raise ValueError
        except (ValueError, IndexError):
            _p(f"연-월로 적어 주세요: {a.month} (예: 2026-09)")
            return 1

    extra = life.load_user_holidays(a.holidays)
    years: set[int] = set()
    for i in range(a.count):
        years.add(year + (month - 1 + i) // 12)
    holidays: dict = {}
    for y in sorted(years):
        holidays.update(life.holidays_for(y, extra))

    for i in range(a.count):
        y, m = year + (month - 1 + i) // 12, (month - 1 + i) % 12 + 1
        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(y, m)
        days = [d for w in weeks for d in w if d.month == m]
        work = len([d for d in days if life.is_workday(d, holidays)])
        rest = [d for d in days if d in holidays]

        if i:
            _p("")
        _p(f"{y}년 {m}월   영업일 {work}일, 공휴일 {len(rest)}일")
        _p("  " + "".join(f" {name} " for name in life.WEEKDAYS))
        for week in weeks:
            cells = []
            for d in week:
                if d.month != m:
                    cells.append("    ")
                else:
                    mark = "*" if d in holidays else "." if d == today else " "
                    cells.append(f"{d.day:>3}{mark}")
            _p("  " + "".join(cells))
        for d in rest:
            _p(f"  {d.day:>3}* {holidays[d]}")

    _p("\n* 공휴일, . 오늘")
    warning = life.missing_lunar_warning(holidays, sorted(years))
    if warning:
        _p("")
        for line in warning:
            _p(line)
    return 0


def cmd_life_workday(a) -> int:
    from datetime import date as _date

    extra = life.load_user_holidays(a.holidays)

    if a.list:
        year = int(a.list)
        table = life.holidays_for(year, extra)
        _p(f"{year}년 공휴일 {len(table)}일")
        for when, name in table.items():
            mark = "  (주말)" if when.weekday() >= 5 else ""
            _p(f"  {when:%Y-%m-%d}({life.weekday_ko(when)})  {name}{mark}")
        warning = life.missing_lunar_warning(table, [year])
        if warning:
            _p("")
            for line in warning:
                _p(line)
        return 0

    if not a.start:
        _p("시작일을 주세요. 예: at life workday 2026-08-14 +5")
        return 1

    try:
        start = life.parse_date(a.start)
    except ValueError:
        _p(f"날짜를 해석하지 못했습니다: {a.start}")
        return 1

    target = (a.target or "").strip()
    years = {start.year}
    if target and (target[0] in "+-" and target[1:].isdigit()):
        days = int(target)
        years.add((start + life.timedelta(days=days * 2 + 14)).year)
        holidays = {}
        for y in sorted(years) + [max(years) + 1]:
            holidays.update(life.holidays_for(y, extra))
        end = life.add_workdays(start, days, holidays)
        _p(f"{start:%Y-%m-%d}({life.weekday_ko(start)}) 에서 "
           f"{abs(days)}영업일 {'뒤' if days > 0 else '앞'}")
        _p(f"  -> {end:%Y-%m-%d}({life.weekday_ko(end)})")
        _p(f"  달력으로는 {abs((end - start).days)}일")
    else:
        try:
            end = life.parse_date(target) if target else _date.today()
        except ValueError:
            _p(f"날짜나 +N/-N 형태로 주세요: {target}")
            return 1
        years.add(end.year)
        holidays = {}
        for y in range(min(years), max(years) + 1):
            holidays.update(life.holidays_for(y, extra))
        count = life.count_workdays(start, end, holidays, include_start=not a.exclusive)
        first, last = min(start, end), max(start, end)
        _p(f"{first:%Y-%m-%d}({life.weekday_ko(first)}) ~ "
           f"{last:%Y-%m-%d}({life.weekday_ko(last)})")
        _p(f"  영업일 {count}일  ·  달력 {(last - first).days + 1}일")
        blocked = [f"{d:%m-%d} {n}" for d, n in sorted(holidays.items())
                   if first <= d <= last and d.weekday() < 5]
        if blocked:
            _p(f"  낀 공휴일: {', '.join(blocked)}")

    for line in life.missing_lunar_warning(holidays, sorted(years)):
        _p(f"  {line}")
    return 0


def add_commands(sub) -> None:
    """life 하위 명령을 붙인다."""
    lp = sub.add_parser("life", help="일상 계산기").add_subparsers(dest="cmd", required=True)

    dd = lp.add_parser("dday", help="D-day, 만 나이, 기념일")
    dd.add_argument("dates", nargs="+", metavar="날짜")
    dd.add_argument("--today", help="기준일 (기본 오늘)")
    dd.add_argument("-n", "--count", type=int, default=4)
    dd.add_argument("--no-milestones", action="store_true")
    dd.set_defaults(func=cmd_life_dday)

    sp = lp.add_parser("split", help="더치페이 정산")
    sp.add_argument("paid", nargs="+", metavar="이름=금액")
    sp.add_argument("--extra", action="append", metavar="이름",
                    help="돈은 안 냈지만 나눠 낼 사람")
    sp.set_defaults(func=cmd_life_split)

    ln = lp.add_parser("loan", help="대출 상환액 계산")
    ln.add_argument("principal", metavar="원금", help="예: 3억5000만, 250000000")
    ln.add_argument("rate", type=float, metavar="연이율")
    ln.add_argument("years", type=float, nargs="?", metavar="년")
    ln.add_argument("--months", type=int, default=0)
    ln.add_argument("--kind", default="원리금균등",
                    choices=["원리금균등", "원금균등", "만기일시"])
    ln.add_argument("--grace", type=int, default=0, metavar="개월", help="거치기간")
    ln.add_argument("--table", type=int, default=0, metavar="회차",
                    help="상환표 출력 (-1 이면 전체)")
    ln.set_defaults(func=cmd_life_loan)

    wd = lp.add_parser("workday", help="영업일 계산과 공휴일 목록")
    wd.add_argument("start", nargs="?", metavar="시작일")
    wd.add_argument("target", nargs="?", metavar="끝날짜|+N|-N",
                    help="날짜면 그 사이 영업일 수, +5 면 5영업일 뒤")
    wd.add_argument("--list", metavar="연도", help="그 해 공휴일 목록")
    wd.add_argument("--holidays", metavar="파일",
                    help="음력 명절 등을 적어 둔 파일 (기본 ~/.attools/holidays.txt)")
    wd.add_argument("--exclusive", action="store_true", help="시작일을 세지 않는다")
    wd.set_defaults(func=cmd_life_workday)

    un = lp.add_parser("unit", help="단위 변환 (평/㎡, 근/돈, 마일, 화씨…)")
    un.add_argument("value", nargs="+", metavar="값+단위", help="예: 84㎡, 30평, 1근, 100F")
    un.set_defaults(func=cmd_life_unit)

    tx = lp.add_parser("tax", help="부가세 계산과 원천징수 실수령액")
    tx.add_argument("amount", nargs="+", metavar="금액", help="예: 1100000, 110만")
    tx.add_argument("--vat-rate", type=float, default=life.VAT_RATE, metavar="%")
    tx.add_argument("--withhold-rate", type=float, default=life.WITHHOLD_RATE,
                    metavar="%", help="소득세율 (사업소득 3, 기타소득 8)")
    tx.set_defaults(func=cmd_life_tax)

    sv = lp.add_parser("save", help="적금·예금 만기 수령액")
    sv.add_argument("--monthly", metavar="금액", help="매달 넣는 돈 (적금)")
    sv.add_argument("--deposit", metavar="금액", help="한 번에 넣는 돈 (예금)")
    sv.add_argument("--months", type=int, required=True, metavar="개월")
    sv.add_argument("--rate", type=float, required=True, metavar="%", help="연 이율")
    sv.add_argument("--tax", type=float, default=life.INTEREST_TAX, metavar="%",
                    help="이자소득세 (기본 15.4, 비과세면 0)")
    sv.set_defaults(func=cmd_life_save)

    cl = lp.add_parser("cal", help="달력 - 공휴일과 그 달 영업일 수")
    cl.add_argument("month", nargs="?", metavar="연-월", help="기본은 이번 달")
    cl.add_argument("-n", "--count", type=int, default=1, metavar="개월",
                    help="이어지는 달까지 함께 (기본 1)")
    cl.add_argument("--holidays", metavar="파일",
                    help="음력 명절 등을 적어 둔 파일 (기본 ~/.attools/holidays.txt)")
    cl.set_defaults(func=cmd_life_cal)

    tz = lp.add_parser("tz", help="시차 - 여러 도시의 같은 시각, 겹치는 근무 시간")
    tz.add_argument("when", nargs="*", metavar="시각",
                    help="예: '2026-09-05 14:00' 또는 '14:00' (기본: 지금)")
    tz.add_argument("--zone", default="서울", metavar="곳", help="기준 시간대")
    tz.add_argument("--to", action="append", metavar="곳", help="볼 곳 (여러 번)")
    tz.add_argument("--overlap", metavar="곳", help="이곳과 겹치는 근무 시간")
    tz.add_argument("-l", "--list", action="store_true", help="쓸 수 있는 별칭")
    tz.set_defaults(func=cmd_life_tz)

    rn = lp.add_parser("rent", help="전월세 전환 - 보증금 <-> 월세")
    rn.add_argument("--deposit", metavar="금액", help="전세보증금 (또는 기준 보증금)")
    rn.add_argument("--keep", metavar="금액", help="남길 보증금 (기본 0)")
    rn.add_argument("--monthly", metavar="금액", help="이걸 주면 월세를 보증금으로")
    rn.add_argument("--rate", type=float, default=5.5, metavar="%",
                    help="연 전환율 (기본 5.5)")
    rn.set_defaults(func=cmd_life_rent)

    wn = lp.add_parser("won", help="금액을 한글로 (계약서·영수증 표기)")
    wn.add_argument("amount", nargs="+", metavar="금액", help="예: 1250000, 125만")
    wn.add_argument("--unit", default="원", metavar="단위")
    wn.set_defaults(func=cmd_life_won)
