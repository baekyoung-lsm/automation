"""원고에서 고유명사를 뽑아 표기 흔들림과 이름 뒤 조사 오류를 찾는다."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

# 조사 목록과 떼기는 hangul 에 있다. 문서 쪽에서도 같은 규칙을 쓴다.
from ..hangul import PARTICLES, has_batchim, strip_particle

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


def merge_nickname_suffix(stems: dict[str, Name]) -> dict[str, Name]:
    """«민준이» 처럼 이름 뒤에 붙는 «이» 를 이름과 한 사람으로 센다.

    받침 있는 이름 뒤의 «이» 는 사람을 부를 때만 붙는다. 따로 세면 «민준» 2회
    와 «민준이» 1회로 갈려 어느 쪽도 후보 수를 못 넘기고, 그 인물의 조사 오류
    도 함께 지나친다. 받침 없는 이름(지수)에는 안 붙으므로 받침을 보고,
    «고양이» 처럼 우연히 «이» 로 끝나는 말은 «고양» 이 따로 나올 때만 합쳐진다.
    """
    merged = {text: name for text, name in stems.items()}
    for text, name in list(stems.items()):
        base = text[:-1]
        if not text.endswith("이") or len(base) < 2 or base not in merged:
            continue
        if has_batchim(base[-1]) is not True:
            continue
        keep = merged[base]
        keep.count += name.count
        keep.particles.update(name.particles)
        merged.pop(text, None)
    return merged


def extract(text: str, *, min_count: int = 3, min_variety: int = 2,
            max_len: int = 5) -> list[Name]:
    """조사가 여러 종류 붙어 반복 등장하는 말을 고유명사 후보로 본다."""
    stems = merge_nickname_suffix(all_stems(text, max_len=max_len))
    return sorted(
        (n for n in stems.values()
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
        # «민준이» 는 «민준» 의 오타가 아니라 부르는 말이다. 흔들림으로 올리면
        # 고치라는 말이 되는데, 고치면 원고의 말맛이 사라진다
        nickname = (name.text + "이") if has_batchim(name.text[-1]) else ""
        for text, stem in stems.items():
            if text in confirmed or text == nickname or stem.count >= name.count:
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
# 대사 옆 줄에 «민준이 물었다» 만 있는 배치가 한국 소설에 아주 흔하다.
# 이름만 있는 줄은 안 보고, 말하는 동사가 함께 있는 줄만 화자로 본다.
SAID_RE = re.compile(
    "말했다|말한다|말을 이었다|물었다|묻는다|되물었다|대답했다|대답한다|"
    "외쳤다|소리쳤다|중얼거렸다|속삭였다|덧붙였다|내뱉었다|읊조렸다")

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
    nearby: bool = False     # 같은 줄이 아니라 옆 줄에서 찾은 화자인가


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
        nearby = False
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
            else:
                speaker = _speaker_nearby(text, m, finder, line_start, line_end)
                nearby = bool(speaker)

        out.append(Speech(body, speaker, _line_of(text, m.start()),
                          bool(POLITE_END.search(body)), nearby))
    return out


def _speaker_nearby(text: str, m: "re.Match", finder: "re.Pattern",
                    line_start: int, line_end: int) -> str:
    """대사 바로 옆 줄에서 화자를 찾는다. 못 찾으면 빈 글자.

    «"오늘도 안 올 거야?"» 다음 줄에 «민준이 물었다» 만 오는 배치가 흔하다.
    이름만 있는 줄은 보지 않는다 - 옆 줄에 다른 인물이 지나가기만 해도
    그 사람이 말한 것이 되어 인물별 집계가 통째로 어긋난다.
    """
    for start, end in _neighbour_lines(text, line_start, line_end):
        line = text[start:end]
        if not line.strip() or DIALOGUE_RE.search(line):
            continue
        found = {m.group(0) for m in finder.finditer(line)}
        # 이름이 둘 이상이면 누가 말했는지 알 수 없다 - «리안은 대답하지
        # 않았다. 카일이 말했다» 에서 아무 쪽이나 집으면 집계가 어긋난다
        if len(found) == 1 and SAID_RE.search(line):
            return found.pop()
        break        # 바로 옆의 지문 한 줄까지만 본다
    return ""


def _neighbour_lines(text: str, line_start: int, line_end: int):
    """대사 줄의 다음 줄, 그다음 앞줄의 (시작, 끝). 빈 줄은 건너뛴다."""
    after = line_end + 1
    while after < len(text):
        stop = text.find("\n", after)
        stop = len(text) if stop < 0 else stop
        if text[after:stop].strip():
            yield after, stop
            break
        after = stop + 1

    before = line_start - 1
    while before > 0:
        start = text.rfind("\n", 0, before) + 1
        if text[start:before].strip():
            yield start, before
            break
        before = start - 1


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


# --------------------------------------------------- 이름 바꾸기 (조사까지)

# 이름 뒤에 붙는 조사 가운데 받침에 따라 꼴이 갈리는 것들. 긴 것부터 본다.
RENAME_PAIRS = [("이라고", "라고"), ("이라는", "라는"), ("이라", "라"),
                ("이었", "였"), ("이랑", "랑"), ("으로", "로"),
                ("이나", "나"), ("이며", "며"), ("이여", "여"),
                ("은", "는"), ("이", "가"), ("을", "를"), ("과", "와"),
                ("아", "야")]
# 받침과 무관한 조사. 이름만 바꾸고 그대로 둔다.
PLAIN_PARTICLES = ["에게서", "한테서", "에게는", "한테는", "에게", "한테", "께서",
                   "에서", "부터", "까지", "조차", "마저", "처럼", "보다",
                   "밖에", "대로", "만큼", "도", "만", "의", "에", "께"]


@dataclass
class Rename:
    line: int
    before: str          # 리안은
    after: str           # 세하는
    excerpt: str


def _particle_after(text: str, at: int) -> str:
    """이름 바로 뒤에 붙은 조사. 없으면 빈 문자열."""
    rest = text[at:at + 4]
    for with_batchim, without in RENAME_PAIRS:
        for form in (with_batchim, without):
            if rest.startswith(form):
                return form
    for plain in PLAIN_PARTICLES:
        if rest.startswith(plain):
            return plain
    return ""


def _fixed_particle(particle: str, new: str) -> str:
    """새 이름의 받침에 맞는 조사. 받침과 무관한 조사는 그대로."""
    for with_batchim, without in RENAME_PAIRS:
        if particle not in (with_batchim, without):
            continue
        if with_batchim.startswith("으") and not has_batchim(new):
            return without
        if with_batchim.startswith("으"):
            from ..hangul import is_riul_batchim

            return without if is_riul_batchim(new) else with_batchim
        return with_batchim if has_batchim(new) else without
    return particle


@dataclass
class RenameHit:
    at: int              # 줄 안에서 이름이 시작하는 자리
    before: str          # 리안은
    after: str           # 세하는


def rename_hits(line: str, old: str, new: str) -> list[RenameHit]:
    """한 줄에서 바꿀 자리들. 미리보기와 적용이 같은 판단을 쓰게 모아 둔다.

    보여 준 것과 실제로 바꾸는 것이 갈리면 되돌리기가 있어도 소용이 없다.
    """
    hits: list[RenameHit] = []
    start = 0
    while (at := line.find(old, start)) != -1:
        end = at + len(old)
        particle = _particle_after(line, end)
        tail = line[end + len(particle):end + len(particle) + 1]
        start = end
        if not particle and tail and "가" <= tail <= "힣":
            continue          # 리안느 - 다른 낱말이다
        # «민준이는» 의 «이» 는 조사가 아니라 받침 있는 이름 뒤에 붙는 말이다.
        # 조사로 보면 «지호가는» 이 되어 문장이 깨진다
        nickname = ""
        if particle == "이" and tail and "가" <= tail <= "힣" and has_batchim(old):
            nickname = "이"
            inner = end + 1
            particle = _particle_after(line, inner)
            tail = line[inner + len(particle):inner + len(particle) + 1]
            if not particle and tail and "가" <= tail <= "힣":
                continue      # 민준이라면 - 다른 낱말이다
        # 새 이름에 받침이 없으면 «이» 도 떨어진다 (지호이는 이라고는 안 한다)
        stem = new + ("이" if nickname and has_batchim(new) else "")
        before = old + nickname + particle
        after = stem + _fixed_particle(particle, stem)
        start = at + len(before)
        if before == after:
            continue
        hits.append(RenameHit(at, before, after))
    return hits


def plan_rename(text: str, old: str, new: str) -> list[Rename]:
    """이름을 바꾸면서 뒤에 붙은 조사도 새 이름에 맞춘다. (바꿀 자리들)

    «리안은» 을 «세하는» 으로 바꾸는 일이다. 이름만 바꾸면 «세하은» 이 되어
    원고 전체를 손으로 고치게 된다. 이름 뒤가 조사도 아니고 띄어쓰기도
    아니면(«리안느») 다른 낱말로 보고 건드리지 않는다.
    """
    if not old or not new:
        raise ValueError("옛 이름과 새 이름을 모두 주세요.")

    out: list[Rename] = []
    for number, line in enumerate(text.splitlines(), 1):
        for hit in rename_hits(line, old, new):
            out.append(Rename(number, hit.before, hit.after, line.strip()))
    return out


def apply_rename(text: str, old: str, new: str) -> tuple[str, int]:
    """이름과 조사를 바꾼 글과 바꾼 횟수."""
    if not old or not new:
        raise ValueError("옛 이름과 새 이름을 모두 주세요.")

    lines = text.splitlines(keepends=True)
    count = 0
    for index, line in enumerate(lines):
        hits = rename_hits(line, old, new)
        if not hits:
            continue
        out: list[str] = []
        done = 0
        for hit in hits:
            out.append(line[done:hit.at])
            out.append(hit.after)
            done = hit.at + len(hit.before)
            count += 1
        out.append(line[done:])
        lines[index] = "".join(out)
    return "".join(lines), count
