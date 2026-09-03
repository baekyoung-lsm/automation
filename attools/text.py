"""여러 파일의 텍스트를 한꺼번에 고친다. 기본은 미리보기, 되돌리기용 백업을 남긴다."""

from __future__ import annotations

import difflib
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .files import IGNORE_DIRS

BACKUP_DIR = Path.home() / ".attools" / "text"
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
    base = journal.parent if journal else BACKUP_DIR / stamp
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
    if not BACKUP_DIR.is_dir():
        return None
    found = sorted(BACKUP_DIR.glob("*/journal.jsonl"))
    return found[-1] if found else None
