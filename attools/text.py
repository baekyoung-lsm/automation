"""여러 파일의 텍스트를 한꺼번에 고친다. 기본은 미리보기, 되돌리기용 백업을 남긴다."""

from __future__ import annotations

import difflib
from collections import Counter
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .files import IGNORE_DIRS

def backup_dir() -> Path:
    """원본 백업이 쌓이는 곳. 홈은 부를 때마다 다시 본다."""
    return Path.home() / ".attools" / "text"
ENCODINGS = ("utf-8", "cp949", "euc-kr", "utf-16")
BOM_UTF8 = b"\xef\xbb\xbf"
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".xz",
    ".7z", ".rar", ".exe", ".dll", ".so", ".dylib", ".pyc", ".class", ".jar",
    ".woff", ".woff2", ".ttf", ".otf", ".mp3", ".mp4", ".mov", ".xlsx", ".docx", ".pptx",
}


class TextError(Exception):
    pass


@dataclass
class Change:
    path: Path
    before: str
    after: str
    encoding: str
    hits: int = 0
    note: str = ""

    @property
    def changed(self) -> bool:
        return self.before != self.after

    def diff(self, context: int = 1, limit: int = 12) -> list[str]:
        lines = list(difflib.unified_diff(
            self.before.splitlines(), self.after.splitlines(),
            lineterm="", n=context))[2:]  # 파일 이름 두 줄은 뺀다
        return lines[:limit] + ([f"... {len(lines) - limit}줄 더"] if len(lines) > limit else [])


def read_text_any(path: Path) -> tuple[str, str]:
    """인코딩을 알아서 찾아 읽는다. (내용, 인코딩)"""
    data = path.read_bytes()
    if b"\0" in data[:8000]:
        raise TextError("이진 파일")
    # BOM 이 실제로 있을 때만 utf-8-sig 로 본다. 아니면 다시 쓸 때 BOM 이 붙어 버린다.
    if data.startswith(BOM_UTF8):
        return data.decode("utf-8-sig"), "utf-8-sig"
    for enc in ENCODINGS:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise TextError("인코딩을 알아내지 못했습니다")


def iter_files(paths: list[Path], *, glob: list[str] | None = None,
               hidden: bool = False, max_size: int = 5_000_000):
    patterns = glob or ["*"]
    seen: set[Path] = set()

    def ok(p: Path) -> bool:
        if p in seen or not p.is_file() or p.is_symlink():
            return False
        if p.suffix.lower() in BINARY_SUFFIXES:
            return False
        try:
            return p.stat().st_size <= max_size
        except OSError:
            return False

    for root in paths:
        if root.is_file():
            if ok(root):
                seen.add(root)
                yield root
            continue
        for pattern in patterns:
            for p in sorted(root.rglob(pattern)):
                rel = p.relative_to(root).parts
                if any(part in IGNORE_DIRS for part in rel[:-1]):
                    continue
                if not hidden and any(part.startswith(".") for part in rel):
                    continue
                if ok(p):
                    seen.add(p)
                    yield p


# ------------------------------------------------------------- 찾아 바꾸기

def build_pattern(needle: str, *, regex: bool, ignore_case: bool,
                  whole_word: bool) -> re.Pattern[str]:
    body = needle if regex else re.escape(needle)
    if whole_word:
        body = rf"(?<!\w){body}(?!\w)"
    try:
        return re.compile(body, re.I if ignore_case else 0)
    except re.error as e:
        raise TextError(f"정규식이 잘못됐습니다: {e}") from None


def plan_replace(files, pattern: re.Pattern[str], replacement: str, *,
                 regex: bool = False) -> list[Change]:
    changes = []
    for path in files:
        try:
            before, encoding = read_text_any(path)
        except (TextError, OSError):
            continue
        repl = replacement if regex else replacement.replace("\\", "\\\\")
        after, hits = pattern.subn(repl, before)
        if hits:
            changes.append(Change(path, before, after, encoding, hits))
    return changes


# ------------------------------------------------ 인코딩 · 줄바꿈 · 공백

def plan_encoding(files, target: str = "utf-8") -> list[Change]:
    """cp949 로 저장된 파일을 utf-8 로 바꾼다. 내용은 그대로."""
    changes = []
    for path in files:
        try:
            text, encoding = read_text_any(path)
        except (TextError, OSError):
            continue
        if encoding.replace("-sig", "") == target:
            continue
        c = Change(path, text, text, encoding, hits=1,
                   note=f"{encoding} -> {target}")
        changes.append(c)
    return changes


def plan_eol(files, target: str = "lf") -> list[Change]:
    ending = "\n" if target == "lf" else "\r\n"
    changes = []
    for path in files:
        try:
            before, encoding = read_text_any(path)
        except (TextError, OSError):
            continue
        after = before.replace("\r\n", "\n").replace("\r", "\n")
        if ending == "\r\n":
            after = after.replace("\n", "\r\n")
        if after != before:
            crlf = before.count("\r\n")
            changes.append(Change(path, before, after, encoding, hits=max(1, crlf),
                                  note=f"줄바꿈 -> {target.upper()}"))
    return changes


def plan_trim(files, *, tabs: int = 0, final_newline: bool = True) -> list[Change]:
    """줄 끝 공백 제거, 파일 끝 개행 보정, 필요하면 탭을 공백으로."""
    changes = []
    for path in files:
        try:
            before, encoding = read_text_any(path)
        except (TextError, OSError):
            continue
        lines = before.split("\n")
        after_lines = [ln.replace("\t", " " * tabs) if tabs else ln for ln in lines]
        after_lines = [ln.rstrip(" \t") for ln in after_lines]
        after = "\n".join(after_lines)
        if final_newline and after and not after.endswith("\n"):
            after += "\n"
        after = re.sub(r"\n{3,}\Z", "\n", after)
        if after != before:
            trimmed = sum(1 for a, b in zip(lines, after_lines) if a != b)
            changes.append(Change(path, before, after, encoding, hits=max(1, trimmed),
                                  note="공백 정리"))
    return changes


# --------------------------------------------------------- 적용 · 되돌리기

def apply_changes(changes: list[Change], *, target_encoding: str | None = None,
                  journal: Path | None = None) -> Path | None:
    """원본을 백업하고 새 내용을 쓴다. 저널 경로를 돌려준다."""
    if not changes:
        return None

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = journal.parent if journal else backup_dir() / stamp
    base.mkdir(parents=True, exist_ok=True)
    journal = journal or base / "journal.jsonl"

    with journal.open("w", encoding="utf-8") as fh:
        for n, c in enumerate(changes):
            backup = base / f"{n:05d}{c.path.suffix or '.bak'}"
            shutil.copy2(c.path, backup)
            encoding = target_encoding or c.encoding
            c.path.write_text(c.after, encoding=encoding, newline="")
            fh.write(json.dumps({"path": str(c.path), "backup": str(backup),
                                 "encoding": encoding, "was": c.encoding},
                                ensure_ascii=False) + "\n")
            fh.flush()
    return journal


def undo(journal: Path) -> tuple[int, list[str]]:
    entries = [json.loads(l) for l in journal.read_text(encoding="utf-8").splitlines() if l.strip()]
    restored, errors = 0, []
    for e in reversed(entries):
        backup, path = Path(e["backup"]), Path(e["path"])
        if not backup.is_file():
            errors.append(f"백업 없음: {backup}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, path)
        restored += 1
    return restored, errors


def latest_journal() -> Path | None:
    base = backup_dir()
    if not base.is_dir():
        return None
    found = sorted(base.glob("*/journal.jsonl"))
    return found[-1] if found else None


# --------------------------------------------------------------------- 줄 다루기

@dataclass
class LineStats:
    total: int = 0
    blank: int = 0
    unique: int = 0
    duplicated: int = 0     # 두 번 이상 나온 줄의 종류 수

    @property
    def extra(self) -> int:
        """중복으로 늘어난 줄 수."""
        return self.total - self.blank - self.unique


def read_lines(path: Path, *, strip: bool = True, keep_blank: bool = False) -> list[str]:
    content, _ = read_text_any(path)
    lines = content.splitlines()
    if strip:
        lines = [line.strip() for line in lines]
    return lines if keep_blank else [line for line in lines if line]


def line_stats(lines: list[str]) -> LineStats:
    counts = Counter(line for line in lines if line)
    return LineStats(total=len(lines),
                     blank=sum(1 for line in lines if not line),
                     unique=len(counts),
                     duplicated=sum(1 for n in counts.values() if n > 1))


def unique_lines(lines: list[str], *, ignore_case: bool = False) -> list[str]:
    """순서를 지키며 중복을 없앤다. 정렬하면 원래 순서를 잃는다."""
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.lower() if ignore_case else line
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def compare_lines(left: list[str], right: list[str], *,
                  ignore_case: bool = False) -> dict[str, list[str]]:
    """두 목록을 줄 단위로 대조한다. 명단 맞춰볼 때 쓴다."""
    def key(line: str) -> str:
        return line.lower() if ignore_case else line

    left_keys = {key(line): line for line in left}
    right_keys = {key(line): line for line in right}
    return {
        "공통": [left_keys[k] for k in left_keys if k in right_keys],
        "왼쪽만": [left_keys[k] for k in left_keys if k not in right_keys],
        "오른쪽만": [right_keys[k] for k in right_keys if k not in left_keys],
    }


def sort_lines(lines: list[str], *, descending: bool = False,
               numeric: bool = False) -> list[str]:
    if numeric:
        def key(line: str):
            head = re.match(r"\s*-?\d+(?:\.\d+)?", line)
            return (0, float(head.group()), "") if head else (1, 0.0, line)
    else:
        def key(line: str):
            return (0, 0.0, line)
    return sorted(lines, key=key, reverse=descending)


# ------------------------------------------------------------------ 뽑아내기

@dataclass
class ExtractResult:
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    matched_lines: int = 0
    total_lines: int = 0
    samples_missed: list[tuple[int, str]] = field(default_factory=list)

    @property
    def missed(self) -> int:
        return self.total_lines - self.matched_lines


def extract(lines: list[str], pattern: re.Pattern[str], *,
            samples: int = 5) -> ExtractResult:
    """줄마다 정규식을 맞춰 캡처한 것을 표로 만든다.

    이름 붙인 그룹((?P<이름>...))이 있으면 그 이름을 열 이름으로 쓴다.
    없으면 1, 2, 3... 을 쓴다.
    """
    named = sorted(pattern.groupindex, key=lambda k: pattern.groupindex[k])
    result = ExtractResult(total_lines=len(lines))
    result.headers = named or [str(i + 1) for i in range(pattern.groups)] or ["전체"]

    for number, line in enumerate(lines, 1):
        m = pattern.search(line)
        if not m:
            if len(result.samples_missed) < samples and line.strip():
                result.samples_missed.append((number, line.strip()))
            continue
        result.matched_lines += 1
        if named:
            result.rows.append([m.group(name) or "" for name in named])
        elif pattern.groups:
            result.rows.append([g or "" for g in m.groups()])
        else:
            result.rows.append([m.group(0)])
    return result


# ---------------------------------------------------------------- 문서 비교

@dataclass
class Edit:
    """바뀐 한 자리. 줄 번호는 1부터, 없으면 0."""
    kind: str          # 추가 / 삭제 / 수정
    old_no: int
    new_no: int
    old: str
    new: str

    @property
    def ratio(self) -> float:
        if not self.old or not self.new:
            return 0.0
        return difflib.SequenceMatcher(None, self.old, self.new).ratio()


@dataclass
class DiffReport:
    unit: str
    old_total: int
    new_total: int
    same: int = 0
    edits: list[Edit] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        out = {"수정": 0, "추가": 0, "삭제": 0}
        for e in self.edits:
            out[e.kind] += 1
        return out

    @property
    def ratio(self) -> float:
        """전체 비슷한 정도. 둘 다 비었으면 1."""
        total = self.old_total + self.new_total
        return 1.0 if not total else 2 * self.same / total


def split_units(text: str, unit: str = "line") -> list[str]:
    """비교 단위로 쪼갠다. 빈 줄은 세지 않는다."""
    if unit == "line":
        return [ln.strip() for ln in text.splitlines() if ln.strip()]
    if unit == "para":
        return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if unit == "sentence":
        # 문장 끝 뒤에 따옴표가 붙는 한국어 대사를 함께 끊는다.
        parts = re.split(r"(?<=[.!?…])[\"'”’」』\)]*\s+|\n+", text)
        return [s.strip() for s in parts if s and s.strip()]
    raise TextError(f"모르는 단위입니다: {unit}")


def diff_units(old: str, new: str, *, unit: str = "line",
               similar: float = 0.5) -> DiffReport:
    """두 글을 단위별로 대조한다. 옮겨진 자리는 추가+삭제로 본다.

    similar 보다 덜 닮은 짝은 '수정' 으로 묶지 않는다. 전혀 다른 두 줄을
    한 줄 고친 것처럼 보여주면 실제로 지워진 내용을 놓치기 때문이다.
    """
    a, b = split_units(old, unit), split_units(new, unit)
    report = DiffReport(unit=unit, old_total=len(a), new_total=len(b))
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            report.same += i2 - i1
            continue
        if tag == "replace":
            # 짝이 맞는 만큼은 '수정'으로 묶고 남는 쪽만 추가/삭제로 남긴다.
            pairs = min(i2 - i1, j2 - j1)
            for k in range(pairs):
                one = Edit("수정", i1 + k + 1, j1 + k + 1, a[i1 + k], b[j1 + k])
                if one.ratio >= similar:
                    report.edits.append(one)
                else:
                    report.edits.append(Edit("삭제", i1 + k + 1, 0, a[i1 + k], ""))
                    report.edits.append(Edit("추가", 0, j1 + k + 1, "", b[j1 + k]))
            for k in range(pairs, i2 - i1):
                report.edits.append(Edit("삭제", i1 + k + 1, 0, a[i1 + k], ""))
            for k in range(pairs, j2 - j1):
                report.edits.append(Edit("추가", 0, j1 + k + 1, "", b[j1 + k]))
        elif tag == "delete":
            for k in range(i1, i2):
                report.edits.append(Edit("삭제", k + 1, 0, a[k], ""))
        else:                                   # insert
            for k in range(j1, j2):
                report.edits.append(Edit("추가", 0, k + 1, "", b[k]))
    return report


def word_marks(old: str, new: str) -> str:
    """한 줄 안에서 무엇이 바뀌었는지 [-지움-]{+넣음+} 으로 표시한다."""
    a, b = old.split(), new.split()
    out: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b,
                                                       autojunk=False).get_opcodes():
        if tag == "equal":
            out.extend(a[i1:i2])
            continue
        if tag in ("replace", "delete"):
            out.append("[-" + " ".join(a[i1:i2]) + "-]")
        if tag in ("replace", "insert"):
            out.append("{+" + " ".join(b[j1:j2]) + "+}")
    return " ".join(out)


# ------------------------------------------------------------------ 줄 접기

FENCE = re.compile(r"^\s*(```+|~~~+)")
KEEP_AS_IS = re.compile(r"^\s*(\||>|#{1,6}\s|[-*+]\s|\d+[.)]\s|\s{4,}\S)")


def display_width(text: str) -> int:
    """한글·한자·전각은 두 칸으로 센다."""
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def wrap_line(line: str, width: int) -> list[str]:
    """공백에서만 끊는다. 한국어는 낱말 안에서 끊으면 읽기 나빠진다."""
    indent = line[:len(line) - len(line.lstrip())]
    words = line.split()
    if not words:
        return [line]

    out: list[str] = []
    current = indent
    for word in words:
        candidate = word if current.strip() == "" else f"{current} {word}"
        if current.strip() and display_width(candidate) > width:
            out.append(current)
            current = indent + word
        else:
            current = candidate if current.strip() else indent + word
    out.append(current)
    return out


def wrap_text(body: str, *, width: int = 80, skip_code: bool = True,
              skip_marked: bool = True) -> str:
    """긴 줄을 폭에 맞춰 접는다. 코드 블록과 표는 건드리지 않는다."""
    out: list[str] = []
    fence: str | None = None
    for line in body.splitlines():
        m = FENCE.match(line)
        if m and skip_code:
            fence = None if fence else m.group(1)
            out.append(line)
            continue
        if fence or (skip_marked and KEEP_AS_IS.match(line)):
            out.append(line)
            continue
        if display_width(line) <= width:
            out.append(line)
            continue
        out.extend(wrap_line(line, width))
    text = "\n".join(out)
    return text + "\n" if body.endswith("\n") else text
