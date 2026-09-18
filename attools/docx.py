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

from . import slots
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


# XML 1.0 이 담지 못하는 제어 문자. 그대로 넣으면 워드가 «파일이 손상됐다» 며
# 열지 못하고, 우리 리더도 못 읽는다. PDF·로그에서 옮겨 온 글에 섞여 온다.
ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _xml_text(text: str) -> str:
    return escape(ILLEGAL.sub("", str(text)))


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
           + f'<w:t xml:space="preserve">{_xml_text(text)}</w:t></w:r>')
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
    """표의 칸 글자. 칸 안이 내용 컨트롤이나 표로 한 겹 더 싸여 있어도 읽는다.

    가로로 병합한 칸(gridSpan)은 그 수만큼 자리를 채운다. 한 칸으로 세면
    병합한 머리글이 있는 표에서 열이 밀려, 뒤 열의 값이 통째로 사라진다.
    """
    rows = []
    for tr in table.findall(f"{W}tr"):
        cells = []
        for tc in tr.findall(f"{W}tc"):
            parts = [_run_text(p).strip() for p in tc.iter(f"{W}p")]
            cells.append(" ".join(x for x in parts if x))
            span = tc.find(f"{W}tcPr/{W}gridSpan")
            width = span.get(f"{W}val") if span is not None else None
            if (width or "").isdigit():
                cells += [""] * (int(width) - 1)
        rows.append(cells)
    return rows


def _blocks(node: ET.Element):
    """문단과 표를 문서 차례대로 넘긴다.

    내용 컨트롤(w:sdt)이나 수정 표시로 한 겹 싸인 문단이 흔하다. 바로 아래
    자식만 보면 그런 문단이 통째로 빠지는데, 문서는 «옮겨졌다» 고 나온다.
    """
    for child in node:
        if child.tag in (f"{W}p", f"{W}tbl"):
            yield child
            continue
        if child.tag in (f"{W}sectPr", f"{W}bookmarkStart", f"{W}bookmarkEnd"):
            continue
        yield from _blocks(child)


def read_document(path: Path) -> list[tuple[str, object]]:
    """문서를 ('제목1'|'문단'|'목록'|'표', 내용) 조각으로 읽는다.

    내용은 표만 list[list[str]] 이고 나머지는 글자다.
    """
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "word/document.xml" not in names:
                # 암호 건 워드도 zip 은 zip 인데 알맹이가 EncryptedPackage 뿐이다.
                # «워드 문서가 아니다» 로 알리면 엉뚱한 데를 고치게 된다
                if any(n.startswith("EncryptedPackage") for n in names):
                    raise DocxError("암호가 걸린 워드 문서입니다. 워드에서 암호를 "
                                    "풀고 저장한 뒤에 다시 해 보세요.")
                # 같은 zip 이라도 알맹이를 보면 무엇인지 알 수 있다. 이름을
                # 알려 주는 편이 «워드가 아니다» 보다 쓸모 있다
                for mark, tell in (
                        ("ppt/", "슬라이드(pptx)입니다. 글은 at doc from-pptx, "
                                 "표는 at sheet from-pptx 로 여세요."),
                        ("xl/", "엑셀 파일입니다. at sheet peek 로 여세요."),
                        ("Contents/section", "한글 문서(hwpx)입니다. 글은 "
                                             "at doc from-hwpx, 표는 "
                                             "at sheet from-hwpx 로 여세요.")):
                    if any(n.startswith(mark) for n in names):
                        raise DocxError(tell)
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
    for node in _blocks(body):
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


# ------------------------------------------- 양식 문서에 값 채우기 (메일 머지)

# 위촉장·수료증·공문처럼 서식이 든 워드 양식에 값만 갈아 끼운다. 새로 만들어
# 담으면 글꼴·표·머리글·도장 그림이 다 날아가므로, 원본 zip 을 통째로 베끼고
# 글자가 든 xml 조각만 고친다.
# 글자가 들어 있는 조각. 머리글·바닥글에 문서번호·기관명이 든 양식이 흔하다
FILL_PARTS = re.compile(r"^word/(document|header\d*|footer\d*)\.xml$")
FillReport = slots.FillReport


def placeholders(path: Path) -> list[str]:
    """양식에 든 «{이름}» 자리 목록. 나온 차례대로, 겹치는 것은 한 번만."""
    path = Path(path)
    out: list[str] = []
    try:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if FILL_PARTS.match(n)]
            if not names:
                raise DocxError(f"워드 문서가 아닙니다: {path.name}")
            for name in sorted(names):
                for one in slots.slots_in_part(z.read(name)):
                    if one not in out:
                        out.append(one)
    except zipfile.BadZipFile:
        raise DocxError(f"워드 문서가 아닙니다 (zip 이 아닙니다): {path.name}") from None
    except OSError as exc:
        raise DocxError(f"열지 못했습니다: {exc}") from None
    return out


def fill_document(source: Path, dest: Path, values: dict) -> slots.FillReport:
    """양식의 «{이름}» 을 채워 새 파일로. 원본은 건드리지 않는다.

    값을 모르는 자리는 «{이름}» 그대로 둔다 - 빈 칸으로 만들면 백 장을 만든
    뒤에야 무엇이 빠졌는지 알게 된다. 모른 이름은 보고에 담아 돌려준다.
    """
    source = Path(source)
    try:
        with zipfile.ZipFile(source) as z:
            if "word/document.xml" not in z.namelist():
                raise DocxError(f"워드 문서가 아닙니다: {source.name}")
    except zipfile.BadZipFile:
        raise DocxError(f"워드 문서가 아닙니다 (zip 이 아닙니다): {source.name}") from None
    except OSError as exc:
        raise DocxError(f"열지 못했습니다: {exc}") from None
    return slots.fill_zip(source, dest, values,
                          parts=lambda name: bool(FILL_PARTS.match(name)),
                          error=DocxError)
