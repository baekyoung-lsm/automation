"""파일 정리: 분류 이동, 이름 정규화, 중복 탐지, 되돌리기."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

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


def read_journal(journal: Path) -> list[Move]:
    """저널에 적힌 옮김들. 되돌린 뒤 뒷정리에도 쓴다."""
    lines = Path(journal).read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        if not line.strip():
            continue
        entry = json.loads(line)
        out.append(Move(entry["src"], entry["dst"]))
    return out


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
        try:
            dst.replace(src)
        except OSError:
            # 다른 파티션으로 옮겼던 것은 replace 가 안 된다 (옮길 때도
            # shutil.move 를 썼다). 여기서 터지면 되돌리기가 통째로 멎는다
            try:
                shutil.move(str(dst), str(src))
            except OSError as exc:
                errors.append(f"되돌리지 못함: {dst} ({exc})")
                continue
        restored += 1
    return restored, errors


def prune_empty_dirs(paths, *, stop: Path | None = None) -> int:
    """옮겨 간 자리에 남은 빈 폴더를 지운다. (지운 개수)

    되돌린 뒤에 «문서/», «이미지/» 가 빈 채로 남으면 되돌리기가 안 끝난 것처럼
    보인다. 비어 있을 때만, stop 아래에서만 지운다 - 파일이 하나라도 남아 있는
    폴더는 건드리지 않는다.
    """
    removed = 0
    stop = Path(stop).resolve() if stop else None
    for path in {Path(one).resolve() for one in paths}:
        here = path
        while here.is_dir():
            if stop is not None and (here == stop or stop not in here.parents):
                break
            try:
                next(here.iterdir())
                break                 # 아직 뭔가 들어 있다
            except StopIteration:
                pass
            except OSError:
                break
            try:
                here.rmdir()
            except OSError:
                break
            removed += 1
            here = here.parent
    return removed


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


KEEP_MODES = {
    "shortest": "경로가 가장 짧은 것 (대개 원본 자리)",
    "first": "이름 순으로 첫 번째",
    "oldest": "수정 시각이 가장 이른 것",
}


def pick_keeper(group: list[Path], mode: str = "shortest") -> Path:
    """중복 무리에서 남길 하나를 고른다."""
    if mode == "first":
        return sorted(group)[0]
    if mode == "oldest":
        return min(group, key=lambda p: (p.stat().st_mtime, str(p)))
    if mode == "shortest":
        return min(group, key=lambda p: (len(p.parts), len(str(p)), str(p)))
    raise ValueError(f"알 수 없는 기준: {mode} ({', '.join(KEEP_MODES)})")


def plan_collect_dupes(root: Path, groups: list[list[Path]], dest: Path, *,
                       keep: str = "shortest") -> list[Move]:
    """중복 파일을 지우지 않고 한 폴더로 모으는 계획.

    지우는 대신 옮기는 이유: 옮기면 저널에 남아 at file undo 로 통째로
    되돌아온다. 정말 지울지는 모아 놓은 폴더를 눈으로 보고 정하면 된다.
    무리마다 하나는 반드시 제자리에 남긴다.
    """
    root, dest = root.resolve(), dest.resolve()
    planned: set[Path] = set()
    moves: list[Move] = []

    for group in groups:
        keeper = pick_keeper(group, keep)
        for path in sorted(group):
            if path == keeper or dest in path.parents:
                continue
            try:
                relative = path.resolve().relative_to(root)
            except ValueError:
                relative = Path(path.name)
            target = unique_path(dest / relative, planned)
            planned.add(target)
            moves.append(Move(str(path), str(target)))
    return moves


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


@dataclass
class FileRow:
    path: Path
    relative: str          # 뿌리에서 본 경로
    folder: str            # 상위 폴더 (뿌리면 빈 문자열)
    name: str
    suffix: str
    size: int
    modified: datetime


LIST_SORTS = {"name": "이름", "size": "크기", "date": "수정일",
              "ext": "확장자"}


def list_files(root: Path, *, recursive: bool = True, include_hidden: bool = False,
               glob: list[str] | None = None, sort: str = "name") -> list[FileRow]:
    """폴더 안 파일을 표로 만들 수 있게 모은다.

    «제출 자료 목록»을 손으로 옮겨 적는 일이 잦다. 이름·크기·수정일을 그대로
    뽑아 두면 엑셀에 붙여 쓸 수 있다.
    """
    if sort not in LIST_SORTS:
        raise ValueError(f"알 수 없는 정렬: {sort} ({', '.join(LIST_SORTS)})")

    root = root.resolve()
    patterns = glob or ["*"]
    seen: set[Path] = set()
    out: list[FileRow] = []

    for pattern in patterns:
        walker = root.rglob(pattern) if recursive else root.glob(pattern)
        for path in walker:
            if path in seen or not path.is_file() or path.is_symlink():
                continue
            parts = path.relative_to(root).parts
            if not include_hidden and any(p.startswith(".") for p in parts):
                continue
            seen.add(path)
            stat = path.stat()
            out.append(FileRow(
                path=path,
                relative=str(path.relative_to(root)),
                folder=str(Path(*parts[:-1])) if len(parts) > 1 else "",
                name=path.name,
                suffix=path.suffix.lower().lstrip("."),
                size=stat.st_size,
                modified=datetime.fromtimestamp(stat.st_mtime),
            ))

    keys = {"name": lambda r: (r.folder, r.name.lower()),
            "size": lambda r: -r.size,
            "date": lambda r: -r.modified.timestamp(),
            "ext": lambda r: (r.suffix, r.name.lower())}
    out.sort(key=keys[sort])
    return out


# ------------------------------------------------- 문서 속성 (누가 만든 문서인가)

OOXML_KINDS = {".docx": "워드", ".docm": "워드", ".xlsx": "엑셀",
               ".xlsm": "엑셀", ".pptx": "슬라이드", ".pptm": "슬라이드",
               ".hwpx": "한글"}
CORE_PART = "docProps/core.xml"
APP_PART = "docProps/app.xml"
HWPX_PART = "Contents/content.hpf"      # 한글은 여기에 속성을 담는다
CORE_FIELDS = {                      # core.xml 의 태그 -> 우리 이름
    "title": "title", "subject": "subject", "creator": "author",
    "lastModifiedBy": "last_by", "created": "created", "modified": "modified",
    "revision": "revision", "keywords": "keywords",
}
APP_FIELDS = {"Pages": "pages", "Words": "words", "Slides": "slides",
              "Company": "company", "Application": "program"}


@dataclass
class DocMeta:
    path: Path
    kind: str
    title: str = ""
    subject: str = ""
    author: str = ""            # 만든 사람 (dc:creator)
    last_by: str = ""           # 마지막으로 저장한 사람
    created: str = ""
    modified: str = ""
    revision: str = ""
    keywords: str = ""
    company: str = ""
    program: str = ""           # 무엇으로 만들었나 (한글, LibreOffice …)
    pages: int | None = None
    text_pages: int | None = None   # PDF 에서 글꼴이 걸린 쪽 (0 이면 스캔본)
    words: int | None = None
    slides: int | None = None
    size: int = 0
    error: str = ""             # 못 읽었으면 그 까닭

    @property
    def personal(self) -> list[str]:
        """밖으로 보낼 때 눈에 걸리는 것 - 사람 이름과 회사 이름."""
        return [v for v in (self.author, self.last_by, self.company) if v]


def _xml_texts(raw: bytes) -> dict[str, str]:
    """이름 공간을 떼고 «태그 이름 -> 글자» 로. 속성은 보지 않는다."""
    import xml.etree.ElementTree as ET

    out: dict[str, str] = {}
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return out
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        text = (node.text or "").strip()
        if text and tag not in out:
            out[tag] = text
    return out


def document_meta(path: Path) -> DocMeta:
    """워드·엑셀·슬라이드 파일의 속성을 읽는다. 내용은 열지 않는다.

    문서를 밖으로 보낼 때 «작성자» 에 사내 계정 이름이 그대로 남아 있는 일이
    잦다. 읽지 못하면 빈 칸으로 두지 않고 까닭을 적는다 - 빈 칸은 «속성이
    없다» 로 읽히지만 실제로는 못 읽은 것일 수 있다.
    """
    import zipfile

    meta = DocMeta(path=path, kind=OOXML_KINDS.get(path.suffix.lower(), "문서"))
    try:
        meta.size = path.stat().st_size
    except OSError:
        pass

    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if HWPX_PART in names:        # 한글 문서
                core = _xml_texts(z.read(HWPX_PART))
                app = {}
            elif CORE_PART in names or APP_PART in names:
                core = _xml_texts(z.read(CORE_PART)) if CORE_PART in names else {}
                app = _xml_texts(z.read(APP_PART)) if APP_PART in names else {}
            else:
                meta.error = "문서 속성이 없습니다"
                return meta
    except zipfile.BadZipFile:
        meta.error = "열지 못했습니다 (이름만 바꾼 옛 형식일 수 있습니다)"
        return meta
    except OSError as e:
        meta.error = str(e)
        return meta

    for tag, field_name in CORE_FIELDS.items():
        if tag in core:
            setattr(meta, field_name, core[tag])
    for tag, field_name in APP_FIELDS.items():
        if tag not in app:
            continue
        value = app[tag]
        if field_name in ("pages", "words", "slides"):
            setattr(meta, field_name, int(value) if value.isdigit() else None)
        else:
            setattr(meta, field_name, value)
    return meta


# ------------------------------------------------------------------- PDF 속성

PDF_SUFFIXES = {".pdf"}


def pdf_meta(path: Path) -> DocMeta:
    """PDF 의 제목·만든 사람·쪽 수를 문서 속성 표에 맞춰 담는다.

    읽는 일은 pdf.py 가 한다. 여기서는 워드·한글과 같은 표에 놓기만 한다.
    """
    from . import pdf as pdfkit

    meta = DocMeta(path=path, kind="PDF")
    try:
        meta.size = path.stat().st_size
    except OSError:
        pass

    info = pdfkit.read_info(path)
    meta.title, meta.author = info.title, info.author
    meta.subject, meta.keywords = info.subject, info.keywords
    meta.created, meta.modified = info.created, info.modified
    meta.program = info.program or info.version
    meta.pages = info.pages
    meta.text_pages = info.text_pages
    meta.error = info.error
    return meta


SCRUB_TAGS = {                       # 지울 자리 -> 사람이 읽는 이름
    "creator": "만든 사람",
    "lastModifiedBy": "마지막 저장한 사람",
    "Company": "회사",
    "Manager": "관리자",
}
SCRUB_PARTS = (CORE_PART, APP_PART, HWPX_PART)
COMMENT_PARTS = ("word/comments.xml", "xl/persons/person.xml",
                 "word/people.xml", "ppt/comments")


@dataclass
class ScrubPlan:
    path: Path
    removed: list = field(default_factory=list)     # [(사람이 읽는 이름, 값)]
    others: list = field(default_factory=list)      # 메모·변경 내역이 있는 자리
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.removed)


def _blank_tag(xml: str, tag: str) -> tuple[str, str]:
    """<dc:creator>김철수</dc:creator> 를 빈 것으로. (새 xml, 지운 값)

    ET 로 다시 쓰면 이름 공간 접두사가 바뀌어 워드가 열지 못하는 일이 있다.
    그래서 태그 안쪽 글자만 바꾼다 - 나머지는 원문 그대로 둔다.
    """
    pattern = re.compile(
        rf"(<(?:\w+:)?{tag}(?:\s[^>]*)?>)(.*?)(</(?:\w+:)?{tag}>)", re.S)
    match = pattern.search(xml)
    if not match or not match.group(2).strip():
        return xml, ""
    return (xml[:match.start()] + match.group(1) + match.group(3)
            + xml[match.end():], match.group(2).strip())


def _plan_scrub_pdf(path: Path) -> ScrubPlan:
    """PDF 는 속성(Info)과 XMP 에 이름이 남는다."""
    from . import pdf as pdfkit

    plan = ScrubPlan(path=path)
    try:
        doc = pdfkit.open_pdf(path)
        plan.removed = pdfkit.scrub_names(doc)
        if any("Annots" in page.data for page in doc.pages()):
            plan.others = ["주석(코멘트)"]
    except (pdfkit.PdfError, OSError, ValueError) as e:
        plan.error = str(e)
    return plan


def plan_scrub(path: Path) -> ScrubPlan:
    """이 문서에서 지울 수 있는 이름을 본다. 파일은 건드리지 않는다."""
    import zipfile

    if path.suffix.lower() in PDF_SUFFIXES:
        return _plan_scrub_pdf(path)

    plan = ScrubPlan(path=path)
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            for part in SCRUB_PARTS:
                if part not in names:
                    continue
                xml = z.read(part).decode("utf-8", errors="replace")
                for tag, label in SCRUB_TAGS.items():
                    xml, gone = _blank_tag(xml, tag)
                    if gone:
                        plan.removed.append((label, gone))
            plan.others = [n for n in names
                           if any(n.startswith(p) for p in COMMENT_PARTS)]
    except zipfile.BadZipFile:
        plan.error = "열지 못했습니다 (이름만 바꾼 옛 형식일 수 있습니다)"
    except OSError as e:
        plan.error = str(e)
    return plan


def apply_scrub(path: Path, dest: Path) -> Path:
    """이름을 지운 사본을 만든다. 원본은 그대로 둔다.

    제자리에서 고치지 않는 것은 되돌릴 방법이 없기 때문이다. 문서 안의
    메모·변경 내역에 남은 이름은 지우지 못한다 - 그건 내용이라 여기서
    손대면 문서가 달라진다.

    PDF 는 고친 자리만 덧붙이지 않고 파일을 다시 쓴다. 덧붙이면 옛 이름이
    파일 안에 그대로 남아 꺼내 볼 수 있기 때문이다.
    """
    import zipfile

    if path.suffix.lower() in PDF_SUFFIXES:
        from . import pdf as pdfkit

        dest.parent.mkdir(parents=True, exist_ok=True)
        pdfkit.scrub_pdf(pdfkit.open_pdf(path), dest)
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as src:
        items = src.infolist()
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as out:
            for item in items:
                data = src.read(item.filename)
                if item.filename in SCRUB_PARTS:
                    xml = data.decode("utf-8", errors="replace")
                    for tag in SCRUB_TAGS:
                        xml, _gone = _blank_tag(xml, tag)
                    data = xml.encode("utf-8")
                out.writestr(item, data)
    return dest


def meta_of(path: Path) -> DocMeta:
    """확장자에 맞는 속성 읽기를 고른다."""
    return (pdf_meta(path) if path.suffix.lower() in PDF_SUFFIXES
            else document_meta(path))


def scan_documents(root: Path, *, recursive: bool = True,
                   include_hidden: bool = False,
                   pdf: bool = True) -> list[DocMeta]:
    """폴더 안의 워드·엑셀·슬라이드(·PDF) 파일 속성을 모은다."""
    kinds = set(OOXML_KINDS) | (PDF_SUFFIXES if pdf else set())
    if root.is_file():
        return [meta_of(root)] if root.suffix.lower() in kinds else []
    out: list[DocMeta] = []
    walker = root.rglob("*") if recursive else root.glob("*")
    for path in sorted(walker):
        if not path.is_file() or path.suffix.lower() not in kinds:
            continue
        parts = path.relative_to(root).parts
        if not include_hidden and any(p.startswith(("~$", ".")) for p in parts):
            continue
        out.append(meta_of(path))
    return out


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


# ------------------------------------------------------- 폴더 한 번에 훑기

# 압축·공유 과정에서 딸려 오는 찌꺼기. 지우지는 않고 알리기만 한다.
JUNK_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", "__MACOSX"}
JUNK_PREFIX = ("~$",)                 # 워드·엑셀이 열어 둔 동안 만드는 임시 파일
WINDOWS_BAD = set('\\/:*?"<>|')      # 윈도우에서 못 쓰는 글자
NAME_BYTES = 255                      # 파일 이름 길이 한도 (대개 바이트 기준)


@dataclass
class FolderNote:
    kind: str                 # 중복 · 이름 · 찌꺼기 · 빈 파일 · 큰 파일 · 구성
    detail: str
    samples: list[str] = field(default_factory=list)


@dataclass
class FolderReport:
    root: Path
    files: int = 0
    total: int = 0
    notes: list[FolderNote] = field(default_factory=list)
    looked: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def audit_folder(root: Path, *, recursive: bool = True,
                 include_hidden: bool = False, dupes: bool = True,
                 samples: int = 5) -> FolderReport:
    """받은 폴더를 한 번에 훑는다. 고치지 않고 «볼 만한 곳» 만 모은다.

    납품 자료·제출 자료를 받아 열었을 때 무엇부터 봐야 하는지 알려 준다.
    무엇을 봤는지와 못 봤는지를 함께 적는다 - «문제 없음» 이 «다 봤다» 로
    읽히면 안 된다.
    """
    root = Path(root)
    report = FolderReport(root)
    report.looked = ["파일 구성", "이름에 문제가 있는 파일", "빈 파일",
                     "찌꺼기 파일", "큰 파일"]
    if dupes:
        report.looked.append("내용이 같은 파일")
    else:
        report.skipped.append("내용이 같은 파일은 보지 않았습니다 (--no-dupes)")

    targets = sorted(iter_targets(root, recursive=recursive,
                                  include_hidden=include_hidden))
    report.files = len(targets)
    if not targets:
        report.skipped.append("파일이 없어 아무것도 보지 못했습니다.")
        return report

    kinds: dict[str, int] = {}
    empty: list[Path] = []
    junk: list[Path] = []
    bad_names: list[tuple[Path, str]] = []
    biggest: list[tuple[int, Path]] = []

    for path in targets:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        report.total += size
        suffix = path.suffix.lower() or "(확장자 없음)"
        kinds[suffix] = kinds.get(suffix, 0) + 1
        biggest.append((size, path))
        if size == 0:
            empty.append(path)
        if path.name in JUNK_NAMES or path.name.startswith(JUNK_PREFIX):
            junk.append(path)
            continue

        why = []
        if is_decomposed(path.name):
            why.append("자모가 분리된 한글 (맥에서 만든 이름)")
        if set(path.name) & WINDOWS_BAD:
            why.append("윈도우에서 못 쓰는 글자")
        if len(path.name.encode("utf-8")) > NAME_BYTES:
            why.append("이름이 너무 김")
        if path.name != path.name.strip() or "  " in path.name:
            why.append("앞뒤·가운데 공백")
        if why:
            bad_names.append((path, ", ".join(why)))

    order = sorted(kinds.items(), key=lambda x: -x[1])
    report.notes.append(FolderNote(
        "구성", f"파일 {len(targets):,}개 · {human_size(report.total)}",
        [f"{name} {count:,}개" for name, count in order[:samples]]))

    if bad_names:
        report.notes.append(FolderNote(
            "이름", f"손볼 이름 {len(bad_names):,}개 (at file fixname 으로 정리)",
            [f"{p.relative_to(root)} - {why}" for p, why in bad_names[:samples]]))
    if junk:
        report.notes.append(FolderNote(
            "찌꺼기", f"딸려 온 파일 {len(junk):,}개",
            [str(p.relative_to(root)) for p in junk[:samples]]))
    if empty:
        report.notes.append(FolderNote(
            "빈 파일", f"크기가 0인 파일 {len(empty):,}개",
            [str(p.relative_to(root)) for p in empty[:samples]]))

    biggest.sort(key=lambda x: -x[0])
    if biggest:
        report.notes.append(FolderNote(
            "큰 파일", f"가장 큰 것 {human_size(biggest[0][0])}",
            [f"{p.relative_to(root)} {human_size(size)}"
             for size, p in biggest[:samples]]))

    if dupes:
        groups = find_duplicates(root, recursive=recursive,
                                 include_hidden=include_hidden)
        if groups:
            wasted = sum(g[0].stat().st_size * (len(g) - 1) for g in groups)
            report.notes.append(FolderNote(
                "중복", f"내용이 같은 파일 {len(groups):,}묶음 "
                        f"· 겹치는 용량 {human_size(wasted)} "
                        "(at file dupes 로 자세히)",
                [" = ".join(str(p.relative_to(root)) for p in g[:3])
                 for g in groups[:samples]]))
    return report


# ------------------------------------------------------- 첨부용 나눠 담기

@dataclass
class Pack:
    index: int
    files: list[Path] = field(default_factory=list)
    size: int = 0                 # 원본 크기의 합


def parse_size(text: str) -> int:
    """'25MB', '20m', '1.5GiB' 를 바이트로. 단위가 없으면 MB 로 본다.

    메일 첨부 한도를 사람은 «25MB» 라고 말한다. 숫자만 받으면 25바이트로
    읽히는 실수가 반드시 한 번은 난다.
    """
    body = str(text).strip().replace(",", "").replace(" ", "").upper()
    hit = re.fullmatch(r"([0-9]*\.?[0-9]+)(B|K|KB|KIB|M|MB|MIB|G|GB|GIB)?", body)
    if not hit:
        raise ValueError(f"크기를 읽지 못했습니다: {text} (예: 25MB)")
    scale = {None: 1024 ** 2, "B": 1, "K": 1024, "KB": 1024, "KIB": 1024,
             "M": 1024 ** 2, "MB": 1024 ** 2, "MIB": 1024 ** 2,
             "G": 1024 ** 3, "GB": 1024 ** 3, "GIB": 1024 ** 3}[hit.group(2)]
    size = float(hit.group(1)) * scale
    if size <= 0:
        raise ValueError("크기는 0보다 커야 합니다.")
    return int(size)


# zip 은 항목마다 머리말이 두 벌 붙고 끝에 목록이 하나 더 붙는다. 원본 크기만
# 세어 한도에 딱 맞추면 만들어진 zip 이 한도를 아슬아슬하게 넘는다.
ZIP_TAIL = 1024
ZIP_ENTRY_OVERHEAD = 120


def _entry_cost(path: Path, size: int) -> int:
    return size + ZIP_ENTRY_OVERHEAD + 2 * len(str(path).encode("utf-8"))


def plan_packs(files: list[Path], *, max_bytes: int) -> tuple[list[Pack], list[tuple[Path, int]]]:
    """한도 안에 들어가도록 파일을 묶는다. (묶음들, 혼자서 한도를 넘는 파일들)

    압축한 크기가 아니라 «원본 크기» 로 묶는다. jpg·zip 처럼 이미 눌린 것은
    압축해도 안 줄어들어서, 압축 결과를 낙관하면 한도를 넘긴 첨부가 나온다.
    zip 자체가 차지하는 자리도 미리 빼 둔다.
    """
    budget = max_bytes - ZIP_TAIL
    if budget <= 0:
        raise ValueError(f"한도가 너무 작습니다: {max_bytes} B")

    sized = []
    too_big: list[tuple[Path, int]] = []
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if _entry_cost(path, size) > budget:
            too_big.append((path, size))
        else:
            sized.append((path, size))

    packs: list[Pack] = []
    costs: dict[int, int] = {}
    for path, size in sorted(sized, key=lambda x: -x[1]):    # 큰 것부터 담는다
        cost = _entry_cost(path, size)
        for pack in packs:
            if costs[pack.index] + cost <= budget:
                pack.files.append(path)
                pack.size += size
                costs[pack.index] += cost
                break
        else:
            packs.append(Pack(len(packs) + 1, [path], size))
            costs[len(packs)] = cost
    for pack in packs:
        pack.files.sort()
    return packs, sorted(too_big, key=lambda x: -x[1])


def human_size(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TiB"


RENAME_FIELDS = ("seq", "date", "time", "taken", "taken_time", "stem",
                 "ext", "name", "parent", "size")
TAKEN_FIELDS = ("taken", "taken_time")


def rename_sort_key(path: Path, mode: str):
    stat = path.stat()
    if mode == "date":
        return (stat.st_mtime, str(path))
    if mode == "size":
        return (-stat.st_size, str(path))
    return (str(path).lower(),)


def wants_taken(template: str) -> bool:
    """템플릿이 촬영 시각을 쓰는지. 쓸 때만 EXIF 를 읽는다."""
    return any("{" + field in template for field in TAKEN_FIELDS)


def render_name(path: Path, template: str, *, seq: int,
                date_format: str = "%Y%m%d",
                taken: datetime | None = None) -> str:
    """템플릿의 {seq} {date} {stem} 같은 자리를 채운다.

    {taken} 은 사진을 찍은 시각이다. 수정 시각({date})과 달라서 따로 둔다 -
    복사한 사진은 수정 시각이 복사한 날로 바뀌어 있다.
    """
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
    if taken is not None:
        values["taken"] = taken.strftime(date_format)
        values["taken_time"] = taken.strftime("%H%M%S")
    try:
        return template.format(**values)
    except KeyError as e:
        if str(e).strip("'") in TAKEN_FIELDS:
            raise ValueError(
                f"촬영 시각(EXIF)을 읽지 못했습니다: {path.name}") from None
        raise ValueError(
            f"모르는 항목 {e}. 쓸 수 있는 것: {', '.join('{' + f + '}' for f in RENAME_FIELDS)}"
        ) from None
    except (IndexError, ValueError) as e:
        raise ValueError(f"템플릿이 잘못됐습니다: {e}") from None


@dataclass
class RenamePlan:
    moves: list[Move] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)   # 촬영 시각이 없어 건너뜀


def plan_rename(root: Path, template: str, **kwargs) -> list[Move]:
    """이름 바꾸기 계획(옮길 목록만). 건너뛴 것까지 보려면 plan_rename_report."""
    return plan_rename_report(root, template, **kwargs).moves


def plan_rename_report(root: Path, template: str, *, glob: list[str] | None = None,
                       recursive: bool = False, include_hidden: bool = False,
                       sort: str = "name", start: int = 1,
                       date_format: str = "%Y%m%d",
                       replacements: list[tuple[str, str]] | None = None,
                       regex: bool = False, case: str = "keep") -> RenamePlan:
    """이름 바꾸기 계획. 파일 시스템은 건드리지 않는다.

    {taken} 을 쓰는데 EXIF 가 없는 파일은 이름을 짓지 않고 건너뛴다. 수정
    시각으로 몰래 대신하면 촬영일이라고 적힌 틀린 이름이 남는다.
    """
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

    plan = RenamePlan()
    planned: set[Path] = set()
    needs_taken = wants_taken(template)
    for i, src in enumerate(found, start):
        taken = exif_datetime(src) if needs_taken else None
        if needs_taken and taken is None:
            plan.skipped.append(src)
            continue
        name = render_name(src, template, seq=i, date_format=date_format,
                           taken=taken)
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
        plan.moves.append(Move(str(src), str(dst)))
    return plan


@dataclass
class MapRenamePlan:
    moves: list[Move] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)     # 목록엔 있는데 폴더에 없음
    untouched: list[str] = field(default_factory=list)   # 폴더엔 있는데 목록에 없음
    same: list[str] = field(default_factory=list)        # 이름이 이미 같음


def plan_rename_map(root: Path, mapping: list[tuple[str, str]], *,
                    recursive: bool = False) -> MapRenamePlan:
    """«현재 이름 -> 새 이름» 목록대로 이름을 바꾸는 계획.

    목록에 있는데 폴더에 없는 이름, 폴더에 있는데 목록에 없는 파일을 모두
    알려 준다. 조용히 넘기면 «몇 개는 바뀌고 몇 개는 안 바뀐» 폴더가 남고,
    무엇이 안 바뀌었는지 나중에는 알 수 없다.
    """
    walker = root.rglob("*") if recursive else root.glob("*")
    found = {p.name: p for p in sorted(walker) if p.is_file() and not p.is_symlink()}

    plan = MapRenamePlan()
    planned: set[Path] = set()
    used: set[str] = set()
    for old, new in mapping:
        old, new = old.strip(), new.strip()
        if not old or not new:
            continue
        src = found.get(old)
        if src is None:
            plan.missing.append(old)
            continue
        used.add(old)
        name = sanitize_filename(new)
        if not Path(name).suffix and src.suffix:      # 확장자를 빠뜨렸으면 살려 준다
            name += src.suffix
        if src.with_name(name) == src:      # 이미 그 이름이다
            plan.same.append(old)
            continue
        dst = unique_path(src.with_name(name), planned)
        planned.add(dst)
        plan.moves.append(Move(str(src), str(dst)))

    plan.untouched = sorted(name for name in found if name not in used)
    return plan


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


# ------------------------------------------------------- 백업 폴더에 맞춰 넣기

OLD_VERSIONS_DIR = ".이전 (attools)"      # 덮어쓰기 전의 것을 여기 옮겨 둔다


@dataclass
class SyncPlan:
    new: list = field(default_factory=list)        # 백업에 없는 파일 (상대 경로)
    changed: list = field(default_factory=list)    # 내용이 다른 파일
    extra: list = field(default_factory=list)      # 백업에만 있는 파일
    same: int = 0
    bytes: int = 0                                 # 새로 넣을 용량

    @property
    def empty(self) -> bool:
        return not (self.new or self.changed)


def plan_sync(source: Path, backup: Path, *, include_hidden: bool = False,
              glob: list[str] | None = None, quick: bool = False) -> SyncPlan:
    """원본에서 백업으로 무엇을 넣어야 하는지 센다. 아무것도 건드리지 않는다."""
    diff = diff_dirs(source, backup, include_hidden=include_hidden, glob=glob,
                     quick=quick)
    plan = SyncPlan(new=list(diff.only_left),
                    changed=[name for name, _l, _r in diff.changed],
                    extra=[name for name in diff.only_right
                           if not name.startswith(OLD_VERSIONS_DIR)],
                    same=diff.same)
    for name in plan.new + plan.changed:
        try:
            plan.bytes += (source / name).stat().st_size
        except OSError:
            pass
    return plan


def apply_sync(source: Path, backup: Path, plan: SyncPlan, *,
               keep_old: bool = True, remove_extra: bool = False,
               stamp: str = "") -> tuple[int, int, list]:
    """계획대로 넣는다. (넣은 개수, 지운 개수, 못 한 것)

    덮어쓰기 전의 파일은 백업 폴더 안 «.이전 (attools)/<시각>/» 으로 옮겨
    둔다 - 백업이 원본을 덮어 쓰는 순간 예전 판이 사라지는데, 사람이 원하는
    것은 대개 그 예전 판이다.
    """
    import shutil

    when = stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    kept = backup / OLD_VERSIONS_DIR / when
    copied = removed = 0
    failed: list = []

    for name in plan.new + plan.changed:
        src, dst = source / name, backup / name
        try:
            if keep_old and dst.exists():
                old = kept / name
                old.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst), str(old))
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
        except OSError as exc:
            failed.append((name, str(exc)))

    if remove_extra:
        for name in plan.extra:
            target = backup / name
            if not target.is_file():
                failed.append((name, "지울 파일이 없습니다"))
                continue
            try:
                if keep_old:                 # 지우기 전에도 한 벌 남긴다
                    old = kept / name
                    old.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target), str(old))
                else:
                    target.unlink()
                removed += 1
            except OSError as exc:
                failed.append((name, str(exc)))
    return copied, removed, failed


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


# ------------------------------------------------------- 한글 이름 zip 풀기

# 윈도우에서 만든 zip 은 파일명을 cp949 로 넣는데, 표준에는 그런 표시가 없다.
# zipfile 은 UTF-8 표시가 없으면 cp437 로 읽으므로 한글이 깨져 나온다.
ZIP_UTF8_FLAG = 0x800


@dataclass
class ZipEntry:
    raw: str                # zipfile 이 읽은 그대로
    name: str               # 고친 이름
    size: int
    is_dir: bool = False
    fixed: bool = False     # 이름을 고쳤는가
    unsafe: str = ""        # 위험하면 그 이유


def fix_zip_name(raw: str, flag_bits: int) -> tuple[str, bool]:
    """cp437 로 잘못 읽힌 이름을 cp949 로 되돌린다. (이름, 고쳤는지)"""
    if flag_bits & ZIP_UTF8_FLAG:
        return raw, False
    try:
        data = raw.encode("cp437")
    except UnicodeEncodeError:
        return raw, False
    for encoding in ("cp949", "utf-8"):
        try:
            fixed = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if fixed != raw:
            return to_nfc(fixed), True
        return raw, False
    return raw, False


def unsafe_reason(name: str) -> str:
    """압축 안 경로가 바깥을 가리키는지 본다(zip slip)."""
    if name.startswith("/") or name.startswith("\\\\"):
        return "절대 경로"
    if re.match(r"^[A-Za-z]:", name):
        return "드라이브 경로"
    parts = PurePosixPath(name.replace("\\\\", "/")).parts
    if ".." in parts:
        return "상위 디렉터리(..)"
    return ""


def list_zip(archive: Path) -> list[ZipEntry]:
    """압축 안의 목록을 읽는다. 풀지는 않는다."""
    import zipfile

    out: list[ZipEntry] = []
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name, fixed = fix_zip_name(info.filename, info.flag_bits)
            out.append(ZipEntry(info.filename, name, info.file_size,
                                info.is_dir(), fixed, unsafe_reason(name)))
    return out


def extract_zip(archive: Path, dest: Path, entries: list[ZipEntry], *,
                overwrite: bool = False) -> tuple[list[Path], list[str]]:
    """고친 이름으로 푼다. (푼 파일들, 건너뛴 이유들)"""
    import zipfile

    written: list[Path] = []
    skipped: list[str] = []
    dest = dest.resolve()
    with zipfile.ZipFile(archive) as z:
        for entry in entries:
            if entry.unsafe:
                skipped.append(f"{entry.name}: {entry.unsafe}")
                continue
            target = (dest / entry.name).resolve()
            if not str(target).startswith(str(dest)):
                skipped.append(f"{entry.name}: 대상 디렉터리 밖")
                continue
            if entry.is_dir:
                target.mkdir(parents=True, exist_ok=True)
                continue
            if target.exists() and not overwrite:
                skipped.append(f"{entry.name}: 이미 있음")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(entry.raw) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)
            written.append(target)
    return written, skipped


# ------------------------------------------------------------------ 이미지

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
# 크기만 헤더에서 읽는다. 픽셀은 건드리지 않으므로 의존성이 필요 없다.
JPEG_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


@dataclass
class ImageInfo:
    path: Path
    kind: str
    width: int
    height: int
    size: int

    @property
    def pixels(self) -> int:
        return self.width * self.height

    @property
    def ratio(self) -> str:
        if not self.height:
            return "?"
        from math import gcd

        g = gcd(self.width, self.height) or 1
        w, h = self.width // g, self.height // g
        return f"{w}:{h}" if w <= 40 and h <= 40 else f"{self.width / self.height:.2f}:1"


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in JPEG_SOF:
            height = int.from_bytes(data[i + 5:i + 7], "big")
            width = int.from_bytes(data[i + 7:i + 9], "big")
            return width, height
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if length < 2:
            return None
        i += 2 + length
    return None


def image_info(path: Path, *, head: int = 65536) -> ImageInfo | None:
    """헤더만 읽어 형식과 크기를 알아낸다. 모르는 형식이면 None."""
    try:
        with path.open("rb") as fh:
            data = fh.read(head)
        size = path.stat().st_size
    except OSError:
        return None
    if len(data) < 16:
        return None

    def made(kind: str, w: int, h: int) -> ImageInfo:
        return ImageInfo(path, kind, w, h, size)

    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return made("PNG", int.from_bytes(data[16:20], "big"),
                    int.from_bytes(data[20:24], "big"))
    if data[:3] == b"GIF":
        return made("GIF", int.from_bytes(data[6:8], "little"),
                    int.from_bytes(data[8:10], "little"))
    if data[:2] == b"BM":
        return made("BMP", int.from_bytes(data[18:22], "little", signed=True),
                    abs(int.from_bytes(data[22:26], "little", signed=True)))
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X":
            width = int.from_bytes(data[24:27], "little") + 1
            height = int.from_bytes(data[27:30], "little") + 1
            return made("WebP", width, height)
        if chunk == b"VP8 ":
            return made("WebP", int.from_bytes(data[26:28], "little") & 0x3FFF,
                        int.from_bytes(data[28:30], "little") & 0x3FFF)
        if chunk == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            return made("WebP", (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        return None
    if data[:2] == b"\xff\xd8":
        found = _jpeg_size(data)
        return made("JPEG", *found) if found else None
    return None


# ------------------------------------------------------------- 촬영 시각

# EXIF 태그. 촬영 시각을 알려 주는 것만 본다.
EXIF_SUB_IFD = 0x8769
EXIF_DATETIME_ORIGINAL = 0x9003
EXIF_DATETIME_DIGITIZED = 0x9004
TIFF_DATETIME = 0x0132


def _exif_ascii(data: bytes, base: int, order: str, want: set[int],
                depth: int = 0) -> dict[int, str]:
    """IFD 하나에서 찾는 태그의 ASCII 값을 뽑는다. 하위 IFD 도 한 번 따라간다."""
    out: dict[int, str] = {}
    if depth > 1 or base + 2 > len(data):
        return out
    count = int.from_bytes(data[base:base + 2], order)
    for i in range(count):
        entry = base + 2 + i * 12
        if entry + 12 > len(data):
            break
        tag = int.from_bytes(data[entry:entry + 2], order)
        kind = int.from_bytes(data[entry + 2:entry + 4], order)
        length = int.from_bytes(data[entry + 4:entry + 8], order)
        raw = data[entry + 8:entry + 12]

        if tag == EXIF_SUB_IFD and kind == 4:
            out.update(_exif_ascii(data, int.from_bytes(raw, order), order,
                                   want, depth + 1))
            continue
        if tag not in want or kind != 2 or not 0 < length <= 64:
            continue
        if length > 4:
            offset = int.from_bytes(raw, order)
            chunk = data[offset:offset + length]
        else:
            chunk = raw[:length]
        text = chunk.split(b"\x00")[0].decode("ascii", "replace").strip()
        if text:
            out[tag] = text
    return out


def exif_datetime(path: Path, *, head: int = 262144) -> datetime | None:
    """JPEG 의 촬영 시각(EXIF DateTimeOriginal). 없으면 None.

    파일을 복사하면 수정 시각은 복사한 날로 바뀌지만 EXIF 는 찍은 날 그대로다.
    사진을 날짜별로 묶을 때는 이쪽이 맞다. HEIC·RAW 는 읽지 못하므로 None 을
    돌려주고, 부르는 쪽이 수정 시각으로 물러설지 정한다.
    """
    try:
        with path.open("rb") as fh:
            data = fh.read(head)
    except OSError:
        return None
    if data[:2] != b"\xff\xd8":
        return None

    start = data.find(b"Exif\x00\x00")
    if start < 0:
        return None
    tiff = start + 6
    mark = data[tiff:tiff + 2]
    if mark not in (b"II", b"MM"):
        return None
    order = "little" if mark == b"II" else "big"

    body = data[tiff:]
    if len(body) < 8:
        return None
    first = int.from_bytes(body[4:8], order)
    found = _exif_ascii(body, first, order,
                        {EXIF_DATETIME_ORIGINAL, EXIF_DATETIME_DIGITIZED,
                         TIFF_DATETIME})

    for tag in (EXIF_DATETIME_ORIGINAL, EXIF_DATETIME_DIGITIZED, TIFF_DATETIME):
        text = found.get(tag)
        if not text:
            continue
        try:
            return datetime.strptime(text[:19], "%Y:%m:%d %H:%M:%S")
        except ValueError:
            continue
    return None


PHOTO_SUFFIXES = {".jpg", ".jpeg", ".jpe", ".png", ".gif", ".bmp", ".webp",
                  ".heic", ".heif", ".tif", ".tiff", ".dng", ".raw", ".cr2",
                  ".nef", ".arw"}
PHOTO_BUCKETS = {"year": "%Y", "month": "%Y-%m", "day": "%Y-%m-%d"}


# --------------------------------------------- 사진 정보 (찍은 날·기기·위치)

EXIF_MAKE = 0x010F
EXIF_MODEL = 0x0110
EXIF_ORIENTATION = 0x0112
EXIF_SOFTWARE = 0x0131
EXIF_ARTIST = 0x013B
EXIF_COPYRIGHT = 0x8298
EXIF_GPS_IFD = 0x8825
GPS_LAT_REF, GPS_LAT = 0x0001, 0x0002
GPS_LON_REF, GPS_LON = 0x0003, 0x0004
EXIF_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}
# 사진에 딸려 다니는 메타 자리. 그림 자체는 SOS 뒤에 있어 건드리지 않는다.
JPEG_META_SEGMENTS = {0xE1: "Exif/XMP", 0xE2: "색 프로파일", 0xED: "IPTC",
                      0xEE: "Adobe", 0xFE: "주석"}


@dataclass
class PhotoMeta:
    path: Path
    taken: datetime | None = None
    make: str = ""
    model: str = ""
    software: str = ""
    artist: str = ""
    copyright: str = ""
    orientation: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    size: int = 0
    error: str = ""

    @property
    def where(self) -> str:
        if self.latitude is None or self.longitude is None:
            return ""
        return f"{self.latitude:.5f}, {self.longitude:.5f}"

    @property
    def personal(self) -> list[str]:
        """밖으로 보낼 때 걸리는 것 - 위치, 기기, 사람 이름."""
        out = []
        if self.where:
            out.append(f"위치 {self.where}")
        if self.make or self.model:
            out.append(("기기 " + f"{self.make} {self.model}".strip()))
        if self.artist:
            out.append(f"작성자 {self.artist}")
        return out


def _exif_block(data: bytes) -> tuple[bytes, str] | None:
    """JPEG 에서 TIFF 덩어리와 바이트 순서를 꺼낸다. 없으면 None."""
    start = data.find(b"Exif\x00\x00")
    if start < 0:
        return None
    tiff = data[start + 6:]
    if tiff[:2] not in (b"II", b"MM") or len(tiff) < 8:
        return None
    return tiff, ("little" if tiff[:2] == b"II" else "big")


def _entries(data: bytes, base: int, order: str):
    """IFD 하나의 항목을 (태그, 형, 개수, 값바이트) 로 넘긴다."""
    if base + 2 > len(data):
        return
    count = int.from_bytes(data[base:base + 2], order)
    for i in range(count):
        at = base + 2 + i * 12
        if at + 12 > len(data):
            return
        tag = int.from_bytes(data[at:at + 2], order)
        kind = int.from_bytes(data[at + 2:at + 4], order)
        length = int.from_bytes(data[at + 4:at + 8], order)
        raw = data[at + 8:at + 12]
        size = EXIF_TYPE_SIZES.get(kind, 0) * length
        if size > 4:
            offset = int.from_bytes(raw, order)
            raw = data[offset:offset + size]
        else:
            raw = raw[:size]
        yield tag, kind, length, raw


def _exif_value(kind: int, count: int, raw: bytes, order: str):
    """EXIF 값 하나를 파이썬 값으로. 모르는 형이면 None."""
    if kind == 2:
        return raw.split(b"\x00")[0].decode("utf-8", "replace").strip()
    if kind in (1, 3, 4):
        step = EXIF_TYPE_SIZES[kind]
        numbers = [int.from_bytes(raw[i:i + step], order)
                   for i in range(0, min(len(raw), step * count), step)]
        return numbers[0] if count == 1 and numbers else numbers
    if kind in (5, 10):
        out = []
        for i in range(0, min(len(raw), 8 * count), 8):
            top = int.from_bytes(raw[i:i + 4], order,
                                 signed=(kind == 10))
            bottom = int.from_bytes(raw[i + 4:i + 8], order,
                                    signed=(kind == 10))
            out.append(top / bottom if bottom else 0.0)
        return out
    return None


def _gps_degrees(values, ref: str) -> float | None:
    """도·분·초를 십진 좌표로. 남/서면 음수."""
    if not values or len(values) < 3:
        return None
    degrees = values[0] + values[1] / 60 + values[2] / 3600
    return -degrees if ref.upper() in ("S", "W") else degrees


def photo_info(path: Path, *, head: int = 262144) -> PhotoMeta:
    """사진의 촬영 정보를 읽는다. 위치정보가 남아 있는지 보려는 것이다."""
    meta = PhotoMeta(path=path)
    try:
        meta.size = path.stat().st_size
        with path.open("rb") as fh:
            data = fh.read(head)
    except OSError as e:
        meta.error = str(e)
        return meta
    if data[:2] != b"\xff\xd8":
        meta.error = "JPEG 이 아닙니다 (EXIF 는 jpg 에서만 읽습니다)"
        return meta

    found = _exif_block(data)
    if found is None:
        meta.error = "촬영 정보(EXIF)가 없습니다"
        return meta
    tiff, order = found

    first = int.from_bytes(tiff[4:8], order)
    texts = {EXIF_MAKE: "make", EXIF_MODEL: "model", EXIF_SOFTWARE: "software",
             EXIF_ARTIST: "artist", EXIF_COPYRIGHT: "copyright"}
    gps_base = 0
    for tag, kind, count, raw in _entries(tiff, first, order):
        if tag in texts and kind == 2:
            value = _exif_value(kind, count, raw, order)
            if value:
                setattr(meta, texts[tag], value)
        elif tag == EXIF_ORIENTATION and kind == 3:
            meta.orientation = _exif_value(kind, count, raw, order)
        elif tag == EXIF_GPS_IFD and kind == 4:
            gps_base = int.from_bytes(raw, order)

    if gps_base:
        gps: dict = {}
        for tag, kind, count, raw in _entries(tiff, gps_base, order):
            gps[tag] = _exif_value(kind, count, raw, order)
        meta.latitude = _gps_degrees(gps.get(GPS_LAT),
                                     str(gps.get(GPS_LAT_REF) or ""))
        meta.longitude = _gps_degrees(gps.get(GPS_LON),
                                      str(gps.get(GPS_LON_REF) or ""))

    meta.taken = exif_datetime(path, head=head)
    return meta


def _orientation_exif(orientation: int) -> bytes:
    """방향 하나만 든 최소 EXIF 덩어리. 지운 뒤에도 사진이 눕지 않게."""
    body = bytearray(b"Exif\x00\x00MM\x00\x2a")
    body += (8).to_bytes(4, "big")             # 첫 IFD 자리
    body += (1).to_bytes(2, "big")             # 항목 하나
    body += EXIF_ORIENTATION.to_bytes(2, "big")
    body += (3).to_bytes(2, "big") + (1).to_bytes(4, "big")
    body += orientation.to_bytes(2, "big") + b"\x00\x00"
    body += (0).to_bytes(4, "big")             # 다음 IFD 없음
    return bytes(body)


def strip_exif(src: Path, dest: Path, *, keep_orientation: bool = True
               ) -> tuple[Path, list[str]]:
    """촬영 정보를 뺀 사본을 만든다. (만든 파일, 지운 자리 이름들)

    그림 자체(SOS 뒤)는 손대지 않고 메타 세그먼트만 뺀다. 다시 눌지 않으므로
    화질이 그대로다. 방향(Orientation)은 기본으로 남긴다 - 그것까지 지우면
    폰으로 찍은 사진이 눕혀 보인다.
    """
    raw = src.read_bytes()
    if raw[:2] != b"\xff\xd8":
        raise ValueError(f"JPEG 이 아닙니다: {src.name}")

    meta = photo_info(src)
    out = bytearray(b"\xff\xd8")
    if keep_orientation and meta.orientation and meta.orientation != 1:
        block = _orientation_exif(meta.orientation)
        out += b"\xff\xe1" + (len(block) + 2).to_bytes(2, "big") + block

    removed: list[str] = []
    i = 2
    while i + 4 <= len(raw):
        if raw[i] != 0xFF:
            break
        marker = raw[i + 1]
        if marker == 0xDA:                     # 여기부터는 그림 자료다
            out += raw[i:]
            break
        length = int.from_bytes(raw[i + 2:i + 4], "big")
        if length < 2:
            break
        chunk = raw[i:i + 2 + length]
        if marker in JPEG_META_SEGMENTS:
            removed.append(JPEG_META_SEGMENTS[marker])
        else:
            out += chunk
        i += 2 + length

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(bytes(out))
    return dest, removed


def scan_photos(root: Path, *, recursive: bool = True) -> list[PhotoMeta]:
    """폴더 안 jpg 의 촬영 정보를 모은다."""
    if root.is_file():
        return [photo_info(root)]
    walker = root.rglob("*") if recursive else root.glob("*")
    return [photo_info(p) for p in sorted(walker)
            if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg")]


@dataclass
class PhotoPlan:
    moves: list[Move] = field(default_factory=list)
    from_exif: int = 0
    from_mtime: list[Path] = field(default_factory=list)   # 촬영 시각을 못 읽음
    left: list[Path] = field(default_factory=list)         # 그래서 두고 온 것


def plan_photos(root: Path, *, by: str = "month", recursive: bool = True,
                include_hidden: bool = False, use_mtime: bool = False) -> PhotoPlan:
    """사진을 찍은 날짜별 폴더로 옮기는 계획.

    수정 시각이 아니라 EXIF 촬영 시각을 쓴다. 사진은 옮겨 담는 사이 수정
    시각이 복사한 날로 바뀌어 있기 일쑤다. 촬영 시각을 못 읽은 것은 기본으로
    건드리지 않고, use_mtime 을 켠 사람에게만 수정 시각으로 물러선다.
    """
    if by not in PHOTO_BUCKETS:
        raise ValueError(f"알 수 없는 기준: {by} ({', '.join(PHOTO_BUCKETS)})")

    root = root.resolve()
    plan = PhotoPlan()
    planned: set[Path] = set()
    for src in sorted(iter_targets(root, recursive=recursive,
                                   include_hidden=include_hidden)):
        if src.suffix.lower() not in PHOTO_SUFFIXES:
            continue
        taken = exif_datetime(src)
        if taken is not None:
            plan.from_exif += 1
        else:
            if not use_mtime:
                plan.left.append(src)
                continue
            plan.from_mtime.append(src)
            taken = datetime.fromtimestamp(src.stat().st_mtime)

        folder = root / taken.strftime(PHOTO_BUCKETS[by])
        if src.parent == folder:
            continue
        dst = unique_path(folder / to_nfc(src.name), planned)
        planned.add(dst)
        plan.moves.append(Move(str(src), str(dst)))

    return plan


def scan_images(root: Path, *, recursive: bool = True,
                hidden: bool = False) -> tuple[list[ImageInfo], list[Path]]:
    """이미지 목록과, 이미지 같은데 못 읽은 파일 목록."""
    walker = root.rglob("*") if recursive else root.glob("*")
    found: list[ImageInfo] = []
    unknown: list[Path] = []
    for path in sorted(walker):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if not hidden and any(p.startswith(".") for p in path.parts):
            continue
        if any(d in IGNORE_DIRS for d in path.parts):
            continue
        info = image_info(path)
        (found if info else unknown).append(info or path)
    return found, unknown


# ------------------------------------------------------------- 규칙대로 정리

@dataclass
class Rule:
    """파일 하나를 어디로 보낼지 정하는 규칙."""
    pattern: str = "*"          # 이름 glob (*.pdf, 세금계산서*)
    folder: str = ""            # 보낼 곳. {년}{월}{일}{확장자}{이름} 을 쓸 수 있다
    match: str = ""             # 이름 정규식 (선택). 이름 그룹은 폴더에 쓸 수 있다
    name: str = ""              # 규칙 이름 (표시용)

    def label(self) -> str:
        return self.name or self.pattern


@dataclass
class Routed:
    move: Move
    rule: Rule


def load_rules(data) -> list[Rule]:
    """JSON 에서 규칙을 읽는다. 한글 키와 영문 키를 모두 받는다."""
    if isinstance(data, dict):
        data = data.get("규칙") or data.get("rules") or []
    if not isinstance(data, list) or not data:
        raise ValueError("규칙 목록이 비어 있습니다.")
    out: list[Rule] = []
    for i, item in enumerate(data, 1):
        if not isinstance(item, dict):
            raise ValueError(f"{i}번째 규칙이 객체가 아닙니다.")
        folder = item.get("폴더") or item.get("folder") or ""
        if not folder:
            raise ValueError(f"{i}번째 규칙에 '폴더' 가 없습니다.")
        out.append(Rule(pattern=str(item.get("패턴") or item.get("pattern") or "*"),
                        folder=str(folder),
                        match=str(item.get("정규식") or item.get("match") or ""),
                        name=str(item.get("이름") or item.get("name") or "")))
    return out


def _folder_fields(path: Path, rule: Rule) -> dict[str, str] | None:
    """폴더 이름에 넣을 값들. 정규식이 안 맞으면 None."""
    when = datetime.fromtimestamp(path.stat().st_mtime)
    fields = {"년": f"{when:%Y}", "월": f"{when:%m}", "일": f"{when:%d}",
              "이름": path.stem, "확장자": path.suffix.lstrip("."),
              "분류": category_of(path)}
    if rule.match:
        m = re.search(rule.match, path.name)
        if not m:
            return None
        fields.update({k: v or "" for k, v in (m.groupdict() or {}).items()})
        for i, group in enumerate(m.groups(), 1):
            fields[str(i)] = group or ""
    return fields


def plan_route(root: Path, rules: list[Rule], *, recursive: bool = False,
               include_hidden: bool = False,
               min_age_days: float = 0.0) -> tuple[list[Routed], list[Path]]:
    """규칙대로 옮길 계획과, 어느 규칙에도 안 걸린 파일들."""
    root = root.resolve()
    planned: set[Path] = set()
    routed: list[Routed] = []
    missed: list[Path] = []

    for src in sorted(iter_targets(root, recursive=recursive,
                                   include_hidden=include_hidden,
                                   min_age_days=min_age_days)):
        for rule in rules:                      # 먼저 걸리는 규칙이 이긴다
            if not fnmatch(src.name, rule.pattern):
                continue
            fields = _folder_fields(src, rule)
            if fields is None:
                continue
            try:
                folder = rule.folder.format(**fields)
            except (KeyError, IndexError) as e:
                raise ValueError(f"'{rule.label()}' 규칙의 폴더 이름에서 "
                                 f"{e} 를 채우지 못했습니다.") from None
            dst = unique_path(root / folder / to_nfc(src.name), planned)
            if dst == src:
                break
            planned.add(dst)
            routed.append(Routed(Move(str(src), str(dst)), rule))
            break
        else:
            missed.append(src)
    return routed, missed


# ------------------------------------------------------- 하위 폴더 펼치기

def plan_flatten(root: Path, *, dest: Path | None = None, keep_path: bool = False,
                 sep: str = "_", include_hidden: bool = False) -> list[Move]:
    """하위 폴더의 파일을 한 곳으로 모으는 계획.

    이름이 겹치면 '(1)' 을 붙인다. keep_path 를 주면 폴더 이름을 파일명 앞에
    붙여 어디서 왔는지 남긴다 - 겹침도 줄고 나중에 되짚기도 쉽다.
    """
    root = root.resolve()
    target = (dest or root).resolve()
    planned: set[Path] = set()
    moves: list[Move] = []

    for src in sorted(root.rglob("*")):
        if not src.is_file() or src.is_symlink():
            continue
        rel = src.relative_to(root)
        if len(rel.parts) == 1 and target == root:
            continue                     # 이미 맨 위에 있다
        if not include_hidden and any(p.startswith(".") for p in rel.parts):
            continue
        if any(p in IGNORE_DIRS for p in rel.parts):
            continue

        name = to_nfc(src.name)
        if keep_path and len(rel.parts) > 1:
            name = sep.join([*rel.parts[:-1], name])
        dst = unique_path(target / name, planned)
        if dst == src:
            continue
        planned.add(dst)
        moves.append(Move(str(src), str(dst)))
    return moves


def empty_dirs(root: Path) -> list[Path]:
    """비어 있는 하위 디렉터리. 깊은 것부터 돌려준다."""
    out: list[Path] = []
    for path in sorted(root.rglob("*"), key=lambda p: -len(p.parts)):
        if path.is_dir() and not any(path.iterdir()):
            out.append(path)
    return out
