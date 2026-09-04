"""표 데이터(csv/tsv/xlsx) 읽기·정리·검증·병합·비교·집계."""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .hangul import josa

from . import xlsx

CSV_SUFFIXES = {".csv", ".tsv", ".txt"}
XLSX_SUFFIXES = {".xlsx", ".xlsm"}
ENCODINGS = ("utf-8-sig", "utf-8", "cp949", "euc-kr", "utf-16")

FULLWIDTH_SPACE = "　"
NUMBER_RE = re.compile(r"^\(?\s*[-+]?[\d,]*\d(?:\.\d+)?\s*\)?$")
PERCENT_RE = re.compile(r"^[-+]?[\d,]*\d(?:\.\d+)?\s*%$")
MONEY_RE = re.compile(r"^[₩$€¥]?\s*\(?\s*[-+]?[\d,]*\d(?:\.\d+)?\s*\)?\s*(?:원|KRW|USD)?$")
DATE_PATTERNS = [
    (re.compile(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})$"), (1, 2, 3)),
    (re.compile(r"^(\d{4})(\d{2})(\d{2})$"), (1, 2, 3)),
    (re.compile(r"^(\d{1,2})[-./](\d{1,2})[-./](\d{4})$"), (3, 1, 2)),
    (re.compile(r"^(\d{2})[-./](\d{1,2})[-./](\d{1,2})$"), (1, 2, 3)),
]


class SheetError(Exception):
    pass


@dataclass
class Table:
    headers: list[str]
    rows: list[list]
    source: str = ""
    sheet: str = ""

    @property
    def width(self) -> int:
        return len(self.headers)

    def column(self, name: str) -> list:
        i = self.index_of(name)
        return [r[i] if i < len(r) else None for r in self.rows]

    def index_of(self, name: str) -> int:
        if name in self.headers:
            return self.headers.index(name)
        # 공백·대소문자 차이는 무시하고 한 번 더 찾는다
        norm = {h.strip().lower(): i for i, h in enumerate(self.headers)}
        key = name.strip().lower()
        if key in norm:
            return norm[key]
        raise SheetError(f"'{name}' 열이 없습니다. 있는 열: {', '.join(self.headers)}")

    def as_rows(self) -> list[list]:
        return [list(self.headers), *self.rows]


# ------------------------------------------------------------------ 값 해석

def parse_number(text: str) -> float | int | None:
    """'1,234원', '(1,234)', '12.5%' 를 숫자로. 아니면 None."""
    s = text.strip()
    if not s:
        return None

    percent = bool(PERCENT_RE.match(s))
    if percent:
        s = s.rstrip("%").strip()
    elif MONEY_RE.match(s):
        s = re.sub(r"[₩$€¥]|원|KRW|USD", "", s).strip()
    elif not NUMBER_RE.match(s):
        return None

    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "").strip()
    if not s or not re.fullmatch(r"[-+]?\d+(\.\d+)?", s):
        return None

    digits = s.lstrip("+-")
    if "." not in digits:
        # 0으로 시작하는 우편번호·사번, 16자리 넘는 계좌번호는 숫자로 바꾸면 값이 망가진다
        if len(digits) > 1 and digits.startswith("0"):
            return None
        if len(digits) > 15:
            return None

    value = float(s)
    if negative:
        value = -value
    if percent:
        return value / 100
    return int(value) if value.is_integer() and not percent else value


def parse_date(text: str) -> date | None:
    s = text.strip().replace(" ", "")
    for pattern, (y, m, d) in DATE_PATTERNS:
        match = pattern.match(s)
        if not match:
            continue
        year = int(match.group(y))
        if year < 100:
            year += 2000 if year < 70 else 1900
        try:
            return date(year, int(match.group(m)), int(match.group(d)))
        except ValueError:
            return None
    return None


def parse_value(text):
    """CSV 셀 문자열을 적당한 파이썬 값으로. 해석 못 하면 원문 그대로."""
    if not isinstance(text, str):
        return text
    s = text.strip()
    if not s:
        return None
    if s.upper() in ("TRUE", "FALSE"):
        return s.upper() == "TRUE"
    if (d := parse_date(s)) is not None:
        return d
    if (n := parse_number(s)) is not None:
        return n
    return text


def kind_of(value) -> str:
    if value is None or value == "":
        return "빈칸"
    if isinstance(value, bool):
        return "참거짓"
    if isinstance(value, (datetime, date)):
        return "날짜"
    if isinstance(value, int):
        return "정수"
    if isinstance(value, float):
        return "실수"
    return "문자"


def to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value)


# --------------------------------------------------------------------- 입출력

def sniff_encoding(path: Path) -> str:
    head = path.read_bytes()[:65536]
    for enc in ENCODINGS:
        try:
            head.decode(enc)
        except UnicodeDecodeError:
            continue
        # cp949 로도 읽히지만 utf-8 이 맞는 경우가 있어 순서를 지킨다
        return enc
    return "utf-8"


def load(path: Path, *, sheet: str | None = None, header_row: int = 0,
         raw: bool = False) -> Table:
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in XLSX_SUFFIXES:
        grid = xlsx.read_sheet(path, sheet)
        used_sheet = sheet or (xlsx.sheet_names(path) or [""])[0]
    elif suffix in CSV_SUFFIXES or not suffix:
        encoding = sniff_encoding(path)
        text = path.read_text(encoding=encoding)
        delimiter = "\t" if suffix == ".tsv" or text.count("\t") > text.count(",") else ","
        grid = [list(r) for r in csv.reader(io.StringIO(text), delimiter=delimiter)]
        if not raw:
            grid = [[parse_value(c) for c in row] for row in grid]
        used_sheet = ""
    else:
        raise SheetError(f"지원하지 않는 형식입니다: {suffix} (csv, tsv, xlsx)")

    grid = [row for row in grid if any(c not in (None, "") for c in row)]
    if not grid:
        raise SheetError(f"내용이 없습니다: {path}")
    if header_row >= len(grid):
        raise SheetError(f"헤더 행 번호가 범위를 넘습니다: {header_row + 1}")

    headers = [to_text(c).strip() for c in grid[header_row]]
    headers = _dedupe_headers(headers)
    width = len(headers)
    rows = [(r + [None] * width)[:width] for r in grid[header_row + 1:]]
    return Table(headers, rows, source=str(path), sheet=used_sheet)


def _dedupe_headers(headers: list[str]) -> list[str]:
    seen: Counter = Counter()
    out = []
    for i, h in enumerate(headers):
        name = h or f"열{i + 1}"
        seen[name] += 1
        out.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return out


def save(table: Table, path: Path, *, excel_bom: bool = True, sheet_name: str = "") -> Path:
    path = Path(path)
    suffix = path.suffix.lower()
    path.parent.mkdir(parents=True, exist_ok=True)

    if suffix in XLSX_SUFFIXES:
        xlsx.write_sheets(path, {sheet_name or table.sheet or "Sheet1": table.as_rows()})
        return path

    delimiter = "\t" if suffix == ".tsv" else ","
    # 엑셀에서 바로 열려면 UTF-8 BOM 이 있어야 한글이 안 깨진다
    encoding = "utf-8-sig" if excel_bom else "utf-8"
    with path.open("w", encoding=encoding, newline="") as fh:
        writer = csv.writer(fh, delimiter=delimiter)
        writer.writerow(table.headers)
        writer.writerows([to_text(c) for c in row] for row in table.rows)
    return path


# ---------------------------------------------------------------------- 훑기

@dataclass
class ColumnProfile:
    name: str
    kinds: Counter = field(default_factory=Counter)
    missing: int = 0
    unique: int = 0
    samples: list[str] = field(default_factory=list)
    minimum: object = None
    maximum: object = None

    @property
    def main_kind(self) -> str:
        real = [(k, n) for k, n in self.kinds.items() if k != "빈칸"]
        return max(real, key=lambda x: x[1])[0] if real else "빈칸"

    @property
    def mixed(self) -> bool:
        return len([k for k in self.kinds if k != "빈칸"]) > 1


def profile(table: Table) -> list[ColumnProfile]:
    out = []
    for i, name in enumerate(table.headers):
        col = ColumnProfile(name)
        values = []
        for row in table.rows:
            v = row[i] if i < len(row) else None
            col.kinds[kind_of(v)] += 1
            if v is None or v == "":
                col.missing += 1
            else:
                values.append(v)

        col.unique = len({to_text(v) for v in values})
        col.samples = [to_text(v) for v in values[:3]]
        comparable = [v for v in values if isinstance(v, (int, float, date, datetime))
                      and not isinstance(v, bool)]
        if comparable and not (any(isinstance(v, (date, datetime)) for v in comparable)
                               and any(isinstance(v, (int, float)) for v in comparable)):
            col.minimum, col.maximum = min(comparable), max(comparable)
        out.append(col)
    return out


# ---------------------------------------------------------------------- 정리

@dataclass
class CleanReport:
    trimmed: int = 0
    fullwidth: int = 0
    numbers: int = 0
    dates: int = 0
    dropped_rows: int = 0
    dropped_cols: list[str] = field(default_factory=list)
    duplicate_rows: int = 0


def clean(table: Table, *, drop_duplicates: bool = False,
          drop_empty_cols: bool = True) -> tuple[Table, CleanReport]:
    """실무 파일에서 자주 보는 오염을 정리한다."""
    rep = CleanReport()
    rows: list[list] = []

    for row in table.rows:
        new_row = []
        for value in row:
            if isinstance(value, str):
                original = value
                if FULLWIDTH_SPACE in value:
                    value = value.replace(FULLWIDTH_SPACE, " ")
                    rep.fullwidth += 1
                value = unicodedata.normalize("NFC", value)
                value = re.sub(r"\s+", " ", value).strip()
                if value != original.strip():
                    rep.trimmed += 1
                elif value != original:
                    rep.trimmed += 1

                if value:
                    if (n := parse_number(value)) is not None:
                        rep.numbers += 1
                        new_row.append(n)
                        continue
                    if (d := parse_date(value)) is not None:
                        rep.dates += 1
                        new_row.append(d)
                        continue
                new_row.append(value or None)
            else:
                new_row.append(value)

        if all(v in (None, "") for v in new_row):
            rep.dropped_rows += 1
            continue
        rows.append(new_row)

    headers = list(table.headers)
    if drop_empty_cols:
        keep = [i for i in range(len(headers))
                if any(r[i] not in (None, "") for r in rows)] or list(range(len(headers)))
        rep.dropped_cols = [headers[i] for i in range(len(headers)) if i not in keep]
        headers = [headers[i] for i in keep]
        rows = [[r[i] for i in keep] for r in rows]

    if drop_duplicates:
        seen: set[tuple] = set()
        deduped = []
        for r in rows:
            key = tuple(to_text(v) for v in r)
            if key in seen:
                rep.duplicate_rows += 1
                continue
            seen.add(key)
            deduped.append(r)
        rows = deduped

    return Table(headers, rows, source=table.source, sheet=table.sheet), rep


# ---------------------------------------------------------------------- 검증

@dataclass
class Issue:
    kind: str
    column: str
    detail: str
    rows: list[int] = field(default_factory=list)


def validate(table: Table, *, key: str | None = None, required: list[str] | None = None,
             sample: int = 5) -> list[Issue]:
    issues: list[Issue] = []

    if key:
        i = table.index_of(key)
        seen: dict[str, list[int]] = defaultdict(list)
        for n, row in enumerate(table.rows, 2):  # 엑셀 행 번호(헤더가 1행)
            seen[to_text(row[i] if i < len(row) else None)].append(n)
        dupes = {k: v for k, v in seen.items() if k and len(v) > 1}
        if dupes:
            preview = ", ".join(f"{k}({len(v)}건)" for k, v in list(dupes.items())[:sample])
            issues.append(Issue("중복 키", key, f"{len(dupes)}개 값이 중복: {preview}",
                                sorted(n for v in dupes.values() for n in v)[:20]))
        empties = seen.get("", [])
        if empties:
            issues.append(Issue("키 결측", key, f"{len(empties)}행의 키가 비어 있음", empties[:20]))

    for i, name in enumerate(table.headers):
        kinds: Counter = Counter()
        stray_space: list[int] = []
        text_numbers: list[int] = []
        missing: list[int] = []

        for n, row in enumerate(table.rows, 2):
            v = row[i] if i < len(row) else None
            kinds[kind_of(v)] += 1
            if v is None or v == "":
                missing.append(n)
                continue
            if isinstance(v, str):
                if v != v.strip() or FULLWIDTH_SPACE in v:
                    stray_space.append(n)
                if parse_number(v) is not None or parse_date(v) is not None:
                    text_numbers.append(n)

        real = [k for k in kinds if k != "빈칸"]
        if len(real) > 1:
            mix = ", ".join(f"{k} {kinds[k]}건" for k in sorted(real, key=lambda k: -kinds[k]))
            issues.append(Issue("타입 혼재", name, mix))
        if stray_space:
            issues.append(Issue("앞뒤·전각 공백", name, f"{len(stray_space)}건",
                                stray_space[:20]))
        if text_numbers:
            issues.append(Issue("문자로 저장된 숫자/날짜", name,
                                f"{len(text_numbers)}건 (엑셀에서 계산·정렬이 어긋난다)",
                                text_numbers[:20]))
        if required and name in required and missing:
            issues.append(Issue("필수값 누락", name, f"{len(missing)}행", missing[:20]))

    return issues


# ---------------------------------------------------------------------- 병합

def merge(tables: list[Table], *, add_source: bool = True,
          strict: bool = False) -> tuple[Table, list[str]]:
    """여러 표를 세로로 붙인다. 열 이름 기준으로 맞추고, 없는 열은 빈칸."""
    if not tables:
        raise SheetError("병합할 표가 없습니다.")

    headers: list[str] = []
    for t in tables:
        for h in t.headers:
            if h not in headers:
                headers.append(h)

    warnings: list[str] = []
    for t in tables:
        missing = [h for h in headers if h not in t.headers]
        extra = [h for h in t.headers if h not in tables[0].headers]
        if missing or extra:
            name = Path(t.source).name or "표"
            warnings.append(f"{name}: 없는 열 {missing or '-'} / 첫 표에 없는 열 {extra or '-'}")
    if strict and warnings:
        raise SheetError("열 구성이 다릅니다:\n  " + "\n  ".join(warnings))

    out_headers = (["출처"] if add_source else []) + headers
    rows: list[list] = []
    for t in tables:
        index = {h: t.headers.index(h) for h in t.headers}
        label = Path(t.source).stem + (f"#{t.sheet}" if t.sheet else "")
        for row in t.rows:
            values = [row[index[h]] if h in index and index[h] < len(row) else None
                      for h in headers]
            rows.append(([label] if add_source else []) + values)

    return Table(out_headers, rows, source="merged"), warnings


# ---------------------------------------------------------------------- 비교

@dataclass
class Diff:
    added: list[list] = field(default_factory=list)
    removed: list[list] = field(default_factory=list)
    changed: list[tuple[str, str, object, object]] = field(default_factory=list)
    columns_added: list[str] = field(default_factory=list)
    columns_removed: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed
                    or self.columns_added or self.columns_removed)


def diff(before: Table, after: Table, key: str) -> Diff:
    """키 열을 기준으로 두 표를 비교한다."""
    d = Diff()
    d.columns_added = [h for h in after.headers if h not in before.headers]
    d.columns_removed = [h for h in before.headers if h not in after.headers]
    shared = [h for h in before.headers if h in after.headers]

    bi, ai = before.index_of(key), after.index_of(key)
    bmap = {to_text(r[bi]): r for r in before.rows if bi < len(r)}
    amap = {to_text(r[ai]): r for r in after.rows if ai < len(r)}

    for k, row in amap.items():
        if k not in bmap:
            d.added.append(row)
    for k, row in bmap.items():
        if k not in amap:
            d.removed.append(row)

    for k in bmap.keys() & amap.keys():
        for h in shared:
            if h == key:
                continue
            b = bmap[k][before.headers.index(h)]
            a = amap[k][after.headers.index(h)]
            if to_text(b) != to_text(a):
                d.changed.append((k, h, b, a))
    d.changed.sort(key=lambda x: (x[0], x[1]))
    return d


# ---------------------------------------------------------------------- 집계

AGGS = {
    "sum": lambda vs: sum(vs),
    "count": lambda vs: len(vs),
    "avg": lambda vs: sum(vs) / len(vs) if vs else 0,
    "min": lambda vs: min(vs) if vs else None,
    "max": lambda vs: max(vs) if vs else None,
}


def pivot(table: Table, *, rows: list[str], values: str | None = None,
          agg: str = "sum", cols: str | None = None) -> Table:
    """행 기준으로 묶어 집계한다. cols 를 주면 교차표를 만든다."""
    if agg not in AGGS:
        raise SheetError(f"알 수 없는 집계: {agg} ({', '.join(AGGS)})")

    row_idx = [table.index_of(r) for r in rows]
    val_idx = table.index_of(values) if values else None
    col_idx = table.index_of(cols) if cols else None

    buckets: dict[tuple, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    col_keys: list[str] = []

    for row in table.rows:
        rkey = tuple(to_text(row[i]) if i < len(row) else "" for i in row_idx)
        ckey = (to_text(row[col_idx]) or "(빈칸)") if col_idx is not None else "값"
        if ckey not in col_keys:
            col_keys.append(ckey)

        if val_idx is None:
            buckets[rkey][ckey].append(1)
            continue
        v = row[val_idx] if val_idx < len(row) else None
        if isinstance(v, bool) or v is None:
            continue
        if agg in ("sum", "avg") and not isinstance(v, (int, float)):
            continue
        buckets[rkey][ckey].append(v)

    col_keys.sort()
    headers = list(rows) + col_keys + (["합계"] if col_idx is not None else [])
    out_rows = []
    for rkey in sorted(buckets):
        cells = []
        for ck in col_keys:
            vs = buckets[rkey][ck]
            cells.append(AGGS[agg](vs) if vs else None)
        line = list(rkey) + cells
        if col_idx is not None:
            numbers = [c for c in cells if isinstance(c, (int, float))]
            line.append(sum(numbers) if numbers else None)
        out_rows.append(line)

    return Table(headers, out_rows, source=table.source)


# ------------------------------------------------------- 열·행 고르기

def cut(table: Table, columns: list[str], *, drop: bool = False) -> Table:
    """열을 골라 그 순서로 남긴다. drop 이면 지정한 열만 뺀다."""
    if drop:
        keep = [i for i, h in enumerate(table.headers) if h not in columns]
        missing = [c for c in columns if c not in table.headers]
        if missing:
            raise SheetError(f"없는 열: {', '.join(missing)}")
    else:
        keep = [table.index_of(c) for c in columns]

    headers = [table.headers[i] for i in keep]
    rows = [[r[i] if i < len(r) else None for i in keep] for r in table.rows]
    return Table(headers, rows, source=table.source, sheet=table.sheet)


OPERATORS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
}


@dataclass
class Condition:
    column: str
    op: str
    value: str

    @classmethod
    def parse(cls, op: str, spec: str) -> Condition:
        column, sep, value = spec.partition("=")
        if not sep:
            raise SheetError(f"'열=값' 형태로 적으세요: {spec}")
        return cls(column.strip(), op, value.strip())


def _comparable(cell, wanted: str):
    """숫자·날짜 열은 숫자·날짜로, 아니면 문자열로 비교한다."""
    if isinstance(cell, bool):
        return to_text(cell), wanted.upper()
    if isinstance(cell, (int, float)):
        parsed = parse_number(wanted)
        return (cell, parsed) if parsed is not None else (to_text(cell), wanted)
    if isinstance(cell, (datetime, date)):
        parsed = parse_date(wanted)
        target = cell.date() if isinstance(cell, datetime) else cell
        return (target, parsed) if parsed is not None else (to_text(cell), wanted)
    return to_text(cell), wanted


def where(table: Table, conditions: list[Condition], *, contains: list[Condition] | None = None,
          any_match: bool = False) -> Table:
    """조건에 맞는 행만 남긴다. 기본은 모든 조건을 만족(AND)."""
    checks = list(conditions) + list(contains or [])
    indexes = {c.column: table.index_of(c.column) for c in checks}

    def passes(row: list) -> bool:
        results = []
        for c in checks:
            i = indexes[c.column]
            cell = row[i] if i < len(row) else None
            if c.op == "has":
                results.append(c.value.lower() in to_text(cell).lower())
                continue
            left, right = _comparable(cell, c.value)
            try:
                results.append(OPERATORS[c.op](left, right))
            except TypeError:
                results.append(False)
        return any(results) if any_match else all(results)

    return Table(table.headers, [r for r in table.rows if passes(r)],
                 source=table.source, sheet=table.sheet)


def sort_rows(table: Table, columns: list[str], *, descending: bool = False) -> Table:
    indexes = [table.index_of(c) for c in columns]

    def key(row: list):
        out = []
        for i in indexes:
            cell = row[i] if i < len(row) else None
            # 빈 칸은 항상 뒤로 보낸다
            if cell is None or cell == "":
                out.append((2, 0.0, ""))
            elif isinstance(cell, bool):
                out.append((1, 0.0, to_text(cell)))
            elif isinstance(cell, (int, float)):
                out.append((0, float(cell), ""))
            elif isinstance(cell, (datetime, date)):
                stamp = cell if isinstance(cell, datetime) else datetime(
                    cell.year, cell.month, cell.day)
                out.append((0, stamp.timestamp(), ""))
            else:
                out.append((1, 0.0, to_text(cell)))
        return out

    return Table(table.headers, sorted(table.rows, key=key, reverse=descending),
                 source=table.source, sheet=table.sheet)


def sample(table: Table, count: int, *, seed: int | None = None,
           head: bool = False) -> Table:
    import random

    if head or count >= len(table.rows):
        rows = table.rows[:count]
    else:
        rows = random.Random(seed).sample(table.rows, count)
    return Table(table.headers, rows, source=table.source, sheet=table.sheet)


def split_rows(table: Table, size: int) -> list[Table]:
    if size < 1:
        raise SheetError("나눌 행 수는 1 이상이어야 합니다.")
    return [Table(table.headers, table.rows[i:i + size],
                  source=table.source, sheet=table.sheet)
            for i in range(0, len(table.rows), size)]


def split_by(table: Table, column: str) -> dict[str, Table]:
    """열 값마다 따로 나눈다. 부서별·월별로 파일을 쪼갤 때."""
    i = table.index_of(column)
    groups: dict[str, list[list]] = defaultdict(list)
    for row in table.rows:
        key = to_text(row[i] if i < len(row) else None) or "(빈칸)"
        groups[key].append(row)
    return {k: Table(table.headers, v, source=table.source, sheet=k)
            for k, v in sorted(groups.items())}


# ------------------------------------------------------------- 채워 넣기

PLACEHOLDER = re.compile(r"\{\{|\}\}|\{([^{}]+)\}")


@dataclass
class Filled:
    name: str
    text: str
    row: int


# {이름:을/를} 처럼 조사 짝을 적은 자리. 형식 지정(03d, .2f)과 헷갈리지 않게
# 한글 한두 글자 / 한글 한두 글자 꼴만 조사로 본다.
JOSA_SPEC = re.compile(r"[가-힣]{1,2}/[가-힣]{1,2}")


def placeholders(template: str) -> list[str]:
    """틀에 쓰인 자리표시자 이름을 순서대로 모은다."""
    out: list[str] = []
    for m in PLACEHOLDER.finditer(template):
        key = m.group(1)
        if key:
            name = key.split(":", 1)[0].strip()
            if name and name not in out:
                out.append(name)
    return out


def render(template: str, values: dict[str, object], *,
           missing: set[str] | None = None) -> str:
    """{열이름} 자리를 값으로 바꾼다. {{ 와 }} 는 중괄호 자체를 뜻한다."""
    def swap(m: re.Match) -> str:
        if m.group(0) == "{{":
            return "{"
        if m.group(0) == "}}":
            return "}"
        key, _, spec = m.group(1).partition(":")   # {번호:03d} 같은 형식도 받는다
        key = key.strip()
        if key not in values:
            if missing is not None:
                missing.add(key)
            return ""
        value = values[key]
        spec = spec.strip()
        if JOSA_SPEC.fullmatch(spec):      # {이름:을/를} 은 받침에 맞는 조사를 붙인다
            return josa(to_text(value), spec)
        if spec:
            try:
                return format(value, spec)
            except (ValueError, TypeError):
                pass
        return to_text(value)

    return PLACEHOLDER.sub(swap, template)


def fill(table: Table, template: str, *, name_template: str = "",
         start: int = 1) -> tuple[list[Filled], set[str]]:
    """행마다 틀을 채운다. (결과들, 틀에 있는데 표에 없는 열 이름)"""
    missing: set[str] = set()
    out: list[Filled] = []

    for n, row in enumerate(table.rows, start):
        values: dict[str, object] = {
            h: row[i] if i < len(row) else None for i, h in enumerate(table.headers)}
        values["번호"] = n
        text = render(template, values, missing=missing)
        name = render(name_template, values, missing=missing) if name_template else ""
        out.append(Filled(name.strip(), text, n))
    return out, missing


# ----------------------------------------------------------------- 표 합치기

@dataclass
class JoinReport:
    matched: int = 0            # 짝을 찾은 왼쪽 행
    left_only: int = 0          # 오른쪽에 짝이 없는 왼쪽 행
    right_only: int = 0         # 왼쪽에 짝이 없는 오른쪽 행 (outer 일 때만 들어간다)
    multiplied: int = 0         # 오른쪽 키 중복으로 늘어난 행
    duplicate_keys: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)
    blank_keys: int = 0


def join(left: Table, right: Table, *, on: str, right_on: str = "",
         how: str = "left", suffix: str = "_2") -> tuple[Table, JoinReport]:
    """두 표를 키로 합친다. VLOOKUP 과 달리 짝이 여럿이면 그 사실을 알린다."""
    if how not in ("left", "inner", "outer"):
        raise SheetError(f"알 수 없는 방식: {how} (left, inner, outer)")

    right_key = right_on or on
    li, ri = left.index_of(on), right.index_of(right_key)
    report = JoinReport()

    # 오른쪽을 키별로 모은다. 키가 여러 번 나오면 행이 불어나므로 세어 둔다.
    lookup: dict[str, list[list]] = defaultdict(list)
    for row in right.rows:
        key = to_text(row[ri] if ri < len(row) else None)
        if not key:
            report.blank_keys += 1
            continue
        lookup[key].append(row)
    report.duplicate_keys = sorted(k for k, v in lookup.items() if len(v) > 1)

    # 오른쪽 열 이름이 겹치면 접미사를 붙인다. 키 열은 한 번만 남긴다.
    right_headers: list[str] = []
    keep_right: list[int] = []
    for i, name in enumerate(right.headers):
        if i == ri:
            continue
        keep_right.append(i)
        if name in left.headers:
            new_name = f"{name}{suffix}"
            report.renamed.append((name, new_name))
            right_headers.append(new_name)
        else:
            right_headers.append(name)

    headers = list(left.headers) + right_headers
    blanks = [None] * len(right_headers)
    rows: list[list] = []
    used: set[str] = set()

    for row in left.rows:
        key = to_text(row[li] if li < len(row) else None)
        partners = lookup.get(key, [])
        if not partners:
            report.left_only += 1
            if how != "inner":
                rows.append(list(row) + blanks)
            continue

        used.add(key)
        report.matched += 1
        report.multiplied += len(partners) - 1
        for partner in partners:
            rows.append(list(row) + [partner[i] if i < len(partner) else None
                                     for i in keep_right])

    if how == "outer":
        left_blanks = [None] * len(left.headers)
        for key, partners in lookup.items():
            if key in used:
                continue
            for partner in partners:
                filled = list(left_blanks)
                filled[li] = partner[ri] if ri < len(partner) else None
                rows.append(filled + [partner[i] if i < len(partner) else None
                                      for i in keep_right])
                report.right_only += 1

    return Table(headers, rows, source=f"{left.source} + {right.source}"), report


@dataclass
class DedupeReport:
    kept: int = 0
    removed: int = 0
    duplicate_keys: list[tuple[str, int]] = field(default_factory=list)
    blank_keys: int = 0


def dedupe(table: Table, keys: list[str], *, keep: str = "first",
           by: str = "") -> tuple[Table, DedupeReport]:
    """키가 같은 행 중 하나만 남긴다.

    keep: first/last 는 나온 순서, max/min 은 by 열의 값 기준.
    완전히 같은 행만 지우는 clean --dedupe 와 다르다. 사번이 같고 나머지가
    다른 행에서 최신 것만 남기는 게 실무에서 필요한 쪽이다.
    """
    if keep not in ("first", "last", "max", "min"):
        raise SheetError(f"알 수 없는 방식: {keep} (first, last, max, min)")
    if keep in ("max", "min") and not by:
        raise SheetError(f"--keep {keep} 은 어떤 열로 고를지 --by 로 알려 줘야 합니다.")

    indexes = [table.index_of(k) for k in keys]
    order_index = table.index_of(by) if by else None
    report = DedupeReport()

    groups: dict[tuple, list[list]] = {}
    for row in table.rows:
        key = tuple(to_text(row[i]) if i < len(row) else "" for i in indexes)
        if not any(key):
            report.blank_keys += 1
        groups.setdefault(key, []).append(row)

    def rank(row: list):
        cell = row[order_index] if order_index is not None and order_index < len(row) else None
        if cell is None or cell == "":
            return (1, 0.0, "")
        if isinstance(cell, bool):
            return (0, float(cell), "")
        if isinstance(cell, (int, float)):
            return (0, float(cell), "")
        if isinstance(cell, (datetime, date)):
            stamp = cell if isinstance(cell, datetime) else datetime(
                cell.year, cell.month, cell.day)
            return (0, stamp.timestamp(), "")
        return (0, 0.0, to_text(cell))

    rows: list[list] = []
    for key, members in groups.items():
        if len(members) > 1:
            report.duplicate_keys.append((" / ".join(key) or "(빈 키)", len(members)))
            report.removed += len(members) - 1

        if keep == "first":
            picked = members[0]
        elif keep == "last":
            picked = members[-1]
        elif keep == "max":
            picked = max(members, key=rank)
        else:
            picked = min(members, key=rank)
        rows.append(picked)

    report.kept = len(rows)
    report.duplicate_keys.sort(key=lambda x: -x[1])
    return Table(table.headers, rows, source=table.source, sheet=table.sheet), report


# ------------------------------------------------------------------ 파생 열

import ast as _ast

# 허용할 문법만 열어 둔다. eval 에 아무거나 넣으면 표 하나로 무슨 일이든 할 수 있다.
ALLOWED_NODES = (
    _ast.Expression, _ast.BinOp, _ast.UnaryOp, _ast.BoolOp, _ast.Compare,
    _ast.IfExp, _ast.Name, _ast.Load, _ast.Constant, _ast.Call,
    _ast.Add, _ast.Sub, _ast.Mult, _ast.Div, _ast.FloorDiv, _ast.Mod, _ast.Pow,
    _ast.USub, _ast.UAdd, _ast.Not, _ast.And, _ast.Or,
    _ast.Eq, _ast.NotEq, _ast.Lt, _ast.LtE, _ast.Gt, _ast.GtE,
)
ALLOWED_CALLS = {
    "abs": abs, "round": round, "min": min, "max": max,
    "int": int, "float": float, "len": len, "str": str,
}
BRACED = re.compile(r"\{([^{}]+)\}")


@dataclass
class FxReport:
    name: str
    expression: str
    computed: int = 0
    failed: int = 0
    reasons: Counter = field(default_factory=Counter)
    samples: list[tuple[int, str]] = field(default_factory=list)


def _check_expression(tree: _ast.AST, allowed_names: set[str]) -> None:
    for node in _ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            raise SheetError(f"수식에 쓸 수 없는 문법입니다: {type(node).__name__}")
        if isinstance(node, _ast.Call):
            if not isinstance(node.func, _ast.Name) or node.func.id not in ALLOWED_CALLS:
                raise SheetError(
                    f"쓸 수 있는 함수: {', '.join(sorted(ALLOWED_CALLS))}")
        if isinstance(node, _ast.Name) and node.id not in allowed_names:
            if node.id in ALLOWED_CALLS:
                continue
            raise SheetError(f"'{node.id}' 는 열 이름도 함수도 아닙니다")


def compile_expression(expression: str, headers: list[str]):
    """수식을 확인하고 (실행 코드, 자리표시자 대응표) 를 돌려준다.

    열 이름에 공백이 있으면 {매출 합계} 처럼 중괄호로 감싼다.
    """
    aliases: dict[str, str] = {}
    body = expression

    def swap(m: re.Match) -> str:
        name = m.group(1).strip()
        key = f"_열{len(aliases)}"
        aliases[key] = name
        return key

    body = BRACED.sub(swap, body)
    for header in headers:
        if header and not header.isidentifier() and header in body:
            key = f"_열{len(aliases)}"
            aliases[key] = header
            body = body.replace(header, key)

    try:
        tree = _ast.parse(body, mode="eval")
    except SyntaxError as e:
        raise SheetError(f"수식을 읽지 못했습니다: {e.msg}") from None

    names = {h for h in headers if h.isidentifier()} | set(aliases)
    _check_expression(tree, names)
    unknown = [aliases[k] for k in aliases if aliases[k] not in headers]
    if unknown:
        raise SheetError(f"없는 열: {', '.join(unknown)}")
    return compile(tree, "<수식>", "eval"), aliases


def add_column(table: Table, name: str, expression: str, *,
               digits: int | None = None) -> tuple[Table, FxReport]:
    """수식으로 계산한 열을 붙인다. 이름이 이미 있으면 그 열을 바꾼다."""
    code, aliases = compile_expression(expression, table.headers)
    report = FxReport(name, expression)

    headers = list(table.headers)
    if name in headers:
        target = headers.index(name)
    else:
        headers.append(name)
        target = len(headers) - 1

    rows: list[list] = []
    for number, row in enumerate(table.rows, 2):     # 헤더가 1행
        scope = {h: (row[i] if i < len(row) else None)
                 for i, h in enumerate(table.headers) if h.isidentifier()}
        for key, header in aliases.items():
            index = table.headers.index(header)
            scope[key] = row[index] if index < len(row) else None
        scope.update(ALLOWED_CALLS)

        try:
            value = eval(code, {"__builtins__": {}}, scope)  # noqa: S307 - 문법을 미리 걸렀다
            if digits is not None and isinstance(value, (int, float)) \
                    and not isinstance(value, bool):
                # round(x, 0) 은 4333333.0 처럼 실수를 돌려준다. 0자리면 정수가 낫다.
                value = round(value) if digits == 0 else round(value, digits)
            report.computed += 1
        except ZeroDivisionError:
            value, reason = None, "0으로 나눔"
        except TypeError:
            value, reason = None, "값 종류가 맞지 않음(빈 칸이거나 문자)"
        except Exception as e:                       # 남은 것도 행 하나만 비운다
            value, reason = None, type(e).__name__
        else:
            reason = ""

        if reason:
            report.failed += 1
            report.reasons[reason] += 1
            if len(report.samples) < 3:
                report.samples.append((number, reason))

        new_row = list(row) + [None] * (len(headers) - len(row))
        new_row[target] = value
        rows.append(new_row)

    return Table(headers, rows, source=table.source, sheet=table.sheet), report


# --------------------------------------------------------------------- 규칙 검증

TYPE_CHECKS = {
    "숫자": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "정수": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "날짜": lambda v: isinstance(v, (date, datetime)),
    "참거짓": lambda v: isinstance(v, bool),
    "문자": lambda v: isinstance(v, str),
}


# ------------------------------------------------------------- 국내 형식 검사

BIZNO_WEIGHTS = [1, 3, 7, 1, 3, 7, 1, 3, 5]
MOBILE_RE = re.compile(r"01[016789]-?\d{3,4}-?\d{4}")
PHONE_RE = re.compile(r"(?:02|0[3-6][1-5]|070|080|1[5-9]\d{2})-?\d{3,4}-?\d{4}")
POSTCODE_RE = re.compile(r"\d{5}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+")


def check_bizno(value: object) -> bool:
    """사업자등록번호 10자리의 검증번호를 확인한다.

    국세청이 정한 가중치 계산이라 오타는 대부분 여기서 걸린다. 다만
    '규칙에 맞는 번호'일 뿐 실제로 등록된 사업자인지는 알 수 없다.
    """
    digits = re.sub(r"\D", "", to_text(value))
    if len(digits) != 10:
        return False
    numbers = [int(c) for c in digits]
    total = sum(n * w for n, w in zip(numbers[:9], BIZNO_WEIGHTS))
    total += (numbers[8] * 5) // 10
    return (10 - total % 10) % 10 == numbers[9]


FORMAT_CHECKS = {
    "사업자번호": check_bizno,
    "휴대폰": lambda v: bool(MOBILE_RE.fullmatch(to_text(v).replace(" ", ""))),
    "전화번호": lambda v: bool(PHONE_RE.fullmatch(to_text(v).replace(" ", ""))),
    "우편번호": lambda v: bool(POSTCODE_RE.fullmatch(to_text(v).strip())),
    "이메일": lambda v: bool(EMAIL_RE.fullmatch(to_text(v).strip())),
}


@dataclass
class Rule:
    kind: str            # required / unique / type / match / range / oneof / format
    column: str
    argument: str = ""

    def describe(self) -> str:
        return {
            "required": f"{self.column}: 빈 칸이 없어야 함",
            "unique": f"{self.column}: 값이 겹치지 않아야 함",
            "type": f"{self.column}: {self.argument} 여야 함",
            "format": f"{self.column}: {self.argument} 형식이어야 함",
            "match": f"{self.column}: {self.argument} 에 맞아야 함",
            "range": f"{self.column}: {self.argument} 범위 안이어야 함",
            "oneof": f"{self.column}: {self.argument} 중 하나여야 함",
        }[self.kind]


@dataclass
class Violation:
    rule: Rule
    count: int = 0
    rows: list[int] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)


def parse_rule(kind: str, spec: str) -> Rule:
    if kind in ("required", "unique"):
        return Rule(kind, spec.strip())
    column, sep, argument = spec.partition("=")
    if not sep:
        raise SheetError(f"'열=조건' 형태로 적으세요: --{kind} {spec}")
    return Rule(kind, column.strip(), argument.strip())


def _range_bounds(argument: str) -> tuple[float | None, float | None]:
    low, _, high = argument.partition(":")
    def number(text: str):
        text = text.strip()
        if not text:
            return None
        value = parse_number(text)
        if value is None:
            raise SheetError(f"범위를 숫자로 읽지 못했습니다: {text}")
        return float(value)
    return number(low), number(high)


def validate_rules(table: Table, rules: list[Rule]) -> list[Violation]:
    """규칙을 어긴 행을 모은다. 행 번호는 헤더를 1행으로 센 엑셀 기준."""
    found: list[Violation] = []

    for rule in rules:
        index = table.index_of(rule.column)
        bad = Violation(rule)

        if rule.kind == "unique":
            seen: dict[str, int] = {}
            for number, row in enumerate(table.rows, 2):
                key = to_text(row[index] if index < len(row) else None)
                if not key:
                    continue
                if key in seen:
                    bad.count += 1
                    if len(bad.rows) < 20:
                        bad.rows.append(number)
                    if len(bad.samples) < 5 and key not in bad.samples:
                        bad.samples.append(key)
                else:
                    seen[key] = number
            if bad.count:
                found.append(bad)
            continue

        checker = None
        if rule.kind == "type":
            checker = TYPE_CHECKS.get(rule.argument)
            if checker is None:
                raise SheetError(f"모르는 타입입니다: {rule.argument} "
                                 f"({', '.join(TYPE_CHECKS)})")
        elif rule.kind == "format":
            checker = FORMAT_CHECKS.get(rule.argument)
            if checker is None:
                raise SheetError(f"모르는 형식입니다: {rule.argument} "
                                 f"({', '.join(FORMAT_CHECKS)})")
        elif rule.kind == "match":
            try:
                pattern = re.compile(rule.argument)
            except re.error as e:
                raise SheetError(f"정규식이 잘못됐습니다: {e}") from None
            checker = lambda v: bool(pattern.fullmatch(to_text(v)))  # noqa: E731
        elif rule.kind == "range":
            low, high = _range_bounds(rule.argument)

            def checker(v, low=low, high=high):
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    return False
                return not ((low is not None and v < low)
                            or (high is not None and v > high))
        elif rule.kind == "oneof":
            allowed = {x.strip() for x in rule.argument.split(",") if x.strip()}
            checker = lambda v: to_text(v) in allowed  # noqa: E731

        for number, row in enumerate(table.rows, 2):
            value = row[index] if index < len(row) else None
            blank = value is None or value == ""

            if rule.kind == "required":
                ok = not blank
            elif blank:
                ok = True          # 빈 칸은 required 로만 잡는다. 규칙이 겹치면 시끄럽다
            else:
                ok = checker(value)

            if ok:
                continue
            bad.count += 1
            if len(bad.rows) < 20:
                bad.rows.append(number)
            shown = to_text(value) or "(빈 칸)"
            if len(bad.samples) < 5 and shown not in bad.samples:
                bad.samples.append(shown)

        if bad.count:
            found.append(bad)
    return found


# ------------------------------------------------------------- JSON -> 표

@dataclass
class FlattenReport:
    rows: int = 0
    columns: int = 0
    skipped: int = 0          # 객체가 아니라 건너뛴 원소
    max_depth: int = 0


def flatten_record(record: dict, *, prefix: str = "", depth: int = 2,
                   separator: str = ".") -> dict[str, object]:
    """중첩 객체를 '부모.자식' 꼴로 편다. 깊이를 넘으면 JSON 글자로 둔다."""
    out: dict[str, object] = {}
    for key, value in record.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and depth > 0:
            out.update(flatten_record(value, prefix=f"{name}{separator}",
                                      depth=depth - 1, separator=separator))
        elif isinstance(value, (dict, list)):
            out[name] = json.dumps(value, ensure_ascii=False)
        else:
            out[name] = value
    return out


def from_records(records: list, *, depth: int = 2) -> tuple[Table, FlattenReport]:
    """객체 배열을 표로. 키 합집합이 열이 되고 없는 값은 빈 칸이다."""
    report = FlattenReport()
    flattened: list[dict[str, object]] = []

    for item in records:
        if not isinstance(item, dict):
            report.skipped += 1
            continue
        flattened.append(flatten_record(item, depth=depth))

    if not flattened:
        raise SheetError("표로 만들 객체가 없습니다. 객체들의 배열이어야 합니다.")

    headers: list[str] = []
    for row in flattened:
        for key in row:
            if key not in headers:
                headers.append(key)

    rows = [[row.get(h) for h in headers] for row in flattened]
    report.rows, report.columns = len(rows), len(headers)
    report.max_depth = max((h.count(".") for h in headers), default=0)
    return Table(headers, rows), report


def find_records(data, path: str = "") -> list:
    """표로 만들 배열을 찾는다. path 를 주면 그 자리, 없으면 가장 큰 객체 배열."""
    if path:
        from . import jsonkit

        found = jsonkit.get_path(data, path)
        if not isinstance(found, list):
            raise SheetError(f"'{path}' 는 배열이 아니라 "
                             f"{jsonkit.type_name(found)} 입니다")
        return found

    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        raise SheetError("배열이나 객체여야 합니다.")

    best: list = []
    best_key = ""
    for key, value in data.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            if len(value) > len(best):
                best, best_key = value, key
    if not best:
        raise SheetError("객체들의 배열을 찾지 못했습니다. --path 로 자리를 알려 주세요.")
    return best


def unflatten(row: dict[str, object], *, separator: str = ".") -> dict:
    """'meta.부서' 같은 열 이름을 다시 중첩 객체로 되돌린다."""
    out: dict = {}
    for key, value in row.items():
        parts = [p for p in key.split(separator) if p]
        if not parts:
            continue
        current = out
        for part in parts[:-1]:
            nested = current.get(part)
            if not isinstance(nested, dict):
                nested = {}
                current[part] = nested
            current = nested
        current[parts[-1]] = value
    return out


def to_records(table: Table, *, nest: bool = False, skip_blank: bool = True,
               parse_json: bool = False) -> list[dict]:
    """표를 객체 배열로. 날짜는 ISO 글자, 빈 칸은 기본적으로 빼고 넣는다."""
    records: list[dict] = []
    for row in table.rows:
        item: dict[str, object] = {}
        for i, header in enumerate(table.headers):
            value = row[i] if i < len(row) else None
            if skip_blank and (value is None or value == ""):
                continue
            if isinstance(value, datetime):
                value = value.isoformat(sep=" ")
            elif isinstance(value, date):
                value = value.isoformat()
            elif parse_json and isinstance(value, str) \
                    and value[:1] in "[{" and value[-1:] in "]}":
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
            item[header] = value
        records.append(unflatten(item) if nest else item)
    return records


def melt(table: Table, *, keep: list[str], value_cols: list[str] | None = None,
         name: str = "항목", value: str = "값", skip_blank: bool = True) -> Table:
    """넓은 표를 긴 표로 편다(pivot 의 반대).

    부서·이름은 그대로 두고 1월~12월 열을 '항목/값' 두 열로 눕힌다.
    피벗테이블이나 집계 함수는 대개 이 모양을 요구한다.
    """
    keep_idx = [table.index_of(k) for k in keep]
    if value_cols:
        val_idx = [table.index_of(c) for c in value_cols]
    else:
        val_idx = [i for i in range(table.width) if i not in keep_idx]
    if not val_idx:
        raise SheetError("펼 열이 없습니다. --keep 에 모든 열을 넣지 않았는지 보세요.")

    headers = [table.headers[i] for i in keep_idx] + [name, value]
    rows: list[list] = []
    for row in table.rows:
        base = [row[i] if i < len(row) else None for i in keep_idx]
        for i in val_idx:
            cell = row[i] if i < len(row) else None
            if skip_blank and (cell is None or to_text(cell) == ""):
                continue
            rows.append([*base, table.headers[i], cell])
    return Table(headers, rows, source=table.source, sheet=table.sheet)


def transpose(table: Table, *, header: str = "항목") -> Table:
    """행과 열을 바꾼다. 첫 열의 값이 새 머리글이 된다."""
    if not table.rows:
        raise SheetError("행이 없어 뒤집을 것이 없습니다.")

    first = [to_text(r[0]) if r else "" for r in table.rows]
    seen: dict[str, int] = {}
    names: list[str] = []
    for value in first:                       # 같은 이름이 겹치면 뒤에 번호를 붙인다
        base = value or "(빈칸)"
        seen[base] = seen.get(base, 0) + 1
        names.append(base if seen[base] == 1 else f"{base}-{seen[base]}")

    headers = [header, *names]
    rows: list[list] = []
    for i in range(1, table.width):
        rows.append([table.headers[i]] +
                    [r[i] if i < len(r) else None for r in table.rows])
    return Table(headers, rows, source=table.source, sheet=table.sheet)


@dataclass
class ExpandReport:
    column: str
    pieces: Counter = field(default_factory=Counter)   # 조각 수 -> 행 수
    widest: int = 0
    blanks: int = 0                                    # 값이 비어 있던 행

    @property
    def uneven(self) -> bool:
        """행마다 조각 수가 다르면 사람이 봐야 한다."""
        return len([n for n in self.pieces if n]) > 1


def expand_column(table: Table, column: str, *, sep: str = ",",
                  regex: bool = False, names: list[str] | None = None,
                  keep: bool = False, limit: int = 0) -> tuple[Table, ExpandReport]:
    """한 열을 구분자로 갈라 여러 열로 편다(엑셀의 '텍스트 나누기').

    조각 수는 행마다 다를 수 있다. 열 개수는 가장 많이 갈라진 행에 맞추고
    모자란 자리는 빈칸으로 둔다. 잘라 버리면 조용히 값이 사라진다.
    """
    index = table.index_of(column)
    if regex:
        try:
            pattern = re.compile(sep)
        except re.error as e:
            raise SheetError(f"정규식이 잘못됐습니다: {e}") from None
    elif not sep:
        raise SheetError("구분자가 비어 있습니다.")

    report = ExpandReport(column)
    split_rows: list[list[str]] = []
    for row in table.rows:
        raw = to_text(row[index] if index < len(row) else None)
        if not raw.strip():
            report.blanks += 1
            report.pieces[0] += 1
            split_rows.append([])
            continue
        if regex:
            parts = pattern.split(raw, maxsplit=limit - 1 if limit else 0)
        else:
            parts = raw.split(sep, limit - 1 if limit else -1)
        parts = [p.strip() for p in parts]
        report.pieces[len(parts)] += 1
        report.widest = max(report.widest, len(parts))
        split_rows.append(parts)

    width = report.widest
    if names:
        if len(names) < width:
            raise SheetError(f"이름을 {width}개 주세요. 가장 많이 갈라진 행이 "
                             f"{width}조각입니다: {', '.join(names)}")
        headers_new = names[:width]
    else:
        headers_new = [f"{column}{i}" for i in range(1, width + 1)]

    headers = list(table.headers)
    if not keep:
        headers.pop(index)
    at = index + 1 if keep else index
    headers[at:at] = headers_new

    rows: list[list] = []
    for row, parts in zip(table.rows, split_rows):
        body = list(row) + [None] * (table.width - len(row))
        if not keep:
            body.pop(index)
        filled = parts + [""] * (width - len(parts))
        body[at:at] = filled
        rows.append(body)
    return Table(headers, rows, source=table.source, sheet=table.sheet), report


def combine_columns(table: Table, columns: list[str], *, into: str = "합침",
                    sep: str = " ", keep: bool = False,
                    skip_blank: bool = True) -> Table:
    """여러 열을 하나로 합친다(expand 의 반대).

    빈 칸은 건너뛰므로 '서울시  역삼동' 처럼 구분자가 겹치지 않는다.
    """
    if not columns:
        raise SheetError("합칠 열을 주세요.")
    index = [table.index_of(c) for c in columns]

    headers = list(table.headers)
    at = min(index)
    if not keep:
        for i in sorted(index, reverse=True):
            headers.pop(i)
        at = min(index)
    else:
        at = len(headers)
    headers.insert(at, into)

    rows: list[list] = []
    for row in table.rows:
        body = list(row) + [None] * (table.width - len(row))
        parts = [to_text(body[i]) for i in index]
        if skip_blank:
            parts = [p for p in parts if p.strip()]
        value = sep.join(parts)
        if not keep:
            for i in sorted(index, reverse=True):
                body.pop(i)
        body.insert(at, value)
        rows.append(body)
    return Table(headers, rows, source=table.source, sheet=table.sheet)
