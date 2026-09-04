"""원고에서 고유명사를 뽑아 표기 흔들림과 이름 뒤 조사 오류를 찾는다."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .hangul import has_batchim

# 어간 뒤에 붙는 조사. 긴 것부터 떼어내야 '에게서'를 '에'로 자르지 않는다.
PARTICLES = [
    "에게서", "한테서", "으로써", "으로서", "에서는", "에게는", "이라고", "라고는",
    "에게", "한테", "으로", "께서", "에서", "라고", "이라", "부터", "까지", "조차",
    "마저", "처럼", "보다", "밖에", "대로", "만큼", "이나", "든지",
    "은", "는", "이", "가", "을", "를", "와", "과", "도", "만", "의", "에", "로", "야", "아",
]

# 받침 유무로 갈리는 조사 짝. (받침 있을 때, 받침 없을 때)
PAIRS = [("이", "가"), ("은", "는"), ("을", "를"), ("과", "와"),
         ("으로", "로"), ("이라", "라"), ("이라고", "라고"),
         ("이나", "나"), ("이랑", "랑"), ("아", "야")]

# 이름으로 오해하기 쉬운 흔한 말. 등장 빈도가 높아 후보에 자꾸 올라온다.
STOPWORDS = {
    "그", "그녀", "그것", "이것", "저것", "우리", "당신", "자신", "누구", "무엇",
    "사람", "사람들", "시간", "순간", "생각", "마음", "얼굴", "목소리", "표정",
    "눈", "손", "발", "머리", "가슴", "입", "귀", "어깨", "등", "몸",
    "말", "소리", "이야기", "대답", "질문", "웃음", "한숨", "숨",
    "오늘", "내일", "어제", "지금", "다음", "마지막", "처음", "이번", "정도",
    "여기", "거기", "저기", "안", "밖", "위", "아래", "앞", "뒤", "옆", "사이",
    "하나", "둘", "모두", "전부", "때문", "경우", "문제", "이유", "방법", "결과",
    "세계", "세상", "나라", "도시", "마을", "집", "방", "문", "길", "하늘", "바람",
}

WORD_RE = re.compile(r"[가-힣]{2,}")
QUOTE_RE = re.compile(r"[\"“”]|[「」『』]")


@dataclass
class Name:
    text: str
    count: int = 0
    particles: Counter = field(default_factory=Counter)

    @property
    def variety(self) -> int:
        """붙은 조사의 종류 수. 고유명사일수록 여러 조사가 붙는다."""
        return len(self.particles)


@dataclass
class JosaError:
    name: str
    wrong: str
    right: str
    line: int
    excerpt: str


def strip_particle(word: str) -> tuple[str, str]:
    """어절에서 조사를 떼어 (어간, 조사). 못 떼면 (어절, '')."""
    for p in PARTICLES:
        if len(word) > len(p) + 1 and word.endswith(p):
            return word[: -len(p)], p
    return word, ""


def all_stems(text: str, *, max_len: int = 5) -> dict[str, Name]:
    """어절에서 조사를 떼어 어간별로 센다."""
    found: dict[str, Name] = {}
    for word in WORD_RE.findall(text):
        stem, particle = strip_particle(word)
        if not (2 <= len(stem) <= max_len) or stem in STOPWORDS:
            continue
        name = found.setdefault(stem, Name(stem))
        name.count += 1
        if particle:
            name.particles[particle] += 1
    return found


def extract(text: str, *, min_count: int = 3, min_variety: int = 2,
            max_len: int = 5) -> list[Name]:
    """조사가 여러 종류 붙어 반복 등장하는 말을 고유명사 후보로 본다."""
    return sorted(
        (n for n in all_stems(text, max_len=max_len).values()
         if n.count >= min_count and n.variety >= min_variety),
        key=lambda n: (-n.count, n.text))   # 같은 횟수면 이름 순으로 고정


def edit_distance(a: str, b: str, limit: int = 2) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def variants(names: list[Name], stems: dict[str, Name], *,
             distance: int = 1) -> list[tuple[Name, Name, int]]:
    """확정된 이름과 비슷한데 드물게만 나오는 표기를 찾는다.

    오타는 원래 드물게 나온다. 그래서 자주 나오는 이름끼리 비교하는 대신,
    이름과 닮았으면서 훨씬 덜 나오는 어간을 흔들림 후보로 본다.
    """
    confirmed = {n.text for n in names}
    out = []
    for name in names:
        for text, stem in stems.items():
            if text in confirmed or stem.count >= name.count:
                continue
            if abs(len(text) - len(name.text)) > 1:
                continue
            d = edit_distance(name.text, text, distance)
            if 0 < d <= distance:
                out.append((name, stem, d))
    return sorted(out, key=lambda x: (x[2], -x[0].count, x[1].count))


def check_josa(text: str, names: list[str]) -> list[JosaError]:
    """아는 이름 뒤에 붙은 조사만 검사한다. 어간 경계를 알아야 오탐이 없다."""
    if not names:
        return []

    lookup = {n: has_batchim(n) for n in names}
    lookup = {n: v for n, v in lookup.items() if v is not None}
    if not lookup:
        return []

    pattern = re.compile(
        "(" + "|".join(sorted(map(re.escape, lookup), key=len, reverse=True)) + ")"
        + "(" + "|".join(sorted({p for pair in PAIRS for p in pair},
                                key=len, reverse=True)) + ")"
        + r"(?![가-힣])")

    errors: list[JosaError] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in pattern.finditer(line):
            name, particle = m.group(1), m.group(2)
            batchim = lookup[name]
            for with_b, without_b in PAIRS:
                if particle not in (with_b, without_b):
                    continue
                # 받침이 ㄹ 이면 '로'가 맞다 (서울로, 하늘로)
                if with_b == "으로" and batchim and name[-1] and (ord(name[-1]) - 0xAC00) % 28 == 8:
                    correct = "로"
                else:
                    correct = with_b if batchim else without_b
                if particle != correct:
                    start = max(0, m.start() - 12)
                    errors.append(JosaError(name, particle, correct, lineno,
                                            line[start:m.end() + 12].strip()))
                break
    return errors


def dialogue_speakers(text: str, names: list[str], *, window: int = 20) -> Counter:
    """대사 뒤쪽에 붙어 나오는 이름을 세어 화자 분포를 어림한다."""
    counts: Counter = Counter()
    if not names:
        return counts
    pattern = re.compile("|".join(sorted(map(re.escape, names), key=len, reverse=True)))
    for m in re.finditer(r"[\"“「『](.+?)[\"”」』]", text, re.S):
        tail = text[m.end(): m.end() + window]
        if found := pattern.search(tail):
            counts[found.group(0)] += 1
    return counts


# --------------------------------------------------------------------- 대사

DIALOGUE_RE = re.compile(r"[\"“](.+?)[\"”]|[「『](.+?)[」』]", re.S)

# 존댓말 종결. 대사 끝을 보고 가른다.
POLITE_END = re.compile(
    r"(?:요|니다|니까|세요|십시오|시죠|시오|습니까|답니다|군요|네요|데요|지요|죠)"
    r"[.!?…\s]*$")
# 화자를 알려 주는 서술: "…" 하고 이름이 말했다 / 이름이 물었다
SPEECH_VERB = re.compile(
    r"(?:말했|물었|답했|외쳤|중얼|속삭|덧붙였|되뇌|내뱉|웃었|읊조)")


@dataclass
class Speech:
    text: str
    speaker: str
    line: int
    polite: bool


@dataclass
class VoiceProfile:
    name: str
    count: int = 0
    chars: int = 0
    polite: int = 0
    endings: Counter = field(default_factory=Counter)

    @property
    def avg_length(self) -> float:
        return self.chars / self.count if self.count else 0.0

    @property
    def polite_ratio(self) -> float:
        return self.polite / self.count if self.count else 0.0

    @property
    def top_endings(self) -> list[tuple[str, int]]:
        return self.endings.most_common(3)


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def extract_speech(text: str, people: list[str], *, window: int = 40) -> list[Speech]:
    """대사를 뽑고 화자를 찾는다.

    찾는 범위를 같은 줄로 제한한다. 줄을 넘어가면 다음 문단에 나오는 이름을
    화자로 잘못 집는다. 한국어 소설은 "…" 하고 이름이 말했다 꼴이 많아
    대사 뒤를 먼저 보고, 없으면 같은 줄의 앞부분을 본다. 둘 다 없으면
    화자를 비워 둔다. 억지로 채우면 인물별 집계가 통째로 어긋난다.
    """
    finder = (re.compile("|".join(sorted(map(re.escape, people), key=len, reverse=True)))
              if people else None)
    out: list[Speech] = []

    for m in DIALOGUE_RE.finditer(text):
        body = (m.group(1) or m.group(2) or "").strip()
        if not body:
            continue

        speaker = ""
        if finder:
            line_end = text.find("\n", m.end())
            line_end = len(text) if line_end < 0 else line_end
            tail = text[m.end(): min(line_end, m.end() + window)]

            line_start = text.rfind("\n", 0, m.start()) + 1
            head = text[max(line_start, m.start() - window): m.start()]

            if found := finder.search(tail):
                speaker = found.group(0)
            elif found := finder.search(head):
                speaker = found.group(0)

        out.append(Speech(body, speaker, _line_of(text, m.start()),
                          bool(POLITE_END.search(body))))
    return out


def voice_profiles(speeches: list[Speech]) -> tuple[list[VoiceProfile], int]:
    """인물별 말투 요약과, 화자를 못 찾은 대사 수."""
    table: dict[str, VoiceProfile] = {}
    unknown = 0

    for s in speeches:
        if not s.speaker:
            unknown += 1
            continue
        profile = table.setdefault(s.speaker, VoiceProfile(s.speaker))
        profile.count += 1
        profile.chars += len(re.sub(r"\s", "", s.text))
        profile.polite += int(s.polite)
        if m := re.search(r"([가-힣]{2})[.!?…\"'”’」』)\s]*$", s.text):
            profile.endings[m.group(1)] += 1

    return sorted(table.values(), key=lambda p: -p.count), unknown


# ------------------------------------------------------------------ 어휘 목록

@dataclass
class Word:
    text: str
    count: int = 0
    sources: Counter = field(default_factory=Counter)   # 파일 이름 -> 횟수

    @property
    def first_source(self) -> str:
        return next(iter(self.sources), "")

    @property
    def spread(self) -> int:
        """몇 개 파일에 걸쳐 나왔는지."""
        return len(self.sources)


def merge_short_stems(table: dict[str, Word]) -> dict[str, Word]:
    """'탑에·탑은·탑을' 처럼 한 글자 어간에 조사가 붙은 것들을 합친다.

    strip_particle 은 어간이 두 글자 미만이면 조사를 떼지 않는다. '가을'을
    '가'+'을'로 자르는 사고를 막기 위해서다. 그래서 두 글자 낱말은 조사가
    붙은 채로 남는데, 같은 한 글자 뒤에 서로 다른 조사가 두 종류 넘게 붙어
    나오면 그건 낱말이 아니라 어간이라고 볼 수 있다.
    """
    candidates: dict[str, set[str]] = defaultdict(set)
    for text in table:
        if len(text) != 2:
            continue
        head, tail = text[0], text[1]
        if tail in PARTICLES:
            candidates[head].add(tail)

    merged = dict(table)
    for head, particles in candidates.items():
        if len(particles) < 2:
            continue
        # 한 글자 어간이 확인됐으니 그 뒤에 붙은 조사는 길이에 상관없이 떼어 낸다
        # ('탑에·탑은'으로 어간을 알았으면 '탑에서'도 같은 말이다)
        attached = [w for w in merged
                    if w.startswith(head) and len(w) > 1 and w[1:] in PARTICLES]
        target = merged.setdefault(head, Word(head))
        for word in attached:
            piece = merged.pop(word, None)
            if piece is None:
                continue
            target.count += piece.count
            target.sources.update(piece.sources)
    return merged


def build_wordlist(documents: list[tuple[str, str]], *, max_len: int = 6,
                   min_count: int = 1, skip_common: bool = True) -> list[Word]:
    """(이름, 본문) 목록에서 어간별 빈도와 처음 나온 곳을 모은다.

    파일 순서를 그대로 지켜야 '어느 화에서 처음 나왔는지'가 맞다.
    skip_common 이면 '마을·얼굴' 같은 흔한 말은 빼는데, 어휘 목록을 통째로
    보고 싶으면 끌 수 있다.
    """
    table: dict[str, Word] = {}
    for name, text in documents:
        for word in WORD_RE.findall(text):
            stem, _ = strip_particle(word)
            if not (2 <= len(stem) <= max_len):
                continue
            if skip_common and stem in STOPWORDS:
                continue
            entry = table.setdefault(stem, Word(stem))
            entry.count += 1
            entry.sources[name] += 1

    table = merge_short_stems(table)
    return sorted((w for w in table.values() if w.count >= min_count),
                  key=lambda w: (-w.count, w.text))


def words_only_in(words: list[Word], source: str) -> list[Word]:
    """그 문서에서만 쓰인 말."""
    return [w for w in words if w.spread == 1 and w.first_source == source]


def first_appearances(words: list[Word], order: list[str]) -> dict[str, list[Word]]:
    """문서마다 그 문서에서 처음 나온 말을 모은다."""
    out: dict[str, list[Word]] = {name: [] for name in order}
    for word in words:
        source = word.first_source
        if source in out:
            out[source].append(word)
    for rows in out.values():
        rows.sort(key=lambda w: -w.count)
    return out


# ------------------------------------------------------------- 화별 등장 흐름

@dataclass
class CastRow:
    name: str
    counts: list[int] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.counts)

    @property
    def first(self) -> int:
        """처음 나온 화 번호(1부터). 한 번도 안 나오면 0."""
        for i, n in enumerate(self.counts, 1):
            if n:
                return i
        return 0

    @property
    def last(self) -> int:
        for i in range(len(self.counts), 0, -1):
            if self.counts[i - 1]:
                return i
        return 0

    def gone_for(self, total_chapters: int | None = None) -> int:
        """마지막 등장 뒤 몇 화가 지났는지."""
        end = total_chapters if total_chapters is not None else len(self.counts)
        return end - self.last if self.last else 0


def count_mentions(text: str, name: str) -> int:
    """이름이 몇 번 나오는지. 더 긴 이름의 일부는 세지 않는다.

    '리안' 을 셀 때 '리안나' 를 세면 인물별 집계가 통째로 어긋난다.
    조사가 붙는 것은 세고, 다른 한글이 이어지면 세지 않는다.
    """
    if not name:
        return 0
    tail = "|".join(re.escape(p) for p in sorted(PARTICLES, key=len, reverse=True))
    pattern = re.compile(re.escape(name) + f"(?:{tail})?(?![가-힣])")
    return len(pattern.findall(text))


def cast_by_chapter(chapters: list[tuple[str, str]],
                    people: list[str]) -> list[CastRow]:
    """화마다 인물이 몇 번 나오는지. 많이 나온 인물이 위로."""
    rows = [CastRow(name, [count_mentions(text, name) for _, text in chapters])
            for name in people]
    return sorted(rows, key=lambda r: (-r.total, r.name))
