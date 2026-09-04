"""소설 원고: 분량 집계, 반복·상투구 점검, 스냅샷."""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
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


def strip_headings(text: str) -> str:
    """제목 줄만 비운다. 줄 수는 그대로라 행 번호가 어긋나지 않는다.

    구분선(***, ---)은 남긴다. 장면 경계로 써야 하기 때문이다.
    """
    return re.sub(r"^\s*#{1,6}\s.*$", "", text, flags=re.M)


def strip_markup(text: str) -> str:
    """마크다운 제목·구분선은 본문 분량에서 뺀다."""
    text = strip_headings(text)
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


# --------------------------------------------------------------------- 찾기

# 구분선만 있는 줄은 문맥으로 보여줄 값이 없다
SEPARATOR_ONLY = re.compile(r"^[\s*\-=~◇◆＊※⁂_]+$")


@dataclass
class Mention:
    path: str
    line: int
    scene: int
    before: str
    hit: str
    after: str

    def context(self, mark: str = "**") -> str:
        parts = [self.before, f"{mark}{self.hit}{mark}", self.after]
        return " ".join(p for p in parts if p)


def find_mentions(text: str, pattern: re.Pattern[str], *, path: str = "",
                  context: int = 1, scenes: list[Scene] | None = None) -> list[Mention]:
    """문장 단위로 찾고 앞뒤 문장을 문맥으로 붙인다."""
    sentences = split_sentences(text)
    # 문장이 원문 몇 번째 줄에서 시작하는지 미리 재둔다
    offsets: list[int] = []
    cursor = 0
    for s in sentences:
        found = text.find(s[:30], cursor)
        cursor = found + 1 if found >= 0 else cursor
        offsets.append(text.count("\n", 0, max(found, 0)) + 1)

    scene_starts = [(s.line, s.number) for s in (scenes or [])]

    def scene_of(line: int) -> int:
        number = 0
        for start, n in scene_starts:
            if start <= line:
                number = n
            else:
                break
        return number

    out: list[Mention] = []
    for i, sentence in enumerate(sentences):
        if not pattern.search(sentence):
            continue
        before = " ".join(s for s in sentences[max(0, i - context):i]
                          if not SEPARATOR_ONLY.match(s))
        after = " ".join(s for s in sentences[i + 1:i + 1 + context]
                         if not SEPARATOR_ONLY.match(s))
        out.append(Mention(path, offsets[i], scene_of(offsets[i]),
                           before[-60:], sentence.strip(), after[:60]))
    return out


# ------------------------------------------------------------------ 시간선

TIME_OF_DAY = {
    "새벽": "새벽", "동틀": "새벽", "먼동": "새벽",
    "아침": "아침", "오전": "아침", "해가 뜨": "아침",
    "정오": "낮", "한낮": "낮", "대낮": "낮", "낮": "낮",
    "오후": "오후", "해 질": "저녁", "해질": "저녁", "노을": "저녁",
    "저녁": "저녁", "황혼": "저녁",
    "밤": "밤", "한밤": "밤", "자정": "밤", "새벽녘": "새벽", "야밤": "밤",
}
SEASONS = {"봄": "봄", "여름": "여름", "가을": "가을", "겨울": "겨울"}

TIME_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("날짜", re.compile(r"\d{1,4}\s*년(?:\s*\d{1,2}\s*월)?(?:\s*\d{1,2}\s*일)?")),
    ("날짜", re.compile(r"\d{1,2}\s*월\s*\d{1,2}\s*일")),
    ("시각", re.compile(r"(?:오전|오후)?\s*\d{1,2}\s*시(?:\s*\d{1,2}\s*분)?")),
    ("요일", re.compile(r"[월화수목금토일]요일")),
    ("상대", re.compile(
        r"(?:그저께|그제|어제|오늘|내일|모레|글피|이튿날|다음\s*날|그날|그해|이듬해|"
        r"작년|지난해|올해|내년|훗날|그때|그 무렵|얼마 뒤|얼마 후)")),
    ("기간", re.compile(
        r"(?:하루|이틀|사흘|나흘|닷새|엿새|이레|여드레|아흐레|열흘|보름|"
        r"\d+\s*(?:분|시간|일|주|달|개월|년|해))\s*(?:뒤|후|만에|전|째|간|동안)")),
    ("시간대", re.compile("|".join(sorted(TIME_OF_DAY, key=len, reverse=True)))),
    ("계절", re.compile("|".join(SEASONS))),
]


@dataclass
class TimeMark:
    kind: str
    text: str
    line: int
    scene: int
    sentence: str
    bucket: str = ""      # 시간대·계절은 같은 것끼리 묶는 이름


@dataclass
class TimeConflict:
    scene: int
    kind: str
    values: list[str]
    lines: list[int]


def find_time_marks(text: str, *, scenes: list[Scene] | None = None) -> list[TimeMark]:
    """원고에서 시간을 가리키는 표현을 뽑는다."""
    sentences = split_sentences(text)
    offsets: list[int] = []
    cursor = 0
    for s in sentences:
        found = text.find(s[:30], cursor)
        cursor = found + 1 if found >= 0 else cursor
        offsets.append(text.count("\n", 0, max(found, 0)) + 1)

    starts = [(s.line, s.number) for s in (scenes or [])]

    def scene_of(line: int) -> int:
        number = 0
        for start, n in starts:
            if start <= line:
                number = n
            else:
                break
        return number

    marks: list[TimeMark] = []
    for i, sentence in enumerate(sentences):
        seen: set[tuple[str, str]] = set()
        spans: list[tuple[int, int]] = []
        for kind, pattern in TIME_PATTERNS:
            for m in pattern.finditer(sentence):
                # "2026년 3월 5일" 안의 "3월 5일" 처럼 겹치는 것은 긴 쪽만 남긴다
                if any(a <= m.start() and m.end() <= b for a, b in spans):
                    continue
                raw = m.group(0).strip()
                bucket = ""
                if kind == "시간대":
                    bucket = next((v for k, v in TIME_OF_DAY.items() if raw.startswith(k)), raw)
                elif kind == "계절":
                    bucket = SEASONS.get(raw, raw)
                if (kind, bucket or raw) in seen:
                    continue
                seen.add((kind, bucket or raw))
                spans.append((m.start(), m.end()))
                marks.append(TimeMark(kind, raw, offsets[i], scene_of(offsets[i]),
                                      sentence.strip(), bucket))
    return marks


def time_conflicts(marks: list[TimeMark]) -> list[TimeConflict]:
    """한 장면 안에서 시간대나 계절이 서로 다르게 나오는 곳."""
    grouped: dict[tuple[int, str], list[TimeMark]] = defaultdict(list)
    for m in marks:
        if m.kind in ("시간대", "계절") and m.scene:
            grouped[(m.scene, m.kind)].append(m)

    out: list[TimeConflict] = []
    for (scene, kind), items in sorted(grouped.items()):
        buckets = {m.bucket for m in items}
        if len(buckets) > 1:
            out.append(TimeConflict(scene, kind, sorted(buckets),
                                    sorted({m.line for m in items})))
    return out


# --------------------------------------------------------------------- 문체

@dataclass
class Style:
    name: str
    sentences: int = 0
    chars: int = 0
    avg_sentence: float = 0.0
    median_sentence: float = 0.0
    long_ratio: float = 0.0        # 긴 문장 비율
    dialogue_ratio: float = 0.0
    paragraph_avg: float = 0.0
    ending_top3: float = 0.0       # 상위 3개 종결 어미가 차지하는 비율
    vocabulary: float = 0.0        # 고유 어절 / 전체 어절

    def as_row(self) -> list[str]:
        return [self.name, f"{self.chars:,}", f"{self.sentences:,}",
                f"{self.avg_sentence:.0f}", f"{self.median_sentence:.0f}",
                f"{self.long_ratio:.0%}", f"{self.dialogue_ratio:.0%}",
                f"{self.paragraph_avg:.0f}", f"{self.ending_top3:.0%}",
                f"{self.vocabulary:.2f}"]


STYLE_COLUMNS = ["대상", "분량", "문장", "평균", "중앙", "긴문장", "대사",
                 "문단", "어미쏠림", "어휘"]


def style_metrics(text: str, name: str = "", *, long_limit: int = 80) -> Style:
    body = strip_markup(text)
    sentences = [s for s in split_sentences(body) if not SEPARATOR_ONLY.match(s)]
    st = Style(name)
    st.chars = len(re.sub(r"\s", "", body))
    if not sentences:
        return st

    lengths = sorted(len(re.sub(r"\s", "", s)) for s in sentences)
    st.sentences = len(sentences)
    st.avg_sentence = sum(lengths) / len(lengths)
    mid = len(lengths) // 2
    st.median_sentence = (lengths[mid] if len(lengths) % 2
                          else (lengths[mid - 1] + lengths[mid]) / 2)
    st.long_ratio = sum(1 for n in lengths if n > long_limit) / len(lengths)

    spoken = sum(len(m.group(1) or m.group(2) or "") for m in QUOTE.finditer(body))
    st.dialogue_ratio = spoken / st.chars if st.chars else 0.0

    paragraphs = [p for p in re.split(r"\n\s*\n", body) if p.strip()]
    if paragraphs:
        st.paragraph_avg = sum(len(re.sub(r"\s", "", p)) for p in paragraphs) / len(paragraphs)

    endings = Counter(m.group(1) for s in sentences if (m := ENDING_RE.search(s)))
    if endings:
        st.ending_top3 = sum(n for _, n in endings.most_common(3)) / sum(endings.values())

    words = body.split()
    if words:
        st.vocabulary = len(set(words)) / len(words)
    return st


def style_outliers(rows: list[Style], *, sigma: float = 1.5) -> dict[str, list[str]]:
    """평균에서 크게 벗어난 항목. {대상 이름: [벗어난 지표…]}"""
    fields = ["avg_sentence", "long_ratio", "dialogue_ratio",
              "paragraph_avg", "ending_top3", "vocabulary"]
    labels = {"avg_sentence": "평균 문장 길이", "long_ratio": "긴 문장 비율",
              "dialogue_ratio": "대사 비율", "paragraph_avg": "문단 길이",
              "ending_top3": "어미 쏠림", "vocabulary": "어휘 다양성"}

    out: dict[str, list[str]] = defaultdict(list)
    if len(rows) < 3:
        return {}

    for field_name in fields:
        values = [getattr(r, field_name) for r in rows]
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        stdev = variance ** 0.5
        if stdev == 0:
            continue
        for row, value in zip(rows, values):
            if abs(value - mean) > sigma * stdev:
                direction = "높음" if value > mean else "낮음"
                out[row.name].append(f"{labels[field_name]} {direction}")
    return dict(out)


# ------------------------------------------------------------------ 내보내기

def normalize_body(text: str, *, indent: bool = False, scene_mark: str = "",
                   join_lines: bool = False) -> str:
    """본문을 읽기 좋게 정리한다. 문단 사이 빈 줄 하나, 선택적으로 첫 줄 들여쓰기.

    한글 원고는 보통 한 줄이 한 문단이라 줄마다 문단으로 본다. 문단이 여러 줄에
    걸쳐 접혀 있는 파일이면 join_lines 로 한 문단으로 합친다.
    """
    text = strip_headings(text)
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        if SEPARATOR_ONLY.match(block):
            paragraphs.append(scene_mark or block)
            continue
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if join_lines:
            lines = [" ".join(lines)]
        for line in lines:
            paragraphs.append(("　" + line) if indent else line)
    return "\n\n".join(paragraphs)


def tidy_text(text: str, *, indent: bool = False, scene_mark: str = "",
              join_lines: bool = False) -> str:
    """원고 파일을 그대로 다시 쓸 수 있게 정리한다. 제목 줄은 남긴다.

    normalize_body 는 내보내기용이라 제목을 뗀다. 파일에 되쓸 때 그걸 쓰면
    화 제목이 사라진다.
    """
    chunks: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        body = normalize_body("\n".join(buffer), indent=indent,
                              scene_mark=scene_mark, join_lines=join_lines)
        if body:
            chunks.append(body)
        buffer.clear()

    for line in text.splitlines():
        if HEADING_LINE.match(line):
            flush()
            chunks.append(line.strip())
        else:
            buffer.append(line)
    flush()
    return "\n\n".join(chunks) + "\n" if chunks else ""


def chapter_title(path: "Path", text: str) -> str:
    """파일 첫 제목 줄이 있으면 그것을, 없으면 파일 이름을 쓴다."""
    for line in text.splitlines():
        if m := HEADING_LINE.match(line):
            return m.group(2).strip()
        if line.strip():
            break
    return path.stem


EXPORT_CSS = """
:root { --ink:#1b1a18; --dim:#6b6862; --paper:#fdfcfa; --line:#e6e2db; }
@media (prefers-color-scheme: dark) {
  :root { --ink:#e9e6e0; --dim:#9a948b; --paper:#171614; --line:#332f2a; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--paper); color:var(--ink);
  font:17px/1.9 "Noto Serif KR","Nanum Myeongjo","Apple SD Gothic Neo",serif;
  word-break:keep-all; }
.wrap { max-width:38rem; margin:0 auto; padding:4rem 1.5rem 6rem; }
.title { text-align:center; margin-bottom:4rem; }
.title h1 { font-size:2rem; margin:0 0 .5rem; letter-spacing:-0.02em; }
.title .author { color:var(--dim); }
.title .meta { color:var(--dim); font-size:.85rem; margin-top:1.5rem; }
nav { border-top:1px solid var(--line); border-bottom:1px solid var(--line);
  padding:1.2rem 0; margin-bottom:3rem; }
nav ol { margin:0; padding-left:1.2rem; color:var(--dim); }
nav a { color:inherit; text-decoration:none; }
nav a:hover { color:var(--ink); text-decoration:underline; }
h2 { font-size:1.3rem; margin:4rem 0 2rem; padding-top:1rem;
  border-top:1px solid var(--line); }
p { margin:0 0 1.1rem; text-align:justify; }
.break { text-align:center; color:var(--dim); margin:2.5rem 0; letter-spacing:.6em; }
footer { margin-top:5rem; color:var(--dim); font-size:.85rem; text-align:center; }
@media print {
  body { background:#fff; color:#000; font-size:11pt; }
  .wrap { max-width:none; padding:0; }
  nav { display:none; }
  h2 { page-break-before:always; border:0; }
  .title { page-break-after:always; }
}
"""


def export_html(chapters: list[tuple[str, str]], *, title: str = "",
                author: str = "", note: str = "", indent: bool = False) -> str:
    """HTML 로 묶는다. 들여쓰기는 공백 문자가 아니라 CSS 로 준다.

    브라우저는 문단 앞 공백을 접어 버려서 전각 공백을 넣어도 보이지 않는다.
    """
    from html import escape

    def paragraphs(body: str) -> str:
        out = []
        for block in body.split("\n\n"):
            block = block.strip()
            if not block:
                continue
            if SEPARATOR_ONLY.match(block) or block in ("＊", "*"):
                out.append('<div class="break">＊ ＊ ＊</div>')
            else:
                out.append(f"<p>{escape(block)}</p>")
        return "\n".join(out)

    toc = "\n".join(f'<li><a href="#장{i}">{escape(name)}</a></li>'
                    for i, (name, _) in enumerate(chapters, 1))
    body = "\n".join(
        f'<h2 id="장{i}">{escape(name)}</h2>\n{paragraphs(text)}'
        for i, (name, text) in enumerate(chapters, 1))

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title or "원고")}</title>
<style>{EXPORT_CSS}{"p { text-indent: 1em; }" if indent else ""}</style>
</head>
<body>
<div class="wrap">
  <div class="title">
    <h1>{escape(title or "원고")}</h1>
    {f'<div class="author">{escape(author)}</div>' if author else ""}
    {f'<div class="meta">{escape(note)}</div>' if note else ""}
  </div>
  <nav><ol>{toc}</ol></nav>
{body}
</div>
</body>
</html>
"""


def export_text(chapters: list[tuple[str, str]], *, title: str = "",
                author: str = "", note: str = "", markdown: bool = False) -> str:
    lines: list[str] = []
    if title:
        lines.append(f"# {title}" if markdown else title)
    if author:
        lines.append(author)
    if note:
        lines.append("")
        lines.append(note)
    lines.append("")

    for name, text in chapters:
        lines.append("")
        lines.append(f"## {name}" if markdown else f"[ {name} ]")
        lines.append("")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ------------------------------------------------------------------ 집필 속도

@dataclass
class DayCount:
    day: date
    total: int
    written: int          # 그날 늘어난 글자수. 첫날은 0(기준일이라 알 수 없다)
    baseline: bool = False


@dataclass
class Pace:
    days: list[DayCount]
    goal: int = 0
    due: date | None = None

    @property
    def current(self) -> int:
        return self.days[-1].total if self.days else 0

    @property
    def span(self) -> int:
        """기록이 걸친 날 수(첫 기록일부터 마지막 기록일까지)."""
        if len(self.days) < 2:
            return 0
        return (self.days[-1].day - self.days[0].day).days

    @property
    def written_days(self) -> int:
        return len([d for d in self.days if d.written > 0])

    @property
    def per_day(self) -> float:
        """달력 하루 평균. 쉰 날도 나눈다. 기록이 하루뿐이면 0."""
        if self.span <= 0:
            return 0.0
        return (self.days[-1].total - self.days[0].total) / self.span

    @property
    def per_written_day(self) -> float:
        """실제로 쓴 날만 나눈 평균."""
        wrote = [d.written for d in self.days if d.written > 0]
        return sum(wrote) / len(wrote) if wrote else 0.0

    @property
    def best(self) -> DayCount | None:
        wrote = [d for d in self.days if d.written > 0]
        return max(wrote, key=lambda d: d.written) if wrote else None

    @property
    def remaining(self) -> int:
        return max(0, self.goal - self.current) if self.goal else 0

    def days_left(self, today: date | None = None) -> int | None:
        if self.due is None:
            return None
        return (self.due - (today or date.today())).days

    def need_per_day(self, today: date | None = None) -> float | None:
        """마감까지 하루에 써야 하는 양. 마감이 지났으면 None."""
        left = self.days_left(today)
        if left is None or left <= 0 or not self.goal:
            return None
        return self.remaining / left

    def finish_day(self, today: date | None = None) -> date | None:
        """지금 속도로 갔을 때 목표에 닿는 날. 속도나 목표가 없으면 None."""
        if not self.goal or self.per_day <= 0:
            return None
        if not self.remaining:
            return today or date.today()
        return (today or date.today()) + timedelta(
            days=int(self.remaining / self.per_day + 0.999))


def daily_counts(snapshots: list[dict]) -> list[DayCount]:
    """스냅샷을 날짜별로 접는다. 하루에 여러 번 찍었으면 그날 마지막 것만 본다.

    첫날은 그 전에 얼마를 썼는지 알 수 없으므로 증가량을 0 으로 두고
    기준일로 표시한다. 0자를 쓴 날과 섞이지 않게 하려는 것이다.
    """
    by_day: dict[date, int] = {}
    for snap in snapshots:
        stamp = snap.get("time") or ""
        try:
            when = datetime.fromisoformat(stamp).date()
        except ValueError:
            continue
        by_day[when] = snap.get("total", 0)

    out: list[DayCount] = []
    previous: int | None = None
    for when in sorted(by_day):
        amount = by_day[when]
        if previous is None:
            out.append(DayCount(when, amount, 0, baseline=True))
        else:
            out.append(DayCount(when, amount, amount - previous))
        previous = amount
    return out


def pace(snapshots: list[dict], *, window: int = 0, goal: int = 0,
         due: date | None = None) -> Pace:
    """window 일 안의 기록만 본다. 0 이면 전부."""
    days = daily_counts(snapshots)
    if window and days:
        edge = days[-1].day - timedelta(days=window)
        kept = [d for d in days if d.day >= edge]
        if len(kept) >= 2:
            kept[0] = DayCount(kept[0].day, kept[0].total, 0, baseline=True)
            days = kept
    return Pace(days=days, goal=goal, due=due)


# --------------------------------------------------------------------- EPUB

EPUB_CSS = """@charset "utf-8";
body { margin: 0 5%; line-height: 1.8; word-break: keep-all; }
h1 { font-size: 1.6em; margin: 2em 0 1.5em; text-align: center; }
h2 { font-size: 1.25em; margin: 1.5em 0 1.5em; }
p { margin: 0 0 0.9em; text-align: justify; }
p.indent { text-indent: 1em; }
.break { text-align: center; margin: 2em 0; letter-spacing: 0.5em; }
.author { text-align: center; color: #666; }
"""


def _xhtml(title: str, body: str) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops" lang="ko">\n'
            f"<head><meta charset=\"utf-8\"/><title>{title}</title>"
            '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
            f"<body>\n{body}\n</body>\n</html>\n")


def epub_chapter(name: str, body: str, *, indent: bool = False) -> str:
    """한 화를 XHTML 로. 리더가 XML 파서를 쓰므로 태그를 반드시 닫는다."""
    from html import escape

    out = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if SEPARATOR_ONLY.match(block) or block in ("＊", "*"):
            out.append('<p class="break">＊ ＊ ＊</p>')
            continue
        text = escape(block).replace("\n", "<br/>\n")
        out.append(f'<p class="indent">{text}</p>' if indent else f"<p>{text}</p>")
    return _xhtml(escape(name), f"<h2>{escape(name)}</h2>\n" + "\n".join(out))


def export_epub(chapters: list[tuple[str, str]], dest: "Path", *, title: str = "",
                author: str = "", note: str = "", indent: bool = False,
                language: str = "ko", identifier: str = "") -> "Path":
    """EPUB 3 로 묶는다. e북 리더에서 교정할 때 쓴다.

    mimetype 은 압축하지 않고 맨 앞에 넣어야 한다. 이 순서가 어긋나면
    리더가 파일을 열지 못한다.
    """
    import uuid
    import zipfile
    from html import escape

    book_title = title or "원고"
    book_id = identifier or f"urn:uuid:{uuid.uuid4()}"
    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    names = [f"ch{i:03d}.xhtml" for i in range(1, len(chapters) + 1)]

    cover_body = [f"<h1>{escape(book_title)}</h1>"]
    if author:
        cover_body.append(f'<p class="author">{escape(author)}</p>')
    if note:
        cover_body.append(f'<p class="author">{escape(note)}</p>')

    items = "\n".join(
        f'    <item id="ch{i:03d}" href="{name}" media-type="application/xhtml+xml"/>'
        for i, name in enumerate(names, 1))
    spine = "\n".join(f'    <itemref idref="ch{i:03d}"/>'
                      for i in range(1, len(names) + 1))
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{escape(book_id)}</dc:identifier>
    <dc:title>{escape(book_title)}</dc:title>
    <dc:language>{escape(language)}</dc:language>
    {f"<dc:creator>{escape(author)}</dc:creator>" if author else ""}
    <meta property="dcterms:modified">{stamp}</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="css" href="style.css" media-type="text/css"/>
    <item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>
{items}
  </manifest>
  <spine>
    <itemref idref="cover"/>
{spine}
  </spine>
</package>
"""
    toc = "\n".join(f'      <li><a href="{name}">{escape(chapter[0])}</a></li>'
                    for name, chapter in zip(names, chapters))
    nav = _xhtml("목차",
                 '<nav epub:type="toc" id="toc">\n    <h2>목차</h2>\n'
                 f"    <ol>\n{toc}\n    </ol>\n  </nav>")

    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0" encoding="utf-8"?>\n'
                   '<container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
                   '  <rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles>\n'
                   "</container>\n")
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", nav)
        z.writestr("OEBPS/style.css", EPUB_CSS)
        z.writestr("OEBPS/cover.xhtml", _xhtml(escape(book_title),
                                               "\n".join(cover_body)))
        for name, (chapter, body) in zip(names, chapters):
            z.writestr(f"OEBPS/{name}", epub_chapter(chapter, body, indent=indent))
    return dest
