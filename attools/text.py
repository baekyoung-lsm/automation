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

from . import docx, hwpx
from .files import IGNORE_DIRS

def backup_dir() -> Path:
    """원본 백업이 쌓이는 곳. 홈은 부를 때마다 다시 본다."""
    return Path.home() / ".attools" / "text"
ENCODINGS = ("utf-8", "cp949", "euc-kr", "utf-16")
BOM_UTF8 = b"\xef\xbb\xbf"
# 글자를 꺼낼 수 있는 문서. 찾기에서만 쓴다 - 고치지는 못한다.
DOCUMENT_SUFFIXES = {".docx", ".hwpx"}

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".xz",
    ".7z", ".rar", ".exe", ".dll", ".so", ".dylib", ".pyc", ".class", ".jar",
    ".woff", ".woff2", ".ttf", ".otf", ".mp3", ".mp4", ".mov", ".xlsx", ".docx", ".pptx",
    ".hwp", ".hwpx",
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
               hidden: bool = False, max_size: int = 5_000_000,
               documents: bool = False):
    """훑을 파일. documents 를 켜면 워드 문서도 낸다 (찾기 전용이다)."""
    patterns = glob or ["*"]
    seen: set[Path] = set()

    def ok(p: Path) -> bool:
        if p in seen or not p.is_file() or p.is_symlink():
            return False
        suffix = p.suffix.lower()
        if suffix in BINARY_SUFFIXES and not (documents and suffix in DOCUMENT_SUFFIXES):
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



# --------------------------------------------------------------- 뽑아내기

# 정규식을 모르는 사람이 자주 찾는 것만 골라 둔다. 넓게 잡으면 오탐이 쏟아져
# 결과를 아예 안 보게 되므로, 애매한 것은 넣지 않는다.
PICK_RULES: dict[str, re.Pattern[str]] = {
    "이메일": re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
    "휴대폰": re.compile(r"\b01[016789][-. ]?\d{3,4}[-. ]?\d{4}\b"),
    "전화": re.compile(r"\b(?:02|0[3-6][1-5]|070|080)[-. ]\d{3,4}[-. ]\d{4}\b"
                     r"|\b1[5-9]\d{2}[-. ]?\d{4}\b"),
    # 하이픈이 있는 것만 본다. 숫자 열 자리는 계좌·주문번호일 수도 있다.
    "사업자번호": re.compile(r"\b\d{3}-\d{2}-\d{5}\b"),
    "주소": re.compile(r"https?://[^\s<>\"')\]]+"),
    "금액": re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*(?:원|만원|억원)\b"),
    "날짜": re.compile(r"\b(?:19|20)\d{2}[-./]\d{1,2}[-./]\d{1,2}\b"
                     r"|\b(?:19|20)\d{2}년\s?\d{1,2}월\s?\d{1,2}일"),
}


@dataclass
class Picked:
    kind: str
    value: str
    line: int
    source: str = ""
    context: str = ""


def pick(body: str, kinds: list[str] | None = None, *,
         source: str = "") -> list[Picked]:
    """글에서 이메일·전화·금액 같은 것을 뽑는다. 정규식을 몰라도 되게."""
    wanted = list(kinds or PICK_RULES)
    unknown = [k for k in wanted if k not in PICK_RULES]
    if unknown:
        raise TextError(f"모르는 종류: {', '.join(unknown)} "
                        f"(쓸 수 있는 것: {', '.join(PICK_RULES)})")

    out: list[Picked] = []
    for number, line in enumerate(body.splitlines(), 1):
        for kind in wanted:
            for match in PICK_RULES[kind].finditer(line):
                out.append(Picked(kind, match.group(0), number, source,
                                  line.strip()[:80]))
    return out


def unique_picked(found: list[Picked]) -> list[Picked]:
    """같은 종류의 같은 값은 처음 것만 남긴다."""
    seen: set[tuple[str, str]] = set()
    out: list[Picked] = []
    for item in found:
        key = (item.kind, item.value)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


# ------------------------------------------------------------------ 찾기만

@dataclass
class Hit:
    path: Path
    line: int
    text: str
    count: int = 1                                  # 그 줄에서 걸린 횟수
    before: list[str] = field(default_factory=list)  # 앞 문맥 줄
    after: list[str] = field(default_factory=list)   # 뒤 문맥 줄


@dataclass
class FileHits:
    path: Path
    hits: list[Hit] = field(default_factory=list)

    @property
    def count(self) -> int:
        return sum(h.count for h in self.hits)


def read_words_or_text(path: Path) -> tuple[str, str]:
    """글자를 꺼낸다. 워드 문서면 문단만 꺼낸다. (글자, 무엇으로 읽었는지)

    두 문서를 견주는 자리에서 쓴다. 워드에서 꺼낸 글에는 서식·그림이 없으므로
    «무엇으로 읽었는지» 를 함께 돌려주어 부르는 쪽이 밝힐 수 있게 한다.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".hwpx":
        return hwpx.read_text(path, separator="\n\n"), "한글 문단"
    if suffix in DOCUMENT_SUFFIXES:
        # 문단 사이를 빈 줄로 띄운다. 문단 단위로 견줄 때 한 덩어리가 되지 않게.
        return docx.read_text(path, separator="\n\n"), "워드 문단"
    body, encoding = read_text_any(path)
    return body, encoding


def find_in_files(files, pattern: re.Pattern[str], *, context: int = 0,
                  per_file: int = 0, documents: bool = False) -> list[FileHits]:
    """바꾸지 않고 찾기만 한다. 파일마다 걸린 줄을 모아 돌려준다.

    바꾸기와 같은 pattern 을 쓴다. 찾을 때와 바꿀 때 걸리는 것이 다르면
    미리보기를 믿을 수 없게 된다.

    documents 를 켜면 워드·한글 문서에서 글자를 꺼내 함께 본다. 기본은 끔이다 -
    그 문서들은 at text replace 로 고치지 못하므로, 찾기에서만 걸리면
    «찾았는데 안 바뀐다» 가 된다. 켤지 말지는 부르는 쪽이 정한다.
    """
    out: list[FileHits] = []
    for path in files:
        try:
            if documents and Path(path).suffix.lower() in DOCUMENT_SUFFIXES:
                body, _kind = read_words_or_text(Path(path))
                body = body.replace("\n\n", "\n")   # 줄 번호는 문단 번호가 된다
            else:
                body, _encoding = read_text_any(path)
        except (TextError, docx.DocxError, hwpx.HwpxError, OSError):
            continue

        lines = body.splitlines()
        found = FileHits(path)
        for number, line in enumerate(lines, 1):
            n = len(pattern.findall(line))
            if not n:
                continue
            found.hits.append(Hit(
                path, number, line, n,
                before=lines[max(0, number - 1 - context):number - 1] if context else [],
                after=lines[number:number + context] if context else []))
            if per_file and len(found.hits) >= per_file:
                break
        if found.hits:
            out.append(found)
    return out


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
        if path.is_dir():
            # copy2 는 폴더를 주면 그 안에 넣는다 - 되돌린 척하고 엉뚱한
            # 자리에 파일이 하나 생긴다
            errors.append(f"되돌리지 못함: {path} (같은 이름의 폴더가 있습니다)")
            continue
        # 한 파일에서 터져도 나머지는 되돌린다. 통째로 멎으면 반만 돌아간
        # 상태로 남는데, 무엇이 돌아갔는지도 알 수 없다
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, path)
        except OSError as exc:
            errors.append(f"되돌리지 못함: {path} ({exc})")
            continue
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


# --------------------------------------------------------------- 반복 문장

@dataclass
class Repeat:
    text: str
    places: list[tuple[str, int]] = field(default_factory=list)   # 파일, 줄

    @property
    def count(self) -> int:
        return len(self.places)

    @property
    def same_file(self) -> bool:
        return len({name for name, _ in self.places}) == 1


def normalize_sentence(text: str) -> str:
    """비교용으로만 쓰는 형태. 공백과 문장부호 차이는 무시한다."""
    body = re.sub(r"[\s]+", " ", text).strip()
    return re.sub(r"[\"'“”‘’.,!?·…\-—~()\[\]]", "", body).lower()


def repeated_sentences(sources: list[tuple[str, str]], *, min_chars: int = 12,
                       min_count: int = 2) -> list[Repeat]:
    """여러 글에서 똑같이 반복되는 문장을 찾는다.

    복사해 붙이다 남은 문장이나, 원고에서 같은 설명을 두 번 한 자리를 찾는다.
    짧은 문장('그렇다.')은 자연스럽게 반복되므로 길이로 거른다. 코드 블록과
    표의 줄은 보지 않는다 - 거기서 같은 줄이 나오는 것은 반복이 아니다.
    """
    seen: dict[str, Repeat] = {}
    for name, body in sources:
        line_no = 0
        fence: str | None = None
        for line in body.splitlines():
            line_no += 1
            m = FENCE.match(line)
            if m:                       # 코드 블록 안은 반복이 당연하다
                fence = None if fence else m.group(1)
                continue
            if fence or line.lstrip().startswith("|"):   # 표의 머리글 줄도 뺀다
                continue
            for piece in split_units(line, "sentence"):
                key = normalize_sentence(piece)
                if len(key) < min_chars:
                    continue
                spot = seen.setdefault(key, Repeat(piece.strip()))
                spot.places.append((name, line_no))
    return sorted((r for r in seen.values() if r.count >= min_count),
                  key=lambda r: (-r.count, r.text))


# ------------------------------------------------------------------ 글자 세기

MANUSCRIPT_SHEET = 200          # 원고지 한 장 = 200자 (국내에서 쓰는 기준)


@dataclass
class TextCount:
    path: Path
    kind: str = ""              # 무엇으로 읽었는지 (인코딩, 워드 문단 …)
    chars: int = 0              # 공백 포함
    chars_no_space: int = 0     # 공백 뺀 것 (자소서·과제에서 세는 기준)
    words: int = 0
    lines: int = 0
    paragraphs: int = 0         # 빈 줄로 나눈 덩어리
    bytes: int = 0              # utf-8 로 적었을 때
    error: str = ""

    @property
    def sheets(self) -> float:
        """원고지 매수. 200자를 한 장으로 센다."""
        return round(self.chars / MANUSCRIPT_SHEET, 1)


def count_text(path: Path) -> TextCount:
    """글자 수를 센다. 워드·한글 문서면 문단 글자만 센다.

    «공백 포함» 과 «공백 제외» 를 함께 낸다 - 자소서·과제는 둘 중 어느
    기준인지가 매번 다르고, 하나만 내면 반드시 틀린 쪽을 보게 된다.
    """
    count = TextCount(path=path)
    try:
        body, kind = read_words_or_text(path)
    except (TextError, docx.DocxError, hwpx.HwpxError, OSError) as exc:
        count.error = str(exc)
        return count

    return count_body(body, kind=kind, path=path)


def count_body(body: str, *, kind: str = "", path: Path | None = None) -> TextCount:
    """이미 읽은 글의 글자 수. 화면에 붙여 넣은 글도 같은 방법으로 센다."""
    count = TextCount(path=path or Path(""), kind=kind)
    count.chars = len(body)
    count.chars_no_space = len(re.sub(r"\s", "", body))
    count.words = len(body.split())
    count.lines = len(body.splitlines())
    count.paragraphs = len([p for p in re.split(r"\n\s*\n", body) if p.strip()])
    count.bytes = len(body.encode("utf-8"))
    return count
