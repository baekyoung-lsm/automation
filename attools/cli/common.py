"""여러 그룹이 함께 쓰는 출력 도우미. 사람이 보는 문구는 각 그룹 파일에 있다."""

from __future__ import annotations

import sys
from pathlib import Path

from ..write import manuscript
def _pad(text: str, width: int) -> str:
    """한글처럼 두 칸을 차지하는 문자를 고려한 왼쪽 정렬."""
    import unicodedata

    shown = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    return text + " " * max(0, width - shown)


def _p(*args, **kwargs):
    print(*args, **kwargs)


def _confirm(question: str) -> bool:
    if not sys.stdin.isatty():
        return False
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


class InputError(Exception):
    """읽을 것을 못 찾았을 때. 사람이 읽을 문구는 부르는 쪽에서 만든다."""


def _read_input(target: str) -> str:
    """'-' 면 표준 입력, 아니면 파일 하나. 디렉터리는 여기서 막는다."""
    if target == "-":
        return sys.stdin.read()
    path = Path(target)
    if path.is_dir():
        raise InputError(f"파일 하나를 주세요. 디렉터리입니다: {path}")
    if not path.is_file():
        raise InputError(f"파일이 없습니다: {path}")
    return manuscript.read_text(path)


def _width(text: str) -> int:
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _cut(text: str, limit: int) -> str:
    if _width(text) <= limit:
        return text
    out = ""
    for ch in text:
        if _width(out + ch) > limit - 1:
            return out + "…"
        out += ch
    return out


def _grid(headers: list[str], rows: list[list[str]], *, limit: int = 24) -> None:
    """터미널에 표를 정렬해 찍는다."""
    cells = [[_cut(h, limit) for h in headers]] + [[_cut(c, limit) for c in r] for r in rows]
    widths = [max(_width(row[i]) for row in cells if i < len(row))
              for i in range(len(headers))]
    line = "  ".join(_pad(h, w) for h, w in zip(cells[0], widths))
    _p("  " + line.rstrip())
    _p("  " + "  ".join("-" * w for w in widths))
    for row in cells[1:]:
        _p("  " + "  ".join(_pad(c, w) for c, w in zip(row, widths)).rstrip())


MD_SUFFIXES = {".md", ".markdown"}
