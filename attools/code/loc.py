"""줄 수 세기. 코드·주석·빈 줄을 갈라 언어별로 모은다.

주석 규칙을 아는 확장자만 주석을 가른다. 모르는 확장자는 줄 수만 세고
주석은 «모름» 으로 둔다 - 아무 규칙이나 갖다 대면 숫자가 조용히 틀린다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .gitkit import SKIP_DIRS, SKIP_SUFFIX, _readable

Block = tuple[str, str]

# 확장자 -> (표시 이름, 줄 주석, 블록 주석)
LANGUAGES: dict[str, tuple[str, tuple[str, ...], tuple[Block, ...]]] = {
    ".py": ("파이썬", ("#",), (('"""', '"""'), ("'''", "'''"))),
    ".pyi": ("파이썬", ("#",), (('"""', '"""'), ("'''", "'''"))),
    ".js": ("자바스크립트", ("//",), (("/*", "*/"),)),
    ".mjs": ("자바스크립트", ("//",), (("/*", "*/"),)),
    ".cjs": ("자바스크립트", ("//",), (("/*", "*/"),)),
    ".jsx": ("자바스크립트", ("//",), (("/*", "*/"),)),
    ".ts": ("타입스크립트", ("//",), (("/*", "*/"),)),
    ".tsx": ("타입스크립트", ("//",), (("/*", "*/"),)),
    ".java": ("자바", ("//",), (("/*", "*/"),)),
    ".kt": ("코틀린", ("//",), (("/*", "*/"),)),
    ".swift": ("스위프트", ("//",), (("/*", "*/"),)),
    ".go": ("Go", ("//",), (("/*", "*/"),)),
    ".rs": ("러스트", ("//",), (("/*", "*/"),)),
    ".c": ("C", ("//",), (("/*", "*/"),)),
    ".h": ("C 헤더", ("//",), (("/*", "*/"),)),
    ".cpp": ("C++", ("//",), (("/*", "*/"),)),
    ".cc": ("C++", ("//",), (("/*", "*/"),)),
    ".hpp": ("C++ 헤더", ("//",), (("/*", "*/"),)),
    ".cs": ("C#", ("//",), (("/*", "*/"),)),
    ".php": ("PHP", ("//", "#"), (("/*", "*/"),)),
    ".rb": ("루비", ("#",), (("=begin", "=end"),)),
    ".sh": ("셸", ("#",), ()),
    ".bash": ("셸", ("#",), ()),
    ".zsh": ("셸", ("#",), ()),
    ".sql": ("SQL", ("--",), (("/*", "*/"),)),
    ".css": ("CSS", (), (("/*", "*/"),)),
    ".scss": ("SCSS", ("//",), (("/*", "*/"),)),
    ".html": ("HTML", (), (("<!--", "-->"),)),
    ".htm": ("HTML", (), (("<!--", "-->"),)),
    ".xml": ("XML", (), (("<!--", "-->"),)),
    ".md": ("마크다운", (), (("<!--", "-->"),)),
    ".yml": ("YAML", ("#",), ()),
    ".yaml": ("YAML", ("#",), ()),
    ".toml": ("TOML", ("#",), ()),
    ".ini": ("INI", ("#", ";"), ()),
    ".cfg": ("설정", ("#", ";"), ()),
    ".json": ("JSON", (), ()),          # JSON 에는 주석이 없다. 모르는 것과 다르다
}


@dataclass
class FileCount:
    path: str
    language: str
    code: int = 0
    comment: int = 0
    blank: int = 0
    known: bool = True                  # 주석 규칙을 아는 언어인가

    @property
    def total(self) -> int:
        return self.code + self.comment + self.blank


@dataclass
class LangCount:
    language: str
    files: int = 0
    code: int = 0
    comment: int = 0
    blank: int = 0
    known: bool = True

    @property
    def total(self) -> int:
        return self.code + self.comment + self.blank


@dataclass
class LocReport:
    languages: list[LangCount] = field(default_factory=list)
    files: list[FileCount] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (파일, 까닭)

    @property
    def code(self) -> int:
        return sum(l.code for l in self.languages)

    @property
    def total(self) -> int:
        return sum(l.total for l in self.languages)


def count_text(body: str, lines_marks: tuple[str, ...],
               blocks: tuple[Block, ...]) -> tuple[int, int, int]:
    """(코드, 주석, 빈 줄).

    블록 주석은 그 줄이 여는 기호로 «시작할» 때만 주석으로 센다. 코드 뒤에
    붙은 /* ... */ 까지 주석으로 세면 코드 줄이 사라져 버린다.
    """
    code = comment = blank = 0
    closing = ""

    for raw in body.splitlines():
        line = raw.strip()

        if closing:                      # 블록 주석 안이다
            comment += 1
            if closing in line:
                closing = ""
            continue

        if not line:
            blank += 1
            continue

        opened = ""
        for start, end in blocks:
            if line.startswith(start):
                rest = line[len(start):]
                opened = start
                if end not in rest:      # 이 줄에서 안 닫혔다
                    closing = end
                break
        if opened:
            comment += 1
            continue

        if any(line.startswith(m) for m in lines_marks):
            comment += 1
            continue
        code += 1

    return code, comment, blank


def count_file(path: Path) -> FileCount | None:
    """한 파일. 읽지 못하면 None."""
    body = _readable(path)
    if body is None:
        return None
    name, marks, blocks = LANGUAGES.get(
        path.suffix.lower(), ("", (), ()))
    known = bool(name)
    if not known:
        name = path.suffix.lower() or "(확장자 없음)"
    code, comment, blank = count_text(body, marks, blocks)
    if not known:                        # 규칙을 모르면 주석을 갈랐다고 말하지 않는다
        code, comment = code + comment, 0
    return FileCount(str(path), name, code, comment, blank, known)


def scan(paths: list[Path], *, glob: str = "") -> LocReport:
    """경로들을 훑어 언어별로 모은다. 폴더는 아래를 전부 본다."""
    report = LocReport()
    targets: list[Path] = []
    for base in paths:
        if base.is_dir():
            targets += [p for p in sorted(base.rglob(glob or "*"))
                        if p.is_file() and not any(d in p.parts for d in SKIP_DIRS)]
        elif base.is_file():
            targets.append(base)
        else:
            report.skipped.append((str(base), "그런 경로가 없습니다"))

    groups: dict[str, LangCount] = {}
    for path in targets:
        if path.suffix.lower() in SKIP_SUFFIX:
            continue
        counted = count_file(path)
        if counted is None:
            report.skipped.append((str(path), "읽지 못했습니다 (이진 파일이거나 너무 큽니다)"))
            continue
        report.files.append(counted)
        group = groups.setdefault(counted.language,
                                  LangCount(counted.language, known=counted.known))
        group.files += 1
        group.code += counted.code
        group.comment += counted.comment
        group.blank += counted.blank

    report.languages = sorted(groups.values(), key=lambda g: (-g.code, g.language))
    report.files.sort(key=lambda f: -f.code)
    return report
