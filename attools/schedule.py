"""cron 표현식 해석: 다음 실행 시각과 사람이 읽는 설명."""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta

MONTH_NAMES = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
               "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
DOW_NAMES = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
DOW_KO = ["일", "월", "화", "수", "목", "금", "토"]

MACROS = {
    "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *", "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *", "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}

# (이름, 최소, 최대)
FIELDS = [("분", 0, 59), ("시", 0, 23), ("일", 1, 31), ("월", 1, 12), ("요일", 0, 7)]


class CronError(ValueError):
    pass


def _named(token: str, index: int) -> str:
    up = token.upper()
    if index == 3 and up in MONTH_NAMES:
        return str(MONTH_NAMES.index(up) + 1)
    if index == 4 and up in DOW_NAMES:
        return str(DOW_NAMES.index(up))
    return token


def _parse_field(spec: str, index: int) -> set[int]:
    name, lo, hi = FIELDS[index]
    values: set[int] = set()

    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, _, step_s = part.partition("/")
            if not step_s.isdigit() or int(step_s) == 0:
                raise CronError(f"{name} 필드의 간격이 잘못됐습니다: /{step_s}")
            step = int(step_s)

        if part in ("*", "?"):
            start, end = lo, hi
        elif "-" in part.lstrip("-"):
            a, _, b = part.partition("-")
            start, end = int(_named(a, index)), int(_named(b, index))
        else:
            start = end = int(_named(part, index))

        if start > end:
            raise CronError(f"{name} 필드 범위가 거꾸로입니다: {part}")
        if start < lo or end > hi:
            raise CronError(f"{name} 필드는 {lo}~{hi} 범위여야 합니다: {part}")
        values.update(range(start, end + 1, step))

    if index == 4 and 7 in values:  # 일요일은 0과 7 둘 다 쓴다
        values.discard(7)
        values.add(0)
    return values


class Cron:
    def __init__(self, expression: str):
        expr = expression.strip()
        expr = MACROS.get(expr.lower(), expr)
        parts = expr.split()
        if len(parts) != 5:
            raise CronError(f"5개 필드가 필요합니다 (분 시 일 월 요일). 받은 값: {len(parts)}개")

        self.expression = expr
        self.raw = parts
        try:
            self.minute, self.hour, self.dom, self.month, self.dow = (
                _parse_field(p, i) for i, p in enumerate(parts))
        except ValueError as e:
            raise CronError(str(e)) from None

        # 일/요일이 둘 다 제한돼 있으면 cron 은 OR 로 판단한다.
        self.dom_restricted = parts[2] not in ("*", "?")
        self.dow_restricted = parts[4] not in ("*", "?")

    def matches_day(self, d: datetime) -> bool:
        if d.month not in self.month:
            return False
        dom_ok = d.day in self.dom
        dow_ok = (d.weekday() + 1) % 7 in self.dow  # 파이썬 월=0 -> cron 일=0
        if self.dom_restricted and self.dow_restricted:
            return dom_ok or dow_ok
        return dom_ok and dow_ok

    def next_runs(self, start: datetime, count: int = 5) -> list[datetime]:
        cur = (start + timedelta(minutes=1)).replace(second=0, microsecond=0)
        out: list[datetime] = []
        guard = 0
        while len(out) < count:
            guard += 1
            if guard > 500_000:
                raise CronError("다음 실행 시각을 찾지 못했습니다. 표현식을 확인하세요.")
            if not self.matches_day(cur):
                cur = (cur + timedelta(days=1)).replace(hour=0, minute=0)
                continue
            if cur.hour not in self.hour:
                cur += timedelta(hours=1)
                cur = cur.replace(minute=0)
                continue
            if cur.minute not in self.minute:
                cur += timedelta(minutes=1)
                continue
            out.append(cur)
            cur += timedelta(minutes=1)
        return out

    # ------------------------------------------------------------- 설명

    def _describe_set(self, values: set[int], index: int) -> str:
        raw = self.raw[index]
        if raw in ("*", "?"):
            return "매"
        ordered = sorted(values)
        if len(ordered) > 12:
            return f"{len(ordered)}개 값"
        if index == 4:
            return ", ".join(DOW_KO[v] for v in ordered)
        return ", ".join(str(v) for v in ordered)

    def describe(self) -> str:
        m, h, dom, mon, dow = self.raw
        when = []

        if mon != "*":
            when.append(f"{self._describe_set(self.month, 3)}월")
        if self.dow_restricted:
            when.append(f"{self._describe_set(self.dow, 4)}요일")
        if self.dom_restricted:
            when.append(f"{self._describe_set(self.dom, 2)}일")
        if not when:
            when.append("매일")
        if self.dom_restricted and self.dow_restricted:
            when.append("(일 또는 요일 중 하나만 맞아도 실행)")

        if h == "*" and m == "*":
            time_part = "1분마다"
        elif h == "*":
            time_part = f"매시 {self._describe_set(self.minute, 0)}분"
        elif re.fullmatch(r"\*/\d+", h):
            time_part = f"{h[2:]}시간마다 {self._describe_set(self.minute, 0)}분"
        elif re.fullmatch(r"\*/\d+", m):
            time_part = f"{self._describe_set(self.hour, 1)}시에 {m[2:]}분마다"
        else:
            time_part = f"{self._describe_set(self.hour, 1)}시 {self._describe_set(self.minute, 0)}분"

        return " ".join(when) + " " + time_part


def month_last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]
