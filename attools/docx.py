"""의존성 없는 docx 리더·라이터. 워드 문서는 xml 몇 장을 담은 zip 이다.

쓸 때는 스타일 파일(styles.xml)을 참조하지 않고 문단마다 서식을 직접 적어
넣는다. 뷰어마다 스타일 해석이 달라 열리지 않는 곳이 생기는 것을 피하려는
것이다.

읽을 때는 문단·제목·표만 가져온다. 그림·머리글·바닥글·각주·메모는 가져오지
않는다 - 가져온 척하면 «옮겼는데 내용이 빠졌다» 를 나중에 알게 된다.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from html import escape
from pathlib import Path

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
FONT = "맑은 고딕"
MONO = "D2Coding"
# A4 세로, 위아래 2.5cm 좌우 2cm 쯤
SECTION = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
           '<w:pgMar w:top="1417" w:right="1134" w:bottom="1417" w:left="1134"/>'
           "</w:sectPr>")


def paragraph(text: str = "", *, size: int = 20, bold: bool = False,
              italic: bool = False, center: bool = False, indent: int = 0,
              first_line: bool = False, mono: bool = False,
              page_break: bool = False, spacing: int = 360) -> str:
    """문단 하나. size 는 하프포인트(20 이면 10pt), indent 는 트윕."""
    marks = []
    if center:
        marks.append('<w:jc w:val="center"/>')
    if indent:
        marks.append(f'<w:ind w:left="{indent}"/>')
    if first_line:
        marks.append('<w:ind w:firstLine="200"/>')
    marks.append(f'<w:spacing w:line="{spacing}" w:lineRule="auto"/>')
    properties = f"<w:pPr>{''.join(marks)}</w:pPr>"

    font = MONO if mono else FONT
    run_marks = (f'<w:rFonts w:eastAsia="{font}" w:ascii="{font}"/>'
                 f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
                 + ("<w:b/>" if bold else "") + ("<w:i/>" if italic else ""))
    run = (f"<w:r><w:rPr>{run_marks}</w:rPr>"
           + ('<w:br w:type="page"/>' if page_break else "")
           + f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r>')
    return f"<w:p>{properties}{run}</w:p>"


def table(rows: list[list[str]], *, header: bool = True) -> str:
    """간단한 표. 칸 수는 가장 넓은 줄에 맞춘다."""
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    borders = ("<w:tblBorders>" + "".join(
        f'<w:{side} w:val="single" w:sz="4" w:color="BBBBBB"/>'
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
        + "</w:tblBorders>")
    out = [f'<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/>{borders}</w:tblPr>']
    for number, row in enumerate(rows):
        cells = (list(row) + [""] * width)[:width]
        out.append("<w:tr>")
        for cell in cells:
            body = paragraph(cell, bold=header and number == 0, spacing=240)
            out.append(f"<w:tc><w:tcPr/>{body}</w:tc>")
        out.append("</w:tr>")
    out.append("</w:tbl>")
    # 표 뒤에 빈 문단이 없으면 워드가 다음 내용을 표에 붙여 그린다
    out.append(paragraph(""))
    return "".join(out)


def write_document(path: Path, parts: list[str]) -> Path:
    """문단·표 조각들을 한 문서로 저장한다."""
    body = "".join(parts) or paragraph("")
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                f"<w:document {NS}><w:body>{body}{SECTION}</w:body></w:document>")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("word/document.xml", document)
    return path


# ------------------------------------------------------------------- 읽기

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
HEADING = re.compile(r"(?:heading|제목)\s*([1-6])", re.IGNORECASE)


class DocxError(Exception):
    pass


def _run_text(node: ET.Element) -> str:
    """한 문단 안의 글자. 줄바꿈과 탭도 살린다."""
    out = []
    for el in node.iter():
        if el.tag == f"{W}t":
            out.append(el.text or "")
        elif el.tag in (f"{W}br", f"{W}cr"):
            out.append("\n")
        elif el.tag == f"{W}tab":
            out.append("\t")
    return "".join(out)


def _style_of(paragraph: ET.Element) -> str:
    style = paragraph.find(f"{W}pPr/{W}pStyle")
    return (style.get(f"{W}val") or "") if style is not None else ""


def _is_list(paragraph: ET.Element) -> bool:
    return paragraph.find(f"{W}pPr/{W}numPr") is not None


def _table_rows(table: ET.Element) -> list[list[str]]:
    rows = []
    for tr in table.findall(f"{W}tr"):
        cells = []
        for tc in tr.findall(f"{W}tc"):
            parts = [_run_text(p).strip() for p in tc.findall(f"{W}p")]
            cells.append(" ".join(x for x in parts if x))
        rows.append(cells)
    return rows


def read_document(path: Path) -> list[tuple[str, object]]:
    """문서를 ('제목1'|'문단'|'목록'|'표', 내용) 조각으로 읽는다.

    내용은 표만 list[list[str]] 이고 나머지는 글자다.
    """
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as z:
            if "word/document.xml" not in z.namelist():
                raise DocxError("워드 문서가 아닙니다 (word/document.xml 이 없습니다). "
                                "구버전 .doc 은 읽지 못합니다.")
            with z.open("word/document.xml") as stream:
                tree = ET.parse(stream)
    except zipfile.BadZipFile:
        raise DocxError("워드 문서가 아닙니다 (zip 이 아닙니다). "
                        "구버전 .doc 은 읽지 못합니다.") from None
    except OSError as exc:
        raise DocxError(str(exc)) from None

    body = tree.getroot().find(f"{W}body")
    if body is None:
        return []

    parts: list[tuple[str, object]] = []
    for node in body:
        if node.tag == f"{W}p":
            text = _run_text(node).strip()
            if not text:
                continue
            level = HEADING.search(_style_of(node))
            if level:
                parts.append((f"제목{level.group(1)}", text))
            elif _is_list(node):
                parts.append(("목록", text))
            else:
                parts.append(("문단", text))
        elif node.tag == f"{W}tbl":
            rows = _table_rows(node)
            if rows:
                parts.append(("표", rows))
    return parts


def to_markdown(parts: list[tuple[str, object]]) -> str:
    """읽은 조각을 마크다운으로. 표는 마크다운 표로 옮긴다."""
    lines: list[str] = []
    for kind, body in parts:
        if kind.startswith("제목"):
            lines += ["#" * int(kind[-1]) + " " + str(body), ""]
        elif kind == "목록":
            lines.append("- " + str(body))
        elif kind == "표":
            rows = [[str(c).replace("|", "\\|").replace("\n", " ") for c in row]
                    for row in body]      # type: ignore[union-attr]
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            lines.append("| " + " | ".join(rows[0]) + " |")
            lines.append("|" + "|".join([" --- "] * width) + "|")
            for row in rows[1:]:
                lines.append("| " + " | ".join(row) + " |")
            lines.append("")
        else:
            lines += [str(body).replace("\n", "  \n"), ""]
    return "\n".join(lines).strip() + "\n"


def read_text(path: Path, *, separator: str = "\n") -> str:
    """문서의 글자만. 찾기·세기용이다.

    기본은 한 줄에 한 문단이다 - 찾기에서 «몇 번째 문단» 을 줄 번호로 쓴다.
    문단 단위로 견주려면 separator 를 빈 줄로 준다.
    """
    out = []
    for kind, body in read_document(path):
        if kind == "표":
            out += [" ".join(str(c) for c in row) for row in body]  # type: ignore[union-attr]
        else:
            out.append(str(body))
    return separator.join(out)
