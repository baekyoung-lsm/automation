"""소설 원고: 분량 집계, 반복·상투구 점검, 스냅샷."""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".text"}
SNAPSHOT_DIR = ".attools-snapshots"

# 한국어 기준값. 원고지는 200자, 묵독 속도는 분당 500~600자로 잡는다.
WONGOJI_CHARS = 200
READ_CPM = 550
BOOK_CHARS = 100_000  # 단행본 1권 어림값(공백 제외). 출판사마다 다르다.

SENT_SPLIT = re.compile(r"(?<=[.!?…\?])[\"'”’」』\)]*\s+|\n+")
QUOTE = re.compile(r"[\"“](.+?)[\"”]|[「『](.+?)[」』]", re.S)

CLICHES = [
    "미소를 지었다", "고개를 끄덕였다", "고개를 저었다", "고개를 갸웃",
    "숨을 삼켰다", "숨을 들이켰다", "입을 열었다", "입술을 깨물었다",
    "눈을 빛냈다", "눈살을 찌푸렸다", "어깨를 으쓱", "한숨을 내쉬었다",
    "알 수 없는", "묘한", "저도 모르게", "왠지 모르게", "어쩐지",
    "잠시 후", "얼마나 지났을까", "그런 것이었다", "하고 말았다",
    "말없이", "이내", "다름 아닌", "그럼에도 불구하고",
]
FILLER_ADVERBS = [
    "정말", "진짜", "너무", "매우", "아주", "굉장히", "엄청",
    "그냥", "조금", "약간", "살짝", "좀", "그저", "결국", "순간",
]
ENDING_RE = re.compile(r"([가-힣]{2})[.!?…\"'”’」』\)\s]*$")  # 종결 어미 2음절


@dataclass
class Stats:
    path: str
    chars: int = 0
    chars_no_space: int = 0
    words: int = 0
    sentences: int = 0
    paragraphs: int = 0
    dialogue_chars: int = 0

    @property
    def wongoji(self) -> float:
        return self.chars / WONGOJI_CHARS

    @property
    def avg_sentence(self) -> float:
        return self.chars_no_space / self.sentences if self.sentences else 0.0

    @property
    def dialogue_ratio(self) -> float:
        return self.dialogue_chars / self.chars if self.chars else 0.0

    @property
    def read_minutes(self) -> float:
        return self.chars_no_space / READ_CPM

    @property
    def book_ratio(self) -> float:
        return self.chars_no_space / BOOK_CHARS


def read_text(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp949", "euc-kr"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def strip_markup(text: str) -> str:
    """마크다운 제목·구분선은 본문 분량에서 뺀다."""
    text = re.sub(r"^\s*#{1,6}\s.*$", "", text, flags=re.M)
    return re.sub(r"^\s*(?:-{3,}|\*{3,}|={3,})\s*$", "", text, flags=re.M)


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(text) if s and s.strip()]


def analyze(path: Path, text: str | None = None) -> Stats:
    text = read_text(path) if text is None else text
    body = strip_markup(text)
    st = Stats(path=str(path))
    st.chars = len(body.replace("\n", ""))
    st.chars_no_space = len(re.sub(r"\s", "", body))
    st.words = len(body.split())
    st.sentences = len(split_sentences(body))
    st.paragraphs = len([p for p in re.split(r"\n\s*\n", body) if p.strip()])
    st.dialogue_chars = sum(len(m.group(1) or m.group(2) or "") for m in QUOTE.finditer(body))
    return st


def collect(paths: list[Path]) -> list[Path]:
    """디렉터리는 텍스트 파일만 재귀 수집, 파일은 그대로."""
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out.extend(sorted(q for q in p.rglob("*")
                              if q.is_file() and q.suffix.lower() in TEXT_SUFFIXES
                              and SNAPSHOT_DIR not in q.parts))
        elif p.is_file():
            out.append(p)
    return out


def total(stats: list[Stats]) -> Stats:
    t = Stats(path=f"합계 ({len(stats)}개 파일)")
    for s in stats:
        t.chars += s.chars
        t.chars_no_space += s.chars_no_space
        t.words += s.words
        t.sentences += s.sentences
        t.paragraphs += s.paragraphs
        t.dialogue_chars += s.dialogue_chars
    return t


# ------------------------------------------------------------------- 반복 점검

@dataclass
class Findings:
    cliches: list[tuple[str, int]] = field(default_factory=list)
    adverbs: list[tuple[str, int]] = field(default_factory=list)
    phrases: list[tuple[str, int]] = field(default_factory=list)
    ending_runs: list[tuple[str, int, int]] = field(default_factory=list)   # 어미, 연속수, 시작문장
    start_runs: list[tuple[str, int, int]] = field(default_factory=list)    # 첫 어절, 연속수, 시작문장
    long_sentences: list[tuple[int, int, str]] = field(default_factory=list)  # 번호, 길이, 미리보기


def _runs(values: list[str | None], threshold: int) -> list[tuple[str, int, int]]:
    """같은 값이 threshold 번 이상 연달아 나오는 구간."""
    out: list[tuple[str, int, int]] = []
    start = 0
    for i in range(1, len(values) + 1):
        if i < len(values) and values[i] is not None and values[i] == values[start]:
            continue
        length = i - start
        if values[start] is not None and length >= threshold:
            out.append((values[start], length, start + 1))
        start = i
    return out


def inspect(text: str, *, top: int = 10, long_limit: int = 100,
            run_threshold: int = 4) -> Findings:
    text = strip_markup(text)
    sentences = split_sentences(text)
    f = Findings()

    f.cliches = sorted(((c, text.count(c)) for c in CLICHES if text.count(c)),
                       key=lambda x: -x[1])[:top]
    f.adverbs = sorted(((a, len(re.findall(rf"(?<![가-힣]){re.escape(a)}(?![가-힣])", text)))
                        for a in FILLER_ADVERBS),
                       key=lambda x: -x[1])
    f.adverbs = [x for x in f.adverbs if x[1] > 0][:top]

    # 2어절 연쇄 반복 (고유명사/대사 반복을 잡되 조사 차이는 무시하지 않는다)
    tokens = [t for t in re.findall(r"[가-힣A-Za-z0-9]+", text) if len(t) > 1]
    bigrams = Counter(f"{a} {b}" for a, b in zip(tokens, tokens[1:]))
    f.phrases = [(p, n) for p, n in bigrams.most_common(top * 3) if n >= 3][:top]

    endings = [m.group(1) if (m := ENDING_RE.search(s)) else None for s in sentences]
    f.ending_runs = _runs(endings, run_threshold)

    starts = [(s.split()[0] if s.split() else None) for s in sentences]
    f.start_runs = _runs(starts, 3)

    f.long_sentences = [(i + 1, len(s), s[:40] + "…")
                        for i, s in enumerate(sentences) if len(s) > long_limit]
    return f


# --------------------------------------------------------------------- 스냅샷

def snapshot(root: Path, *, note: str = "") -> Path:
    """원고 디렉터리를 통째로 복사해 시점 기록을 남긴다."""
    root = root.resolve()
    files = collect([root])
    base = root / SNAPSHOT_DIR
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = base / stamp
    for i in range(2, 100):  # 같은 초에 두 번 찍어도 덮어쓰지 않는다
        if not dest.exists():
            break
        dest = base / f"{stamp}-{i}"
    dest.mkdir(parents=True, exist_ok=True)

    manifest = {"time": datetime.now().isoformat(timespec="seconds"), "note": note, "files": {}}
    for src in files:
        rel = src.relative_to(root)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        manifest["files"][str(rel)] = analyze(src).chars_no_space

    manifest["total"] = sum(manifest["files"].values())
    (dest / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def list_snapshots(root: Path) -> list[dict]:
    base = root.resolve() / SNAPSHOT_DIR
    if not base.is_dir():
        return []
    out = []
    for d in sorted(base.iterdir()):
        mf = d / "manifest.json"
        if mf.is_file():
            data = json.loads(mf.read_text(encoding="utf-8"))
            data["id"] = d.name
            out.append(data)
    return out


# --------------------------------------------------------------------- 장면

# 장면을 가르는 표시. 마크다운 제목과 흔히 쓰는 구분선을 본다.
SCENE_BREAK = re.compile(
    r"^\s*(?:\*\s*\*\s*\*|-{3,}|={3,}|#{1,6}\s+.*|◇+|◆+|＊+|※+|⁂|~{3,})\s*$")
HEADING_LINE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$")


@dataclass
class Scene:
    number: int
    title: str
    line: int
    text: str = ""
    people: list[str] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return len(re.sub(r"\s", "", self.text))

    @property
    def dialogue_ratio(self) -> float:
        if not self.chars:
            return 0.0
        spoken = sum(len(m.group(1) or m.group(2) or "") for m in QUOTE.finditer(self.text))
        return spoken / self.chars

    @property
    def opening(self) -> str:
        for line in self.text.splitlines():
            if line.strip():
                return line.strip()
        return ""


def split_scenes(text: str, *, min_chars: int = 30,
                 blank_run: int = 3) -> list[Scene]:
    """제목·구분선·긴 빈 줄을 기준으로 장면을 나눈다."""
    lines = text.splitlines()
    scenes: list[Scene] = []
    buffer: list[str] = []
    title = ""
    start = 1
    blanks = 0

    def flush(next_title: str, next_line: int) -> None:
        nonlocal buffer, title, start
        body = "\n".join(buffer).strip()
        if len(re.sub(r"\s", "", body)) >= min_chars:
            scenes.append(Scene(len(scenes) + 1, title, start, body))
        buffer = []
        title = next_title
        start = next_line

    for n, line in enumerate(lines, 1):
        if SCENE_BREAK.match(line):
            heading = HEADING_LINE.match(line)
            flush(heading.group(2).strip() if heading else "", n + 1)
            blanks = 0
            continue

        if not line.strip():
            blanks += 1
            if blanks >= blank_run and buffer:
                flush("", n + 1)
                blanks = 0
                continue
        else:
            blanks = 0
        buffer.append(line)

    flush("", len(lines))
    return scenes


def tag_people(scenes: list[Scene], people: list[str]) -> None:
    """장면마다 등장하는 이름을 채운다."""
    if not people:
        return
    ordered = sorted(people, key=len, reverse=True)
    for scene in scenes:
        scene.people = [p for p in ordered if p in scene.text]
        scene.people.sort(key=lambda p: -scene.text.count(p))
