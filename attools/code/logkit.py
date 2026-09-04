"""로그 파일 훑기: 레벨 집계, 시간대 분포, 반복되는 에러 묶기."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

LEVELS = ["FATAL", "CRITICAL", "ERROR", "WARN", "WARNING", "INFO", "DEBUG", "TRACE"]
LEVEL_ORDER = {name: i for i, name in enumerate(LEVELS)}
SEVERE = {"FATAL", "CRITICAL", "ERROR"}

LEVEL_RE = re.compile(rf"(?<![A-Z])({'|'.join(LEVELS)})(?![A-Z])")

TIME_PATTERNS = [
    (re.compile(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})"), "%Y-%m-%d %H:%M:%S"),
    (re.compile(r"(\d{4}/\d{2}/\d{2})[T ](\d{2}:\d{2}:\d{2})"), "%Y/%m/%d %H:%M:%S"),
    (re.compile(r"(\d{2}/\w{3}/\d{4}):(\d{2}:\d{2}:\d{2})"), "%d/%b/%Y %H:%M:%S"),
]

# 메시지를 묶으려면 매번 달라지는 값을 지워야 한다.
NOISE = [
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?"), "<ip>"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "<email>"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<hex>"),
    (re.compile(r"\b[0-9a-fA-F]{16,}\b"), "<hash>"),
    (re.compile(r"(/[\w.-]+){2,}"), "<path>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b"), "<time>"),
    (re.compile(r'"[^"]{2,}"'), '"<str>"'),
    (re.compile(r"'[^']{2,}'"), "'<str>'"),
    (re.compile(r"\b\d[\d,.]*\b"), "<n>"),
]

TRACE_LINE = re.compile(r"^\s+(?:at\s|File \"|\.\.\.|Caused by|\tat\s)")


@dataclass
class Entry:
    line: int
    level: str
    when: datetime | None
    message: str
    raw: str


@dataclass
class Group:
    pattern: str
    count: int = 0
    level: str = ""
    first: datetime | None = None
    last: datetime | None = None
    sample: str = ""
    lines: list[int] = field(default_factory=list)


def parse_time(line: str, *, year: int | None = None) -> datetime | None:
    for pattern, fmt in TIME_PATTERNS:
        if m := pattern.search(line):
            try:
                return datetime.strptime(f"{m.group(1)} {m.group(2)}", fmt)
            except ValueError:
                continue
    return None


def parse_level(line: str) -> str:
    m = LEVEL_RE.search(line)
    if not m:
        return ""
    level = m.group(1)
    return "WARN" if level == "WARNING" else ("FATAL" if level == "CRITICAL" else level)


def normalize(message: str) -> str:
    """매번 달라지는 값을 자리표시자로 바꿔 같은 사고끼리 묶는다."""
    text = message.strip()
    for pattern, holder in NOISE:
        text = pattern.sub(holder, text)
    return re.sub(r"\s+", " ", text).strip()[:200]


def strip_prefix(line: str) -> str:
    """시각·레벨·로거 이름 같은 앞부분을 떼어 메시지만 남긴다."""
    text = line
    for pattern, _ in TIME_PATTERNS:
        text = pattern.sub("", text, count=1)
    if m := LEVEL_RE.search(text):
        text = text[m.end():]
    return text.lstrip(" \t:[]-|").rstrip()


def parse(lines, *, attach_traces: bool = True) -> list[Entry]:
    """줄을 훑어 항목으로 만든다. 스택 트레이스는 앞 줄에 붙인다."""
    entries: list[Entry] = []
    for n, raw in enumerate(lines, 1):
        raw = raw.rstrip("\n")
        if not raw.strip():
            continue
        if attach_traces and entries and TRACE_LINE.match(raw):
            entries[-1].raw += "\n" + raw
            continue
        entries.append(Entry(n, parse_level(raw), parse_time(raw),
                             strip_prefix(raw), raw))
    return entries


def group_messages(entries: list[Entry], *, levels: set[str] | None = None,
                   top: int = 10) -> list[Group]:
    buckets: dict[str, Group] = {}
    for e in entries:
        if levels and e.level not in levels:
            continue
        key = normalize(e.message)
        if not key:
            continue
        g = buckets.setdefault(key, Group(key, level=e.level, sample=e.message.strip()))
        g.count += 1
        if len(g.lines) < 5:
            g.lines.append(e.line)
        if e.when:
            g.first = e.when if g.first is None else min(g.first, e.when)
            g.last = e.when if g.last is None else max(g.last, e.when)
        if LEVEL_ORDER.get(e.level, 9) < LEVEL_ORDER.get(g.level, 9):
            g.level = e.level
    return sorted(buckets.values(), key=lambda g: -g.count)[:top]


BUCKETS = {"1m": 60, "5m": 300, "10m": 600, "1h": 3600, "1d": 86400}


def histogram(entries: list[Entry], *, bucket: str = "1h",
              levels: set[str] | None = None) -> list[tuple[datetime, int]]:
    seconds = BUCKETS.get(bucket)
    if seconds is None:
        raise ValueError(f"알 수 없는 단위: {bucket} ({', '.join(BUCKETS)})")

    counts: Counter = Counter()
    for e in entries:
        if e.when is None or (levels and e.level not in levels):
            continue
        stamp = int(e.when.timestamp()) // seconds * seconds
        counts[stamp] += 1
    return [(datetime.fromtimestamp(k), v) for k, v in sorted(counts.items())]


def level_counts(entries: list[Entry]) -> dict[str, int]:
    counts: Counter = Counter(e.level for e in entries if e.level)
    return dict(sorted(counts.items(), key=lambda x: LEVEL_ORDER.get(x[0], 9)))


def spikes(series: list[tuple[datetime, int]], *, factor: float = 3.0,
           minimum: int = 5) -> list[tuple[datetime, int, float]]:
    """평소보다 몇 배로 튄 구간. (시각, 건수, 배수)"""
    values = [v for _, v in series]
    if len(values) < 3:
        return []
    ordered = sorted(values)
    median = ordered[len(ordered) // 2] or 1
    return [(when, count, count / median)
            for when, count in series
            if count >= minimum and count >= median * factor]


def span(entries: list[Entry]) -> tuple[datetime | None, datetime | None]:
    stamps = [e.when for e in entries if e.when]
    return (min(stamps), max(stamps)) if stamps else (None, None)


# ------------------------------------------------------------------ 응답 시간

# 12ms, 1.5s, 340 ms 처럼 적힌 값을 찾는다. 단위 없는 숫자는 세지 않는다 -
# 상태 코드나 바이트 수를 응답 시간으로 잘못 세는 것보다 못 세는 게 낫다.
DURATION_RE = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s*(ms|밀리초|s|sec|secs|seconds|초)(?![\w가-힣])",
    re.IGNORECASE)
UNIT_MS = {"ms": 1.0, "밀리초": 1.0, "s": 1000.0, "sec": 1000.0,
           "secs": 1000.0, "seconds": 1000.0, "초": 1000.0}
ROUTE_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(\S+)",
                      re.IGNORECASE)
PATH_NUM = re.compile(r"/(?:\d+|[0-9a-f]{8}-[0-9a-f-]{27}|[0-9a-f]{16,})", re.IGNORECASE)


@dataclass
class Timed:
    entry: "Entry"
    ms: float
    route: str = ""


@dataclass
class RouteStat:
    route: str
    values: list[float] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.values)

    @property
    def total(self) -> float:
        return sum(self.values)

    @property
    def avg(self) -> float:
        return self.total / self.count if self.values else 0.0

    def p(self, percent: float) -> float:
        return percentile(self.values, percent)


def percentile(values: list[float], percent: float) -> float:
    """가장 가까운 순위 방식. 값이 적을 때 보간하면 없는 값을 지어내게 된다."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if percent <= 0:
        return ordered[0]
    rank = max(1, min(len(ordered), math.ceil(percent / 100 * len(ordered))))
    return ordered[rank - 1]


def duration_ms(line: str) -> float | None:
    """한 줄에서 응답 시간을 찾는다. 여러 개면 마지막 것(대개 총 소요)."""
    found = DURATION_RE.findall(line)
    if not found:
        return None
    value, unit = found[-1]
    return float(value) * UNIT_MS[unit.lower()]


def route_of(line: str) -> str:
    """GET /api/users/12 -> GET /api/users/{n}. 못 찾으면 빈 문자열."""
    m = ROUTE_RE.search(line)
    if not m:
        return ""
    path = m.group(2).split("?", 1)[0]
    return f"{m.group(1).upper()} {PATH_NUM.sub('/{n}', path)}"


def timings(entries: list["Entry"], *,
            pattern: "re.Pattern | None" = None) -> list[Timed]:
    """응답 시간이 적힌 줄만 골라낸다. pattern 을 주면 그 첫 그룹을 ms 로 본다."""
    out: list[Timed] = []
    for e in entries:
        if pattern:
            m = pattern.search(e.raw)
            if not m:
                continue
            try:
                ms = float(m.group(1) if m.groups() else m.group(0))
            except ValueError:
                continue
        else:
            found = duration_ms(e.raw)
            if found is None:
                continue
            ms = found
        out.append(Timed(e, ms, route_of(e.raw)))
    return out


def by_route(timed: list[Timed], *, top: int = 10,
             sort: str = "p95") -> list[RouteStat]:
    """경로별로 묶는다. 경로를 못 찾은 줄은 '(경로 없음)' 으로 함께 센다."""
    buckets: dict[str, RouteStat] = {}
    for t in timed:
        key = t.route or "(경로 없음)"
        buckets.setdefault(key, RouteStat(key)).values.append(t.ms)

    keys = {"p95": lambda s: -s.p(95), "p50": lambda s: -s.p(50),
            "avg": lambda s: -s.avg, "count": lambda s: -s.count,
            "total": lambda s: -s.total}
    return sorted(buckets.values(), key=keys.get(sort, keys["p95"]))[:top]
