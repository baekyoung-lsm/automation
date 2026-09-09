"""HTML 을 마크다운으로. 웹 문서를 저장소로 옮길 때 쓴다.

전부를 옮기지 않는다. 지원하는 태그만 옮기고 나머지는 글자만 남긴다.
표준 라이브러리 html.parser 로 읽으므로 깨진 HTML 도 대충 넘어간다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

SKIP_TAGS = {"script", "style", "head", "meta", "link", "noscript", "svg"}
BLOCK_TAGS = {"p", "div", "section", "article", "header", "footer", "main",
              "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "table",
              "tr", "blockquote", "pre", "hr"}
SUPPORTED = ("제목, 문단, 목록, 표, 인용, 코드(pre·code), 링크, 이미지, "
             "굵게·기울임·취소선, 수평선")


@dataclass
class Cell:
    text: str
    colspan: int = 1
    rowspan: int = 1
    header: bool = False


def _span(value) -> int:
    """colspan/rowspan 값. 없거나 이상하면 1. 너무 큰 값은 잘라 둔다."""
    text = str(value or "").strip()
    if not text.isdigit():
        return 1
    return max(1, min(int(text), 50))


def expand_spans(rows: list[list[Cell]]) -> list[list[str]]:
    """가로·세로로 병합한 칸을 펴서 네모난 격자로 만든다.

    한 칸으로 세면 열이 밀려 뒤 열의 값이 통째로 어긋난다. 세로 병합(rowspan)
    은 그 값이 아래 줄에도 걸린 것이므로 값을 내려 채우고, 가로 병합은 머리글
    일 때만 되풀이한다 - 자료 칸에서 되풀이하면 없던 값이 생겨 합계가 는다.
    """
    grid: list[list[str]] = []
    carry: dict[int, list] = {}          # 열 -> [남은 줄 수, 값]
    for cells in rows:
        line: list[str] = []
        column = 0
        for cell in cells:
            while carry.get(column, [0])[0] > 0:
                line.append(carry[column][1])
                carry[column][0] -= 1
                column += 1
            for step in range(cell.colspan):
                line.append(cell.text if (step == 0 or cell.header) else "")
                if cell.rowspan > 1:
                    carry[column + step] = [cell.rowspan - 1, cell.text]
            column += cell.colspan
        while carry.get(column, [0])[0] > 0:   # 줄 끝까지 내려오는 값
            line.append(carry[column][1])
            carry[column][0] -= 1
            column += 1
        grid.append(line)
    return grid


def table_lines(rows: list[list[Cell]]) -> tuple[list[list[str]], bool]:
    """표를 (마크다운 줄들, 머리글이 있었나)로. 머리글이 여러 줄이면 합친다.

    마크다운 표는 머리글이 한 줄뿐이다. 웹 표는 «1분기 / 1월·2월» 처럼 두 줄
    로 된 것이 흔한데, 그대로 두면 구분줄이 가운데 끼어 표가 깨진다.
    """
    if not rows:
        return [], False
    grid = expand_spans(rows)
    heads = 0
    for cells in rows:
        if cells and all(c.header for c in cells):
            heads += 1
        else:
            break
    if heads <= 1:
        return grid, heads == 1

    merged: list[str] = []
    width = max(len(line) for line in grid[:heads])
    for column in range(width):
        parts: list[str] = []
        for line in grid[:heads]:
            piece = line[column] if column < len(line) else ""
            if piece and piece not in parts:
                parts.append(piece)
        merged.append(" ".join(parts))
    return [merged] + grid[heads:], True


class Converter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.text: list[str] = []
        self.skip = 0
        self.pre = 0
        self.list_stack: list[tuple[str, int]] = []   # (ul|ol, 번호)
        self.quote = 0
        self.row: list[Cell] = []
        self.table: list[list[Cell]] = []
        self.in_cell = False
        self.header_row = False
        self.span = (1, 1)          # 지금 읽는 칸의 (가로, 세로) 병합 수
        self.hrefs: list[str] = []

    # ---- 도우미

    def _flush(self, prefix: str = "") -> None:
        body = "".join(self.text)
        self.text.clear()
        if not self.pre:
            body = re.sub(r"[ \t]*\n[ \t]*", " ", body)
            body = re.sub(r"\s{2,}", " ", body).strip()
        if not body:
            return
        self.out.append(prefix + body)

    def _blank(self) -> None:
        if self.out and self.out[-1] != "":
            self.out.append("")

    # ---- 파서 훅

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag in SKIP_TAGS:
            self.skip += 1
            return
        if self.skip:
            return

        if tag in BLOCK_TAGS and not self.in_cell:
            self._flush(self._prefix())
            if tag not in ("li",):
                self._blank()

        if tag == "li" and self.list_stack:
            kind, number = self.list_stack[-1]
            self.list_stack[-1] = (kind, number + 1)

        if tag == "br":
            self.text.append("\n" if self.pre else "  \n")
        elif tag == "hr":
            self.out.append("---")
            self._blank()
        elif tag in ("strong", "b"):
            self.text.append("**")
        elif tag in ("em", "i"):
            self.text.append("*")
        elif tag in ("del", "s", "strike"):
            self.text.append("~~")
        elif tag == "code" and not self.pre:
            self.text.append("`")
        elif tag == "pre":
            self.pre += 1
        elif tag == "a":
            self.hrefs.append(attr.get("href", ""))
            self.text.append("[")
        elif tag == "img":
            alt = attr.get("alt", "").strip()
            src = attr.get("src", "")
            if src:
                self.text.append(f"![{alt}]({src})")
        elif tag in ("ul", "ol"):
            self.list_stack.append((tag, 0))
        elif tag == "blockquote":
            self.quote += 1
        elif tag == "table":
            self.table = []
        elif tag == "tr":
            self.row = []
            self.header_row = False
        elif tag in ("td", "th"):
            self.in_cell = True
            self.header_row = self.header_row or tag == "th"
            self.span = (_span(attr.get("colspan")), _span(attr.get("rowspan")))
            self.text.clear()

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return

        if tag in ("strong", "b"):
            self.text.append("**")
        elif tag in ("em", "i"):
            self.text.append("*")
        elif tag in ("del", "s", "strike"):
            self.text.append("~~")
        elif tag == "code" and not self.pre:
            self.text.append("`")
        elif tag == "a":
            href = self.hrefs.pop() if self.hrefs else ""
            self.text.append(f"]({href})" if href else "]")
        elif tag == "pre":
            body = "".join(self.text).strip("\n")
            self.text.clear()
            self.pre = max(0, self.pre - 1)
            self.out.append("```\n" + body + "\n```")
            self._blank()
        elif tag in ("td", "th"):
            body = re.sub(r"\s+", " ", "".join(self.text)).strip()
            self.text.clear()
            self.in_cell = False
            self.row.append(Cell(body, *self.span, header=tag == "th"))
            self.span = (1, 1)
        elif tag == "tr":
            if self.row:
                self.table.append(self.row)
            self.row = []
        elif tag == "table":
            self._write_table()
        elif tag in ("ul", "ol"):
            self._flush(self._prefix())
            if self.list_stack:
                self.list_stack.pop()
            if not self.list_stack:
                self._blank()
        elif tag == "li":
            self._flush(self._prefix())
        elif tag == "blockquote":
            self._flush(self._prefix())
            self.quote = max(0, self.quote - 1)
            self._blank()
        elif tag in BLOCK_TAGS:
            self._flush(self._prefix(tag))
            self._blank()

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in ("br", "hr", "img"):
            self.handle_endtag(tag)

    def handle_data(self, data):
        if self.skip:
            return
        if not self.pre and not data.strip() and not self.text:
            return                      # 태그 사이의 줄바꿈·들여쓰기는 버린다
        self.text.append(data)

    # ---- 출력

    def _prefix(self, tag: str = "") -> str:
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            return "#" * int(tag[1]) + " "
        if self.list_stack:
            kind, number = self.list_stack[-1]
            indent = "  " * (len(self.list_stack) - 1)
            mark = "-" if kind == "ul" else f"{max(1, number)}."
            return f"{indent}{mark} "
        if self.quote:
            return "> "
        return ""

    def _write_table(self) -> None:
        if not self.table:
            return
        rows, header = table_lines(self.table)
        self.table = []
        if not rows:
            return
        width = max(len(r) for r in rows)
        lines = [(r + [""] * width)[:width] for r in rows]
        if not header:
            # 머리글(th)이 없던 표. 첫 줄을 머리글로 쓴 것을 적어 둔다 -
            # 마크다운 표는 머리글 없이는 못 쓴다
            self.out.append("<!-- 머리글이 없는 표라 첫 줄을 머리글로 놓았습니다 -->")
        self.out.append("| " + " | ".join(lines[0]) + " |")
        self.out.append("| " + " | ".join(["---"] * width) + " |")
        for row in lines[1:]:
            self.out.append("| " + " | ".join(row) + " |")
        self._blank()

    def result(self) -> str:
        self._flush(self._prefix())
        lines = [line.rstrip() for line in self.out]
        text = "\n".join(lines)
        return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
