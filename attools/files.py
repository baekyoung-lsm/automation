"""파일 정리: 분류 이동, 이름 정규화, 중복 탐지, 되돌리기."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .hangul import is_decomposed, sanitize_filename, to_nfc

CATEGORIES: dict[str, tuple[str, ...]] = {
    "문서": ("pdf", "doc", "docx", "hwp", "hwpx", "txt", "md", "rtf", "odt", "epub"),
    "표": ("xls", "xlsx", "csv", "tsv", "ods", "numbers"),
    "발표": ("ppt", "pptx", "key", "odp"),
    "이미지": ("jpg", "jpeg", "png", "gif", "webp", "heic", "bmp", "tiff", "svg", "psd"),
    "영상": ("mp4", "mov", "avi", "mkv", "webm", "wmv", "flv"),
    "음악": ("mp3", "wav", "flac", "m4a", "aac", "ogg"),
    "압축": ("zip", "tar", "gz", "bz2", "xz", "7z", "rar", "alz", "egg"),
    "코드": ("py", "js", "ts", "tsx", "jsx", "java", "kt", "go", "rs", "rb", "php",
             "c", "h", "cpp", "sh", "sql", "json", "yaml", "yml", "toml", "ipynb"),
    "설치": ("dmg", "pkg", "exe", "msi", "deb", "rpm", "apk", "appimage"),
    "폰트": ("ttf", "otf", "woff", "woff2"),
}

_EXT_MAP = {ext: cat for cat, exts in CATEGORIES.items() for ext in exts}
ETC = "기타"

def journal_dir() -> Path:
    """되돌리기 저널이 쌓이는 곳. 홈은 부를 때마다 다시 본다.

    import 시점에 Path.home() 을 굳혀 두면 시험에서 홈을 바꿔도 실제 홈을
    건드리게 된다.
    """
    return Path.home() / ".attools" / "journal"


@dataclass
class Move:
    src: str
    dst: str

    def as_dict(self) -> dict[str, str]:
        return {"src": self.src, "dst": self.dst}


def category_of(path: Path) -> str:
    return _EXT_MAP.get(path.suffix.lstrip(".").lower(), ETC)


def bucket_of(path: Path, by: str) -> Path:
    """분류 기준에 따른 하위 디렉터리 경로(상대)."""
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    if by == "ext":
        return Path(category_of(path))
    if by == "date":
        return Path(mtime.strftime("%Y-%m"))
    if by == "ext-date":
        return Path(category_of(path)) / mtime.strftime("%Y-%m")
    if by == "date-ext":
        return Path(mtime.strftime("%Y-%m")) / category_of(path)
    raise ValueError(f"알 수 없는 분류 기준: {by}")


def unique_path(dst: Path, taken: set[Path] | None = None) -> Path:
    """이미 있는 이름이면 ' (1)', ' (2)'... 를 붙인다."""
    taken = taken if taken is not None else set()
    if not dst.exists() and dst not in taken:
        return dst
    stem, ext = dst.stem, dst.suffix
    for i in range(1, 10000):
        cand = dst.with_name(f"{stem} ({i}){ext}")
        if not cand.exists() and cand not in taken:
            return cand
    raise RuntimeError(f"이름 충돌을 해소하지 못했습니다: {dst}")


def iter_targets(root: Path, *, recursive: bool, include_hidden: bool,
                 min_age_days: float = 0.0):
    walker = root.rglob("*") if recursive else root.glob("*")
    cutoff = time.time() - min_age_days * 86400
    for p in walker:
        if not p.is_file() or p.is_symlink():
            continue
        if not include_hidden and any(part.startswith(".") for part in p.relative_to(root).parts):
            continue
        if min_age_days and p.stat().st_mtime > cutoff:
            continue
        yield p


def plan_organize(root: Path, *, by: str = "ext", recursive: bool = False,
                  include_hidden: bool = False, min_age_days: float = 0.0,
                  fixname: bool = False) -> list[Move]:
    """이동 계획을 만든다. 파일 시스템은 건드리지 않는다."""
    root = root.resolve()
    known_dirs = set(CATEGORIES) | {ETC}
    planned: set[Path] = set()
    moves: list[Move] = []

    for src in sorted(iter_targets(root, recursive=recursive,
                                   include_hidden=include_hidden,
                                   min_age_days=min_age_days)):
        # 이미 분류된 디렉터리 안의 파일은 건너뛴다.
        rel_parts = src.relative_to(root).parts
        if len(rel_parts) > 1 and rel_parts[0] in known_dirs:
            continue

        name = sanitize_filename(src.name) if fixname else to_nfc(src.name)
        dst = unique_path(root / bucket_of(src, by) / name, planned)
        if dst == src:
            continue
        planned.add(dst)
        moves.append(Move(str(src), str(dst)))

    return moves


def apply_moves(moves: list[Move], *, journal: Path | None = None) -> Path | None:
    """계획을 실제로 실행하고 되돌리기용 저널을 남긴다."""
    if not moves:
        return None
    if journal is None:
        base = journal_dir()
        base.mkdir(parents=True, exist_ok=True)
        journal = base / f"{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    else:
        journal.parent.mkdir(parents=True, exist_ok=True)

    with journal.open("w", encoding="utf-8") as fh:
        for mv in moves:
            src, dst = Path(mv.src), Path(mv.dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            final = unique_path(dst)
            shutil.move(str(src), str(final))  # 다른 파티션으로도 옮길 수 있게
            fh.write(json.dumps(Move(str(src), str(final)).as_dict(), ensure_ascii=False) + "\n")
            fh.flush()
    return journal


def undo(journal: Path) -> tuple[int, list[str]]:
    """저널을 역순으로 되돌린다. (복구 개수, 실패 메시지)"""
    entries = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()]
    restored, errors = 0, []
    for e in reversed(entries):
        src, dst = Path(e["src"]), Path(e["dst"])
        if not dst.exists():
            errors.append(f"없음: {dst}")
            continue
        if src.exists():
            errors.append(f"원래 자리에 이미 파일이 있음: {src}")
            continue
        src.parent.mkdir(parents=True, exist_ok=True)
        dst.replace(src)
        restored += 1
    return restored, errors


def file_hash(path: Path, *, chunk: int = 1 << 20, limit: int | None = None) -> str:
    h = hashlib.blake2b(digest_size=16)
    read = 0
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
            read += len(block)
            if limit and read >= limit:
                break
    return h.hexdigest()


def find_duplicates(root: Path, *, recursive: bool = True,
                    include_hidden: bool = False, min_size: int = 1) -> list[list[Path]]:
    """크기 → 앞부분 해시 → 전체 해시 순으로 좁혀 중복 그룹을 찾는다."""
    by_size: dict[int, list[Path]] = {}
    for p in iter_targets(root, recursive=recursive, include_hidden=include_hidden):
        size = p.stat().st_size
        if size < min_size:
            continue
        by_size.setdefault(size, []).append(p)

    groups: list[list[Path]] = []
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        by_head: dict[str, list[Path]] = {}
        for p in paths:
            by_head.setdefault(file_hash(p, limit=65536), []).append(p)
        for head_group in by_head.values():
            if len(head_group) < 2:
                continue
            if size <= 65536:
                groups.append(sorted(head_group))
                continue
            by_full: dict[str, list[Path]] = {}
            for p in head_group:
                by_full.setdefault(file_hash(p), []).append(p)
            groups.extend(sorted(g) for g in by_full.values() if len(g) > 1)

    return sorted(groups, key=lambda g: -g[0].stat().st_size)


def plan_fixname(root: Path, *, recursive: bool = False, include_hidden: bool = False,
                 space: str = "keep") -> list[Move]:
    """NFD 자모 분리·특수문자·중복 공백을 정리하는 이름 변경 계획."""
    planned: set[Path] = set()
    moves: list[Move] = []
    for p in sorted(iter_targets(root, recursive=recursive, include_hidden=include_hidden)):
        new = sanitize_filename(p.name, space=space)
        if new == p.name and not is_decomposed(p.name):
            continue
        dst = unique_path(p.with_name(new), planned)
        if dst == p:
            continue
        planned.add(dst)
        moves.append(Move(str(p), str(dst)))
    return moves


IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
               ".next", ".mypy_cache", ".pytest_cache", ".idea", "target"}


def snapshot_mtimes(root: Path, patterns: list[str]) -> dict[str, float]:
    """감시 대상 파일의 수정 시각 표."""
    out: dict[str, float] = {}
    for pattern in patterns:
        for p in root.rglob(pattern):
            if not p.is_file() or any(part in IGNORE_DIRS for part in p.parts):
                continue
            try:
                out[str(p)] = p.stat().st_mtime
            except OSError:
                continue
    return out


def diff_mtimes(before: dict[str, float], after: dict[str, float]) -> list[str]:
    changed = [k for k, v in after.items() if before.get(k) != v]
    changed += [k for k in before if k not in after]
    return sorted(set(changed))


def dir_sizes(root: Path, *, depth: int = 1) -> tuple[list[tuple[Path, int]], list[tuple[Path, int]], int]:
    """(디렉터리별 합계, 큰 파일들, 전체 크기)."""
    totals: dict[Path, int] = {}
    biggest: list[tuple[Path, int]] = []
    grand = 0

    for p in root.rglob("*"):
        if p.is_symlink() or not p.is_file():
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        grand += size
        biggest.append((p, size))
        rel = p.relative_to(root).parts
        key = root.joinpath(*rel[:depth]) if len(rel) > depth else root.joinpath(*rel)
        totals[key] = totals.get(key, 0) + size

    biggest.sort(key=lambda x: -x[1])
    return sorted(totals.items(), key=lambda x: -x[1]), biggest, grand


def human_size(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TiB"


RENAME_FIELDS = ("seq", "date", "time", "stem", "ext", "name", "parent", "size")


def rename_sort_key(path: Path, mode: str):
    stat = path.stat()
    if mode == "date":
        return (stat.st_mtime, str(path))
    if mode == "size":
        return (-stat.st_size, str(path))
    return (str(path).lower(),)


def render_name(path: Path, template: str, *, seq: int,
                date_format: str = "%Y%m%d") -> str:
    """템플릿의 {seq} {date} {stem} 같은 자리를 채운다."""
    stat = path.stat()
    when = datetime.fromtimestamp(stat.st_mtime)
    values = {
        "seq": seq,
        "date": when.strftime(date_format),
        "time": when.strftime("%H%M%S"),
        "stem": path.stem,
        "ext": path.suffix,
        "name": path.name,
        "parent": path.parent.name,
        "size": stat.st_size,
    }
    try:
        return template.format(**values)
    except KeyError as e:
        raise ValueError(
            f"모르는 항목 {e}. 쓸 수 있는 것: {', '.join('{' + f + '}' for f in RENAME_FIELDS)}"
        ) from None
    except (IndexError, ValueError) as e:
        raise ValueError(f"템플릿이 잘못됐습니다: {e}") from None


def plan_rename(root: Path, template: str, *, glob: list[str] | None = None,
                recursive: bool = False, include_hidden: bool = False,
                sort: str = "name", start: int = 1, date_format: str = "%Y%m%d",
                replacements: list[tuple[str, str]] | None = None,
                regex: bool = False, case: str = "keep") -> list[Move]:
    """이름 바꾸기 계획. 파일 시스템은 건드리지 않는다."""
    patterns = glob or ["*"]
    found: list[Path] = []
    for pattern in patterns:
        walker = root.rglob(pattern) if recursive else root.glob(pattern)
        for p in walker:
            if not p.is_file() or p.is_symlink() or p in found:
                continue
            rel = p.relative_to(root).parts
            if not include_hidden and any(part.startswith(".") for part in rel):
                continue
            found.append(p)

    found.sort(key=lambda p: rename_sort_key(p, sort))

    planned: set[Path] = set()
    moves: list[Move] = []
    for i, src in enumerate(found, start):
        name = render_name(src, template, seq=i, date_format=date_format)
        for old, new in replacements or []:
            name = re.sub(old, new, name) if regex else name.replace(old, new)
        if case == "lower":
            name = name.lower()
        elif case == "upper":
            name = name.upper()

        name = sanitize_filename(name)
        dst = unique_path(src.with_name(name), planned)
        if dst == src:
            continue
        planned.add(dst)
        moves.append(Move(str(src), str(dst)))
    return moves


@dataclass
class ArchiveResult:
    archive: Path
    stored: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    raw_size: int = 0
    packed_size: int = 0

    @property
    def ratio(self) -> float:
        return self.packed_size / self.raw_size if self.raw_size else 0.0


def plan_archive(root: Path, *, glob: list[str] | None = None,
                 older_days: float = 0.0, include_hidden: bool = False,
                 recursive: bool = True) -> list[Path]:
    patterns = glob or ["*"]
    cutoff = time.time() - older_days * 86400
    found: list[Path] = []
    for pattern in patterns:
        walker = root.rglob(pattern) if recursive else root.glob(pattern)
        for p in walker:
            if not p.is_file() or p.is_symlink() or p in found:
                continue
            rel = p.relative_to(root).parts
            if not include_hidden and any(part.startswith(".") for part in rel):
                continue
            if older_days and p.stat().st_mtime > cutoff:
                continue
            found.append(p)
    return sorted(found)


def make_archive(root: Path, targets: list[Path], archive: Path, *,
                 remove: bool = False) -> ArchiveResult:
    """압축한 뒤 내용이 온전한지 확인하고, 그때만 원본을 지운다."""
    import zipfile

    result = ArchiveResult(archive)
    if not targets:
        return result

    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        raise RuntimeError(f"이미 있는 파일입니다: {archive}")

    sizes: dict[str, int] = {}
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in targets:
            name = str(path.relative_to(root))
            z.write(path, name)
            sizes[name] = path.stat().st_size
            result.stored.append(path)
            result.raw_size += sizes[name]
    result.packed_size = archive.stat().st_size

    # 지우기 전에 정말 다 들어갔는지 본다
    with zipfile.ZipFile(archive) as z:
        broken = z.testzip()
        if broken:
            result.failed.append(f"압축이 깨졌습니다: {broken}")
            return result
        inside = {info.filename: info.file_size for info in z.infolist()}
        for name, size in sizes.items():
            if inside.get(name) != size:
                result.failed.append(f"압축에 빠졌거나 크기가 다릅니다: {name}")

    if result.failed or not remove:
        return result

    for path in result.stored:
        try:
            path.unlink()
            result.removed.append(path)
        except OSError as e:
            result.failed.append(f"지우지 못했습니다: {path} ({e})")
    return result


@dataclass
class DirDiff:
    only_left: list[str] = field(default_factory=list)
    only_right: list[str] = field(default_factory=list)
    changed: list[tuple[str, int, int]] = field(default_factory=list)  # 경로, 왼쪽, 오른쪽
    same: int = 0

    @property
    def empty(self) -> bool:
        return not (self.only_left or self.only_right or self.changed)

    @property
    def total(self) -> int:
        return len(self.only_left) + len(self.only_right) + len(self.changed)


def _relative_files(root: Path, *, include_hidden: bool, glob: list[str] | None) -> dict[str, Path]:
    patterns = glob or ["*"]
    out: dict[str, Path] = {}
    for pattern in patterns:
        for p in root.rglob(pattern):
            if not p.is_file() or p.is_symlink():
                continue
            rel = p.relative_to(root)
            if not include_hidden and any(part.startswith(".") for part in rel.parts):
                continue
            if any(part in IGNORE_DIRS for part in rel.parts[:-1]):
                continue
            out[str(rel)] = p
    return out


def diff_dirs(left: Path, right: Path, *, include_hidden: bool = False,
              glob: list[str] | None = None, quick: bool = False) -> DirDiff:
    """두 디렉터리를 비교한다. 크기가 같으면 해시까지 봐야 진짜 같은지 안다."""
    a = _relative_files(left, include_hidden=include_hidden, glob=glob)
    b = _relative_files(right, include_hidden=include_hidden, glob=glob)

    result = DirDiff()
    result.only_left = sorted(set(a) - set(b))
    result.only_right = sorted(set(b) - set(a))

    for name in sorted(set(a) & set(b)):
        left_size = a[name].stat().st_size
        right_size = b[name].stat().st_size
        if left_size != right_size:
            result.changed.append((name, left_size, right_size))
            continue
        if quick or file_hash(a[name]) == file_hash(b[name]):
            result.same += 1
        else:
            result.changed.append((name, left_size, right_size))
    return result


CODE_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".go", ".rs", ".rb",
    ".php", ".c", ".h", ".cpp", ".hpp", ".cs", ".swift", ".sh", ".sql", ".vue",
    ".scala", ".ex", ".exs", ".lua", ".pl", ".r", ".m", ".dart",
}


def tracked_paths(root: Path) -> list[Path] | None:
    """git 이 무시하지 않는 파일 목록. git 저장소가 아니면 None.

    .gitignore 를 직접 해석하지 않고 git 에게 물어본다. 부정 패턴이나 **
    같은 규칙을 흉내 내다 어긋나는 것보다 낫다.
    """
    import subprocess

    try:
        # core.quotepath=false 를 안 주면 한글 파일명이 8진수로 이스케이프돼 나온다
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=false",
             "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return [root / name for name in proc.stdout.splitlines() if name.strip()]


def count_lines(path: Path, *, limit: int = 2_000_000) -> int | None:
    try:
        if path.stat().st_size > limit:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8000]:
        return None
    return data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1)


@dataclass
class TreeNode:
    name: str
    path: Path
    is_dir: bool
    children: list["TreeNode"] = field(default_factory=list)
    size: int = 0
    lines: int | None = None

    @property
    def total_size(self) -> int:
        return self.size + sum(c.total_size for c in self.children)

    @property
    def total_lines(self) -> int:
        return (self.lines or 0) + sum(c.total_lines for c in self.children)

    @property
    def file_count(self) -> int:
        return (0 if self.is_dir else 1) + sum(c.file_count for c in self.children)


def build_tree(root: Path, *, depth: int = 0, use_git: bool = True,
               glob: list[str] | None = None, with_lines: bool = False) -> TreeNode:
    root = root.resolve()
    paths = tracked_paths(root) if use_git else None
    if paths is None:
        paths = [p for p in root.rglob("*")
                 if p.is_file() and not any(part in IGNORE_DIRS or part.startswith(".")
                                            for part in p.relative_to(root).parts)]

    if glob:
        from fnmatch import fnmatch

        paths = [p for p in paths
                 if any(fnmatch(p.name, g) or fnmatch(str(p.relative_to(root)), g)
                        for g in glob)]

    tree = TreeNode(root.name or str(root), root, True)
    index: dict[Path, TreeNode] = {root: tree}

    for path in sorted(paths):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if depth and len(rel.parts) > depth:
            rel = Path(*rel.parts[:depth])          # 깊이를 넘으면 그 위 디렉터리로 접는다
            if root / rel in index:
                continue

        parent = tree
        for i, part in enumerate(rel.parts[:-1], 1):
            key = root.joinpath(*rel.parts[:i])
            node = index.get(key)
            if node is None:
                node = TreeNode(part, key, True)
                index[key] = node
                parent.children.append(node)
            parent = node

        leaf_path = root / rel
        if leaf_path in index:
            continue
        leaf = TreeNode(rel.parts[-1], leaf_path, not leaf_path.is_file())
        if leaf_path.is_file():
            try:
                leaf.size = leaf_path.stat().st_size
            except OSError:
                leaf.size = 0
            if with_lines and leaf_path.suffix.lower() in CODE_SUFFIXES:
                leaf.lines = count_lines(leaf_path)
        index[leaf_path] = leaf
        parent.children.append(leaf)

    def order(node: TreeNode) -> None:
        node.children.sort(key=lambda c: (not c.is_dir, c.name.lower()))
        for child in node.children:
            order(child)

    order(tree)
    return tree


def render_tree(node: TreeNode, *, prefix: str = "", show_lines: bool = False,
                show_size: bool = False, is_last: bool = True,
                is_root: bool = True) -> list[str]:
    label = node.name + ("/" if node.is_dir else "")
    extra = []
    if show_lines and node.lines:
        extra.append(f"{node.lines:,}줄")
    if show_size and not node.is_dir:
        extra.append(human_size(node.size))
    suffix = f"  {' · '.join(extra)}" if extra else ""

    if is_root:
        rows = [label + suffix]
        child_prefix = ""
    else:
        rows = [f"{prefix}{'└─ ' if is_last else '├─ '}{label}{suffix}"]
        child_prefix = prefix + ("   " if is_last else "│  ")

    for i, child in enumerate(node.children):
        rows += render_tree(child, prefix=child_prefix, show_lines=show_lines,
                            show_size=show_size, is_last=i == len(node.children) - 1,
                            is_root=False)
    return rows


def language_summary(node: TreeNode) -> list[tuple[str, int, int]]:
    """(확장자, 파일 수, 줄 수) - 줄 수가 많은 순."""
    table: dict[str, list[int]] = {}

    def visit(n: TreeNode) -> None:
        if not n.is_dir:
            key = n.path.suffix.lower() or "(확장자 없음)"
            row = table.setdefault(key, [0, 0])
            row[0] += 1
            row[1] += n.lines or 0
        for child in n.children:
            visit(child)

    visit(node)
    return sorted(((k, *v) for k, v in table.items()), key=lambda x: (-x[2], -x[1]))


def recent_files(root: Path, *, days: float = 1.0, glob: list[str] | None = None,
                 include_hidden: bool = False, use_git: bool = False,
                 limit: int = 0) -> list[tuple[Path, float, int]]:
    """최근에 손댄 파일. (경로, 수정 시각, 크기) 를 최신 순으로."""
    cutoff = time.time() - days * 86400
    candidates: list[Path]

    tracked = tracked_paths(root) if use_git else None
    if tracked is not None:
        candidates = tracked
    else:
        candidates = [p for p in root.rglob("*")
                      if p.is_file() and not p.is_symlink()
                      and not any(part in IGNORE_DIRS
                                  for part in p.relative_to(root).parts[:-1])]

    if glob:
        from fnmatch import fnmatch

        candidates = [p for p in candidates
                      if any(fnmatch(p.name, g) for g in glob)]

    found: list[tuple[Path, float, int]] = []
    for path in candidates:
        rel = path.relative_to(root).parts
        if not include_hidden and any(part.startswith(".") for part in rel):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime < cutoff:
            continue
        found.append((path, stat.st_mtime, stat.st_size))

    found.sort(key=lambda item: -item[1])
    return found[:limit] if limit else found


def day_label(stamp: float, *, today: datetime | None = None) -> str:
    """오늘·어제·그저께는 이름으로, 그보다 오래면 날짜로."""
    when = datetime.fromtimestamp(stamp)
    today = today or datetime.now()
    delta = (today.date() - when.date()).days
    return {0: "오늘", 1: "어제", 2: "그저께"}.get(delta, f"{when:%Y-%m-%d}")


HASH_ALGORITHMS = {"sha256": "sha256", "sha1": "sha1", "md5": "md5",
                   "blake2": "blake2b"}


def digest(path: Path, algorithm: str = "sha256", *, chunk: int = 1 << 20) -> str:
    name = HASH_ALGORITHMS.get(algorithm)
    if name is None:
        raise ValueError(f"모르는 방식입니다: {algorithm} "
                         f"({', '.join(HASH_ALGORITHMS)})")
    h = hashlib.new(name)
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


@dataclass
class CheckResult:
    ok: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    malformed: list[tuple[int, str]] = field(default_factory=list)

    @property
    def failed(self) -> int:
        return len(self.changed) + len(self.missing) + len(self.malformed)


def write_sums(root: Path, targets: list[Path], algorithm: str = "sha256") -> list[str]:
    """sha256sum 과 같은 형식으로 줄을 만든다. 다른 도구로도 검증할 수 있다."""
    lines = []
    for path in targets:
        rel = path.relative_to(root) if path.is_relative_to(root) else path
        lines.append(f"{digest(path, algorithm)}  {rel}")
    return lines


def check_sums(root: Path, lines: list[str], algorithm: str = "sha256") -> CheckResult:
    result = CheckResult()
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2 or not parts[0]:
            result.malformed.append((number, line[:60]))
            continue
        expected, name = parts[0].strip(), parts[1].strip()
        target = root / name
        if not target.is_file():
            result.missing.append(name)
            continue
        result.ok.append(name) if digest(target, algorithm) == expected \
            else result.changed.append(name)
    return result
