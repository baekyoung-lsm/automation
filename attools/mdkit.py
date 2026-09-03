"""마크다운 유지보수: 목차 만들기, 깨진 링크·앵커 찾기, 제목 계층 점검."""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

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
