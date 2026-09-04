"""의존성 없는 docx 라이터. 워드 문서는 xml 몇 장을 담은 zip 이다.

스타일 파일(styles.xml)을 참조하지 않고 문단마다 서식을 직접 적어 넣는다.
뷰어마다 스타일 해석이 달라 열리지 않는 곳이 생기는 것을 피하려는 것이다.
"""

from __future__ import annotations

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
