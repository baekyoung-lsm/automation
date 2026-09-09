"""의존성 없는 hwpx(한글) 리더. 문단과 표만 꺼낸다.

한글 2010 이후의 `.hwpx` 는 zip 안에 XML(OWPML)이 들어 있는 형식이라 표준
라이브러리만으로 읽을 수 있다. 옛 `.hwp`(이진 형식)는 읽지 못한다 - 한글에서
«hwpx 로 저장» 을 한 번 거쳐야 한다.

이름 공간 접두사(hp:, hs: …)는 판마다 달라서 붙잡지 않고 **태그의 뒷이름**만
본다. 접두사를 굳혀 두면 다음 판에서 조용히 아무것도 못 읽게 된다.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

SECTION_RE = re.compile(r"^Contents/section\d+\.xml$", re.IGNORECASE)
MIMETYPE = "application/hwp+zip"


class HwpxError(Exception):
    pass


def _tag(node: ET.Element) -> str:
    """이름 공간을 뗀 태그 이름."""
    return node.tag.rsplit("}", 1)[-1] if isinstance(node.tag, str) else ""


def _sections(z: zipfile.ZipFile) -> list[str]:
    """본문 조각들. section0, section1 … 순서를 지킨다."""
    names = [n for n in z.namelist() if SECTION_RE.match(n)]
    return sorted(names, key=lambda n: int(re.search(r"(\d+)", n).group(1)))


def _text_of(node: ET.Element) -> str:
    """이 조각 안의 글자를 모은다. <t> 안의 글자와 줄바꿈·탭만 센다.

    한 문단 안에서 줄을 바꾼 자리(<lineBreak/>)를 버리면 두 줄이 한 줄로
    붙는다. 원고나 주소처럼 줄이 뜻을 가지는 글에서 조용히 달라진다.
    """
    out: list[str] = []
    for child in node.iter():
        tag = _tag(child)
        if tag == "t":
            out.append("".join(child.itertext()))
        elif tag == "lineBreak":
            out.append("\n")
        elif tag == "tab":
            out.append("\t")
    return "".join(out).strip()


def _cell_text(cell: ET.Element) -> str:
    """칸 안의 문단이 여럿이면 줄바꿈 없이 이어 붙인다 (표는 한 칸이 한 값)."""
    pieces = [_text_of(p) for p in cell.iter() if _tag(p) == "p"]
    joined = " ".join(piece for piece in pieces if piece)
    return joined or _text_of(cell)


def _table_rows(table: ET.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table.iter():
        if _tag(tr) != "tr":
            continue
        cells = [_cell_text(tc) for tc in tr if _tag(tc) == "tc"]
        if cells:
            rows.append(cells)
    return rows


def _open(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise HwpxError("한글 문서(hwpx)가 아닙니다 (zip 이 아닙니다). "
                        "옛 .hwp 는 읽지 못합니다 - 한글에서 hwpx 로 "
                        "저장하세요.") from None
    except OSError as exc:
        raise HwpxError(str(exc)) from None


def _walk(node: ET.Element, parts: list) -> None:
    """문서 차례대로 훑는다. 표를 만나면 표로 담고 그 안으로 더 들어가지 않는다.

    iter() 로 훑으면 표 안의 문단이 표와 따로 한 번 더 나온다 - 옮긴 문서에
    같은 글이 두 번 들어간다.
    """
    for child in node:
        name = _tag(child)
        if name == "tbl":
            rows = _table_rows(child)
            if rows:
                parts.append(("표", rows))
            continue
        if name == "p":
            if any(_tag(a) == "tbl" for a in child.iter()):
                _walk_around_tables(child, parts)
                continue
            text = _text_of(child)
            if text:
                parts.append(("문단", text))
            continue
        _walk(child, parts)


def _walk_around_tables(node: ET.Element, parts: list) -> None:
    """표를 품은 문단. 표 앞뒤에 붙은 글자도 잃지 않게 차례대로 본다."""
    buffer: list[str] = []

    def flush() -> None:
        text = "".join(buffer).strip()
        buffer.clear()
        if text:
            parts.append(("문단", text))

    def walk(inner: ET.Element) -> None:
        for child in inner:
            name = _tag(child)
            if name == "tbl":
                flush()
                rows = _table_rows(child)
                if rows:
                    parts.append(("표", rows))
                continue
            if name == "t":
                buffer.append("".join(child.itertext()))
                continue
            if name == "lineBreak":
                buffer.append("\n")
                continue
            if name == "tab":
                buffer.append("\t")
                continue
            walk(child)

    walk(node)
    flush()


def read_document(path: Path) -> list[tuple[str, object]]:
    """문서를 ('문단'|'표', 내용) 조각으로 읽는다.

    내용은 표만 list[list[str]] 이고 나머지는 글자다. 한글은 제목을 문단
    모양으로만 구분하는 일이 많아 제목 단계를 짐작하지 않는다 - 잘못
    짐작한 제목은 목차를 통째로 어긋나게 한다.
    """
    path = Path(path)
    parts: list[tuple[str, object]] = []
    with _open(path) as z:
        sections = _sections(z)
        if not sections:
            raise HwpxError("본문을 찾지 못했습니다 (Contents/section0.xml 이 "
                            "없습니다). 한글 문서(hwpx)가 맞는지 확인하세요.")
        for name in sections:
            try:
                with z.open(name) as stream:
                    root = ET.parse(stream).getroot()
            except ET.ParseError as exc:
                raise HwpxError(f"{name} 을 읽지 못했습니다: {exc}") from None

            _walk(root, parts)
    return parts


def read_text(path: Path, *, separator: str = "\n") -> str:
    """글자만 이어 붙인다. 표는 칸을 탭으로 나눈다."""
    lines: list[str] = []
    for kind, body in read_document(path):
        if kind == "표":
            lines += ["\t".join(row) for row in body]
        else:
            lines.append(str(body))
    return separator.join(lines)


def tables(path: Path) -> list[list[list[str]]]:
    """표만 모은다."""
    return [body for kind, body in read_document(path) if kind == "표"]


def to_markdown(parts: list[tuple[str, object]]) -> str:
    """읽은 조각을 마크다운으로. 표는 마크다운 표로 낸다."""
    out: list[str] = []
    for kind, body in parts:
        if kind == "표":
            rows = [[str(c).replace("|", "\\|") for c in row] for row in body]
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            out.append("| " + " | ".join(rows[0]) + " |")
            out.append("| " + " | ".join(["---"] * width) + " |")
            out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
            out.append("")
        else:
            out.append(str(body))
            out.append("")
    return "\n".join(out).strip() + "\n"
