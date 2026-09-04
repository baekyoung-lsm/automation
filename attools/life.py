"""일상 계산기: D-day, 더치페이 정산, 대출 상환, 단위 변환."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# ------------------------------------------------------------ 숫자 읽기

_UNITS = [("조", 10**12), ("억", 10**8), ("만", 10**4), ("천", 10**3)]


def parse_amount(text: str) -> float:
    """'3억5000만', '1.5억', '350,000,000' 을 숫자로."""
    s = text.strip().replace(",", "").replace("원", "").replace(" ", "")
    if not s:
        raise ValueError("금액이 비어 있습니다.")
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return float(s)

    total = 0.0
    rest = s
    for name, mult in _UNITS:
        if name not in rest:
            continue
        head, _, rest = rest.partition(name)
        head = head or "1"
        if not re.fullmatch(r"\d+(\.\d+)?", head):
            raise ValueError(f"금액을 해석하지 못했습니다: {text}")
        total += float(head) * mult
    if rest:
        if not re.fullmatch(r"\d+(\.\d+)?", rest):
            raise ValueError(f"금액을 해석하지 못했습니다: {text}")
        total += float(rest)
    if total == 0:
        raise ValueError(f"금액을 해석하지 못했습니다: {text}")
    return total


def format_won(value: float) -> str:
    """큰 금액은 억/만 단위 설명을 붙인다."""
    n = round(value)
    out = f"{n:,}원"
    if abs(n) >= 10**6:  # 백만 이상일 때만 억/만 단위를 덧붙인다
        eok, rest = divmod(abs(n), 10**8)
        man, won = divmod(rest, 10**4)
        parts = []
        if eok:
            parts.append(f"{eok}억")
        if man:
            parts.append(f"{man:,}만")
        if won and not eok:
            parts.append(f"{won:,}")
        if parts:
            out += f" ({'-' if n < 0 else ''}{' '.join(parts)})"
    return out


# ------------------------------------------------------------------ D-day

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def parse_date(text: str) -> date:
    s = text.strip()
    if s in ("오늘", "today"):
        return date.today()
    s = re.sub(r"[./]", "-", s)
    if re.fullmatch(r"\d{8}", s):
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return datetime.strptime(s, "%Y-%m-%d").date()


def korean_age(born: date, on: date | None = None) -> int:
    """만 나이. 생일이 지났으면 그해 나이, 아니면 한 살 적다."""
    on = on or date.today()
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


@dataclass
class DDay:
    target: date
    today: date

    @property
    def delta(self) -> int:
        return (self.target - self.today).days

    @property
    def nth_day(self) -> int:
        """당일을 1일로 세는 한국식 '오늘이 며칠째'."""
        return (self.today - self.target).days + 1

    def milestones(self, counts=(100, 200, 300, 365, 500, 1000, 2000)) -> list[tuple[str, date, int]]:
        """다가올 기념일 (이름, 날짜, 남은 일수)."""
        out = []
        for n in counts:
            # 한국식으로 시작일을 1일로 세므로 100일은 시작일 + 99일
            when = self.target + timedelta(days=n - 1)
            if when >= self.today:
                out.append((f"{n}일", when, (when - self.today).days))
        for years in range(1, 51):
            try:
                when = self.target.replace(year=self.target.year + years)
            except ValueError:  # 2월 29일
                when = self.target.replace(year=self.target.year + years, day=28)
            if when >= self.today:
                out.append((f"{years}주년", when, (when - self.today).days))
                break
        return sorted(out, key=lambda x: x[1])


def weekday_ko(d: date) -> str:
    return WEEKDAYS[d.weekday()]


# --------------------------------------------------------------- 더치페이

@dataclass
class Transfer:
    payer: str
    payee: str
    amount: float


def settle(paid: dict[str, float], *, extra: list[str] | None = None,
           weights: dict[str, float] | None = None) -> tuple[float, dict[str, float], list[Transfer]]:
    """각자 낸 돈에서 정산 송금 목록을 만든다. (1인 기준액, 잔액, 송금 목록)"""
    people = dict(paid)
    for name in extra or []:
        people.setdefault(name, 0.0)
    if not people:
        raise ValueError("참여자가 없습니다.")

    weights = weights or {}
    total_weight = sum(weights.get(n, 1.0) for n in people)
    total = sum(people.values())
    share = {n: total * weights.get(n, 1.0) / total_weight for n in people}

    balance = {n: round(people[n] - share[n]) for n in people}

    creditors = sorted(((n, v) for n, v in balance.items() if v > 0), key=lambda x: -x[1])
    debtors = sorted(((n, -v) for n, v in balance.items() if v < 0), key=lambda x: -x[1])

    transfers: list[Transfer] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        (dn, dv), (cn, cv) = debtors[i], creditors[j]
        amount = min(dv, cv)
        if amount >= 1:
            transfers.append(Transfer(dn, cn, amount))
        debtors[i] = (dn, dv - amount)
        creditors[j] = (cn, cv - amount)
        if debtors[i][1] < 1:
            i += 1
        if creditors[j][1] < 1:
            j += 1

    return total / total_weight, balance, transfers


# ------------------------------------------------------------------ 대출

@dataclass
class Payment:
    no: int
    payment: float
    interest: float
    principal: float
    balance: float


def amortize(principal: float, annual_rate: float, months: int, *,
             kind: str = "원리금균등", grace: int = 0) -> list[Payment]:
    """상환 스케줄. kind: 원리금균등 | 원금균등 | 만기일시"""
    r = annual_rate / 100 / 12
    rows: list[Payment] = []
    balance = principal

    for n in range(1, grace + 1):  # 거치기간: 이자만 낸다
        interest = balance * r
        rows.append(Payment(n, interest, interest, 0.0, balance))

    left = months - grace
    if left <= 0:
        raise ValueError("거치기간이 전체 기간보다 깁니다.")

    if kind == "원리금균등":
        pay = balance * r / (1 - (1 + r) ** -left) if r else balance / left
        for n in range(grace + 1, months + 1):
            interest = balance * r
            part = pay - interest
            if n == months:
                part, pay = balance, balance + interest
            balance -= part
            rows.append(Payment(n, pay, interest, part, max(balance, 0.0)))
    elif kind == "원금균등":
        part = balance / left
        for n in range(grace + 1, months + 1):
            interest = balance * r
            balance -= part
            rows.append(Payment(n, part + interest, interest, part, max(balance, 0.0)))
    elif kind == "만기일시":
        for n in range(grace + 1, months + 1):
            interest = balance * r
            if n == months:
                rows.append(Payment(n, balance + interest, interest, balance, 0.0))
            else:
                rows.append(Payment(n, interest, interest, 0.0, balance))
    else:
        raise ValueError(f"알 수 없는 상환 방식: {kind}")

    return rows


# ------------------------------------------------------------- 단위 변환

# 그룹별로 기준 단위를 하나 정하고 배수를 적어 둔다.
UNIT_GROUPS: dict[str, dict[str, float]] = {
    "넓이": {"㎡": 1.0, "m2": 1.0, "제곱미터": 1.0, "평": 400 / 121,
             "평방미터": 1.0, "ha": 10000.0, "헥타르": 10000.0, "에이커": 4046.8564224},
    "길이": {"m": 1.0, "미터": 1.0, "cm": 0.01, "mm": 0.001, "km": 1000.0,
             "인치": 0.0254, "in": 0.0254, "피트": 0.3048, "ft": 0.3048,
             "야드": 0.9144, "마일": 1609.344, "자": 0.303, "치": 0.0303, "리": 392.7},
    "무게": {"g": 1.0, "kg": 1000.0, "mg": 0.001, "t": 10**6, "톤": 10**6,
             "근": 600.0, "관": 3750.0, "돈": 3.75, "냥": 37.5,
             "파운드": 453.59237, "lb": 453.59237, "온스": 28.349523125, "oz": 28.349523125},
    "부피": {"L": 1.0, "l": 1.0, "리터": 1.0, "mL": 0.001, "ml": 0.001,
             "되": 1.8039, "말": 18.039, "홉": 0.18039,
             "갤런": 3.785411784, "gal": 3.785411784},
}

_VALUE_UNIT = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*([^\d\s]+)\s*$")


def convert(text: str) -> tuple[str, float, str, list[tuple[str, float]]]:
    """'84㎡' 를 같은 그룹의 다른 단위로 모두 바꾼다. (그룹, 값, 단위, 결과들)"""
    text = text.strip()
    if m := re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*(?:도)?\s*([cCfF])\s*", text):
        value = float(m.group(1))
        if m.group(2) in "cC":
            return "온도", value, "℃", [("℉", value * 9 / 5 + 32), ("K", value + 273.15)]
        return "온도", value, "℉", [("℃", (value - 32) * 5 / 9), ("K", (value - 32) * 5 / 9 + 273.15)]

    m = _VALUE_UNIT.match(text)
    if not m:
        raise ValueError(f"'숫자+단위' 형태여야 합니다: {text}")
    value, unit = float(m.group(1)), m.group(2)

    for group, table in UNIT_GROUPS.items():
        if unit not in table:
            continue
        base = value * table[unit]
        seen: set[float] = {table[unit]}  # 같은 배수의 별칭은 한 번만
        results = []
        for name, factor in table.items():
            if factor in seen or name == unit:
                continue
            seen.add(factor)
            results.append((name, base / factor))
        return group, value, unit, results

    known = ", ".join(sorted({u for t in UNIT_GROUPS.values() for u in t}))
    raise ValueError(f"모르는 단위입니다: {unit}\n쓸 수 있는 단위: {known}")


# ------------------------------------------------------------- 공휴일·영업일

USER_HOLIDAYS = None  # 실행 시 ~/.attools/holidays.txt 로 채운다

# 날짜가 해마다 같은 양력 공휴일. (월, 일, 이름)
FIXED_HOLIDAYS = [
    (1, 1, "신정"), (3, 1, "삼일절"), (5, 5, "어린이날"), (6, 6, "현충일"),
    (8, 15, "광복절"), (10, 3, "개천절"), (10, 9, "한글날"), (12, 25, "성탄절"),
]
# 주말과 겹치면 대체공휴일이 붙는 것들. 현충일·신정·성탄절은 대상이 아니다.
SUBSTITUTE_TARGETS = {"삼일절", "어린이날", "광복절", "개천절", "한글날"}

# 음력이라 계산해 주지 못하는 것들. 사용자가 직접 넣어야 한다.
LUNAR_HOLIDAYS = ["설날 연휴", "추석 연휴", "부처님오신날"]


def holiday_file() -> "Path":
    from pathlib import Path

    return Path.home() / ".attools" / "holidays.txt"


def load_user_holidays(path=None) -> dict[date, str]:
    """'2026-02-17 설날' 형식의 파일을 읽는다."""
    from pathlib import Path

    path = Path(path) if path else holiday_file()
    if not path.is_file():
        return {}

    out: dict[date, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split(None, 1)
        try:
            out[parse_date(parts[0])] = parts[1].strip() if len(parts) > 1 else "휴일"
        except ValueError:
            continue
    return out


def solar_holidays(year: int) -> dict[date, str]:
    """양력 고정 공휴일과 대체공휴일."""
    base: dict[date, str] = {}
    for month, day, name in FIXED_HOLIDAYS:
        try:
            base[date(year, month, day)] = name
        except ValueError:
            continue

    out = dict(base)
    for when, name in sorted(base.items()):
        if name not in SUBSTITUTE_TARGETS or when.weekday() < 5:
            continue
        candidate = when + timedelta(days=1)
        while candidate.weekday() >= 5 or candidate in out:
            candidate += timedelta(days=1)
        out[candidate] = f"{name} 대체공휴일"
    return out


def holidays_for(year: int, extra: dict[date, str] | None = None) -> dict[date, str]:
    merged = solar_holidays(year)
    for when, name in (extra or {}).items():
        if when.year == year:
            merged[when] = name
    return dict(sorted(merged.items()))


def is_workday(day: date, holidays: dict[date, str]) -> bool:
    return day.weekday() < 5 and day not in holidays


def count_workdays(start: date, end: date, holidays: dict[date, str],
                   *, include_start: bool = True) -> int:
    if end < start:
        start, end = end, start
    day = start if include_start else start + timedelta(days=1)
    count = 0
    while day <= end:
        if is_workday(day, holidays):
            count += 1
        day += timedelta(days=1)
    return count


def add_workdays(start: date, days: int, holidays: dict[date, str]) -> date:
    """영업일 기준으로 앞뒤로 옮긴다. days 가 0 이면 시작일 그대로."""
    if days == 0:
        return start
    step = 1 if days > 0 else -1
    remaining = abs(days)
    day = start
    while remaining:
        day += timedelta(days=step)
        if is_workday(day, holidays):
            remaining -= 1
    return day


def missing_lunar_warning(holidays: dict[date, str], years: list[int]) -> list[str]:
    """음력 명절이 빠져 있으면 알려 준다. 조용히 틀린 답을 내면 안 된다."""
    names = " ".join(holidays.values())
    missing = [n for n in LUNAR_HOLIDAYS if n.split()[0] not in names]
    if not missing:
        return []
    return [f"{', '.join(missing)} 은(는) 음력이라 자동으로 넣지 못했습니다.",
            f"{holiday_file()} 에 '2026-02-17 설날' 처럼 적어 두면 반영됩니다.",
            f"확인한 해: {', '.join(str(y) for y in years)}"]


# ------------------------------------------------------------------- 세금

VAT_RATE = 10.0             # 부가가치세
WITHHOLD_RATE = 3.0         # 사업소득 원천징수 소득세율(지방소득세는 그 10%)
INTEREST_TAX = 15.4         # 이자소득세 14% + 지방소득세 1.4%


@dataclass
class VatSplit:
    supply: int             # 공급가액
    vat: int                # 부가세
    total: int              # 합계


def vat_add(supply: float, *, rate: float = VAT_RATE) -> VatSplit:
    """공급가액에 부가세를 더한다. 원 미만은 버린다."""
    base = int(supply)
    tax = int(base * rate / 100)
    return VatSplit(base, tax, base + tax)


def vat_extract(total: float, *, rate: float = VAT_RATE) -> VatSplit:
    """부가세가 포함된 금액에서 공급가액을 되뽑는다.

    공급가액을 먼저 내림하고 부가세는 차액으로 둔다. 둘을 따로 반올림하면
    합이 원래 금액과 1원씩 어긋난다.
    """
    whole = int(total)
    # 1,100,000 / 1.1 이 999999.999... 로 떨어지는 부동소수 오차를 막는다.
    base = int(whole * 100 / (100 + rate) + 1e-6)
    return VatSplit(base, whole - base, whole)


@dataclass
class Withholding:
    gross: int              # 지급액
    income_tax: int         # 소득세
    local_tax: int          # 지방소득세
    net: int                # 실수령액

    @property
    def tax(self) -> int:
        return self.income_tax + self.local_tax

    @property
    def rate(self) -> float:
        return self.tax / self.gross * 100 if self.gross else 0.0


def withhold(gross: float, *, rate: float = WITHHOLD_RATE) -> Withholding:
    """원천징수. 지방소득세는 소득세의 10% 이고, 각각 원 미만을 버린다.

    3.3% 를 한 번에 곱하는 것과 1~2원 다를 수 있다. 실제 원천징수는
    소득세를 먼저 떼고 그 10% 를 지방소득세로 떼는 순서다.
    """
    amount = int(gross)
    income = int(amount * rate / 100)
    local = int(income * 0.1)
    return Withholding(amount, income, local, amount - income - local)


# ------------------------------------------------------------------- 적금

@dataclass
class Saving:
    kind: str               # 적금 | 예금
    principal: int          # 원금 합계
    interest: int           # 세전 이자
    tax: int                # 이자소득세
    months: int
    annual_rate: float
    tax_rate: float

    @property
    def net_interest(self) -> int:
        return self.interest - self.tax

    @property
    def total(self) -> int:
        return self.principal + self.net_interest

    @property
    def effective(self) -> float:
        """원금 대비 세후 수익률(연 환산). 기간이 0이면 0."""
        if not self.principal or not self.months:
            return 0.0
        return self.net_interest / self.principal * (12 / self.months) * 100


def saving_plan(*, monthly: float = 0, deposit: float = 0, months: int,
                annual_rate: float, tax_rate: float = INTEREST_TAX) -> Saving:
    """정기적금(매달 넣기)과 정기예금(한 번 넣기)의 단리 만기 계산.

    적금 이자는 먼저 넣은 돈이 더 오래 붙으므로 월 이자 × (n(n+1)/2) 이다.
    은행 표시 금리는 대개 이 단리 기준이다. 복리 상품은 계산이 다르다.
    """
    if months <= 0:
        raise ValueError("기간은 1개월 이상이어야 합니다.")
    if bool(monthly) == bool(deposit):
        raise ValueError("매달 넣는 금액(적금)이나 한 번에 넣는 금액(예금) 중 하나만 주세요.")

    r = annual_rate / 100 / 12
    if monthly:
        principal = int(monthly) * months
        interest = int(monthly) * r * months * (months + 1) / 2
        kind = "적금"
    else:
        principal = int(deposit)
        interest = principal * r * months
        kind = "예금"

    interest = int(interest)
    tax = int(interest * tax_rate / 100)
    return Saving(kind, principal, interest, tax, months, annual_rate, tax_rate)
