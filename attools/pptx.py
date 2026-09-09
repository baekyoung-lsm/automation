"""의존성 없는 pptx(슬라이드) 리더. 슬라이드의 글자와 표만 꺼낸다.

pptx 도 xml 을 담은 zip 이라 표준 라이브러리만으로 읽을 수 있다. 그림·도형
모양·애니메이션·발표자 노트는 가져오지 않는다 - 가져온 척하면 «옮겼는데
빠졌다» 를 나중에 알게 된다(노트는 notes=True 로 따로 받는다).

슬라이드 차례는 파일 이름(slide1, slide2 …)이 아니라 발표 문서가 적어 둔
차례(p:sldIdLst)를 따른다. 이름 순으로 세면 슬라이드를 옮겨 붙인 파일에서
차례가 뒤바뀐다.

이름 공간 접두사는 붙잡지 않고 태그의 뒷이름만 본다 - 판마다 다르다.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

SLIDE_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$", re.IGNORECASE)
NOTES_RE = re.compile(r"^ppt/notesSlides/notesSlide(\d+)\.xml$", re.IGNORECASE)
RELS = "ppt/_rels/presentation.xml.rels"


class PptxError(Exception):
    pass


@dataclass
class Slide:
    number: int                      # 보이는 차례 (1부터)
    source: str = ""                 # 파일 안의 이름 (slide3.xml)
    blocks: list = field(default_factory=list)   # ('문단'|'표', 내용)
    notes: str = ""

    @property
    def title(self) -> str:
        """첫 문단을 제목으로 본다. 없으면 빈 글자."""
        for kind, body in self.blocks:
            if kind == "문단" and str(body).strip():
                return str(body).strip()
        return ""

    @property
    def text(self) -> str:
        out = []
        for kind, body in self.blocks:
            if kind == "표":
                out += ["\t".join(row) for row in body]
            else:
                out.append(str(body))
        return "\n".join(out)


def _tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1] if isinstance(node.tag, str) else ""


def _open(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise PptxError("슬라이드 문서(pptx)가 아닙니다 (zip 이 아닙니다). "
                        "옛 .ppt 는 읽지 못합니다 - 파워포인트에서 pptx 로 "
                        "저장하세요.") from None
    except OSError as exc:
        raise PptxError(str(exc)) from None


def slide_order(z: zipfile.ZipFile) -> list[str]:
    """발표 문서가 적어 둔 차례대로 슬라이드 부품 이름을 돌려준다."""
    names = [n for n in z.namelist() if SLIDE_RE.match(n)]
    by_number = sorted(names, key=lambda n: int(SLIDE_RE.match(n).group(1)))
    try:
        rels = ET.fromstring(z.read(RELS))
        deck = ET.fromstring(z.read("ppt/presentation.xml"))
    except (KeyError, ET.ParseError, OSError):
        return by_number

    target = {}
    for node in rels:
        rid = node.get("Id")
        path = (node.get("Target") or "").lstrip("/")
        if rid and path:
            target[rid] = path if path.startswith("ppt/") else f"ppt/{path}"
    ordered: list[str] = []
    for node in deck.iter():
        if _tag(node) != "sldId":
            continue
        for key, value in node.attrib.items():
            # 슬라이드 번호(id)가 아니라 관계 번호(r:id)를 본다. 뒷이름이 둘 다
            # «id» 라서 이름 공간이 붙었는지로 가른다
            if "}" not in key:
                continue
            found = target.get(value)
            if found in names and found not in ordered:
                ordered.append(found)
    # 차례에 없는 슬라이드는 뒤에 붙인다 - 빼먹느니 뒤에 두는 편이 낫다
    ordered += [n for n in by_number if n not in ordered]
    return ordered or by_number


def _paragraph_text(node: ET.Element) -> str:
    """한 문단(a:p)의 글자. 줄바꿈(a:br)도 살린다."""
    out: list[str] = []
    for child in node.iter():
        name = _tag(child)
        if name == "t":
            out.append("".join(child.itertext()))
        elif name == "br":
            out.append("\n")
    return "".join(out).strip()


def _table_rows(node: ET.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in node.iter():
        if _tag(tr) != "tr":
            continue
        cells: list[str] = []
        for tc in tr:
            if _tag(tc) != "tc":
                continue
            pieces = [_paragraph_text(p) for p in tc.iter() if _tag(p) == "p"]
            cells.append(" ".join(piece for piece in pieces if piece))
        if cells:
            rows.append(cells)
    return rows


def _walk(node: ET.Element, blocks: list) -> None:
    """도형을 차례대로 훑는다. 표를 만나면 표로 담고 안으로 더 들어가지 않는다."""
    for child in node:
        name = _tag(child)
        if name == "tbl":
            rows = _table_rows(child)
            if rows:
                blocks.append(("표", rows))
            continue
        if name == "p":
            text = _paragraph_text(child)
            if text:
                blocks.append(("문단", text))
            continue
        _walk(child, blocks)


def read_slides(path: Path, *, notes: bool = False) -> list[Slide]:
    """슬라이드마다 문단과 표를 읽는다."""
    path = Path(path)
    out: list[Slide] = []
    with _open(path) as z:
        order = slide_order(z)
        if not order:
            if any(n.startswith("EncryptedPackage") for n in z.namelist()):
                raise PptxError("암호가 걸린 슬라이드 문서입니다. 파워포인트에서 "
                                "암호를 풀고 저장한 뒤에 다시 해 보세요.")
            raise PptxError("슬라이드를 찾지 못했습니다 (ppt/slides/ 가 "
                            "비었습니다). pptx 가 맞는지 확인하세요.")
        notes_by_number = _notes(z) if notes else {}
        for number, name in enumerate(order, 1):
            try:
                root = ET.fromstring(z.read(name))
            except (ET.ParseError, KeyError, OSError) as exc:
                raise PptxError(f"{name} 을 읽지 못했습니다: {exc}") from None
            slide = Slide(number=number, source=name.rsplit("/", 1)[-1])
            _walk(root, slide.blocks)
            match = SLIDE_RE.match(name)
            slide.notes = notes_by_number.get(int(match.group(1)), "") if match else ""
            out.append(slide)
    return out


def _notes(z: zipfile.ZipFile) -> dict[int, str]:
    """발표자 노트. 슬라이드 번호로 묶어 둔다."""
    found: dict[int, str] = {}
    for name in z.namelist():
        match = NOTES_RE.match(name)
        if not match:
            continue
        try:
            root = ET.fromstring(z.read(name))
        except (ET.ParseError, OSError):
            continue
        blocks: list = []
        _walk(root, blocks)
        text = "\n".join(str(body) for kind, body in blocks if kind == "문단")
        if text.strip():
            found[int(match.group(1))] = text.strip()
    return found


def slide_count(path: Path) -> int:
    """슬라이드 장 수. 못 읽으면 0."""
    try:
        with _open(path) as z:
            return len([n for n in z.namelist() if SLIDE_RE.match(n)])
    except PptxError:
        return 0


def read_text(path: Path, *, separator: str = "\n", notes: bool = False) -> str:
    """글자만 이어 붙인다. 표는 칸을 탭으로 나눈다."""
    lines: list[str] = []
    for slide in read_slides(path, notes=notes):
        lines.append(slide.text)
        if notes and slide.notes:
            lines.append(slide.notes)
    return separator.join(line for line in lines if line)


def to_markdown(slides: list[Slide], *, notes: bool = False) -> str:
    """슬라이드를 마크다운으로. 첫 문단을 제목으로 올린다."""
    out: list[str] = []
    for slide in slides:
        head = slide.title or f"슬라이드 {slide.number}"
        out.append(f"## {slide.number}. {head}")
        out.append("")
        first = True
        for kind, body in slide.blocks:
            if kind == "표":
                rows = [[str(c).replace("|", "\\|") for c in row] for row in body]
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                out.append("| " + " | ".join(rows[0]) + " |")
                out.append("| " + " | ".join(["---"] * width) + " |")
                out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                out.append("")
                continue
            if first and str(body).strip() == head:
                first = False          # 제목으로 올린 문단은 다시 적지 않는다
                continue
            first = False
            out.append(str(body).replace("\n", "  \n"))
            out.append("")
        if notes and slide.notes:
            out.append("> 발표자 노트: " + slide.notes.replace("\n", " "))
            out.append("")
    return "\n".join(out).strip() + "\n"
