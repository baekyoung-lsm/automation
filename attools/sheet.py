"""표 데이터(csv/tsv/xlsx) 읽기·정리·검증·병합·비교·집계."""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

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
        if spec:
            try:
                return format(value, spec.strip())
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
