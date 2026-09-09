"""일상 계산 화면. D-day, 더치페이, 대출, 단위, 세금을 한 화면 안에서."""

from __future__ import annotations

from datetime import date as _date
from datetime import timedelta

from ... import life
from .. import App, UiError, form

LOAN_KINDS = {"원리금균등", "원금균등", "만기일시"}


def _plain(value: float) -> str:
    """상환표처럼 줄이 많은 곳에는 억·만 설명 없이 숫자만 넣는다."""
    return f"{round(value):,}원"


def _amount(payload: dict, key: str) -> float:
    raw = form.text(payload, key)
    if not raw:
        raise UiError("금액을 적어 주세요.")
    try:
        return life.parse_amount(raw)
    except ValueError as exc:
        raise UiError(str(exc)) from None


def dday(payload: dict) -> dict:
    raw = form.text(payload, "date")
    if not raw:
        raise UiError("날짜를 적어 주세요. 예: 2026-03-15")
    try:
        target = life.parse_date(raw)
        today = life.parse_date(form.text(payload, "today")) if form.text(payload, "today") else _date.today()
    except ValueError as exc:
        raise UiError(f"날짜를 읽지 못했습니다: {exc}") from None

    d = life.DDay(target, today)
    if d.delta > 0:
        headline = f"D-{d.delta} · {d.delta}일 남았습니다"
    elif d.delta == 0:
        headline = "D-Day · 오늘입니다"
    else:
        headline = f"D+{-d.delta} · 지난 지 {-d.delta}일 (당일 포함 {d.nth_day}일째)"

    rows = [[name, f"{when:%Y-%m-%d}({life.weekday_ko(when)})",
             "오늘" if left == 0 else f"{left}일 뒤"]
            for name, when, left in d.milestones()]
    return {"headline": headline,
            "target": f"{target:%Y-%m-%d}({life.weekday_ko(target)})",
            "age": life.korean_age(target, today),
            "rows": rows}


def _holidays(years: list[int]) -> dict:
    return life.holidays_between(min(years), max(years), life.load_user_holidays())


def workday(payload: dict) -> dict:
    """영업일 계산. 음력 명절이 빠져 있으면 그대로 밝힌다."""
    raw = form.text(payload, "start")
    try:
        start = life.parse_date(raw) if raw else _date.today()
    except ValueError:
        raise UiError(f"날짜를 읽지 못했습니다: {raw}") from None

    target = form.text(payload, "target")
    years = sorted({start.year - 1, start.year, start.year + 1})

    if target and target[0] in "+-" and target[1:].strip().isdigit():
        days = int(target[0] + target[1:].strip())
        if abs(days) > 2000:
            raise UiError("영업일 수가 너무 큽니다. 2000 이내로 적어 주세요.")
        # 영업일 N 은 달력으로 대략 N*7/5 일. 사이의 해를 모두 넣어야 한다
        far = (start + timedelta(days=days * 2 + 14)).year
        years = sorted({start.year - 1, start.year, far, far + 1})
        end = life.add_workdays(start, days, _holidays(years))
        headline = (f"{end:%Y-%m-%d}({life.weekday_ko(end)})")
        rows = [["기준일", f"{start:%Y-%m-%d}({life.weekday_ko(start)})"],
                ["옮긴 영업일", f"{abs(days)}영업일 {'뒤' if days > 0 else '앞'}"],
                ["달력으로", f"{abs((end - start).days)}일"]]
    else:
        try:
            end = life.parse_date(target) if target else _date.today()
        except ValueError:
            raise UiError(f"날짜를 읽지 못했습니다: {target}") from None
        years = sorted({start.year, end.year})
        count = life.count_workdays(start, end, _holidays(years),
                                    include_start=not form.flag(payload, "exclusive"))
        first, last = sorted((start, end))
        headline = f"{count}영업일"
        rows = [["처음", f"{first:%Y-%m-%d}({life.weekday_ko(first)})"],
                ["끝", f"{last:%Y-%m-%d}({life.weekday_ko(last)})"],
                ["달력으로", f"{(last - first).days + 1}일"]]

    return {"headline": headline, "rows": rows,
            "warning": life.missing_lunar_warning(_holidays(years), years)}


def holidays(payload: dict) -> dict:
    year = int(form.number(payload, "year", _date.today().year,
                           low=1900, high=2200))
    table = life.holidays_for(year, life.load_user_holidays())
    rows = [[f"{when:%Y-%m-%d}", life.weekday_ko(when), name,
             "주말과 겹침" if when.weekday() >= 5 else ""]
            for when, name in sorted(table.items())]
    return {"rows": rows, "year": year,
            "warning": life.missing_lunar_warning(table, [year])}


def split(payload: dict) -> dict:
    paid: dict[str, float] = {}
    for line in form.text(payload, "paid").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.rsplit(None, 1)
        if len(parts) == 1:
            paid[parts[0]] = paid.get(parts[0], 0.0)
            continue
        name, money = parts
        try:
            paid[name] = paid.get(name, 0.0) + life.parse_amount(money)
        except ValueError:
            raise UiError(f"금액을 읽지 못했습니다: {line}") from None

    for name in [n.strip() for n in form.text(payload, "extra").split(",") if n.strip()]:
        paid.setdefault(name, 0.0)
    if not paid:
        raise UiError("누가 얼마 냈는지 한 줄에 하나씩 적어 주세요. 예: 홍길동 42000")

    share, balance, transfers = life.settle(paid)
    rows = [[name, life.format_won(paid[name]),
             ("+" if balance[name] > 0 else "") + life.format_won(balance[name])]
            for name in sorted(paid, key=lambda n: -paid[n])]
    moves = [[t.payer, t.payee, life.format_won(t.amount)] for t in transfers]
    return {"share": life.format_won(round(share)), "rows": rows,
            "moves": moves, "people": len(paid),
            "total": life.format_won(sum(paid.values()))}


def loan(payload: dict) -> dict:
    principal = _amount(payload, "principal")
    rate = form.number(payload, "rate", 4.0, low=0.0, high=100.0)
    months = int(form.number(payload, "months", 12, low=1, high=1200))
    grace = int(form.number(payload, "grace", 0, low=0, high=1199))
    kind = form.choice(payload, "kind", LOAN_KINDS, "원리금균등")
    try:
        rows = life.amortize(principal, rate, months, kind=kind, grace=grace)
    except ValueError as exc:
        raise UiError(str(exc)) from None

    interest = sum(r.interest for r in rows)
    shown = rows if len(rows) <= 24 else rows[:12] + rows[-12:]
    table = [[str(r.no), _plain(r.payment), _plain(r.interest),
              _plain(r.principal), _plain(r.balance)] for r in shown]
    return {"rows": table,
            "skipped": max(0, len(rows) - len(shown)),
            "first": life.format_won(rows[0].payment),
            "interest": life.format_won(interest),
            "total": life.format_won(principal + interest),
            "months": months}


def unit(payload: dict) -> dict:
    raw = form.text(payload, "value")
    if not raw:
        raise UiError("바꿀 값을 적어 주세요. 예: 84㎡, 3근, 25도c")
    try:
        group, value, from_unit, results = life.convert(raw)
    except ValueError as exc:
        raise UiError(str(exc)) from None
    rows = [[name, f"{amount:,.4f}".rstrip("0").rstrip(".")] for name, amount in results]
    return {"group": group, "from": f"{value:g}{from_unit}", "rows": rows}


def tax(payload: dict) -> dict:
    amount = _amount(payload, "amount")
    mode = form.choice(payload, "mode", {"add", "extract", "withhold"}, "add")

    if mode == "withhold":
        w = life.withhold(amount)
        return {"headline": f"실수령 {life.format_won(w.net)}",
                "rows": [["지급액", life.format_won(w.gross)],
                         ["소득세 (3%)", life.format_won(w.income_tax)],
                         ["지방소득세 (소득세의 10%)", life.format_won(w.local_tax)],
                         ["떼는 돈 합계", life.format_won(w.tax)],
                         ["실수령액", life.format_won(w.net)]],
                "note": "소득세를 먼저 떼고 그 10% 를 지방소득세로 뗍니다. "
                        "3.3% 를 한 번에 곱한 값과 1~2원 다를 수 있습니다."}

    v = life.vat_add(amount) if mode == "add" else life.vat_extract(amount)
    return {"headline": f"합계 {life.format_won(v.total)}" if mode == "add"
                        else f"공급가액 {life.format_won(v.supply)}",
            "rows": [["공급가액", life.format_won(v.supply)],
                     ["부가세 (10%)", life.format_won(v.vat)],
                     ["합계", life.format_won(v.total)]],
            "note": "원 미만은 버립니다."}


def saving(payload: dict) -> dict:
    """적금·예금 만기 계산. 단리 기준이라는 것을 그 자리에 적는다."""
    kind = form.choice(payload, "kind", {"적금", "예금"}, "적금")
    amount = _amount(payload, "amount")
    months = int(form.number(payload, "months", 12, low=1, high=600))
    rate = form.number(payload, "rate", 3.5, low=0.0, high=100.0)
    try:
        plan = life.saving_plan(
            monthly=amount if kind == "적금" else 0,
            deposit=amount if kind == "예금" else 0,
            months=months, annual_rate=rate)
    except ValueError as exc:
        raise UiError(str(exc)) from None

    return {"headline": f"만기에 {life.format_won(plan.total)}",
            "rows": [["넣는 방식", plan.kind],
                     ["원금 합계", life.format_won(plan.principal)],
                     ["세전 이자", life.format_won(plan.interest)],
                     [f"이자소득세 ({plan.tax_rate}%)", life.format_won(plan.tax)],
                     ["세후 이자", life.format_won(plan.net_interest)],
                     ["만기 수령액", life.format_won(plan.total)],
                     ["원금 대비 연 수익률", f"{plan.effective:.2f}%"]],
            "note": "은행이 표시하는 단리 기준입니다. 복리 상품은 계산이 "
                    "다릅니다. 우대금리·중도해지는 넣지 않았습니다."}


def rent(payload: dict) -> dict:
    """전월세 전환. 전환율 상한은 지역·시기마다 달라 여기서 정하지 않는다."""
    rate = form.number(payload, "rate", 5.5, low=0.1, high=100.0)
    monthly = form.text(payload, "monthly")
    try:
        if monthly:
            plan = life.to_deposit(_amount(payload, "monthly"),
                                   _amount(payload, "deposit") if form.text(payload, "deposit") else 0,
                                   rate)
            headline = f"보증금 {life.format_won(plan.deposit)}"
        else:
            plan = life.to_monthly(
                _amount(payload, "deposit"),
                _amount(payload, "keep") if form.text(payload, "keep") else 0,
                rate)
            headline = f"월세 {life.format_won(plan.monthly)}"
    except ValueError as exc:
        raise UiError(str(exc)) from None

    return {"headline": headline,
            "rows": [["보증금", life.format_won(plan.deposit)],
                     ["월세", life.format_won(plan.monthly)],
                     ["옮긴 금액", life.format_won(plan.moved)],
                     ["연 전환율", f"{plan.rate}%"],
                     ["월세 1년치", life.format_won(plan.yearly)]],
            "note": "전환율은 넣은 값을 그대로 씁니다. 법정 상한은 지역과 "
                    "시기에 따라 달라 여기서 정하지 않습니다."}


def weekly(payload: dict) -> dict:
    """주휴수당. 계산식을 그대로 돌려줘서 사람이 검산할 수 있게 한다."""
    try:
        hourly_won = int(life.parse_amount(form.text(payload, "wkhourly")))
    except ValueError as exc:
        raise UiError(str(exc)) from None
    hours = form.number(payload, "wkhours", 40, low=0, high=168)
    try:
        week = life.weekly_holiday_pay(hourly_won, float(hours))
    except ValueError as exc:
        raise UiError(str(exc)) from None

    rows = [["일한 시간 임금", f"{week.work_pay:,}원"]]
    if week.eligible:
        rows += [["주휴수당", f"{week.holiday_pay:,}원"],
                 ["주급 합계", f"{week.weekly_total:,}원"],
                 ["한 달 어림", f"{week.monthly:,}원"]]
    formula = (f"({week.weekly_hours:g}시간 ÷ {life.WEEKLY_FULL_HOURS}) × "
               f"{life.WEEKLY_PAID_HOURS} × {hourly_won:,}원 = "
               f"{week.holiday_pay:,}원 ({week.paid_hours:g}시간분)")
    return {"rows": rows, "eligible": week.eligible, "formula": formula,
            "capped": week.weekly_hours > life.WEEKLY_FULL_HOURS,
            "least": life.WEEKLY_MIN_HOURS,
            "command": form.command("life", "weekly", hourly_won,
                                    "--hours", f"{float(hours):g}")}


def hourly(payload: dict) -> dict:
    """통상시급과 연장·야간·휴일 가산 수당."""
    try:
        monthly = life.parse_amount(form.text(payload, "hmonthly"))
    except ValueError as exc:
        raise UiError(str(exc)) from None
    hours = form.number(payload, "hhours", life.MONTHLY_HOURS, low=1, high=400)
    try:
        pay = life.hourly_pay(monthly, hours=hours)
    except ValueError as exc:
        raise UiError(str(exc)) from None

    extra = life.extra_pay(
        pay,
        overtime=form.number(payload, "hover", 0, low=0, high=400),
        night=form.number(payload, "hnight", 0, low=0, high=400),
        holiday=form.number(payload, "hholiday", 0, low=0, high=400))

    args: list = ["life", "hourly", monthly]
    if hours != life.MONTHLY_HOURS:
        args += ["--hours", f"{hours:g}"]
    for name, value in (("--overtime", extra.overtime_hours),
                        ("--night", extra.night_hours),
                        ("--holiday", extra.holiday_hours)):
        if value:
            args += [name, f"{value:g}"]

    rows = [["통상시급", f"{pay.hourly:,}원", "1.0"],
            ["연장근로", f"{pay.overtime:,}원", "1.5"],
            ["야간 가산분", f"{pay.night_extra:,}원", "0.5"],
            ["휴일근로 (8시간까지)", f"{pay.holiday:,}원", "1.5"],
            ["휴일근로 (8시간 넘게)", f"{pay.holiday_over:,}원", "2.0"]]
    paid = []
    if extra.overtime_hours:
        paid.append([f"연장 {extra.overtime_hours:g}시간", f"{extra.overtime:,}원"])
    if extra.night_hours:
        paid.append([f"야간 {extra.night_hours:g}시간 (가산분만)",
                     f"{extra.night:,}원"])
    if extra.holiday_hours:
        paid.append([f"휴일 {extra.holiday_hours:g}시간", f"{extra.holiday:,}원"])
    if paid:
        paid.append(["합계", f"{extra.total:,}원"])

    return {"rows": rows, "paid": paid, "hours": hours,
            "note": "근로기준법 제56조의 가산율입니다. 한 달 소정근로시간 "
                    f"{hours:g}시간은 법이 정한 값이 아니라 흔한 값입니다. "
                    "통상임금 범위는 회사 규정·판례에 따라 다르고, 5인 미만 "
                    "사업장은 가산 규정이 적용되지 않습니다.",
            "command": form.command(*args)}


def worktime(payload: dict) -> dict:
    """근무 시간 계산. 09:00-18:30 처럼 구간을 줄마다 적는다."""
    spans, bad = [], []
    for line in form.raw_text(payload, "spans").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            spans.append(life.parse_span(line))
        except life.TimeError:
            bad.append(line)
    if bad:
        raise UiError(f"시간 구간을 읽지 못했습니다: {', '.join(bad[:3])} "
                      "('09:00-18:30' 꼴로 적어 주세요)")
    if not spans:
        raise UiError("근무 구간을 한 줄에 하나씩 적어 주세요. 예: 09:00-18:30")

    rest = int(form.number(payload, "rest", 0, low=0, high=1440))
    minutes = life.work_minutes(spans, rest=rest)
    rate = form.number(payload, "rate", 0, low=0, high=1_000_000)
    rows = [["구간", ", ".join(f"{life.format_minutes(s.minutes)}" for s in spans)],
            ["휴게", life.format_minutes(rest)],
            ["일한 시간", life.format_minutes(minutes)],
            ["시각으로", life.format_minutes(minutes, clock=True)]]
    if rate:
        rows.append(["임금", life.format_won(minutes / 60 * rate)])
    return {"headline": life.format_minutes(minutes), "rows": rows,
            "note": "연장·야간 가산은 넣지 않았습니다. 실제 임금은 사업장 "
                    "규모와 근로 형태에 따라 달라집니다."}


def severance(payload: dict) -> dict:
    try:
        joined = life.parse_date(form.text(payload, "sjoined"))
        left = life.parse_date(form.text(payload, "sleft"))
    except ValueError as exc:
        raise UiError(f"날짜를 읽지 못했습니다: {exc}") from None
    try:
        got = life.severance_pay(
            joined, left,
            base_pay=_amount(payload, "spay"),
            bonus=_amount(payload, "sbonus") if form.text(payload, "sbonus") else 0.0,
            leave_pay=(_amount(payload, "sleave")
                       if form.text(payload, "sleave") else 0.0),
            ordinary_daily=(_amount(payload, "sordinary")
                            if form.text(payload, "sordinary") else 0.0))
    except ValueError as exc:
        raise UiError(str(exc)) from None

    years, days = divmod(got.worked_days, 365)
    rows = [["3개월 임금총액", life.format_won(got.base_pay)],
            ["그 기간의 일수", f"{got.window_days}일"],
            ["1일 평균임금", life.format_won(got.daily)]]
    if got.ordinary_daily:
        rows.append(["1일 통상임금", life.format_won(got.ordinary_daily)])
    rows.append(["계산에 쓴 1일 임금", life.format_won(got.used_daily)])

    args: list[object] = ["life", "severance", f"{joined:%Y-%m-%d}",
                          f"{left:%Y-%m-%d}", "--pay", form.text(payload, "spay")]
    for flag, key in (("--bonus", "sbonus"), ("--leave-pay", "sleave"),
                      ("--ordinary", "sordinary")):
        if form.text(payload, key):
            args += [flag, form.text(payload, key)]

    return {"headline": life.format_won(got.amount) if got.eligible else "없음",
            "span": f"재직 {got.worked_days:,}일 ({years}년 {days}일)",
            "rows": rows,
            "notes": got.notes + [
                "근로자퇴직급여 보장법 제8조 기준, 세전입니다.",
                "퇴직소득세는 빼지 않았습니다. 근속연수공제가 얽혀 있어 여기서 "
                "못 맞춥니다.",
                "퇴직연금(DC)에 든 회사는 운용 결과에 따라 달라집니다."],
            "command": form.command(*args)}


def annual(payload: dict) -> dict:
    raw = form.text(payload, "joined")
    if not raw:
        raise UiError("입사일을 적어 주세요. 예: 2023-03-02")
    try:
        joined = life.parse_date(raw)
        on = (life.parse_date(form.text(payload, "on"))
              if form.text(payload, "on") else _date.today())
    except ValueError as exc:
        raise UiError(f"날짜를 읽지 못했습니다: {exc}") from None
    try:
        got = life.annual_leave(joined, on)
    except ValueError as exc:
        raise UiError(str(exc)) from None

    ahead = int(form.number(payload, "ahead", 5, low=0, high=40))
    rows = []
    for step in range(1, ahead + 1):
        years = got.years + step
        when = life.add_years(joined, years)
        rows.append([f"{years}년차", f"{when:%Y-%m-%d}", f"{life.annual_days(years)}일"])

    span = f"근속 {got.years}년" if got.years else f"근속 {got.months}개월"
    return {"headline": f"{got.days}일",
            "span": f"입사 {joined:%Y-%m-%d} · 기준 {on:%Y-%m-%d} · {span}",
            "basis": got.basis,
            "next": (f"{got.next_date:%Y-%m-%d}({life.weekday_ko(got.next_date)}) "
                     f"· {got.next_days}일" if got.next_date else ""),
            "rows": rows,
            "command": form.command("life", "annual", f"{joined:%Y-%m-%d}",
                                    *(["--on", f"{on:%Y-%m-%d}"]
                                      if form.text(payload, "on") else []),
                                    *(["--table", ahead] if ahead else []))}


def won(payload: dict) -> dict:
    amount = _amount(payload, "amount")
    return {"plain": life.format_won(amount),
            "korean": life.korean_amount(amount),
            "formal": life.formal_amount(amount)}


BODY = """
<nav class="tabs" id="tabs">
  <button data-tab="dday" aria-selected="true">D-day</button>
  <button data-tab="split" aria-selected="false">더치페이</button>
  <button data-tab="loan" aria-selected="false">대출</button>
  <button data-tab="workday" aria-selected="false">영업일</button>
  <button data-tab="unit" aria-selected="false">단위</button>
  <button data-tab="tax" aria-selected="false">부가세·원천징수</button>
  <button data-tab="saving" aria-selected="false">적금·예금</button>
  <button data-tab="rent" aria-selected="false">전월세</button>
  <button data-tab="worktime" aria-selected="false">근무 시간</button>
  <button data-tab="hourly" aria-selected="false">시급·수당</button>
  <button data-tab="weekly" aria-selected="false">주휴수당</button>
  <button data-tab="annual" aria-selected="false">연차</button>
  <button data-tab="severance" aria-selected="false">퇴직금</button>
  <button data-tab="won" aria-selected="false">금액 한글</button>
</nav>

<section class="card" data-panel="dday">
  <h2>며칠 남았나 / 며칠째인가</h2>
  <div class="row">
    <div><label for="d-date">날짜</label>
      <input type="text" id="d-date" placeholder="2026-03-15, 20260315" spellcheck="false"></div>
    <div><label for="d-today">기준일 (비우면 오늘)</label>
      <input type="text" id="d-today" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-dday">계산</button></div>
  </div>
  <div id="dday-out"></div>
</section>

<section class="card" data-panel="split" hidden>
  <h2>누가 누구에게 얼마를 보내면 되나</h2>
  <div>
    <label for="s-paid">한 줄에 «이름 금액»</label>
    <textarea id="s-paid" spellcheck="false" placeholder="홍길동 84000&#10;김철수 12000&#10;이영희 0"></textarea>
  </div>
  <div class="row" style="margin-top:.8rem">
    <div><label for="s-extra">돈은 안 냈지만 함께한 사람 (쉼표)</label>
      <input type="text" id="s-extra" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-split">정산</button></div>
  </div>
  <div id="split-out"></div>
</section>

<section class="card" data-panel="loan" hidden>
  <h2>다달이 얼마를 갚나</h2>
  <div class="row">
    <div><label for="l-principal">빌리는 돈</label>
      <input type="text" id="l-principal" placeholder="3억, 300000000" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="l-rate">연 이자율(%)</label>
      <input type="text" id="l-rate" value="4.0" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="l-months">개월</label>
      <input type="text" id="l-months" value="360" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="l-grace">거치(개월)</label>
      <input type="text" id="l-grace" value="0" spellcheck="false"></div>
    <div><label for="l-kind">방식</label>
      <select id="l-kind">
        <option>원리금균등</option><option>원금균등</option><option>만기일시</option>
      </select></div>
  </div>
  <div class="actions"><button class="primary" id="btn-loan">계산</button></div>
  <div id="loan-out"></div>
</section>

<section class="card" data-panel="workday" hidden>
  <h2>영업일</h2>
  <div class="row">
    <div><label for="k-start">기준일 (비우면 오늘)</label>
      <input type="text" id="k-start" placeholder="2026-08-14" spellcheck="false"></div>
    <div><label for="k-target">끝날짜 또는 +N</label>
      <input type="text" id="k-target" placeholder="+5 또는 2026-09-30" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-workday">계산</button></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="k-exclusive"> 기준일은 세지 않기</label>
  </div>
  <div id="workday-out"></div>
  <div class="row" style="margin-top:1.2rem">
    <div style="flex:0 1 8rem"><label for="k-year">공휴일 볼 해</label>
      <input type="text" id="k-year" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button id="btn-holidays">공휴일 목록</button></div>
  </div>
  <div id="holiday-out"></div>
</section>

<section class="card" data-panel="unit" hidden>
  <h2>단위 바꾸기</h2>
  <div class="row">
    <div><label for="u-value">숫자와 단위</label>
      <input type="text" id="u-value" placeholder="84㎡, 3근, 25도c, 5마일" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-unit">바꾸기</button></div>
  </div>
  <div id="unit-out"></div>
</section>

<section class="card" data-panel="tax" hidden>
  <h2>세금</h2>
  <div class="row">
    <div><label for="t-amount">금액</label>
      <input type="text" id="t-amount" placeholder="1100000, 110만" spellcheck="false"></div>
    <div><label for="t-mode">무엇을</label>
      <select id="t-mode">
        <option value="add">부가세를 더한다 (공급가액 입력)</option>
        <option value="extract">부가세를 빼낸다 (총액 입력)</option>
        <option value="withhold">원천징수 3.3% (지급액 입력)</option>
      </select></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-tax">계산</button></div>
  </div>
  <div id="tax-out"></div>
</section>

<section class="card" data-panel="saving" hidden>
  <h2>만기에 얼마를 받나</h2>
  <div class="row">
    <div><label for="v-kind">방식</label>
      <select id="v-kind"><option>적금</option><option>예금</option></select></div>
    <div><label for="v-amount">금액 (적금은 매달, 예금은 한 번에)</label>
      <input type="text" id="v-amount" placeholder="50만" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="v-months">개월</label>
      <input type="text" id="v-months" value="12" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="v-rate">연 금리(%)</label>
      <input type="text" id="v-rate" value="3.5" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-saving">계산</button></div>
  </div>
  <div id="saving-out"></div>
</section>

<section class="card" data-panel="rent" hidden>
  <h2>전세 ↔ 월세</h2>
  <div class="row">
    <div><label for="r-deposit">전세보증금 (또는 기준 보증금)</label>
      <input type="text" id="r-deposit" placeholder="3억" spellcheck="false"></div>
    <div><label for="r-keep">남길 보증금</label>
      <input type="text" id="r-keep" placeholder="1억" spellcheck="false"></div>
    <div><label for="r-monthly">월세 (적으면 보증금으로 되돌림)</label>
      <input type="text" id="r-monthly" placeholder="비워 두세요" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="r-rate">전환율(%)</label>
      <input type="text" id="r-rate" value="5.5" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-rent">계산</button></div>
  </div>
  <div id="rent-out"></div>
</section>

<section class="card" data-panel="worktime" hidden>
  <h2>몇 시간 일했나</h2>
  <div>
    <label for="t-spans">한 줄에 하나씩 «09:00-18:30»</label>
    <textarea id="t-spans" spellcheck="false" placeholder="09:00-18:30&#10;20:00-22:00"></textarea>
  </div>
  <div class="row" style="margin-top:.8rem">
    <div style="flex:0 1 8rem"><label for="t-rest">휴게(분)</label>
      <input type="text" id="t-rest" value="60" spellcheck="false"></div>
    <div style="flex:0 1 9rem"><label for="t-rate">시급 (선택)</label>
      <input type="text" id="t-rate" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-worktime">계산</button></div>
  </div>
  <div id="worktime-out"></div>
</section>

<section class="card" data-panel="hourly" hidden>
  <h2>통상시급과 가산 수당</h2>
  <p class="note">월 통상임금에서 시급과 연장·야간·휴일 단가를 냅니다
     (근로기준법 제56조: 연장·야간 50%, 휴일 8시간까지 50%, 넘는 시간 100%).
     한 달 소정근로시간 209시간은 <b>법이 정한 값이 아니라 흔한 값</b>입니다.
     야간은 연장과 겹치는 일이 많아 <b>가산분만</b> 셉니다.</p>
  <div class="row">
    <div style="flex:1 1 10rem"><label for="hmonthly">월 통상임금</label>
      <input type="text" id="hmonthly" placeholder="300만" spellcheck="false"></div>
    <div style="flex:0 1 8rem"><label for="hhours">소정근로시간</label>
      <input type="text" id="hhours" value="209" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="hover">연장(시간)</label>
      <input type="text" id="hover" value="0" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="hnight">야간(시간)</label>
      <input type="text" id="hnight" value="0" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="hholiday">휴일(시간)</label>
      <input type="text" id="hholiday" value="0" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-hourly">계산</button></div>
  </div>
  <div id="hourly-out"></div>
</section>

<section class="card" data-panel="weekly" hidden>
  <h2>주휴수당</h2>
  <p class="note">1주 소정근로시간이 <b>15시간 이상</b>이면 주휴수당이 붙습니다
     (근로기준법 제55조·시행령 제30조). <code>(1주 소정근로시간 ÷ 40) × 8 × 시급</code>
     이고, 40시간을 넘겨 일해도 주휴는 8시간분까지입니다. <b>계산식을 그대로
     보여 드리니</b> 숫자가 이상하면 어디가 틀렸는지 바로 보입니다.
     1주 소정근로일을 «개근» 해야 나오므로 결근한 주에는 없습니다.</p>
  <div class="row">
    <div style="flex:1 1 10rem"><label for="wkhourly">시급</label>
      <input type="text" id="wkhourly" placeholder="10030" spellcheck="false"></div>
    <div style="flex:0 1 10rem"><label for="wkhours">1주 소정근로시간</label>
      <input type="text" id="wkhours" value="40" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-weekly">계산</button></div>
  </div>
  <div id="weeklymsg"></div>
  <div id="weekly-out"></div>
</section>

<section class="card" data-panel="annual" hidden>
  <h2>연차 며칠 생기나</h2>
  <p class="note">입사일 기준으로 근로기준법 제60조 그대로 셉니다. 1년 미만은
     한 달 개근마다 하루(최대 11일), 1년부터 15일, 3년째부터 2년마다 하루씩
     늘어 최대 25일입니다. <b>회계연도 기준으로 운영하는 회사는 회사 규정이
     우선</b>이고, 출근율 80% 미달·휴직은 반영하지 않습니다.</p>
  <div class="row">
    <div><label for="a-joined">입사일</label>
      <input type="text" id="a-joined" placeholder="2023-03-02" spellcheck="false"></div>
    <div><label for="a-on">기준일 (비우면 오늘)</label>
      <input type="text" id="a-on" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="a-ahead">앞으로 몇 년</label>
      <input type="text" id="a-ahead" value="5" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-annual">계산</button></div>
  </div>
  <div id="annual-out"></div>
</section>

<section class="card" data-panel="severance" hidden>
  <h2>퇴직금 얼마나 나오나</h2>
  <p class="note">평균임금(퇴직 전 3개월 임금총액 ÷ 그 기간의 달력 일수) x 30일 x
     재직일수 ÷ 365. 연간 상여금과 전년도 연차수당은 <b>3/12 만</b> 더합니다.
     <b>세전</b>이고, 퇴직소득세는 빼지 않습니다.</p>
  <div class="row">
    <div><label for="s-joined">입사일</label>
      <input type="text" id="s-joined" placeholder="2021-03-02" spellcheck="false"></div>
    <div><label for="s-left">퇴사일</label>
      <input type="text" id="s-left" placeholder="2026-09-01" spellcheck="false"></div>
    <div><label for="s-pay">3개월 임금총액</label>
      <input type="text" id="s-pay" placeholder="1500만" spellcheck="false"></div>
  </div>
  <div class="row" style="margin-top:.6rem">
    <div><label for="s-bonus">연간 상여금 (없으면 비움)</label>
      <input type="text" id="s-bonus" spellcheck="false"></div>
    <div><label for="s-leave">전년도 연차수당</label>
      <input type="text" id="s-leave" spellcheck="false"></div>
    <div><label for="s-ordinary">1일 통상임금</label>
      <input type="text" id="s-ordinary" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-severance">계산</button></div>
  </div>
  <div id="severance-out"></div>
</section>

<section class="card" data-panel="won" hidden>
  <h2>계약서에 쓰는 금액 표기</h2>
  <div class="row">
    <div><label for="w-amount">금액</label>
      <input type="text" id="w-amount" placeholder="1250000, 125만" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-won">바꾸기</button></div>
  </div>
  <div id="won-out"></div>
</section>

<script>
(function () {
  const $ = (id) => document.getElementById(id);

  document.querySelectorAll("#tabs button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll("#tabs button").forEach(function (b) {
        b.setAttribute("aria-selected", String(b === btn));
      });
      document.querySelectorAll("[data-panel]").forEach(function (panel) {
        panel.hidden = panel.dataset.panel !== btn.dataset.tab;
      });
    });
  });

  function big(text) { return '<p class="big">' + text + "</p>"; }

  async function run(where, path, body, draw) {
    try { draw(await AT.call(path, body)); }
    catch (e) { AT.message($(where), AT.esc(e.message), "bad"); }
  }

  $("btn-dday").addEventListener("click", function () {
    run("dday-out", "/api/life/dday",
        { date: $("d-date").value, today: $("d-today").value }, function (d) {
      $("dday-out").innerHTML = big(AT.esc(d.headline)) +
        '<p class="note">' + AT.esc(d.target) + " · 만 " + d.age + "년</p>" +
        AT.table(["기념일", "날짜", "언제"], d.rows);
    });
  });

  $("btn-severance").addEventListener("click", function () {
    run("severance-out", "/api/life/severance",
        { sjoined: $("s-joined").value, sleft: $("s-left").value,
          spay: $("s-pay").value, sbonus: $("s-bonus").value,
          sleave: $("s-leave").value, sordinary: $("s-ordinary").value },
        function (d) {
      $("severance-out").innerHTML = big(AT.esc(d.headline)) +
        '<p class="note">' + AT.esc(d.span) + "</p>" +
        AT.table(["항목", "값"], d.rows) +
        '<p class="note">' + d.notes.map(AT.esc).join("<br>") + "</p>" +
        AT.command(d.command);
    });
  });

  $("btn-annual").addEventListener("click", function () {
    run("annual-out", "/api/life/annual",
        { joined: $("a-joined").value, on: $("a-on").value,
          ahead: $("a-ahead").value }, function (d) {
      $("annual-out").innerHTML = big(AT.esc(d.headline)) +
        '<p class="note">' + AT.esc(d.span) + "<br>" + AT.esc(d.basis) +
        (d.next ? " · 다음 발생 " + AT.esc(d.next) : "") + "</p>" +
        (d.rows.length ? AT.table(["근속", "그 날짜", "연차"], d.rows) : "") +
        AT.command(d.command);
    });
  });

  $("btn-split").addEventListener("click", function () {
    run("split-out", "/api/life/split",
        { paid: $("s-paid").value, extra: $("s-extra").value }, function (d) {
      $("split-out").innerHTML = big("한 사람당 " + AT.esc(d.share)) +
        '<p class="note">' + d.people + "명, 모두 " + AT.esc(d.total) + "</p>" +
        AT.table(["이름", "낸 돈", "더 낸 만큼"], d.rows, [null, "num", "num"]) +
        (d.moves.length
          ? "<h2>이렇게 보내면 됩니다</h2>" +
            AT.table(["보내는 사람", "받는 사람", "금액"], d.moves,
                     [null, null, "num"])
          : '<p class="note">주고받을 것이 없습니다.</p>');
    });
  });

  $("btn-loan").addEventListener("click", function () {
    run("loan-out", "/api/life/loan", {
      principal: $("l-principal").value, rate: $("l-rate").value,
      months: $("l-months").value, grace: $("l-grace").value,
      kind: $("l-kind").value,
    }, function (d) {
      $("loan-out").innerHTML = big("첫 달 " + AT.esc(d.first)) +
        '<p class="note">' + d.months + "개월 동안 이자 " +
        AT.esc(d.interest) + ", 원리금 합계 " + AT.esc(d.total) + "</p>" +
        (d.skipped ? '<p class="note">가운데 ' + d.skipped +
                     "개월은 줄였습니다.</p>" : "") +
        AT.table(["회차", "낼 돈", "이자", "원금", "남은 원금"], d.rows,
                 ["num", "num", "num", "num", "num"]);
    });
  });

  function warn(lines) {
    return lines && lines.length
      ? '<p class="note">' + lines.map(AT.esc).join("<br>") + "</p>" : "";
  }

  $("btn-workday").addEventListener("click", function () {
    run("workday-out", "/api/life/workday", {
      start: $("k-start").value, target: $("k-target").value,
      exclusive: $("k-exclusive").checked,
    }, function (d) {
      $("workday-out").innerHTML = big(AT.esc(d.headline)) +
        AT.table(["항목", "값"], d.rows) + warn(d.warning);
    });
  });

  $("btn-holidays").addEventListener("click", function () {
    run("holiday-out", "/api/life/holidays", { year: $("k-year").value },
        function (d) {
      $("holiday-out").innerHTML = big(d.year + "년 공휴일 " + d.rows.length + "일") +
        AT.table(["날짜", "요일", "이름", ""], d.rows) + warn(d.warning);
    });
  });

  $("btn-unit").addEventListener("click", function () {
    run("unit-out", "/api/life/unit", { value: $("u-value").value },
        function (d) {
      $("unit-out").innerHTML = big(AT.esc(d.from) + " · " + AT.esc(d.group)) +
        AT.table(["단위", "값"], d.rows, [null, "num"]);
    });
  });

  $("btn-tax").addEventListener("click", function () {
    run("tax-out", "/api/life/tax",
        { amount: $("t-amount").value, mode: $("t-mode").value }, function (d) {
      $("tax-out").innerHTML = big(AT.esc(d.headline)) +
        AT.table(["항목", "금액"], d.rows, [null, "num"]) +
        '<p class="note">' + AT.esc(d.note) + "</p>";
    });
  });

  function table2(where, d) {
    $(where).innerHTML = big(AT.esc(d.headline)) +
      AT.table(["항목", "값"], d.rows, [null, "num"]) +
      '<p class="note">' + AT.esc(d.note) + "</p>";
  }

  $("btn-saving").addEventListener("click", function () {
    run("saving-out", "/api/life/saving", {
      kind: $("v-kind").value, amount: $("v-amount").value,
      months: $("v-months").value, rate: $("v-rate").value,
    }, function (d) { table2("saving-out", d); });
  });

  $("btn-rent").addEventListener("click", function () {
    run("rent-out", "/api/life/rent", {
      deposit: $("r-deposit").value, keep: $("r-keep").value,
      monthly: $("r-monthly").value, rate: $("r-rate").value,
    }, function (d) { table2("rent-out", d); });
  });

  $("btn-weekly").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/life/weekly",
        { wkhourly: $("wkhourly").value, wkhours: $("wkhours").value });
      $("weekly-out").innerHTML =
        AT.table(["무엇", "얼마"], d.rows, [null, "num"]) +
        (d.eligible
          ? '<p class="note">계산식: ' + AT.esc(d.formula) +
            (d.capped ? " · 40시간을 넘겨도 주휴는 8시간분까지입니다." : "") + "</p>"
          : "") + AT.command(d.command);
      AT.message($("weeklymsg"), d.eligible
        ? "1주 소정근로일을 개근해야 나옵니다."
        : "1주 소정근로시간이 " + d.least + "시간 미만이라 주휴수당이 없습니다.",
        d.eligible ? "ok" : "bad");
    } catch (e) { AT.message($("weeklymsg"), AT.esc(e.message), "bad"); }
  });

  $("btn-hourly").addEventListener("click", function () {
    run("hourly-out", "/api/life/hourly", {
      hmonthly: $("hmonthly").value, hhours: $("hhours").value,
      hover: $("hover").value, hnight: $("hnight").value,
      hholiday: $("hholiday").value,
    }, function (d) {
      $("hourly-out").innerHTML =
        AT.table(["무엇", "1시간", "배수"], d.rows, [null, "num", "num"]) +
        (d.paid.length
          ? "<h2>이번 달 가산 수당</h2>" +
            AT.table(["무엇", "얼마"], d.paid, [null, "num"]) +
            '<p class="note">가산 수당만 더한 것입니다. 월급은 따로입니다.</p>'
          : "") +
        '<p class="note">' + AT.esc(d.note) + "</p>" + AT.command(d.command);
    });
  });

  $("btn-worktime").addEventListener("click", function () {
    run("worktime-out", "/api/life/worktime", {
      spans: $("t-spans").value, rest: $("t-rest").value,
      rate: $("t-rate").value,
    }, function (d) { table2("worktime-out", d); });
  });

  $("btn-won").addEventListener("click", function () {
    run("won-out", "/api/life/won", { amount: $("w-amount").value },
        function (d) {
      $("won-out").innerHTML = big(AT.esc(d.plain)) +
        AT.table(["표기", "값"],
                 [["한글", d.korean], ["계약서용", d.formal]]);
    });
  });
})();
</script>
"""


def make() -> App:
    return App(
        key="life",
        name="일상 계산",
        summary="D-day·더치페이·대출·영업일·적금·전월세·근무시간·단위·세금",
        subtitle="숫자만 다룹니다 · 파일은 건드리지 않습니다",
        body=lambda: BODY,
        actions={"dday": dday, "split": split, "loan": loan, "unit": unit,
                 "annual": annual, "severance": severance,
                 "tax": tax, "won": won, "workday": workday,
                 "holidays": holidays, "saving": saving, "rent": rent,
                 "worktime": worktime, "hourly": hourly,
                 "weekly": weekly},
        aliases=("일상", "계산", "계산기"),
        section="그 밖",
    )
