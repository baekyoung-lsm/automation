"""한글 파일명·텍스트 처리 유틸."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# macOS(HFS+/APFS)에서 만들어진 한글 파일명은 자모가 분리된 NFD로 저장된다.
# 리눅스/윈도우로 옮기면 "ㅎㅏㄴㄱㅡㄹ"처럼 깨져 보이거나 검색이 안 된다.
JAMO_RANGES = (
    (0x1100, 0x11FF),  # Hangul Jamo
    (0x3130, 0x318F),  # Hangul Compatibility Jamo
    (0xA960, 0xA97F),  # Jamo Extended-A
    (0xD7B0, 0xD7FF),  # Jamo Extended-B
)

WIN_FORBIDDEN = r'<>:"/\|?*'
WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def is_decomposed(text: str) -> bool:
    """NFD로 분리된 한글 자모가 섞여 있으면 True."""
    for ch in text:
        code = ord(ch)
        for lo, hi in JAMO_RANGES:
            if lo <= code <= hi:
                return True
    return False


def to_nfc(text: str) -> str:
    """분리된 자모를 완성형(NFC)으로 합친다."""
    return unicodedata.normalize("NFC", text)


NAME_BYTES = 255            # 파일 이름 하나의 바이트 한도


def sanitize_filename(name: str, *, space: str = "keep", lower_ext: bool = True) -> str:
    """파일명을 안전하게 다듬는다. 확장자는 보존한다.

    space: keep(그대로) | underscore(_로) | strip(공백 압축만)
    """
    name = to_nfc(name)

    dotfile = name.startswith(".")
    if dotfile:
        name = name[1:]

    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:  # 확장자 없음 또는 ".bashrc"
        stem, ext = name, ""
    ext = re.sub(r"[^0-9A-Za-z가-힣]", "", ext.strip())
    if lower_ext:
        ext = ext.lower()

    # 제어문자 제거 + 윈도우 금지문자 치환
    stem = "".join(ch for ch in stem if unicodedata.category(ch) != "Cc")
    stem = re.sub(f"[{re.escape(WIN_FORBIDDEN)}]", "-", stem)

    # 공백/구분자 정리
    stem = re.sub(r"\s+", " ", stem).strip()
    stem = re.sub(r"[-_]{2,}", lambda m: m.group(0)[0], stem)
    stem = stem.strip(" .-_")

    if space == "underscore":
        stem = stem.replace(" ", "_")

    if not stem:
        stem = "untitled"
    if stem.upper() in WIN_RESERVED:
        stem = f"_{stem}"

    # 파일 이름 하나는 대개 255바이트까지다. 한글은 한 자에 3바이트라 여든
    # 자 남짓이면 넘는다 - 넘겨 쓰면 OSError 가 나고 그 자리에서 멎는다
    room = NAME_BYTES - (len(ext.encode("utf-8")) + 1 if ext else 0) - int(dotfile)
    stem = _clip_bytes(stem, room)

    out = f"{stem}.{ext}" if ext else stem
    return f".{out}" if dotfile else out


def _clip_bytes(text: str, limit: int) -> str:
    """UTF-8 바이트 수로 자른다. 글자 가운데서 자르지 않는다."""
    if len(text.encode("utf-8")) <= limit:
        return text
    out: list[str] = []
    size = 0
    for ch in text:
        width = len(ch.encode("utf-8"))
        if size + width > limit:
            break
        out.append(ch)
        size += width
    return "".join(out).strip(" .-_") or "untitled"


def hangul_ratio(text: str) -> float:
    """전체 문자 중 한글 음절 비율. 언어 판별용."""
    if not text:
        return 0.0
    han = sum(1 for ch in text if 0xAC00 <= ord(ch) <= 0xD7A3)
    return han / len(text)


def has_batchim(syllable: str) -> bool | None:
    """한글 음절의 받침 유무. 한글이 아니면 None."""
    if not syllable:
        return None
    code = ord(syllable[-1])
    if not (0xAC00 <= code <= 0xD7A3):
        return None
    return (code - 0xAC00) % 28 != 0


# 숫자는 읽는 소리로 받침을 본다. 2(이)·4(사)·5(오)·9(구)만 받침이 없다.
DIGIT_BATCHIM = {"0": True, "1": True, "2": False, "3": True, "4": False,
                 "5": False, "6": True, "7": True, "8": True, "9": False}


def ends_with_batchim(word: str) -> bool | None:
    """낱말 끝소리에 받침이 있는지. 한글도 숫자도 아니면 None.

    '2를', '3을' 처럼 숫자로 끝나는 말도 흔해서 읽는 소리로 판단한다.
    """
    if not word:
        return None
    last = word[-1]
    if last in DIGIT_BATCHIM:
        return DIGIT_BATCHIM[last]
    return has_batchim(last)


# 어간 뒤에 붙는 조사. 긴 것부터 떼어내야 '에게서'를 '에'로 자르지 않는다.
PARTICLES = [
    "에게서", "한테서", "으로써", "으로서", "에서는", "에게는", "이라고", "라고는",
    "에게", "한테", "으로", "께서", "에서", "라고", "이라", "부터", "까지", "조차",
    "마저", "처럼", "보다", "밖에", "대로", "만큼", "이나", "든지",
    "은", "는", "이", "가", "을", "를", "와", "과", "도", "만", "의", "에", "로", "야", "아",
]


def strip_particle(word: str) -> tuple[str, str]:
    """어절에서 조사를 떼어 (어간, 조사). 못 떼면 (어절, '')."""
    for p in PARTICLES:
        if len(word) > len(p) + 1 and word.endswith(p):
            return word[: -len(p)], p
    return word, ""


def is_riul_batchim(word: str) -> bool:
    """끝 글자의 받침이 ㄹ 인지. '서울로' 처럼 조사가 달라진다."""
    if not word:
        return False
    code = ord(word[-1])
    return 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 == 8


def josa(word: str, pair: str = "은/는") -> str:
    """받침에 맞는 조사를 붙여 반환한다. 예: josa("책", "이/가") -> "책이"."""
    with_batchim, _, without = pair.partition("/")
    flag = ends_with_batchim(word)
    if flag is None:
        return word + with_batchim
    # 받침이 ㄹ 이면 '으로' 가 아니라 '로' 다 (서울로, 하늘로).
    if flag and with_batchim.startswith("으") and is_riul_batchim(word):
        return word + without
    return word + (with_batchim if flag else without)


# ------------------------------------------------------------ 흔한 표기 오류

# 맞춤법 검사기가 아니다. 문맥을 봐야 하는 것(되/돼 전반, 낳다/낫다,
# 들리다/들르다, 바램)은 넣지 않았다. 어떤 문맥에서도 틀린 표기만 넣는다.
# '찌게'(살이 찌게), '일부로'(일부로 나뉘다)처럼 다른 뜻으로 쓰일 수 있는 말은
# 통째로 빼거나 '김치찌게'처럼 앞말을 붙여 좁혔다.
# (틀린 표기, 바른 표기, 설명)
TYPO_RULES: list[tuple[str, str, str]] = [
    ("몇일", "며칠", "'며칠'만 맞는 표기다"),
    ("왠만", "웬만", "'웬만하다'"),
    ("웬지", "왠지", "'왜인지'가 줄어 '왠지'"),
    ("어떻해", "어떡해", "'어떻게 해'가 줄면 '어떡해'"),
    ("됬", "됐", "'되었'이 줄면 '됐'"),
    ("되요", "돼요", "'되어요'가 줄면 '돼요'"),
    ("뵈요", "봬요", "'뵈어요'가 줄면 '봬요'"),
    ("뭐에요", "뭐예요", "받침 없는 말 뒤에는 '예요'"),
    ("역활", "역할", ""),
    ("설레임", "설렘", "'설레다'의 명사형"),
    ("희안", "희한", ""),
    ("오랫만", "오랜만", "'오래간만'이 줄면 '오랜만'"),
    ("어의없", "어이없", ""),
    ("뇌졸증", "뇌졸중", ""),
    ("궁시렁", "구시렁", ""),
    ("짜집기", "짜깁기", ""),
    ("무릎쓰", "무릅쓰", "'무릅쓰다'. 신체 무릎과 다르다"),
    ("곰곰히", "곰곰이", ""),
    ("일일히", "일일이", ""),
    ("틈틈히", "틈틈이", ""),
    ("깨끗히", "깨끗이", ""),
    ("솔직이", "솔직히", ""),
    ("잠궈", "잠가", "'잠그다'라서 '잠가'"),
    ("잠궜", "잠갔", "'잠그다'라서 '잠갔'"),
    ("담궈", "담가", "'담그다'라서 '담가'"),
    ("담궜", "담갔", "'담그다'라서 '담갔'"),
    ("치뤘", "치렀", "'치르다'라서 '치렀'"),
    ("치룰", "치를", "'치르다'라서 '치를'"),
    ("설겆이", "설거지", ""),
    ("육계장", "육개장", ""),
    ("떡볶기", "떡볶이", ""),
    ("김치찌게", "김치찌개", ""),
    ("된장찌게", "된장찌개", ""),
    ("부대찌게", "부대찌개", ""),
    ("순두부찌게", "순두부찌개", ""),
    ("베게를", "베개를", "베는 물건은 '베개'"),
    ("베게가", "베개가", "베는 물건은 '베개'"),
    ("베게에", "베개에", "베는 물건은 '베개'"),
    ("갯수", "개수", "한자어 사이에는 사이시옷을 넣지 않는다"),
    ("촛점", "초점", "한자어 사이에는 사이시옷을 넣지 않는다"),
    ("읍니다", "습니다", "1988년에 '습니다'로 통일됐다"),
    ("나름데로", "나름대로", ""),
    ("오랜동안", "오랫동안", "'오랫동안'만 맞는 표기다"),
    ("왠일", "웬일", "'어찌 된 일'은 '웬일'"),
    ("삼가하", "삼가", "'삼가다'라서 '삼가세요'"),
    ("삼가해", "삼가", "'삼가다'라서 '삼가 주세요'"),
    ("만듬", "만듦", "'만들다'의 명사형은 '만듦'"),
    ("폐륜", "패륜", ""),
    ("뒤치닥거리", "뒤치다꺼리", ""),
    ("널부러", "널브러", ""),
    ("움추리", "움츠리", ""),
    ("부시시", "부스스", ""),
    ("쭈꾸미", "주꾸미", ""),
    ("곱배기", "곱빼기", ""),
    ("닥달", "닦달", ""),
    ("어리버리", "어리바리", ""),
    ("재털이", "재떨이", ""),
    ("눈쌀", "눈살", "'눈살을 찌푸리다'"),
    ("안스러", "안쓰러", ""),
    ("개거품", "게거품", "게가 뿜는 거품이라 '게거품'"),
    ("아지랭이", "아지랑이", ""),
    ("챙피", "창피", ""),
    ("승락", "승낙", ""),
    ("통채로", "통째로", ""),
    ("실증나", "싫증나", "'싫증'"),
    ("궁굼", "궁금", ""),
    ("임마", "인마", "'이놈아'가 줄면 '인마'"),

    # 외래어 표기법. 사무 문서에 자주 나오는 것만.
    ("워크샵", "워크숍", "외래어 표기법"),
    ("스케쥴", "스케줄", "외래어 표기법"),
    ("프리젠테이션", "프레젠테이션", "외래어 표기법"),
    ("비지니스", "비즈니스", "외래어 표기법"),
    ("메세지", "메시지", "외래어 표기법"),
    ("컨텐츠", "콘텐츠", "외래어 표기법"),
    ("컨셉트", "콘셉트", "외래어 표기법"),
    ("데이타", "데이터", "외래어 표기법"),
    ("버젼", "버전", "외래어 표기법"),
    ("비젼", "비전", "외래어 표기법"),
    ("리더쉽", "리더십", "외래어 표기법"),
    ("멤버쉽", "멤버십", "외래어 표기법"),
    ("악세사리", "액세서리", "외래어 표기법"),
    ("카달로그", "카탈로그", "외래어 표기법"),
    ("리모콘", "리모컨", "외래어 표기법"),
    ("심포지움", "심포지엄", "외래어 표기법"),
    ("앙케이트", "앙케트", "외래어 표기법"),
    ("트랜드", "트렌드", "외래어 표기법"),
    ("매니아", "마니아", "외래어 표기법"),
    ("미스테리", "미스터리", "외래어 표기법"),
    ("로얄", "로열", "외래어 표기법"),
    ("씨리즈", "시리즈", "외래어 표기법"),
    ("어플리케이션", "애플리케이션", "외래어 표기법"),
    ("네트웍", "네트워크", "외래어 표기법"),
    ("팜플렛", "팸플릿", "외래어 표기법"),
    ("앰블런스", "앰뷸런스", "외래어 표기법"),
    ("소세지", "소시지", "외래어 표기법"),
    ("초콜렛", "초콜릿", "외래어 표기법"),
    ("도너츠", "도넛", "외래어 표기법"),
    ("쥬스", "주스", "외래어 표기법"),
    ("까페", "카페", "외래어 표기법"),
    ("텔레비젼", "텔레비전", "외래어 표기법"),
    ("알콜", "알코올", "외래어 표기법"),
    ("데뷰", "데뷔", "외래어 표기법"),
    ("넌센스", "난센스", "외래어 표기법"),
    ("바베큐", "바비큐", "외래어 표기법"),
    ("스티로폴", "스티로폼", "외래어 표기법"),
    ("레포트", "리포트", "외래어 표기법"),
]

# 약속의 어미는 '-ㄹ게' 다. '할께, 갈께' 처럼 ㄹ 받침 뒤의 '께' 만 본다
# ('선생님께' 같은 조사는 건드리면 안 된다).
RIUL_KKE = re.compile(r"([가-힣])께(?![\w가-힣])")


@dataclass
class Typo:
    line: int
    column: int
    wrong: str
    right: str
    note: str
    context: str


def _kke_fix(text: str) -> list[tuple[int, str, str, str]]:
    """(위치, 틀린 표기, 바른 표기, 설명) 목록."""
    out = []
    for m in RIUL_KKE.finditer(text):
        if not is_riul_batchim(m.group(1)):
            continue
        out.append((m.start(), m.group(0), m.group(1) + "게",
                    "약속의 어미는 '-ㄹ게'"))
    return out


def find_typos(text: str) -> list[Typo]:
    """확인한 규칙에 걸리는 자리를 찾는다. 맞춤법 검사기가 아니다."""
    starts: list[int] = []
    pos = 0
    for line in text.splitlines(keepends=True):
        starts.append(pos)
        pos += len(line)

    def where(index: int) -> tuple[int, int, str]:
        line_no = max(0, len([s for s in starts if s <= index]) - 1)
        begin = starts[line_no] if starts else 0
        body = text[begin:].split("\n", 1)[0]
        return line_no + 1, index - begin + 1, body.strip()

    hits: list[tuple[int, str, str, str]] = []
    for wrong, right, note in TYPO_RULES:
        start = 0
        while (found := text.find(wrong, start)) != -1:
            hits.append((found, wrong, right, note))
            start = found + len(wrong)
    hits.extend(_kke_fix(text))

    out: list[Typo] = []
    for index, wrong, right, note in sorted(hits):
        line, column, context = where(index)
        out.append(Typo(line, column, wrong, right, note, context))
    return out


def fix_typos(text: str) -> tuple[str, int]:
    """찾은 자리를 바른 표기로 바꾼다. (새 글, 고친 수)"""
    found = find_typos(text)
    if not found:
        return text, 0

    # 뒤에서부터 바꿔야 앞의 위치가 밀리지 않는다. 위치는 줄·칸으로만 들고
    # 있으므로 같은 글을 다시 찾아 인덱스를 얻는다.
    hits: list[tuple[int, str, str]] = []
    for wrong, right, _ in TYPO_RULES:
        start = 0
        while (index := text.find(wrong, start)) != -1:
            hits.append((index, wrong, right))
            start = index + len(wrong)
    hits += [(i, w, r) for i, w, r, _ in _kke_fix(text)]

    body = text
    for index, wrong, right in sorted(hits, reverse=True):
        body = body[:index] + right + body[index + len(wrong):]
    return body, len(hits)


# --------------------------------------------------- 한/영 자판 잘못 누른 글

# 두벌식 자판. 한글을 칠 자리에 영문으로 쳤을 때 무엇이 나왔어야 하는지.
QWERTY_TO_JAMO = {
    "q": "ㅂ", "w": "ㅈ", "e": "ㄷ", "r": "ㄱ", "t": "ㅅ", "y": "ㅛ",
    "u": "ㅕ", "i": "ㅑ", "o": "ㅐ", "p": "ㅔ",
    "a": "ㅁ", "s": "ㄴ", "d": "ㅇ", "f": "ㄹ", "g": "ㅎ",
    "h": "ㅗ", "j": "ㅓ", "k": "ㅏ", "l": "ㅣ",
    "z": "ㅋ", "x": "ㅌ", "c": "ㅊ", "v": "ㅍ", "b": "ㅠ", "n": "ㅜ", "m": "ㅡ",
    "Q": "ㅃ", "W": "ㅉ", "E": "ㄸ", "R": "ㄲ", "T": "ㅆ",
    "O": "ㅒ", "P": "ㅖ",
}
# 윗글쇠가 따로 없는 자리는 소문자와 같은 자모다 (A -> ㅁ).
for _key, _jamo in list(QWERTY_TO_JAMO.items()):
    QWERTY_TO_JAMO.setdefault(_key.upper(), _jamo)

CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
JONG = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"

# 두 번에 나눠 치는 겹모음·겹받침
JUNG_PAIRS = {("ㅗ", "ㅏ"): "ㅘ", ("ㅗ", "ㅐ"): "ㅙ", ("ㅗ", "ㅣ"): "ㅚ",
              ("ㅜ", "ㅓ"): "ㅝ", ("ㅜ", "ㅔ"): "ㅞ", ("ㅜ", "ㅣ"): "ㅟ",
              ("ㅡ", "ㅣ"): "ㅢ"}
JONG_PAIRS = {("ㄱ", "ㅅ"): "ㄳ", ("ㄴ", "ㅈ"): "ㄵ", ("ㄴ", "ㅎ"): "ㄶ",
              ("ㄹ", "ㄱ"): "ㄺ", ("ㄹ", "ㅁ"): "ㄻ", ("ㄹ", "ㅂ"): "ㄼ",
              ("ㄹ", "ㅅ"): "ㄽ", ("ㄹ", "ㅌ"): "ㄾ", ("ㄹ", "ㅍ"): "ㄿ",
              ("ㄹ", "ㅎ"): "ㅀ", ("ㅂ", "ㅅ"): "ㅄ"}
JUNG_SPLIT = {v: k for k, v in JUNG_PAIRS.items()}
JONG_SPLIT = {v: k for k, v in JONG_PAIRS.items()}
JAMO_TO_QWERTY = {jamo: key for key, jamo in QWERTY_TO_JAMO.items()
                  if key.islower() or jamo in "ㅃㅉㄸㄲㅆㅒㅖ"}

_BASE = 0xAC00


def compose_jamo(jamos: str) -> str:
    """자모 나열을 음절로 묶는다. 한글 IME 가 하는 일을 그대로 흉내 낸다."""
    out: list[str] = []
    cho = jung = jong = ""

    def flush() -> None:
        nonlocal cho, jung, jong
        if cho and jung:
            # 받침이 없으면 JONG.index("") 가 0 이라 그대로 맞는다
            out.append(chr(_BASE + (CHO.index(cho) * 21 + JUNG.index(jung)) * 28
                           + JONG.index(jong)))
        else:
            out.append(cho or jung)
        cho = jung = jong = ""

    for ch in jamos:
        vowel = ch in JUNG
        if not (vowel or ch in CHO or ch in JONG.strip()):
            if cho or jung:
                flush()
            out.append(ch)
            continue

        if not cho and not jung:
            if vowel:
                jung = ch
            else:
                cho = ch
            continue

        if cho and not jung:
            if vowel:
                jung = ch
            else:
                flush()
                cho = ch
            continue

        if jung and not cho:                    # 홀로 선 모음 뒤
            if vowel and (jung, ch) in JUNG_PAIRS:
                jung = JUNG_PAIRS[(jung, ch)]
            else:
                flush()
                if vowel:
                    jung = ch
                else:
                    cho = ch
            continue

        if not jong:
            if vowel:
                if (jung, ch) in JUNG_PAIRS:
                    jung = JUNG_PAIRS[(jung, ch)]
                else:
                    flush()
                    jung = ch
            elif ch in JONG:
                jong = ch
            else:                               # ㄸ·ㅃ·ㅉ 은 받침이 못 된다
                flush()
                cho = ch
            continue

        if vowel:                               # 받침이 다음 글자로 넘어간다
            moved = jong
            if jong in JONG_SPLIT:
                jong, moved = JONG_SPLIT[jong]
            else:
                jong = ""
            flush()
            cho, jung = moved, ch
        elif (jong, ch) in JONG_PAIRS:
            jong = JONG_PAIRS[(jong, ch)]
        else:
            flush()
            cho = ch

    if cho or jung:
        flush()
    return "".join(out)


def decompose_syllable(ch: str) -> str:
    """음절 하나를 자모로 푼다. 겹모음·겹받침도 친 순서대로 나눈다."""
    code = ord(ch) - _BASE
    if not 0 <= code < 11172:
        return ch
    cho = CHO[code // 588]
    jung = JUNG[(code % 588) // 28]
    jong = JONG[code % 28].strip()
    parts = [cho, *JUNG_SPLIT.get(jung, (jung,))]
    if jong:
        parts.extend(JONG_SPLIT.get(jong, (jong,)))
    return "".join(parts)


def to_hangul(text: str) -> str:
    """영문 자판으로 친 글을 한글로. dkssud -> 안녕"""
    return compose_jamo("".join(QWERTY_TO_JAMO.get(ch, ch) for ch in text))


def to_qwerty(text: str) -> str:
    """한글로 친 글을 영문 자판 글자로. 안녕 -> dkssud"""
    out = []
    for ch in text:
        for jamo in decompose_syllable(ch):
            out.append(JAMO_TO_QWERTY.get(jamo, jamo))
    return "".join(out)


def mistyped_direction(text: str) -> str:
    """어느 쪽으로 고쳐야 할지 짐작한다. 'ko', 'en', 또는 빈 문자열."""
    hangul = sum(1 for ch in text if "가" <= ch <= "힣" or ch in JUNG or ch in CHO)
    letters = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    if hangul and not letters:
        return "en"
    if letters and not hangul:
        return "ko"
    return ""
