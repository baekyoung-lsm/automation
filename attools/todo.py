"""코드에 흩어진 TODO·FIXME 를 모아 작성자와 방치된 기간까지 보여준다."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .gitkit import SKIP_DIRS, SKIP_SUFFIX, _readable, run

MARKERS = ["FIXME", "TODO", "HACK", "XXX", "BUG", "NOTE", "DEPRECATED", "WORKAROUND"]
# 심각한 것부터. 정렬에 쓴다.
SEVERITY = {"BUG": 0, "FIXME": 1, "HACK": 2, "XXX": 3, "WORKAROUND": 4,
            "TODO": 5, "DEPRECATED": 6, "NOTE": 7}

MARKER_RE = re.compile(
    rf"(?:^|[^A-Za-z])({'|'.join(MARKERS)})\b[ \t]*[:\-–]?[ \t]*(.*)$")
# 주석 닫는 기호를 떼어낸다
STRIP_TAIL = re.compile(r"\s*(?:\*/|-->)\s*$")

# 주석 안에 있을 때만 센다. 문자열 리터럴 안의 "TODO" 까지 잡으면 쓸모가 없다.
# --(SQL) 나 %(TeX) 는 --option, 서식 문자열과 헷갈려서 뺐다.
COMMENT_OPEN = re.compile(r"(#|//|/\*|<!--|;)")
BLOCK_CONT = re.compile(r"^\s*\*(?!/)")
# 마크다운·메모처럼 주석 기호가 없는 글에서는 줄머리에 온 것만 센다.
BARE_LEAD = re.compile(r"^\s*(?:[-*+>]\s+|\d+[.)]\s+|\[[ xX]\]\s*)?$")
OWNER_RE = re.compile(r"^\(([^)]{1,40})\)\s*|^@([\w.\-]{1,40})\s+")


def in_comment(line: str, marker_at: int) -> bool:
    """표시가 주석 안(또는 줄머리)에 있을 때만 True."""
    opener = COMMENT_OPEN.search(line)
    if opener and opener.start() < marker_at:
        return True
    if BLOCK_CONT.match(line) and marker_at > 0:
        return True
    return bool(BARE_LEAD.fullmatch(line[:marker_at]))


@dataclass
class Todo:
    path: str
    line: int
    marker: str
    text: str
    owner: str = ""          # TODO(이름) 처럼 코드에 적힌 담당자
    author: str = ""         # git blame 이 알려준 마지막 수정자
    when: datetime | None = None

    @property
    def age_days(self) -> int | None:
        return (datetime.now() - self.when).days if self.when else None

    @property
    def severity(self) -> int:
        return SEVERITY.get(self.marker, 9)


def scan_text(content: str, path: str, *, markers: list[str] | None = None) -> list[Todo]:
    wanted = set(markers or MARKERS)
    out: list[Todo] = []
    for lineno, raw in enumerate(content.splitlines(), 1):
        if len(raw) > 2000:
            continue
        m = MARKER_RE.search(raw)
        if not m or m.group(1) not in wanted:
            continue
        if not in_comment(raw, m.start(1)):
            continue
        body = STRIP_TAIL.sub("", m.group(2)).strip()

        owner = ""
        if om := OWNER_RE.match(body):
            owner = (om.group(1) or om.group(2) or "").strip()
            # TODO(이름): 처럼 담당자 뒤에 남는 구분 기호도 떼어낸다
            body = re.sub(r"^[\s:\-–]+", "", body[om.end():]).strip()
        out.append(Todo(path, lineno, m.group(1), body or "(내용 없음)", owner=owner))
    return out


def collect(root: Path, *, tracked: bool = True, markers: list[str] | None = None,
            glob: list[str] | None = None) -> list[Todo]:
    root = root.resolve()
    names: list[str] = []
    if tracked:
        try:
            names = [n for n in run(["ls-files"], root).splitlines() if n]
        except RuntimeError:
            tracked = False
    if not tracked:
        names = [str(p.relative_to(root)) for p in root.rglob("*")
                 if p.is_file() and not any(d in p.parts for d in SKIP_DIRS)]

    if glob:
        from fnmatch import fnmatch

        names = [n for n in names if any(fnmatch(n, g) for g in glob)]

    found: list[Todo] = []
    for name in names:
        p = root / name
        if not p.is_file() or p.suffix.lower() in SKIP_SUFFIX:
            continue
        content = _readable(p)
        if content is None:
            continue
        found.extend(scan_text(content, name, markers=markers))
    return found


def add_blame(root: Path, todos: list[Todo]) -> None:
    """파일마다 한 번씩만 blame 을 돌려 작성자와 시각을 채운다."""
    by_file: dict[str, list[Todo]] = {}
    for t in todos:
        by_file.setdefault(t.path, []).append(t)

    for name, items in by_file.items():
        try:
            out = subprocess.run(
                ["git", "-c", "core.quotepath=false",
                 "blame", "--line-porcelain", "--", name],
                cwd=root, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out.returncode != 0:
            continue

        info = _parse_blame(out.stdout)
        for t in items:
            if t.line in info:
                t.author, t.when = info[t.line]


def _parse_blame(output: str) -> dict[int, tuple[str, datetime]]:
    """--line-porcelain 출력을 줄 번호 -> (작성자, 시각) 으로."""
    result: dict[int, tuple[str, datetime]] = {}
    line_no = None
    author = ""
    stamp = None
    for raw in output.splitlines():
        if re.match(r"^[0-9a-f]{40} \d+ \d+", raw):
            line_no = int(raw.split()[2])
        elif raw.startswith("author "):
            author = raw[7:].strip()
        elif raw.startswith("author-time "):
            try:
                stamp = datetime.fromtimestamp(int(raw[12:]))
            except ValueError:
                stamp = None
        elif raw.startswith("\t") and line_no is not None:
            if stamp:
                result[line_no] = (author, stamp)
            line_no = None
    return result


def sort_todos(todos: list[Todo], mode: str = "age") -> list[Todo]:
    if mode == "age":   # 오래 방치된 것부터
        return sorted(todos, key=lambda t: (-(t.age_days or -1), t.severity, t.path))
    if mode == "severity":
        return sorted(todos, key=lambda t: (t.severity, -(t.age_days or 0), t.path))
    if mode == "file":
        return sorted(todos, key=lambda t: (t.path, t.line))
    if mode == "author":
        return sorted(todos, key=lambda t: (t.owner or t.author or "~",
                                            t.severity, t.path))
    raise ValueError(f"알 수 없는 정렬: {mode}")


def summarize(todos: list[Todo]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in todos:
        counts[t.marker] = counts.get(t.marker, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: SEVERITY.get(x[0], 9)))
