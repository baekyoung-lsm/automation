"""의존성 없이 xlsx 를 읽고 쓴다.

xlsx 는 XML 을 담은 zip 이라 표준 라이브러리만으로 다룰 수 있다.
서식·수식·차트까지 필요하면 openpyxl 을 쓰는 게 맞고, 여기서는 값만 오간다.
"""

from __future__ import annotations

import re
import zipfile
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


def sheet_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
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
    with zipfile.ZipFile(path) as z:
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
                for c in el.findall("m:c", NS):
                    idx = col_to_index(c.get("r", "A1"))
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


def _cell_xml(ref: str, value, style: int) -> str:
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
