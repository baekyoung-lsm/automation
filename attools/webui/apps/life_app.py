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
        summary="D-day, 더치페이, 대출, 영업일, 단위, 세금, 금액 한글 표기",
        subtitle="숫자만 다룹니다 · 파일은 건드리지 않습니다",
        body=lambda: BODY,
        actions={"dday": dday, "split": split, "loan": loan, "unit": unit,
                 "tax": tax, "won": won, "workday": workday,
                 "holidays": holidays},
        aliases=("일상", "계산", "계산기"),
        section="그 밖",
    )
