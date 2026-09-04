"""마크다운 유지보수: 목차 만들기, 깨진 링크·앵커 찾기, 제목 계층 점검."""

from __future__ import annotations

import re
import urllib.parse
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ..hangul import strip_particle

TOC_START = "<!-- toc -->"
TOC_END = "<!-- /toc -->"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
LINK_RE = re.compile(r"(!?)\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
REF_DEF_RE = re.compile(r"^\s{0,3}\[(?P<name>[^\]]+)\]:\s*(?P<target>\S+)")
REF_USE_RE = re.compile(r"(!?)\[(?P<text>[^\]]*)\]\[(?P<name>[^\]]*)\]")
SLUG_DROP = re.compile(r"[^\w\s-]", re.UNICODE)


@dataclass
class Heading:
    level: int
    title: str
    line: int
    slug: str = ""


@dataclass
class Link:
    kind: str          # link | image | ref
    text: str
    target: str
    line: int


@dataclass
class Issue:
    kind: str
    detail: str
    line: int = 0


def github_slug(title: str, seen: dict[str, int] | None = None) -> str:
    """GitHub 이 제목에 붙이는 앵커와 같은 규칙. 한글은 그대로 남는다."""
    text = LINK_RE.sub(lambda m: m.group("text"), title)
    text = re.sub(r"[`*_~]", "", text)
    slug = SLUG_DROP.sub("", text).strip().lower().replace(" ", "-")
    if seen is None:
        return slug
    n = seen.get(slug, 0)
    seen[slug] = n + 1
    return slug if n == 0 else f"{slug}-{n}"


def _outside_fences(text: str):
    """코드 블록 안은 건너뛴다. 예제 안의 # 을 제목으로 세면 안 된다."""
    fence = None
    for lineno, line in enumerate(text.splitlines(), 1):
        m = FENCE_RE.match(line)
        if m:
            if fence is None:
                fence = m.group(1)
            elif line.strip().startswith(fence):
                fence = None
            continue
        if fence is None:
            yield lineno, line


def headings(text: str) -> list[Heading]:
    seen: dict[str, int] = {}
    out = []
    for lineno, line in _outside_fences(text):
        if m := HEADING_RE.match(line):
            h = Heading(len(m.group(1)), m.group(2).strip(), lineno)
            h.slug = github_slug(h.title, seen)
            out.append(h)
    return out


def build_toc(items: list[Heading], *, depth: int = 3, skip_first_h1: bool = True,
              bullet: str = "-") -> str:
    rows = [h for h in items if h.level <= depth]
    if skip_first_h1 and rows and rows[0].level == 1:
        rows = rows[1:]
    if not rows:
        return ""
    base = min(h.level for h in rows)
    lines = []
    for h in rows:
        indent = "  " * (h.level - base)
        title = re.sub(r"[`*_]", "", h.title)
        lines.append(f"{indent}{bullet} [{title}](#{h.slug})")
    return "\n".join(lines)


def update_toc(text: str, toc: str) -> tuple[str, bool]:
    """<!-- toc --> 와 <!-- /toc --> 사이를 갈아 끼운다. (새 내용, 바뀜)"""
    start = text.find(TOC_START)
    if start < 0:
        return text, False
    end = text.find(TOC_END, start)
    if end < 0:
        return text, False

    block = f"{TOC_START}\n\n{toc}\n\n"
    new = text[:start] + block + text[end:]
    return new, new != text


# ---------------------------------------------------------------------- 링크

def links(text: str) -> list[Link]:
    out: list[Link] = []
    refs: dict[str, str] = {}
    for lineno, line in _outside_fences(text):
        if m := REF_DEF_RE.match(line):
            refs[m.group("name").lower()] = m.group("target")
    for lineno, line in _outside_fences(text):
        for m in LINK_RE.finditer(line):
            out.append(Link("image" if m.group(1) else "link",
                            m.group("text"), m.group("target"), lineno))
        for m in REF_USE_RE.finditer(line):
            name = (m.group("name") or m.group("text")).lower()
            if name in refs:
                out.append(Link("image" if m.group(1) else "link",
                                m.group("text"), refs[name], lineno))
    return out


def check_links(path: Path, *, root: Path | None = None) -> list[Issue]:
    """상대 경로 파일과 문서 안 앵커가 실제로 있는지 본다. 외부 URL 은 건드리지 않는다."""
    text = path.read_text(encoding="utf-8", errors="replace")
    root = root or path.parent
    anchors = {h.slug for h in headings(text)}
    issues: list[Issue] = []

    for link in links(text):
        target = link.target.strip()
        if not target or target.startswith(("http://", "https://", "mailto:", "tel:", "#/")):
            continue

        file_part, _, anchor = target.partition("#")
        file_part = urllib.parse.unquote(file_part)

        if not file_part:                       # 같은 문서 안 앵커
            if anchor and anchor.lower() not in anchors:
                issues.append(Issue("앵커 없음", f"#{anchor}", link.line))
            continue

        resolved = (path.parent / file_part).resolve()
        if not resolved.exists():
            issues.append(Issue("파일 없음", target, link.line))
            continue
        if anchor and resolved.suffix.lower() in (".md", ".markdown"):
            other = {h.slug for h in headings(
                resolved.read_text(encoding="utf-8", errors="replace"))}
            if anchor.lower() not in other:
                issues.append(Issue("앵커 없음", target, link.line))
    return issues


def check_headings(text: str) -> list[Issue]:
    items = headings(text)
    issues: list[Issue] = []

    tops = [h for h in items if h.level == 1]
    if len(tops) > 1:
        issues.append(Issue("H1 이 여러 개", f"{len(tops)}개", tops[1].line))

    previous = 0
    for h in items:
        if previous and h.level > previous + 1:
            issues.append(Issue("제목 단계 건너뜀",
                                f"H{previous} 다음에 H{h.level}: {h.title}", h.line))
        previous = h.level

    seen: dict[str, int] = {}
    for h in items:
        key = h.title.strip().lower()
        if key in seen:
            issues.append(Issue("같은 제목 반복", f"{h.title} ({seen[key]}행에도 있음)", h.line))
        else:
            seen[key] = h.line
    return issues


@dataclass
class Section:
    number: int
    title: str
    level: int
    line: int
    body: str

    @property
    def slug(self) -> str:
        return github_slug(self.title)


def split_sections(text: str, *, level: int = 2,
                   keep_heading: bool = True) -> tuple[str, list[Section]]:
    """제목 수준을 기준으로 쪼갠다. (첫 제목 앞의 머리말, 절 목록)"""
    lines = text.splitlines()
    marks: list[tuple[int, int, str]] = []      # 줄 번호(0부터), 수준, 제목
    for lineno, line in _outside_fences(text):
        if m := HEADING_RE.match(line):
            depth = len(m.group(1))
            if depth <= level:
                marks.append((lineno - 1, depth, m.group(2).strip()))

    if not marks:
        return text.strip(), []

    preface = "\n".join(lines[:marks[0][0]]).strip()
    sections: list[Section] = []
    for i, (start, depth, title) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(lines)
        block = lines[start:end] if keep_heading else lines[start + 1:end]
        sections.append(Section(i + 1, title, depth, start + 1,
                                "\n".join(block).strip() + "\n"))
    return preface, sections


def section_filename(section: Section, *, digits: int = 2,
                     suffix: str = ".md") -> str:
    """번호를 앞에 붙여 순서가 유지되게 한다."""
    slug = section.slug or f"절{section.number}"
    return f"{section.number:0{digits}d}-{slug}{suffix}"


# ------------------------------------------------------------------ 표 정렬

SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")
CELL_SPLIT = re.compile(r"(?<!\\)\|")


def display_width(text: str) -> int:
    """터미널·고정폭 글꼴에서 차지하는 칸 수. 한글·한자·전각은 두 칸."""
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def split_row(line: str) -> list[str]:
    """한 줄을 칸으로 쪼갠다. `\\|` 는 칸 구분이 아니다."""
    body = line.strip()
    cells = CELL_SPLIT.split(body)
    if cells and not cells[0].strip():
        cells = cells[1:]
    if cells and not cells[-1].strip():
        cells = cells[:-1]
    return [c.strip() for c in cells]


def read_aligns(line: str) -> list[str]:
    out: list[str] = []
    for cell in split_row(line):
        left, right = cell.startswith(":"), cell.endswith(":")
        out.append("가운데" if left and right else
                   "오른쪽" if right else "왼쪽")
    return out


@dataclass
class TableBlock:
    start: int                                  # 1부터
    end: int
    header: list[str]
    aligns: list[str]
    rows: list[list[str]] = field(default_factory=list)

    @property
    def columns(self) -> int:
        return max([len(self.header)] + [len(r) for r in self.rows])


def find_tables(text: str) -> list[TableBlock]:
    """머리글 + 구분줄로 시작하는 표만 찾는다. 코드 블록 안은 보지 않는다."""
    lines = list(_outside_fences(text))
    blocks: list[TableBlock] = []
    i = 0
    while i < len(lines) - 1:
        lineno, line = lines[i]
        nextno, nextline = lines[i + 1]
        if "|" not in line or nextno != lineno + 1 or not SEPARATOR_RE.match(nextline):
            i += 1
            continue

        header = split_row(line)
        aligns = read_aligns(nextline)
        if len(header) != len(aligns):
            i += 1                              # 칸 수가 안 맞으면 표로 보지 않는다
            continue

        rows: list[list[str]] = []
        end = nextno
        j = i + 2
        while j < len(lines):
            no, body = lines[j]
            if no != end + 1 or "|" not in body or not body.strip():
                break
            rows.append(split_row(body))
            end = no
            j += 1
        blocks.append(TableBlock(lineno, end, header, aligns, rows))
        i = j
    return blocks


def format_table(block: TableBlock) -> list[str]:
    """칸 너비를 맞춰 다시 그린다. 한글은 두 칸으로 센다."""
    count = block.columns
    def fit(row: list[str]) -> list[str]:
        return (row + [""] * count)[:count]

    header = fit(block.header)
    aligns = (block.aligns + ["왼쪽"] * count)[:count]
    rows = [fit(r) for r in block.rows]

    widths = [max(3, display_width(header[c]),
                  *[display_width(r[c]) for r in rows] or [0])
              for c in range(count)]

    def cell(value: str, width: int, align: str) -> str:
        pad = width - display_width(value)
        if align == "오른쪽":
            return " " * pad + value
        if align == "가운데":
            left = pad // 2
            return " " * left + value + " " * (pad - left)
        return value + " " * pad

    out = ["| " + " | ".join(cell(v, w, a)
                             for v, w, a in zip(header, widths, aligns)) + " |"]
    marks = []
    for width, align in zip(widths, aligns):
        if align == "가운데":
            marks.append(":" + "-" * (width - 2) + ":")
        elif align == "오른쪽":
            marks.append("-" * (width - 1) + ":")
        else:
            marks.append("-" * width)
    out.append("| " + " | ".join(marks) + " |")
    for row in rows:
        out.append("| " + " | ".join(cell(v, w, a)
                                     for v, w, a in zip(row, widths, aligns)) + " |")
    return out


def format_tables(text: str) -> tuple[str, int]:
    """문서 안의 표를 모두 다시 그린다. (새 내용, 손댄 표 수)"""
    blocks = find_tables(text)
    if not blocks:
        return text, 0

    lines = text.splitlines()
    touched = 0
    for block in reversed(blocks):              # 뒤에서부터 갈아 끼워야 줄 번호가 안 밀린다
        old = lines[block.start - 1:block.end]
        new = format_table(block)
        if old != new:
            touched += 1
        lines[block.start - 1:block.end] = new

    body = "\n".join(lines)
    if text.endswith("\n"):
        body += "\n"
    return body, touched


# ------------------------------------------------------------ 용어 표기 점검

INLINE_CODE = re.compile(r"`[^`]*`")
URL_LIKE = re.compile(r"https?://\S+|\S+@\S+\.\S+")
WORD_EN = re.compile(r"[A-Za-z][A-Za-z0-9]{1,}")
WORD_KO = re.compile(r"[가-힣]{2,}")


@dataclass
class TermUse:
    key: str                                   # 비교용 형태
    kind: str                                  # 대소문자 | 띄어쓰기
    forms: Counter = field(default_factory=Counter)
    places: dict = field(default_factory=dict)  # 표기 -> 처음 본 (파일, 줄)

    @property
    def total(self) -> int:
        return sum(self.forms.values())

    def summary(self) -> str:
        return ", ".join(f"{form} {n}" for form, n in self.forms.most_common())


def prose_lines(text: str):
    """코드 블록·인라인 코드·URL 을 뺀 (줄 번호, 줄). 용어를 셀 때 쓴다."""
    for lineno, line in _outside_fences(text):
        body = INLINE_CODE.sub(" ", line)
        body = URL_LIKE.sub(" ", body)
        yield lineno, body


def term_variants(docs: list[tuple[str, str]], *, min_count: int = 2) -> list[TermUse]:
    """같은 말을 다르게 적은 곳을 찾는다.

    영문은 대소문자만 다른 표기(API/Api/api), 한글은 띄어쓰기만 다른 표기
    ('데이터 베이스'/'데이터베이스')를 본다. 어느 쪽이 옳은지는 정하지
    않는다 - 프로젝트마다 다르고, 틀렸다고 단정하면 결과를 안 보게 된다.
    """
    case: dict[str, TermUse] = {}
    korean: Counter = Counter()
    joined_places: dict[str, tuple[str, int]] = {}
    pairs: dict[str, Counter] = {}
    pair_places: dict[str, tuple[str, int]] = {}

    for name, text in docs:
        for lineno, line in prose_lines(text):
            for m in WORD_EN.finditer(line):
                word = m.group(0)
                spot = case.setdefault(word.lower(), TermUse(word.lower(), "대소문자"))
                spot.forms[word] += 1
                spot.places.setdefault(word, (name, lineno))

            tokens = [strip_particle(w)[0] for w in WORD_KO.findall(line)]
            tokens = [t for t in tokens if len(t) >= 2]
            for token in tokens:
                korean[token] += 1
                joined_places.setdefault(token, (name, lineno))
            for first, second in zip(tokens, tokens[1:]):
                key = first + second
                pairs.setdefault(key, Counter())[f"{first} {second}"] += 1
                pair_places.setdefault(f"{first} {second}", (name, lineno))

    out = [use for use in case.values()
           if len(use.forms) > 1 and use.total >= min_count]

    for key, spaced in pairs.items():
        if key not in korean:
            continue                      # 붙여 쓴 표기가 아예 없으면 흔들림이 아니다
        use = TermUse(key, "띄어쓰기")
        use.forms[key] = korean[key]
        use.places[key] = joined_places[key]
        for form, count in spaced.items():
            use.forms[form] = count
            use.places[form] = pair_places[form]
        if use.total >= min_count:
            out.append(use)

    return sorted(out, key=lambda u: (-u.total, u.key))
