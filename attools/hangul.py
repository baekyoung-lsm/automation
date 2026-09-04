"""한글 파일명·텍스트 처리 유틸."""

from __future__ import annotations

import re
import unicodedata

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
