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

    out = f"{stem}.{ext}" if ext else stem
    return f".{out}" if dotfile else out


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
