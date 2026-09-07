"""표 데이터(csv/tsv/xlsx) 읽기·정리·검증·병합·비교·집계."""

from __future__ import annotations

import csv
import difflib
import io
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .hangul import josa

from . import docx, xlsx

CSV_SUFFIXES = {".csv", ".tsv", ".txt"}
XLSX_SUFFIXES = {".xlsx", ".xlsm"}
MARKDOWN_SUFFIXES = {".md", ".markdown"}
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

    return table_from_grid(grid, header_row=header_row, source=str(path),
                           sheet_name=used_sheet, label=str(path))


@dataclass
class SheetInfo:
    name: str
    rows: int = 0            # 머리글을 뺀 행 수
    columns: int = 0
    headers: list[str] = field(default_factory=list)
    error: str = ""          # 읽다 만 시트도 목록에서 빼지 않는다


def describe_sheets(path: Path, *, header_row: int = 0) -> list[SheetInfo]:
    """엑셀 한 파일 안의 시트를 모두 훑는다.

    남이 보낸 파일은 시트가 열 개씩 되고 이름만으로는 어디에 뭐가 들었는지
    알 수 없다. 시트마다 몇 행인지와 머리글을 보여 준다.
    """
    path = Path(path)
    if path.suffix.lower() not in XLSX_SUFFIXES:
        raise SheetError(f"엑셀 파일이 아닙니다: {path.suffix or '확장자 없음'}")

    out: list[SheetInfo] = []
    for name in xlsx.sheet_names(path):
        info = SheetInfo(name)
        try:
            grid = xlsx.read_sheet(path, name)
            table = table_from_grid(grid, header_row=header_row,
                                    source=str(path), sheet_name=name,
                                    label=f"{path.name}[{name}]")
        except (SheetError, OSError, xlsx.XlsxError) as exc:
            # 빈 시트는 오류가 아니라 그냥 빈 시트다. 목록에서 빼지 않는다.
            info.error = "비어 있음" if "내용이 없습니다" in str(exc) else str(exc)
            out.append(info)
            continue
        info.rows = len(table.rows)
        info.columns = table.width
        info.headers = list(table.headers)
        out.append(info)
    return out


def table_from_grid(grid: list[list], *, header_row: int = 0, source: str = "",
                    sheet_name: str = "", label: str = "입력") -> Table:
    """격자를 표로. 빈 행 걸러내기, 머리글 중복, 짧은 행을 여기서 맞춘다.

    파일에서 읽든 붙여넣은 글에서 만들든 같은 규칙을 써야 열 개수와 이름이
    어긋나지 않는다.
    """
    grid = [row for row in grid if any(c not in (None, "") for c in row)]
    if not grid:
        raise SheetError(f"내용이 없습니다: {label}")
    if header_row >= len(grid):
        raise SheetError(f"헤더 행 번호가 범위를 넘습니다: {header_row + 1}")

    headers = _dedupe_headers([to_text(c).strip() for c in grid[header_row]])
    width = len(headers)
    rows = [(list(r) + [None] * width)[:width] for r in grid[header_row + 1:]]
    return Table(headers, rows, source=source, sheet=sheet_name)


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

    if suffix in MARKDOWN_SUFFIXES:
        path.write_text(to_markdown(table), encoding="utf-8")
        return path

    if suffix == ".docx":
        # 보고서에 붙일 표. 값은 글자로 바꿔 넣는다.
        from . import docx

        rows = [[to_text(cell) for cell in row] for row in table.as_rows()]
        docx.write_document(path, [docx.table(rows)])
        return path

    delimiter = "\t" if suffix == ".tsv" else ","
    # 엑셀에서 바로 열려면 UTF-8 BOM 이 있어야 한글이 안 깨진다
    encoding = "utf-8-sig" if excel_bom else "utf-8"
    with path.open("w", encoding=encoding, newline="") as fh:
        writer = csv.writer(fh, delimiter=delimiter)
        writer.writerow(table.headers)
        writer.writerows([to_text(c) for c in row] for row in table.rows)
    return path



def to_markdown(table: Table) -> str:
    """표를 마크다운 표로. 칸 너비는 맞추지 않는다.

    보기 좋게 칸을 맞추는 일은 at doc tables 가 이미 한다. 여기서 폭 계산을
    한 벌 더 두면 두 곳이 서로 달라진다.
    """
    def cell(value) -> str:
        # 세로줄은 칸 구분자라 반드시 벗어나게 하고, 줄바꿈은 칸을 깨뜨린다
        return to_text(value).replace("|", "\\|").replace("\n", " ").strip()

    head = [cell(h) or " " for h in table.headers]
    lines = ["| " + " | ".join(head) + " |",
             "| " + " | ".join("---" for _ in head) + " |"]
    for row in table.rows:
        cells = [cell(v) for v in (list(row) + [""] * len(head))[:len(head)]]
        lines.append("| " + " | ".join(c or " " for c in cells) + " |")
    return "\n".join(lines) + "\n"


def unique_sheet_names(names) -> list[str]:
    """엑셀 시트 이름 규칙(31자·금지 문자)에 맞추고, 겹치면 번호를 붙인다.

    긴 파일 이름 둘이 앞 31자가 같으면 잘린 뒤 같은 이름이 된다. 그대로
    두면 시트 하나가 조용히 사라진다.
    """
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        base = xlsx.safe_sheet_name(str(name))
        candidate, number = base, 1
        while candidate.lower() in seen:
            number += 1
            tail = f"_{number}"
            candidate = base[:31 - len(tail)] + tail
        seen.add(candidate.lower())
        out.append(candidate)
    return out


def save_sheets(tables: dict, path: Path, *, header: bool = True) -> Path:
    """여러 표를 한 xlsx 의 여러 시트로 저장한다.

    부서별로 파일을 쪼개면 열어 볼 때마다 파일을 찾아야 한다. 한 파일 안의
    탭으로 두면 엑셀에서 그대로 넘겨 본다.
    """
    path = Path(path)
    if path.suffix.lower() not in XLSX_SUFFIXES:
        raise SheetError("여러 시트는 xlsx 로만 저장할 수 있습니다.")
    if not tables:
        raise SheetError("저장할 표가 없습니다.")
    names = unique_sheet_names(tables.keys())
    xlsx.write_sheets(path, dict(zip(names, (t.as_rows() for t in tables.values()))),
                      header=header)
    return path


# ------------------------------------------------------- 빈 칸 채우기·합계

def fill_down(table: Table, columns: list[str] | None = None) -> tuple[Table, int]:
    """빈 칸을 바로 위 값으로 채운다. (새 표, 채운 칸 수)

    엑셀에서 병합된 셀을 풀면 첫 칸만 남고 아래가 빈다. 그대로 두면 정렬·
    피벗·필터가 전부 어긋난다. 실무 파일에서 제일 자주 손보는 자리다.
    """
    indexes = ([table.index_of(c) for c in columns] if columns
               else list(range(len(table.headers))))
    last: dict[int, object] = {}
    rows, filled = [], 0

    for row in table.rows:
        row = list(row) + [None] * (len(table.headers) - len(row))
        for i in indexes:
            if _is_blank(row[i]):
                if i in last:
                    row[i] = last[i]
                    filled += 1
            else:
                last[i] = row[i]
        rows.append(row)

    return Table(list(table.headers), rows, source=table.source,
                 sheet=table.sheet), filled


TOTAL_KINDS = {"sum": "합계", "avg": "평균", "count": "개수"}


def total_row(table: Table, columns: list[str] | None = None, *,
              kind: str = "sum", label: str = "") -> tuple[list, list[str]]:
    """합계 줄을 만든다. (한 줄, 셈한 열 이름들)

    숫자가 아닌 열은 세지 않고 빈 칸으로 둔다. 0 을 넣으면 «합이 0» 으로
    읽혀 실제로 0 인 열과 구분이 안 된다.
    """
    if kind not in TOTAL_KINDS:
        raise SheetError(f"알 수 없는 셈: {kind} ({', '.join(TOTAL_KINDS)})")

    wanted = ([table.index_of(c) for c in columns] if columns
              else list(range(len(table.headers))))
    line: list = [None] * len(table.headers)
    counted: list[str] = []

    for i in wanted:
        numbers = [row[i] for row in table.rows
                   if i < len(row) and isinstance(row[i], (int, float))
                   and not isinstance(row[i], bool)]
        if not numbers and kind != "count":
            continue
        if kind == "sum":
            line[i] = sum(numbers)
        elif kind == "avg":
            line[i] = round(sum(numbers) / len(numbers), 2)
        else:
            line[i] = len([row for row in table.rows
                           if i < len(row) and not _is_blank(row[i])])
        counted.append(table.headers[i])

    # 첫 칸이 비어 있으면 «합계» 라고 적어 무슨 줄인지 알아보게 한다
    if line and line[0] is None:
        line[0] = label or TOTAL_KINDS[kind]
    return line, counted


def with_total(table: Table, columns: list[str] | None = None, *,
               kind: str = "sum", label: str = "") -> tuple[Table, list[str]]:
    """합계 줄을 붙인 새 표."""
    line, counted = total_row(table, columns, kind=kind, label=label)
    return Table(list(table.headers), [*table.rows, line],
                 source=table.source, sheet=table.sheet), counted


# --------------------------------------------------------------- 값 찾기

@dataclass
class Hit:
    path: str
    sheet: str
    row: int              # 머리글을 1행으로 세는 실제 줄 번호
    column: str
    value: str
    context: str = ""     # 같은 행의 첫 열 값 (누구의 행인지 알아보게)


def find_in_table(table: Table, needle: str, *, column: str | None = None,
                  exact: bool = False, ignore_case: bool = True) -> list[Hit]:
    """표 안에서 값을 찾는다. 열을 주면 그 열만 본다."""
    wanted = needle if not ignore_case else needle.lower()
    indexes = ([table.index_of(column)] if column
               else list(range(len(table.headers))))

    out: list[Hit] = []
    for number, row in enumerate(table.rows, 2):     # 머리글이 1행
        first = to_text(row[0]) if row else ""
        for i in indexes:
            cell = to_text(row[i]) if i < len(row) else ""
            body = cell.lower() if ignore_case else cell
            if (body == wanted) if exact else (wanted in body):
                out.append(Hit(table.source, table.sheet, number,
                               table.headers[i], cell, first))
    return out


def find_in_files(paths, needle: str, *, column: str | None = None,
                  exact: bool = False, ignore_case: bool = True,
                  header_row: int = 0) -> tuple[list[Hit], list[tuple[str, str]]]:
    """여러 파일에서 값을 찾는다. (찾은 것, 못 읽은 파일과 그 까닭)

    «이 사번이 어느 파일에 있나»는 사무 일에서 늘 나오는데, 파일마다 열어
    보는 것 말고는 방법이 없었다. xlsx 는 시트를 모두 본다.
    """
    found: list[Hit] = []
    skipped: list[tuple[str, str]] = []

    for path in paths:
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix in XLSX_SUFFIXES:
            try:
                names = xlsx.sheet_names(path) or [None]
            except (OSError, xlsx.XlsxError) as exc:
                skipped.append((str(path), str(exc)))
                continue
        elif suffix in CSV_SUFFIXES:
            names = [None]
        else:
            skipped.append((str(path), f"읽을 수 없는 형식: {suffix or '확장자 없음'}"))
            continue

        for name in names:
            try:
                table = load(path, sheet=name, header_row=header_row)
            except (SheetError, OSError, xlsx.XlsxError) as exc:
                skipped.append((f"{path}" + (f"[{name}]" if name else ""), str(exc)))
                continue
            try:
                found.extend(find_in_table(table, needle, column=column,
                                           exact=exact, ignore_case=ignore_case))
            except SheetError as exc:      # 그 파일에 그 열이 없을 수 있다
                skipped.append((f"{path}" + (f"[{name}]" if name else ""), str(exc)))
    return found, skipped


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
        if op in ("empty", "filled"):        # 값이 필요 없는 조건
            return cls(spec.strip(), op, "")
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


def _row_test(table: Table, checks: list[Condition], any_match: bool):
    """조건을 한 행에 걸어 보는 함수를 만든다. where 와 find_rows 가 같이 쓴다."""
    indexes = {c.column: table.index_of(c.column) for c in checks}

    def passes(row: list) -> bool:
        results = []
        for c in checks:
            i = indexes[c.column]
            cell = row[i] if i < len(row) else None
            if c.op == "has":
                results.append(c.value.lower() in to_text(cell).lower())
                continue
            if c.op in ("empty", "filled"):
                blank = cell is None or to_text(cell).strip() == ""
                results.append(blank if c.op == "empty" else not blank)
                continue
            left, right = _comparable(cell, c.value)
            try:
                results.append(OPERATORS[c.op](left, right))
            except TypeError:
                results.append(False)
        return any(results) if any_match else all(results)

    return passes


def where(table: Table, conditions: list[Condition], *, contains: list[Condition] | None = None,
          any_match: bool = False) -> Table:
    """조건에 맞는 행만 남긴다. 기본은 모든 조건을 만족(AND)."""
    passes = _row_test(table, list(conditions) + list(contains or []), any_match)
    return Table(table.headers, [r for r in table.rows if passes(r)],
                 source=table.source, sheet=table.sheet)


def find_rows(table: Table, conditions: list[Condition] | None = None, *,
              number: int | None = None,
              any_match: bool = False) -> list[tuple[int, list]]:
    """행을 골라 (줄 번호, 행) 로 돌려준다. 줄 번호는 머리글을 1행으로 센다.

    엑셀에서 본 줄 번호와 같아야 «몇 행이 이상하다» 는 말이 통한다.
    """
    checks = list(conditions or [])
    passes = _row_test(table, checks, any_match) if checks else None
    found = []
    for line, row in enumerate(table.rows, 2):
        if number is not None and line != number:
            continue
        if passes is not None and not passes(row):
            continue
        found.append((line, list(row) + [None] * (len(table.headers) - len(row))))
    return found


def _is_blank(cell) -> bool:
    return cell is None or cell == ""


def _sort_key(cell) -> tuple:
    """정렬용 값. 빈 칸 여부는 여기 넣지 않는다(방향과 무관해야 한다)."""
    if _is_blank(cell):
        return (0, 0.0, "")
    if isinstance(cell, bool):
        return (1, 0.0, to_text(cell))
    if isinstance(cell, (int, float)):
        return (0, float(cell), "")
    if isinstance(cell, (datetime, date)):
        stamp = cell if isinstance(cell, datetime) else datetime(
            cell.year, cell.month, cell.day)
        return (0, stamp.timestamp(), "")
    return (1, 0.0, to_text(cell))


def sort_rows(table: Table, columns: list[str], *, descending: bool = False,
              order: list[bool] | None = None) -> Table:
    """여러 열로 정렬한다. order 로 열마다 방향을 따로 줄 수 있다.

    열마다 방향이 다르면 뒤 열부터 차례로 정렬한다. 파이썬 정렬은 안정
    정렬이라 앞 열의 순서가 유지되고, 문자열을 뒤집는 꼼수도 필요 없다.
    """
    indexes = [table.index_of(c) for c in columns]
    flags = list(order or [descending] * len(indexes))
    flags += [descending] * (len(indexes) - len(flags))

    rows = list(table.rows)

    def cell_of(row: list, index: int):
        return row[index] if index < len(row) else None

    # 뒤 열부터 차례로 정렬한다. 파이썬 정렬은 안정 정렬이라 앞 열의 순서가
    # 유지된다. 열마다 방향이 달라도 되고, 빈 칸을 늘 뒤로 보낼 수 있다.
    for index, down in reversed(list(zip(indexes, flags))):
        rows.sort(key=lambda row, i=index: _sort_key(cell_of(row, i)), reverse=down)
        rows.sort(key=lambda row, i=index: _is_blank(cell_of(row, i)))

    return Table(table.headers, rows, source=table.source, sheet=table.sheet)


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
        if spec in ("한글", "계약서") and isinstance(value, (int, float)) \
                and not isinstance(value, bool):
            from .life import formal_amount, korean_amount

            return (korean_amount(value) if spec == "한글"
                    else formal_amount(value))
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


def _alias_expression(expression: str, headers: list[str]):
    """열 이름을 파이썬 이름으로 바꾼다. (바뀐 식, 자리표시자 대응표)

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

    unknown = [aliases[k] for k in aliases if aliases[k] not in headers]
    if unknown:
        raise SheetError(f"없는 열: {', '.join(unknown)}")
    return body, aliases


def compile_expression(expression: str, headers: list[str]):
    """수식을 확인하고 (실행 코드, 자리표시자 대응표) 를 돌려준다."""
    body, aliases = _alias_expression(expression, headers)
    try:
        tree = _ast.parse(body, mode="eval")
    except SyntaxError as e:
        raise SheetError(f"수식을 읽지 못했습니다: {e.msg}") from None

    names = {h for h in headers if h.isidentifier()} | set(aliases)
    _check_expression(tree, names)
    return compile(tree, "<수식>", "eval"), aliases


EXCEL_FUNCS = {"abs": "ABS", "round": "ROUND", "min": "MIN", "max": "MAX",
               "int": "INT", "len": "LEN"}
_EXCEL_BINOPS = {_ast.Add: "+", _ast.Sub: "-", _ast.Mult: "*", _ast.Div: "/",
                 _ast.Pow: "^"}
_EXCEL_COMPARE = {_ast.Eq: "=", _ast.NotEq: "<>", _ast.Lt: "<", _ast.LtE: "<=",
                  _ast.Gt: ">", _ast.GtE: ">="}


def excel_formula(expression: str, headers: list[str], row: int) -> str:
    """수식을 그 행의 엑셀 수식으로 옮긴다 (= 는 빼고).

    옮길 수 있는 것만 옮긴다. 파이썬에서만 되는 문법을 엑셀 수식인 척
    적어 두면, 파일을 여는 사람 화면에서 #NAME? 이 뜬다.
    """
    body, aliases = _alias_expression(expression, headers)
    try:
        tree = _ast.parse(body, mode="eval")
    except SyntaxError as e:
        raise SheetError(f"수식을 읽지 못했습니다: {e.msg}") from None

    letters = {h: xlsx.index_to_col(i) for i, h in enumerate(headers)}

    def where(name: str) -> str:
        header = aliases.get(name, name)
        if header not in letters:
            raise SheetError(f"없는 열: {header}")
        return f"{letters[header]}{row}"

    def walk(node) -> str:
        if isinstance(node, _ast.Name):
            return where(node.id)
        if isinstance(node, _ast.Constant):
            if isinstance(node.value, bool):
                return "TRUE" if node.value else "FALSE"
            if isinstance(node.value, (int, float)):
                return repr(node.value)
            if isinstance(node.value, str):
                return '"' + node.value.replace('"', '""') + '"'
            raise SheetError("엑셀 수식으로 옮길 수 없는 값입니다.")
        if isinstance(node, _ast.BinOp):
            if type(node.op) is _ast.Mod:
                return f"MOD({walk(node.left)}, {walk(node.right)})"
            mark = _EXCEL_BINOPS.get(type(node.op))
            if mark is None:
                raise SheetError("엑셀 수식으로 옮길 수 없는 연산입니다 "
                                 "(// 같은 것은 INT(a/b) 로 적어 주세요).")
            return f"({walk(node.left)} {mark} {walk(node.right)})"
        if isinstance(node, _ast.UnaryOp):
            if type(node.op) is _ast.USub:
                return f"-{walk(node.operand)}"
            if type(node.op) is _ast.UAdd:
                return walk(node.operand)
            if type(node.op) is _ast.Not:
                return f"NOT({walk(node.operand)})"
        if isinstance(node, _ast.BoolOp):
            name = "AND" if isinstance(node.op, _ast.And) else "OR"
            return name + "(" + ", ".join(walk(v) for v in node.values) + ")"
        if isinstance(node, _ast.Compare):
            if len(node.ops) != 1:
                raise SheetError("비교는 한 번만 쓸 수 있습니다 (a < b < c 는 안 됩니다).")
            mark = _EXCEL_COMPARE.get(type(node.ops[0]))
            if mark is None:
                raise SheetError("엑셀 수식으로 옮길 수 없는 비교입니다.")
            return f"({walk(node.left)} {mark} {walk(node.comparators[0])})"
        if isinstance(node, _ast.IfExp):
            return (f"IF({walk(node.test)}, {walk(node.body)}, "
                    f"{walk(node.orelse)})")
        if isinstance(node, _ast.Call):
            if not isinstance(node.func, _ast.Name) or node.func.id not in EXCEL_FUNCS:
                raise SheetError("엑셀 수식으로 옮길 수 없는 함수입니다 "
                                 f"(되는 것: {', '.join(EXCEL_FUNCS)})")
            if node.keywords:
                raise SheetError("엑셀 수식에는 이름 붙인 인자를 쓸 수 없습니다.")
            args = ", ".join(walk(a) for a in node.args)
            if node.func.id == "round" and len(node.args) == 1:
                args += ", 0"          # 엑셀 ROUND 는 자릿수를 꼭 받는다
            return f"{EXCEL_FUNCS[node.func.id]}({args})"
        raise SheetError("엑셀 수식으로 옮길 수 없는 식입니다.")

    return walk(tree.body)


def add_formula_column(table: Table, name: str, expression: str
                       ) -> tuple[Table, FxReport]:
    """계산 «결과» 대신 엑셀 수식을 넣은 열을 붙인다.

    받는 사람이 숫자를 고치면 엑셀이 다시 계산한다. 값으로 넣어 두면 원본이
    바뀌어도 그대로 남아 조용히 틀린 표가 된다.
    """
    computed, report = add_column(table, name, expression)   # 지금 값도 함께 넣는다
    target = computed.headers.index(name)

    rows = []
    for number, row in enumerate(computed.rows, 2):
        row = list(row)
        body = excel_formula(expression, table.headers, number)
        row[target] = xlsx.Formula(body, row[target])
        rows.append(row)
    return Table(list(computed.headers), rows, source=table.source,
                 sheet=table.sheet), report


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


# ------------------------------------------------------------- 열 형식 통일

# 지역번호. 여기 없는 번호는 규칙을 모르는 것으로 보고 손대지 않는다.
AREA_CODES = {"02", "031", "032", "033", "041", "042", "043", "044",
              "051", "052", "053", "054", "055",
              "061", "062", "063", "064"}


def format_phone(value: object) -> str | None:
    """전화번호를 하이픈 표기로. 규칙을 모르면 None 을 돌려 원래 값을 남긴다.

    모르는 번호를 억지로 3-4-4 로 자르면 조용히 틀린 번호가 된다.
    """
    raw = to_text(value).strip()
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+82") and digits.startswith("82"):
        digits = "0" + digits[2:]
    if not digits.startswith("0") and not digits.startswith("1"):
        return None

    if MOBILE_RE.fullmatch(digits) and len(digits) in (10, 11):
        head, tail = digits[:3], digits[3:]
        return f"{head}-{tail[:-4]}-{tail[-4:]}"
    if digits[:3] in ("070", "080") and len(digits) in (10, 11):
        head, tail = digits[:3], digits[3:]
        return f"{head}-{tail[:-4]}-{tail[-4:]}"
    if re.fullmatch(r"1[5-9]\d{2}\d{4}", digits):        # 15xx·16xx·18xx 대표번호
        return f"{digits[:4]}-{digits[4:]}"
    if digits.startswith("02") and len(digits) in (9, 10):
        tail = digits[2:]
        return f"02-{tail[:-4]}-{tail[-4:]}"
    if digits[:3] in AREA_CODES and len(digits) in (10, 11):
        head, tail = digits[:3], digits[3:]
        return f"{head}-{tail[:-4]}-{tail[-4:]}"
    return None


def format_bizno(value: object) -> str | None:
    digits = re.sub(r"\D", "", to_text(value))
    return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}" if len(digits) == 10 else None


def format_postcode(value: object) -> str | None:
    """다섯 자리 새 우편번호만 본다. 여섯 자리 옛 번호는 바꿔 줄 수 없다."""
    digits = re.sub(r"\D", "", to_text(value))
    return digits if len(digits) == 5 else None


def format_date_cell(value: object) -> str | None:
    if isinstance(value, datetime):
        return f"{value:%Y-%m-%d}"
    if isinstance(value, date):
        return f"{value:%Y-%m-%d}"
    parsed = parse_date(to_text(value))
    return f"{parsed:%Y-%m-%d}" if parsed else None


def format_number_cell(value: object):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return parse_number(to_text(value))


COLUMN_FORMATS = {
    "전화": (format_phone, "010-1234-5678 꼴로"),
    "사업자번호": (format_bizno, "123-45-67890 꼴로"),
    "우편번호": (format_postcode, "다섯 자리 숫자로"),
    "날짜": (format_date_cell, "2026-01-02 꼴로"),
    "숫자": (format_number_cell, "쉼표·«원»을 떼고 숫자로"),
}

# 형식을 맞춘 뒤 한 번 더 보는 검사. 맞추기와 옳은지는 다른 문제다.
FORMAT_VERIFY = {"사업자번호": check_bizno}


@dataclass
class FormatReport:
    column: str
    kind: str
    changed: int = 0
    already: int = 0
    blank: int = 0
    failed: list[tuple[int, str]] = field(default_factory=list)   # (행, 원래 값)
    invalid: list[tuple[int, str]] = field(default_factory=list)  # 꼴은 맞으나 검증 실패


def format_column(table: Table, column: str, kind: str) -> tuple[Table, FormatReport]:
    """한 열의 표기를 통일한다. 못 알아본 값은 그대로 두고 따로 알려준다.

    실무 파일에서 전화번호·사업자번호는 사람마다 다르게 적혀 있어 그대로는
    합치거나 대조할 수 없다. 다만 규칙을 모르는 값까지 억지로 자르면 조용히
    틀린 값이 생기므로, 못 알아본 것은 손대지 않고 몇 행인지 알려 준다.
    """
    if kind not in COLUMN_FORMATS:
        raise SheetError(f"알 수 없는 형식: {kind} ({', '.join(COLUMN_FORMATS)})")

    index = table.index_of(column)
    convert, _desc = COLUMN_FORMATS[kind]
    verify = FORMAT_VERIFY.get(kind)
    report = FormatReport(table.headers[index], kind)

    rows = []
    for number, row in enumerate(table.rows, 2):     # 머리글이 1행
        row = list(row)
        cell = row[index] if index < len(row) else None
        if _is_blank(cell):
            report.blank += 1
            rows.append(row)
            continue

        new = convert(cell)
        if new is None:
            report.failed.append((number, to_text(cell)))
        else:
            if to_text(new) != to_text(cell):
                report.changed += 1
                row[index] = new
            else:
                report.already += 1
            if verify and not verify(new):
                report.invalid.append((number, to_text(new)))
        rows.append(row)

    return Table(list(table.headers), rows, source=table.source,
                 sheet=table.sheet), report


FORMAT_CHECKS = {
    "사업자번호": check_bizno,
    "휴대폰": lambda v: bool(MOBILE_RE.fullmatch(to_text(v).replace(" ", ""))),
    "전화번호": lambda v: bool(PHONE_RE.fullmatch(to_text(v).replace(" ", ""))),
    "우편번호": lambda v: bool(POSTCODE_RE.fullmatch(to_text(v).strip())),
    "이메일": lambda v: bool(EMAIL_RE.fullmatch(to_text(v).strip())),
}


# --------------------------------------------------------------- 이상치

OUTLIER_METHODS = {"iqr": "사분위 범위 (한쪽으로 쏠린 자료에 강하다)",
                   "sigma": "평균 ± 표준편차 (종 모양 자료에 맞다)"}
OUTLIER_MIN_ROWS = 8          # 이보다 적으면 «드문 값» 을 말할 수 없다


@dataclass
class Outlier:
    row: int                  # 머리글을 1행으로 센 줄 번호
    value: float
    side: str                 # '높음' 또는 '낮음'


@dataclass
class OutlierReport:
    column: str
    method: str
    counted: int              # 숫자로 읽은 칸 수
    low: float
    high: float
    middle: float             # iqr 이면 중앙값, sigma 면 평균
    found: list[Outlier] = field(default_factory=list)
    note: str = ""


def _quantile(values: list[float], q: float) -> float:
    """오름차순 값에서 백분위. 사이 값은 선형으로 잇는다."""
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * q
    low = int(pos)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (pos - low)


def find_outliers(table: Table, column: str, *, method: str = "iqr",
                  factor: float = 1.5) -> OutlierReport:
    """한 숫자 열에서 드문 값을 찾는다. 지우지 않고 어디인지만 알려 준다.

    «0 이 하나, 1억이 하나» 같은 입력 실수를 검수 때 잡으려는 것이다. 드문
    값이 곧 틀린 값은 아니므로 판단은 사람이 한다.
    """
    if method not in OUTLIER_METHODS:
        raise SheetError(f"모르는 방법: {method} ({', '.join(OUTLIER_METHODS)})")
    if factor <= 0:
        raise SheetError("배수는 0 보다 커야 합니다.")

    index = table.index_of(column)
    numbers: list[tuple[int, float]] = []
    for line, row in enumerate(table.rows, 2):
        cell = row[index] if index < len(row) else None
        if isinstance(cell, bool) or _is_blank(cell):
            continue
        if isinstance(cell, (int, float)):
            numbers.append((line, float(cell)))
        else:
            parsed = parse_number(to_text(cell))
            if parsed is not None:
                numbers.append((line, float(parsed)))

    report = OutlierReport(table.headers[index], method, len(numbers), 0.0, 0.0, 0.0)
    if len(numbers) < OUTLIER_MIN_ROWS:
        report.note = (f"숫자가 {len(numbers)}개뿐이라 드문 값을 말할 수 없습니다 "
                       f"(적어도 {OUTLIER_MIN_ROWS}개).")
        return report

    values = sorted(v for _line, v in numbers)
    if method == "iqr":
        q1, q3 = _quantile(values, 0.25), _quantile(values, 0.75)
        spread = q3 - q1
        report.middle = _quantile(values, 0.5)
        report.low, report.high = q1 - factor * spread, q3 + factor * spread
    else:
        mean = sum(values) / len(values)
        var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        sigma = var ** 0.5
        report.middle = mean
        report.low, report.high = mean - factor * sigma, mean + factor * sigma

    if report.high == report.low:
        report.note = "값이 모두 같아 드문 값이 없습니다."
        return report

    for line, value in numbers:
        if value < report.low:
            report.found.append(Outlier(line, value, "낮음"))
        elif value > report.high:
            report.found.append(Outlier(line, value, "높음"))
    report.found.sort(key=lambda o: -abs(o.value - report.middle))
    return report


# ------------------------------------------------------------ 값 바꾸기

@dataclass
class ReplaceReport:
    changed: int = 0                 # 바꾼 칸 수
    rows: int = 0                    # 바뀐 행 수
    columns: list[str] = field(default_factory=list)
    skipped_typed: int = 0           # 숫자·날짜라서 건드리지 않은 칸


def replace_values(table: Table, find: str, to: str, *,
                   columns: list[str] | None = None, exact: bool = False,
                   ignore_case: bool = False) -> tuple[Table, ReplaceReport]:
    """표 안의 값을 찾아 바꾼다. 엑셀의 «모두 바꾸기» 를 파일째 하는 것.

    숫자·날짜 칸은 건드리지 않는다. 글자로 바꿔 넣으면 그 열이 통째로 글자가
    되어 합계와 정렬이 어긋난다. 몇 칸을 건드리지 않았는지는 알려 준다.
    """
    if not find:
        raise SheetError("찾을 값을 주세요.")
    wanted = ([table.index_of(c) for c in columns] if columns
              else list(range(len(table.headers))))
    needle = find.lower() if ignore_case else find
    report = ReplaceReport()
    touched: set[str] = set()

    rows = []
    for row in table.rows:
        row = list(row) + [None] * (len(table.headers) - len(row))
        hit_in_row = False
        for i in wanted:
            cell = row[i]
            if _is_blank(cell):
                continue
            if isinstance(cell, (int, float, datetime, date)) and not isinstance(cell, str):
                text = to_text(cell)
                if (needle in (text.lower() if ignore_case else text)
                        or (exact and text == find)):
                    report.skipped_typed += 1
                continue
            text = to_text(cell)
            body = text.lower() if ignore_case else text
            if exact:
                if body != needle:
                    continue
                new_text = to
            else:
                if needle not in body:
                    continue
                if ignore_case:
                    new_text = re.sub(re.escape(find), to.replace("\\", "\\\\"),
                                      text, flags=re.IGNORECASE)
                else:
                    new_text = text.replace(find, to)
            if new_text == text:
                continue
            row[i] = new_text
            report.changed += 1
            touched.add(table.headers[i])
            hit_in_row = True
        rows.append(row)
        if hit_in_row:
            report.rows += 1

    report.columns = [h for h in table.headers if h in touched]
    return Table(list(table.headers), rows, source=table.source,
                 sheet=table.sheet), report


# ------------------------------------------------------------- 날짜 쪼개기

WEEKDAYS_KO = ("월", "화", "수", "목", "금", "토", "일")

DATE_PARTS: dict[str, str] = {
    "연도": "2026",
    "월": "3",
    "일": "2",
    "요일": "월",
    "연월": "2026-03",
    "분기": "2026 Q1",
    "주차": "2026-W10",
}


def date_part(value: date, part: str) -> object:
    """날짜에서 한 조각. 피벗·필터에 쓸 파생 열을 만든다."""
    if part == "연도":
        return value.year
    if part == "월":
        return value.month
    if part == "일":
        return value.day
    if part == "요일":
        return WEEKDAYS_KO[value.weekday()]
    if part == "연월":
        return f"{value.year:04d}-{value.month:02d}"
    if part == "분기":
        return f"{value.year} Q{(value.month - 1) // 3 + 1}"
    if part == "주차":
        # ISO 주차. 연말·연초의 주는 해가 넘어갈 수 있어 그 해까지 붙인다
        iso = value.isocalendar()
        return f"{iso[0]:04d}-W{iso[1]:02d}"
    raise SheetError(f"모르는 조각: {part} ({', '.join(DATE_PARTS)})")


def _as_date(cell: object) -> date | None:
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    if _is_blank(cell):
        return None
    return parse_date(to_text(cell))


def add_date_parts(table: Table, column: str, parts: list[str]
                   ) -> tuple[Table, list[tuple[int, str]]]:
    """날짜 열에서 요일·월·분기 같은 열을 만들어 붙인다. (새 표, 못 읽은 칸)

    피벗을 돌리기 전에 늘 손으로 만드는 열이다. 날짜로 못 읽은 칸은 비워
    두고 몇 행이었는지 알려 준다 - 오늘 날짜 같은 걸 채워 넣으면 그 행이
    엉뚱한 달에 잡힌다.
    """
    for part in parts:
        if part not in DATE_PARTS:
            raise SheetError(f"모르는 조각: {part} ({', '.join(DATE_PARTS)})")
    if not parts:
        raise SheetError("만들 열을 하나 이상 고르세요. "
                         f"({', '.join(DATE_PARTS)})")

    index = table.index_of(column)
    headers = list(table.headers) + [f"{column} {p}" for p in parts]
    rows: list[list] = []
    failed: list[tuple[int, str]] = []

    for line, row in enumerate(table.rows, 2):
        row = list(row) + [None] * (len(table.headers) - len(row))
        when = _as_date(row[index] if index < len(row) else None)
        if when is None:
            if not _is_blank(row[index]):
                failed.append((line, to_text(row[index])))
            rows.append(row + [None] * len(parts))
            continue
        rows.append(row + [date_part(when, p) for p in parts])

    return Table(_dedupe_headers(headers), rows, source=table.source,
                 sheet=table.sheet), failed


# ---------------------------------------------------------------- SQL 로

SQL_DIALECTS = {"sqlite": '"', "postgres": '"', "mysql": "`"}

_SQL_TYPES = {"정수": {"sqlite": "INTEGER", "postgres": "INTEGER", "mysql": "INT"},
              "실수": {"sqlite": "REAL", "postgres": "DOUBLE PRECISION",
                       "mysql": "DOUBLE"},
              "날짜": {"sqlite": "TEXT", "postgres": "DATE", "mysql": "DATE"},
              "참거짓": {"sqlite": "INTEGER", "postgres": "BOOLEAN",
                         "mysql": "TINYINT(1)"},
              "글자": {"sqlite": "TEXT", "postgres": "TEXT", "mysql": "TEXT"}}


def sql_name(name: str, dialect: str) -> str:
    """열·표 이름을 그 dialect 의 따옴표로 감싼다."""
    quote = SQL_DIALECTS[dialect]
    return quote + str(name).replace(quote, quote * 2) + quote


def sql_value(value: object, dialect: str) -> str:
    """값 하나를 SQL 리터럴로. 빈 칸은 NULL 이다.

    빈 칸을 ''(빈 글자)로 넣으면 «값이 없음» 과 «빈 글자» 가 섞인다. 나중에
    IS NULL 로 못 찾는다.
    """
    if _is_blank(value):
        return "NULL"
    if isinstance(value, bool):
        if dialect == "postgres":
            return "TRUE" if value else "FALSE"
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, datetime):
        return "'" + value.strftime("%Y-%m-%d %H:%M:%S") + "'"
    if isinstance(value, date):
        return "'" + value.strftime("%Y-%m-%d") + "'"
    return "'" + to_text(value).replace("'", "''") + "'"


def _sql_column_type(values: list, dialect: str) -> str:
    kinds = set()
    for value in values:
        if _is_blank(value):
            continue
        if isinstance(value, bool):
            kinds.add("참거짓")
        elif isinstance(value, int):
            kinds.add("정수")
        elif isinstance(value, float):
            kinds.add("실수")
        elif isinstance(value, (datetime, date)):
            kinds.add("날짜")
        else:
            kinds.add("글자")
    if not kinds or len(kinds) > 1:
        if kinds == {"정수", "실수"}:
            return _SQL_TYPES["실수"][dialect]
        return _SQL_TYPES["글자"][dialect]      # 섞였으면 글자로 둔다
    return _SQL_TYPES[kinds.pop()][dialect]


def to_sql(table: Table, name: str, *, dialect: str = "sqlite",
           batch: int = 100, create: bool = False) -> str:
    """표를 INSERT 문으로. 엑셀 자료를 개발 DB 에 넣을 때.

    타입은 값에서 짐작한다. 짐작한 것이라는 주석을 함께 붙인다 - 실제 스키마와
    다를 수 있고, 그걸 모른 채로 CREATE TABLE 을 돌리면 나중에 더 고생한다.
    """
    if dialect not in SQL_DIALECTS:
        raise SheetError(f"모르는 종류: {dialect} ({', '.join(SQL_DIALECTS)})")
    if not str(name).strip():
        raise SheetError("표(테이블) 이름을 주세요.")
    if batch < 1:
        raise SheetError("한 번에 넣을 행 수는 1 이상이어야 합니다.")
    if not table.rows:
        raise SheetError("넣을 행이 없습니다.")

    columns = ", ".join(sql_name(h, dialect) for h in table.headers)
    lines: list[str] = []

    if create:
        lines.append("-- 아래 CREATE TABLE 은 값에서 짐작한 것입니다. "
                     "실제 스키마에 맞춰 고치세요.")
        pieces = []
        for i, header in enumerate(table.headers):
            values = [row[i] for row in table.rows if i < len(row)]
            pieces.append(f"  {sql_name(header, dialect)} "
                          f"{_sql_column_type(values, dialect)}")
        lines.append(f"CREATE TABLE {sql_name(name, dialect)} (\n"
                     + ",\n".join(pieces) + "\n);")
        lines.append("")

    width = len(table.headers)
    for start in range(0, len(table.rows), batch):
        chunk = table.rows[start:start + batch]
        rows = []
        for row in chunk:
            padded = (list(row) + [None] * width)[:width]
            rows.append("  (" + ", ".join(sql_value(v, dialect) for v in padded) + ")")
        lines.append(f"INSERT INTO {sql_name(name, dialect)} ({columns}) VALUES\n"
                     + ",\n".join(rows) + ";")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------- 비슷한 값

# 상호에 붙는 법인 표기. 이것만 다른 것은 같은 곳으로 본다.
COMPANY_WORDS = ("주식회사", "유한책임회사", "유한회사", "사단법인", "재단법인",
                 "합자회사", "합명회사", "(주)", "(유)", "㈜")
# 기호를 뗀 뒤 «끝에» 붙어 있을 때만 떼는 것들. 이름 가운데서 떼면 딴 이름이 된다.
COMPANY_TAILS = ("coltd", "company", "ltd", "llc", "inc", "corp")
_STRIP = re.compile(r"[\s.,\-_/()\[\]{}'\"·ㆍ]")


def normalize_name(value: object) -> str:
    """견주기 좋게 다듬은 이름. 법인 표기를 떼고 공백·기호를 지운다.

    법인 표기를 먼저 뗀다. 기호를 먼저 지우면 «(주)» 가 «주» 로 남아
    이름 앞에 붙어 버린다.
    """
    text = unicodedata.normalize("NFC", to_text(value)).strip().lower()
    for word in COMPANY_WORDS:
        text = text.replace(word, "")
    text = _STRIP.sub("", text)
    for tail in COMPANY_TAILS:
        if text.endswith(tail) and len(text) > len(tail):
            text = text[: -len(tail)]
            break
    return text


def _one_char_apart(a: str, b: str) -> bool:
    """글자 하나만 다른가. 짧은 이름을 위해 따로 본다.

    «다라테크» 와 «다라테그» 는 닮은 정도가 0.75 밖에 안 나온다. 네 글자짜리
    상호에서 한 글자 오타는 흔한데, 그걸 잡으려고 기준을 낮추면 긴 이름에서
    엉뚱한 짝이 쏟아진다.
    """
    if min(len(a), len(b)) < 3 or abs(len(a) - len(b)) > 1:
        return False
    changed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            continue
        changed += max(i2 - i1, j2 - j1)
        if changed > 1:
            return False
    return changed == 1


@dataclass
class SimilarPair:
    left_row: int             # 머리글을 1행으로 센 줄 번호
    right_row: int
    left: str
    right: str
    score: float              # 1.0 이면 다듬은 뒤 완전히 같다
    reason: str               # '표기만 다름' 또는 '비슷함'


def find_similar(table: Table, column: str, *, threshold: float = 0.85,
                 limit: int = 500) -> tuple[list[SimilarPair], bool]:
    """한 열에서 같은 것으로 보이는 값들을 찾는다. (후보, 다 못 본 것이 있나)

    거래처 명부에 «(주)가나» 와 «주식회사 가나» 가 따로 들어가는 일이 흔하다.
    합치지는 않는다 - 다른 곳일 수도 있어서, 사람이 보고 정하게 후보만 낸다.

    전부 견주면 만 행에서 오천만 번을 재야 한다. 다듬은 이름의 앞 두 글자가
    같은 것끼리만 견주므로, 첫 글자가 다른 오타(«가나» 와 «나나»)는 못 찾는다.
    """
    index = table.index_of(column)
    rows: list[tuple[int, str, str]] = []      # (줄 번호, 원래 값, 다듬은 값)
    for line, row in enumerate(table.rows, 2):
        raw = to_text(row[index]) if index < len(row) else ""
        if not raw.strip():
            continue
        rows.append((line, raw, normalize_name(raw)))

    buckets: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for item in rows:
        buckets[item[2][:2]].append(item)

    pairs: list[SimilarPair] = []
    cut = False
    for bucket in buckets.values():
        for i, (line_a, raw_a, key_a) in enumerate(bucket):
            for line_b, raw_b, key_b in bucket[i + 1:]:
                if raw_a == raw_b:             # 똑같은 값은 at sheet dedupe 의 몫
                    continue
                if key_a == key_b:
                    score, reason = 1.0, "표기만 다름"
                else:
                    score = difflib.SequenceMatcher(None, key_a, key_b).ratio()
                    if score < threshold and not _one_char_apart(key_a, key_b):
                        continue
                    reason = "비슷함"
                if len(pairs) >= limit:
                    cut = True
                    break
                pairs.append(SimilarPair(line_a, line_b, raw_a, raw_b,
                                         round(score, 3), reason))
            if cut:
                break
        if cut:
            break

    pairs.sort(key=lambda p: (-p.score, p.left_row))
    return pairs, cut


# --------------------------------------------------------- 워드 표 꺼내기

def tables_from_docx(path: Path) -> list[Table]:
    """워드 문서 안의 표를 순서대로 꺼낸다. 표가 없으면 빈 목록.

    보고서에 붙은 표를 엑셀로 옮기려고 손으로 다시 치는 일을 대신한다.
    첫 줄을 머리글로 삼되, 병합 때문에 첫 줄이 비면 그 줄도 자료로 남긴다 -
    머리글을 지어내면 어느 열이 무엇인지 아무도 모르게 된다.
    """
    path = Path(path)
    try:
        parts = docx.read_document(path)
    except docx.DocxError as exc:
        raise SheetError(str(exc)) from None

    out: list[Table] = []
    for order, (kind, body) in enumerate([p for p in parts if p[0] == "표"], 1):
        grid = [[parse_value(c) for c in row] for row in body]  # type: ignore[union-attr]
        if not any(any(c not in (None, "") for c in row) for row in grid):
            continue
        first = [to_text(c).strip() for c in grid[0]]
        if all(first) and len(set(first)) == len(first):
            table = table_from_grid(grid, header_row=0, source=str(path),
                                    sheet_name=f"표{order}", label=str(path))
        else:                     # 머리글로 쓸 수 없는 첫 줄이면 자리를 만들어 준다
            width = max(len(r) for r in grid)
            headers = [f"열{i + 1}" for i in range(width)]
            table = table_from_grid([headers] + grid, header_row=0,
                                    source=str(path), sheet_name=f"표{order}",
                                    label=str(path))
        out.append(table)
    return out


# ------------------------------------------------------------- 양식 취합

@dataclass
class CellSpec:
    ref: str                 # B3 처럼 엑셀에서 보이는 칸 주소
    name: str                # 표에 넣을 열 이름


def parse_cell(spec: str) -> CellSpec:
    """'B3=담당자' 또는 'B3' 를 읽는다."""
    ref, _sep, name = spec.partition("=")
    ref = ref.strip().upper()
    try:
        xlsx.split_ref(ref)
    except xlsx.XlsxError as exc:
        raise SheetError(str(exc)) from None
    return CellSpec(ref, name.strip() or ref)


def _csv_cells(path: Path, refs: list[str]) -> dict[str, object]:
    """csv 를 칸 주소로 읽는다. 엑셀에서 열었을 때와 같은 자리여야 한다."""
    encoding = sniff_encoding(path)
    text = path.read_text(encoding=encoding)
    delimiter = "\t" if path.suffix.lower() == ".tsv" or text.count("\t") > text.count(",") else ","
    grid = [list(r) for r in csv.reader(io.StringIO(text), delimiter=delimiter)]
    found: dict[str, object] = {}
    for ref in refs:
        line, column = xlsx.split_ref(ref)
        row = grid[line - 1] if line - 1 < len(grid) else []
        cell = row[column] if column < len(row) else None
        found[ref] = parse_value(cell) if isinstance(cell, str) else cell
    return found


def collect_cells(paths: list[Path], specs: list[CellSpec], *,
                  sheet: str | None = None) -> tuple[Table, list[tuple[str, str]]]:
    """양식이 같은 파일 여러 개에서 같은 칸만 뽑아 한 표로. (표, 못 읽은 것)

    부서마다 같은 서식으로 채워 보낸 파일을 손으로 옮겨 적는 일을 대신한다.
    없는 칸은 빈 칸으로 두고 파일은 표에 남긴다 - 빠뜨린 파일이 조용히
    사라지면 무엇이 안 왔는지 알 수 없다.
    """
    if not specs:
        raise SheetError("뽑을 칸을 하나 이상 주세요. 예: --cell B3=담당자")

    rows: list[list] = []
    skipped: list[tuple[str, str]] = []
    refs = [s.ref for s in specs]

    for path in paths:
        path = Path(path)
        if path.is_dir():
            skipped.append((str(path), "폴더입니다"))
            continue
        suffix = path.suffix.lower()
        try:
            if suffix in XLSX_SUFFIXES:
                found = xlsx.read_cells(path, refs, sheet)
            elif suffix in CSV_SUFFIXES or not suffix:
                found = _csv_cells(path, refs)
            else:
                skipped.append((str(path), f"지원하지 않는 형식입니다: {suffix}"))
                continue
        except (xlsx.XlsxError, SheetError, OSError, UnicodeDecodeError) as exc:
            skipped.append((str(path), str(exc)))
            continue
        rows.append([path.name] + [found.get(s.ref) for s in specs])

    headers = ["파일"] + [s.name for s in specs]
    return Table(headers, rows), skipped


# ------------------------------------------------------------------ 가림

HIDDEN = "****"          # 꼴을 알아보지 못한 값을 통째로 가릴 때


def mask_name(value: object) -> str | None:
    """홍길동 -> 홍*동. 두 글자면 뒤를 가린다 (가운데가 없다)."""
    raw = to_text(value).strip()
    if not raw:
        return None
    if " " in raw:                       # 영문 이름은 낱말마다 첫 글자만
        parts = [w for w in raw.split() if w]
        return " ".join(w[0] + "*" * (len(w) - 1) for w in parts)
    if len(raw) == 1:
        return "*"
    if len(raw) == 2:
        return raw[0] + "*"
    return raw[0] + "*" * (len(raw) - 2) + raw[-1]


def mask_phone(value: object) -> str | None:
    """010-1234-5678 -> 010-****-5678. 가운데 자리를 가린다.

    번호 꼴을 아는 것만 가린다. 아무 숫자나 잘라 «전화처럼» 만들면
    전화가 아닌 값이 전화인 척하게 된다.
    """
    fixed = format_phone(value)
    if fixed is None:
        return None
    parts = fixed.split("-")
    if len(parts) == 3:
        return f"{parts[0]}-{'*' * len(parts[1])}-{parts[2]}"
    if len(parts) == 2:                  # 1588-1234 같은 대표번호
        return f"{parts[0]}-{'*' * len(parts[1])}"
    return None


def mask_email(value: object) -> str | None:
    """hong@example.com -> ho**@example.com. 도메인은 남긴다."""
    raw = to_text(value).strip()
    if raw.count("@") != 1:
        return None
    local, _, domain = raw.partition("@")
    if not local or "." not in domain:
        return None
    # 짧은 아이디는 앞을 남기면 다 드러난다. 세 글자 밑이면 통째로 가린다.
    keep = 2 if len(local) >= 4 else (1 if len(local) == 3 else 0)
    return local[:keep] + "*" * (len(local) - keep) + "@" + domain


RRN_RE = re.compile(r"(\d{6})[-\s]?([1-8])\d{6}")


def mask_rrn(value: object) -> str | None:
    """주민등록번호 -> 900101-1******. 성별 자리까지만 남긴다.

    뒷자리 일곱 개 가운데 첫 자리(성별)만 남기는 것이 표준 처리다.
    """
    raw = to_text(value).strip()
    hit = RRN_RE.fullmatch(raw)
    if not hit:
        return None
    return f"{hit.group(1)}-{hit.group(2)}******"


def mask_account(value: object) -> str | None:
    """계좌·카드 번호 -> 뒤 네 자리만 남긴다. 하이픈 자리는 그대로 둔다."""
    raw = to_text(value).strip()
    digits = [i for i, ch in enumerate(raw) if ch.isdigit()]
    if len(digits) < 8:                  # 짧은 숫자는 계좌인지 알 수 없다
        return None
    if any(not (ch.isdigit() or ch in "- ") for ch in raw):
        return None
    hide = set(digits[:-4])
    return "".join("*" if i in hide else ch for i, ch in enumerate(raw))


ADDRESS_HEADS = ("시", "군", "구")


def mask_address(value: object) -> str | None:
    """주소 -> 시·군·구까지만 남기고 뒤를 가린다.

    번지·동호수가 붙으면 사람을 특정할 수 있다. 어디까지가 행정구역인지
    모르겠는 주소는 None 을 돌려 부르는 쪽이 판단하게 한다.
    """
    parts = [w for w in to_text(value).split() if w]
    if len(parts) < 2:
        return None
    keep = 0
    for i, word in enumerate(parts[:3]):
        if word.endswith(ADDRESS_HEADS) or word.endswith("도"):
            keep = i + 1
    if not keep or keep == len(parts):
        return None
    return " ".join(parts[:keep]) + " " + HIDDEN


MASK_KINDS = {
    "이름": (mask_name, "홍*동"),
    "전화": (mask_phone, "010-****-5678"),
    "이메일": (mask_email, "ho**@example.com"),
    "주민번호": (mask_rrn, "900101-1******"),
    "계좌": (mask_account, "***-****-1234"),
    "주소": (mask_address, "시·군·구까지만"),
}


@dataclass
class MaskReport:
    column: str
    kind: str
    masked: int = 0
    blank: int = 0
    unclear: list[tuple[int, str]] = field(default_factory=list)  # (행, 원래 값)


def mask_column(table: Table, column: str, kind: str) -> tuple[Table, MaskReport]:
    """한 열을 가린다. 꼴을 모르는 값은 통째로 가리고 몇 행인지 알려 준다.

    다른 명령과 달리 «모르면 그대로 둔다» 를 쓰지 않는다. 가림은 밖으로
    내보낼 파일을 만드는 일이라, 잘못 가리는 것보다 못 가리고 새는 것이
    훨씬 나쁘다. 대신 통째로 가린 행을 전부 알려 주어 원본에서 확인할 수
    있게 한다.
    """
    if kind not in MASK_KINDS:
        raise SheetError(f"알 수 없는 가림: {kind} ({', '.join(MASK_KINDS)})")

    index = table.index_of(column)
    hide, _example = MASK_KINDS[kind]
    report = MaskReport(table.headers[index], kind)

    rows = []
    for number, row in enumerate(table.rows, 2):     # 머리글이 1행
        row = list(row) + [None] * (len(table.headers) - len(row))
        cell = row[index]
        if _is_blank(cell):
            report.blank += 1
            rows.append(row)
            continue
        new = hide(cell)
        if new is None:
            report.unclear.append((number, to_text(cell)))
            new = HIDDEN
        report.masked += 1
        row[index] = new
        rows.append(row)

    return Table(list(table.headers), rows, source=table.source,
                 sheet=table.sheet), report


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
        from .code import jsonkit

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


@dataclass
class ColumnStat:
    name: str
    kind: str
    count: int = 0              # 값이 있는 칸 수
    total: float = 0.0
    mean: float = 0.0
    median: float = 0.0
    low: object = None
    high: object = None
    top: str = ""               # 가장 많이 나온 값
    top_count: int = 0

    @property
    def top_ratio(self) -> float:
        return self.top_count / self.count if self.count else 0.0


def column_stats(table: Table) -> list[ColumnStat]:
    """열마다 요약값. 숫자는 합계·평균·중앙값, 나머지는 최빈값.

    평균과 중앙값을 함께 낸다. 한쪽만 보면 치우친 자료를 잘못 읽는다.
    """
    out: list[ColumnStat] = []
    for i, name in enumerate(table.headers):
        values = [row[i] for row in table.rows
                  if i < len(row) and row[i] is not None and row[i] != ""]
        numbers = [v for v in values
                   if isinstance(v, (int, float)) and not isinstance(v, bool)]
        stat = ColumnStat(name, kind_of(values[0]) if values else "빈칸",
                          count=len(values))

        if numbers and len(numbers) >= len(values) / 2:
            ordered = sorted(numbers)
            middle = len(ordered) // 2
            stat.kind = "숫자"
            stat.total = sum(ordered)
            stat.mean = stat.total / len(ordered)
            stat.median = (ordered[middle] if len(ordered) % 2
                           else (ordered[middle - 1] + ordered[middle]) / 2)
            stat.low, stat.high = ordered[0], ordered[-1]
        else:
            counted = Counter(to_text(v) for v in values)
            if counted:
                stat.top, stat.top_count = counted.most_common(1)[0]
            comparable = [v for v in values if isinstance(v, (date, datetime))]
            if comparable and len(comparable) == len(values):
                stat.kind = "날짜"
                stat.low, stat.high = min(comparable), max(comparable)
        out.append(stat)
    return out


@dataclass
class ColumnDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    moved: list[tuple[str, int, int]] = field(default_factory=list)   # 이름, 전, 후
    retyped: list[tuple[str, str, str]] = field(default_factory=list)  # 이름, 전, 후

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.moved or self.retyped)


def column_diff(before: Table, after: Table) -> ColumnDiff:
    """열 구조만 비교한다. 키가 없어도, 행이 아주 많아도 볼 수 있다.

    거래처가 보내 주는 파일의 서식이 바뀌었는지 확인할 때 쓴다.
    """
    old_kinds = {c.name: c.main_kind for c in profile(before)}
    new_kinds = {c.name: c.main_kind for c in profile(after)}
    out = ColumnDiff()
    out.added = [h for h in after.headers if h not in before.headers]
    out.removed = [h for h in before.headers if h not in after.headers]

    for name in before.headers:
        if name not in after.headers:
            continue
        old_at, new_at = before.headers.index(name), after.headers.index(name)
        if old_at != new_at:
            out.moved.append((name, old_at + 1, new_at + 1))
        if old_kinds.get(name) != new_kinds.get(name):
            out.retyped.append((name, old_kinds.get(name, "?"),
                                new_kinds.get(name, "?")))
    return out


def rename_columns(table: Table, mapping: dict, *,
                   strip: bool = False) -> tuple[Table, list[str]]:
    """열 이름을 바꾼다. (새 표, 표에 없던 이름들)

    거래처마다 열 이름이 달라서 합치기 전에 맞춰야 한다. 없는 이름을 조용히
    넘기지 않고 돌려주므로, 매핑이 낡았는지 바로 안다.
    """
    # 엑셀에서 온 헤더에는 공백이 붙어 있는 일이 흔해 느슨하게도 찾는다.
    loose = {str(k).strip().lower(): v for k, v in mapping.items()}
    known = {h.strip().lower() for h in table.headers}
    missing = [old for old in mapping
               if old not in table.headers and str(old).strip().lower() not in known]

    headers: list[str] = []
    for name in table.headers:
        new = mapping.get(name)
        if new is None:
            new = loose.get(name.strip().lower())
        head = new if new is not None else name
        headers.append(head.strip() if strip else head)

    seen: dict[str, int] = {}
    unique: list[str] = []
    for head in headers:                  # 바꾸다 이름이 겹치면 번호를 붙인다
        seen[head] = seen.get(head, 0) + 1
        unique.append(head if seen[head] == 1 else f"{head}-{seen[head]}")

    return Table(unique, [list(r) for r in table.rows],
                 source=table.source, sheet=table.sheet), missing
