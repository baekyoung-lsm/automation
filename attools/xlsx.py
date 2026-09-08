"""의존성 없이 xlsx 를 읽고 쓴다.

xlsx 는 XML 을 담은 zip 이라 표준 라이브러리만으로 다룰 수 있다.
서식·수식·차트까지 필요하면 openpyxl 을 쓰는 게 맞고, 여기서는 값만 오간다.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
EPOCH = datetime(1899, 12, 30)  # 엑셀의 1900 윤년 버그를 포함한 기준일

# 엑셀 기본 날짜/시간 서식 번호
DATE_FMT_IDS = set(range(14, 23)) | {27, 30, 36, 45, 46, 47, 50, 57}
DATE_FMT_CHARS = re.compile(r"(?<!\\)[ymdhs]")
ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class XlsxError(Exception):
    pass


def _text(el: ET.Element | None) -> str:
    return "".join(el.itertext()) if el is not None else ""


def col_to_index(ref: str) -> int:
    """'A1' -> 0, 'AB7' -> 27"""
    letters = "".join(c for c in ref if c.isalpha())
    n = 0
    for c in letters:
        n = n * 26 + (ord(c.upper()) - 64)
    return n - 1


def index_to_col(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def serial_to_datetime(serial: float) -> datetime:
    """엑셀은 날짜를 실수로 저장하므로 초 단위로 반올림해서 돌려준다."""
    dt = EPOCH + timedelta(days=serial)
    if dt.microsecond:
        dt = (dt + timedelta(seconds=0.5)).replace(microsecond=0)
    return dt


# ------------------------------------------------------------------ 읽기

def safe_sheet_name(name: str) -> str:
    """엑셀이 허용하지 않는 문자를 빼고 31자로 자른다."""
    cleaned = re.sub(r"[\[\]:*?/\\]", "_", name).strip("'") or "Sheet1"
    return cleaned[:31]


def _open(path: Path) -> zipfile.ZipFile:
    """xlsx 를 연다. zip 이 아니면 사람 말로 알린다.

    옛 .xls 를 이름만 .xlsx 로 바꿔 두는 일이 흔하다. 그때 파이썬 역추적이
    뜨면 파일이 잘못됐다는 것을 알 수 없다.
    """
    try:
        return zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise XlsxError(
            f"엑셀 파일이 아닙니다: {Path(path).name} "
            "(xlsx 는 zip 인데 그렇지 않습니다. 옛 .xls 라면 엑셀에서 "
            "«다른 이름으로 저장»으로 xlsx 로 바꿔 주세요)") from None
    except OSError as exc:
        raise XlsxError(f"열지 못했습니다: {exc}") from None


def sheet_names(path: Path) -> list[str]:
    with _open(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        return [s.get("name", "") for s in wb.findall("m:sheets/m:sheet", NS)]


def _date_style_flags(z: zipfile.ZipFile) -> list[bool]:
    """셀 스타일 번호마다 날짜 서식인지 표시한다."""
    try:
        styles = ET.fromstring(z.read("xl/styles.xml"))
    except KeyError:
        return []

    custom: dict[int, str] = {}
    for fmt in styles.findall("m:numFmts/m:numFmt", NS):
        try:
            custom[int(fmt.get("numFmtId", "0"))] = fmt.get("formatCode", "")
        except ValueError:
            continue

    flags = []
    for xf in styles.findall("m:cellXfs/m:xf", NS):
        try:
            fmt_id = int(xf.get("numFmtId", "0"))
        except ValueError:
            fmt_id = 0
        code = custom.get(fmt_id)
        flags.append(fmt_id in DATE_FMT_IDS
                     or bool(code and DATE_FMT_CHARS.search(code.split(";")[0])))
    return flags


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t"))
            for si in root.findall("m:si", NS)]


def _sheet_part(z: zipfile.ZipFile, name: str | None) -> str:
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets = {r.get("Id"): r.get("Target", "") for r in rels}

    sheets = wb.findall("m:sheets/m:sheet", NS)
    if not sheets:
        raise XlsxError("시트를 찾지 못했습니다.")

    chosen = None
    if name is None:
        chosen = sheets[0]
    else:
        for s in sheets:
            if s.get("name") == name:
                chosen = s
                break
        if chosen is None:
            names = ", ".join(s.get("name", "") for s in sheets)
            raise XlsxError(f"'{name}' 시트가 없습니다. 있는 시트: {names}")

    rid = chosen.get(f"{{{NS['r']}}}id")
    target = targets.get(rid, "worksheets/sheet1.xml")
    return target[1:] if target.startswith("/") else f"xl/{target.lstrip('/')}"


def read_sheet(path: Path, sheet: str | None = None) -> list[list]:
    """시트를 값의 2차원 리스트로 읽는다. 빈 칸은 None."""
    with _open(path) as z:
        strings = _shared_strings(z)
        date_flags = _date_style_flags(z)
        part = _sheet_part(z, sheet)

        rows: list[list] = []
        width = 0
        # zip 안의 멤버도 반드시 닫는다. 안 닫으면 ResourceWarning 이 뜬다.
        with z.open(part) as stream:
            for _, el in ET.iterparse(stream, events=("end",)):
                if el.tag != f"{{{NS['m']}}}row":
                    continue
                values: dict[int, object] = {}
                # 칸 주소(r)를 안 적는 파일이 있다. 그때는 나온 차례가 곧
                # 열 자리다 - 주소가 없다고 A 열로 몰면 앞 칸이 사라진다.
                at = 0
                for c in el.findall("m:c", NS):
                    ref = c.get("r")
                    idx = col_to_index(ref) if ref else at
                    at = idx + 1
                    value = _cell_value(c, strings, date_flags)
                    if value is not None:
                        values[idx] = value
                el.clear()

                if not values:
                    rows.append([])
                    continue
                top = max(values) + 1
                width = max(width, top)
                rows.append([values.get(i) for i in range(top)])

        return [r + [None] * (width - len(r)) for r in rows]


def split_ref(ref: str) -> tuple[int, int]:
    """'B3' -> (3, 1). 행은 엑셀에서 보이는 번호(1부터), 열은 0부터."""
    text = ref.strip().replace("$", "").upper()
    letters = "".join(c for c in text if c.isalpha())
    digits = "".join(c for c in text if c.isdigit())
    if not letters or not digits or letters + digits != text:
        raise XlsxError(f"칸 주소가 아닙니다: {ref} (예: B3)")
    return int(digits), col_to_index(letters)


def read_cells(path: Path, refs: list[str], sheet: str | None = None) -> dict[str, object]:
    """지정한 칸만 읽는다. 없는 칸은 None 이다.

    read_sheet 는 행을 나온 차례대로 쌓으므로, 가운데 행이 통째로 빠진 파일에서는
    «몇 행» 이 어긋난다. 양식 파일에서 B3 을 집어 오려면 행 번호 자체를 봐야 한다.
    """
    wanted: dict[tuple[int, int], list[str]] = {}
    for ref in refs:
        wanted.setdefault(split_ref(ref), []).append(ref.strip().upper())
    found: dict[str, object] = {name: None for names in wanted.values() for name in names}
    if not wanted:
        return found
    rows_wanted = {row for row, _col in wanted}

    with _open(path) as z:
        strings = _shared_strings(z)
        date_flags = _date_style_flags(z)
        part = _sheet_part(z, sheet)
        line = 0
        with z.open(part) as stream:
            for _, el in ET.iterparse(stream, events=("end",)):
                if el.tag != f"{{{NS['m']}}}row":
                    continue
                mark = el.get("r")
                line = int(mark) if mark and mark.isdigit() else line + 1
                if line not in rows_wanted:
                    el.clear()
                    continue
                column = -1
                for c in el.findall("m:c", NS):
                    ref = c.get("r")
                    column = col_to_index(ref) if ref else column + 1
                    names = wanted.get((line, column))
                    if names:
                        value = _cell_value(c, strings, date_flags)
                        for name in names:
                            found[name] = value
                el.clear()
    return found


def _cell_value(c: ET.Element, strings: list[str], date_flags: list[bool]):
    kind = c.get("t", "n")
    if kind == "inlineStr":
        return _text(c.find("m:is", NS)) or None

    raw = c.find("m:v", NS)
    text = raw.text if raw is not None else None
    if text is None:
        # 계산 결과가 저장돼 있지 않은 수식 셀은 수식 자체를 돌려준다
        formula = c.find("m:f", NS)
        return f"={_text(formula)}" if formula is not None else None

    if kind == "s":
        try:
            return strings[int(text)]
        except (ValueError, IndexError):
            return text
    if kind in ("str", "e"):
        return text
    if kind == "b":
        return text == "1"

    try:
        number = float(text)
    except ValueError:
        return text

    try:
        style = int(c.get("s", "0"))
    except ValueError:
        style = 0
    if style < len(date_flags) and date_flags[style]:
        dt = serial_to_datetime(number)
        if dt.time() == time(0, 0) and number >= 1:
            return dt.date()
        return dt

    return int(number) if number.is_integer() and abs(number) < 2**53 else number


# ------------------------------------------------------------------ 쓰기

def _esc(text: str) -> str:
    text = ILLEGAL.sub("", text)
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
{sheets}
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="2"><numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd"/>
<numFmt numFmtId="165" formatCode="yyyy\\-mm\\-dd\\ hh:mm:ss"/></numFmts>
<fonts count="2"><font><sz val="11"/><name val="맑은 고딕"/></font>
<font><b/><sz val="11"/><name val="맑은 고딕"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFEFEFEF"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="4">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""

STYLE_PLAIN, STYLE_HEADER, STYLE_DATE, STYLE_DATETIME = 0, 1, 2, 3


@dataclass(frozen=True)
class Formula:
    """셀에 넣을 엑셀 수식. body 에는 «=» 를 빼고 담는다.

    지금 계산한 값(cached)도 함께 넣는다. 그 값이 없으면 엑셀이 파일을 열어
    다시 계산하기 전까지 빈 칸으로 보이고, 우리 리더도 빈 칸으로 읽는다.
    값을 고치면 엑셀이 그때 다시 계산하므로 낡은 값이 남지는 않는다.
    """
    body: str
    cached: object = None

    def __str__(self) -> str:
        return "=" + self.body


def _cell_xml(ref: str, value, style: int) -> str:
    if isinstance(value, Formula):
        body = f'<c r="{ref}" s="{style}"><f>{_esc(value.body)}</f>'
        if isinstance(value.cached, bool):
            return body + f"<v>{int(value.cached)}</v></c>"
        if isinstance(value.cached, (int, float)):
            return body + f"<v>{value.cached!r}</v></c>"
        if value.cached is not None and value.cached != "":
            return (f'<c r="{ref}" s="{style}" t="str"><f>{_esc(value.body)}</f>'
                    f"<v>{_esc(str(value.cached))}</v></c>")
        return body + "</c>"

    if value is None or value == "":
        return f'<c r="{ref}" s="{style}"/>' if style else ""
    if isinstance(value, bool):
        return f'<c r="{ref}" s="{style}" t="b"><v>{int(value)}</v></c>'
    if isinstance(value, datetime):
        serial = (value - EPOCH).total_seconds() / 86400
        return f'<c r="{ref}" s="{STYLE_DATETIME}"><v>{serial:.10f}</v></c>'
    if isinstance(value, date):
        serial = (datetime(value.year, value.month, value.day) - EPOCH).days
        return f'<c r="{ref}" s="{STYLE_DATE}"><v>{serial}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}" s="{style}"><v>{value!r}</v></c>'
    return (f'<c r="{ref}" s="{style}" t="inlineStr">'
            f"<is><t xml:space=\"preserve\">{_esc(str(value))}</t></is></c>")


def _sheet_xml(rows: list[list], *, header: bool, freeze: bool) -> str:
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']

    widths = _column_widths(rows)
    if widths:
        parts.append("<cols>" + "".join(
            f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
            for i, w in enumerate(widths)) + "</cols>")

    parts.append("<sheetData>")
    for r, row in enumerate(rows, 1):
        style = STYLE_HEADER if (header and r == 1) else STYLE_PLAIN
        cells = "".join(_cell_xml(f"{index_to_col(c)}{r}", v, style)
                        for c, v in enumerate(row))
        parts.append(f'<row r="{r}">{cells}</row>')
    parts.append("</sheetData>")

    if header and freeze and rows:
        # sheetView 는 sheetData 앞에 와야 해서 나중에 끼워 넣는다
        pane = ('<sheetViews><sheetView workbookViewId="0">'
                '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
                "</sheetView></sheetViews>")
        parts.insert(2, pane)
        parts.append(f'<autoFilter ref="A1:{index_to_col(max(len(r) for r in rows) - 1)}'
                     f'{len(rows)}"/>')

    parts.append("</worksheet>")
    return "".join(parts)


def _column_widths(rows: list[list], *, limit: int = 60) -> list[int]:
    if not rows:
        return []
    width = max(len(r) for r in rows)
    out = []
    for c in range(width):
        longest = 4
        for row in rows[:200]:  # 앞부분만 봐도 충분하다
            if c < len(row) and row[c] is not None:
                # 한글은 두 칸으로 잡는다
                text = str(row[c])
                longest = max(longest, sum(2 if ord(ch) > 0x1100 else 1 for ch in text))
        out.append(min(longest + 2, limit))
    return out


def write_sheets(path: Path, sheets: dict[str, list[list]], *,
                 header: bool = True, freeze: bool = True) -> Path:
    """{시트이름: 행들} 을 xlsx 로 저장한다."""
    path = Path(path)          # 글자로 준 경로도 받는다
    if not sheets:
        raise XlsxError("저장할 시트가 없습니다.")

    names = list(sheets)
    overrides = "\n".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, len(names) + 1))

    wb_sheets = "".join(
        f'<sheet name="{_esc(safe_sheet_name(n))}" sheetId="{i}" r:id="rId{i}"/>'
        for i, n in enumerate(names, 1))
    workbook = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<workbook xmlns="{NS["m"]}" xmlns:r="{NS["r"]}">'
                f"<sheets>{wb_sheets}</sheets></workbook>")

    rels = "".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/'
        f'officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(names) + 1))
    rels += (f'<Relationship Id="rId{len(names) + 1}" Type="http://schemas.openxmlformats.org/'
             f'officeDocument/2006/relationships/styles" Target="styles.xml"/>')
    wb_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               f"{rels}</Relationships>")

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES.format(sheets=overrides))
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/styles.xml", STYLES)
        for i, name in enumerate(names, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml",
                       _sheet_xml(sheets[name], header=header, freeze=freeze))
    return path
