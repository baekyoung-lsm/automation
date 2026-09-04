"""HTML 을 마크다운으로. 웹 문서를 저장소로 옮길 때 쓴다.

전부를 옮기지 않는다. 지원하는 태그만 옮기고 나머지는 글자만 남긴다.
표준 라이브러리 html.parser 로 읽으므로 깨진 HTML 도 대충 넘어간다.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

SKIP_TAGS = {"script", "style", "head", "meta", "link", "noscript", "svg"}
BLOCK_TAGS = {"p", "div", "section", "article", "header", "footer", "main",
              "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "table",
              "tr", "blockquote", "pre", "hr"}
SUPPORTED = ("제목, 문단, 목록, 표, 인용, 코드(pre·code), 링크, 이미지, "
             "굵게·기울임·취소선, 수평선")


class Converter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.text: list[str] = []
        self.skip = 0
        self.pre = 0
        self.list_stack: list[tuple[str, int]] = []   # (ul|ol, 번호)
        self.quote = 0
        self.row: list[str] = []
        self.table: list[list[str]] = []
        self.in_cell = False
        self.header_row = False
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
            cell = re.sub(r"\s+", " ", "".join(self.text)).strip()
            self.text.clear()
            self.in_cell = False
            self.row.append(cell)
        elif tag == "tr":
            if self.row:
                self.table.append(self.row)
                if self.header_row or len(self.table) == 1:
                    self.table.append(["---"] * len(self.row))
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
        width = max(len(r) for r in self.table)
        for row in self.table:
            cells = (row + [""] * width)[:width]
            self.out.append("| " + " | ".join(cells) + " |")
        self.table = []
        self._blank()

    def result(self) -> str:
        self._flush(self._prefix())
        lines = [line.rstrip() for line in self.out]
        text = "\n".join(lines)
        return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
