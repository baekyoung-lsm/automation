"""화면에서 온 값을 다듬는다. 믿지 않고 한 번 더 본다."""

from __future__ import annotations

from pathlib import Path

from . import UiError


def text(payload: dict, key: str, default: str = "") -> str:
    value = payload.get(key, default)
    if not isinstance(value, str):
        raise UiError(f"{key} 값이 글자가 아닙니다.")
    return value.strip()


def raw_text(payload: dict, key: str, default: str = "") -> str:
    """앞뒤 공백을 그대로 둔다. 찾을 말·바꿀 말처럼 공백이 뜻을 갖는 값에 쓴다."""
    value = payload.get(key, default)
    if not isinstance(value, str):
        raise UiError(f"{key} 값이 글자가 아닙니다.")
    return value


def flag(payload: dict, key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    return bool(value)


def number(payload: dict, key: str, default: float = 0.0, *,
           low: float | None = None, high: float | None = None) -> float:
    raw = payload.get(key, default)
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise UiError(f"{key} 값이 숫자가 아닙니다.") from None
    if low is not None and value < low:
        raise UiError(f"{key} 값은 {low:g} 보다 작을 수 없습니다.")
    if high is not None and value > high:
        raise UiError(f"{key} 값은 {high:g} 보다 클 수 없습니다.")
    return value


def choice(payload: dict, key: str, allowed: dict[str, str] | set[str] | tuple,
           default: str) -> str:
    value = text(payload, key, default) or default
    if value not in allowed:
        raise UiError(f"{key} 값 '{value}' 은(는) 고를 수 없는 값입니다.")
    return value


def folder(payload: dict, key: str = "path") -> Path:
    raw = text(payload, key)
    if not raw:
        raise UiError("폴더 경로를 적어 주세요.")
    path = Path(raw).expanduser()
    if not path.exists():
        raise UiError(f"그런 폴더가 없습니다: {path}")
    if not path.is_dir():
        raise UiError(f"폴더가 아닙니다: {path}")
    return path.resolve()


# 화면은 파일을 통째로 읽어 들이는 자리가 많다. 큰 파일에 서버가 멎지 않게
# 선을 두고, 그럴 때는 터미널 쪽을 안내한다.
MAX_FILE = 64 << 20


def existing_file(payload: dict, key: str = "path", *,
                  max_bytes: int = MAX_FILE) -> Path:
    raw = text(payload, key)
    if not raw:
        raise UiError("파일 경로를 적어 주세요.")
    path = Path(raw).expanduser()
    if not path.exists():
        raise UiError(f"그런 파일이 없습니다: {path}")
    if path.is_dir():
        raise UiError(f"파일이 아니라 폴더입니다: {path}")
    size = path.stat().st_size
    if max_bytes and size > max_bytes:
        raise UiError(f"파일이 너무 큽니다 ({size / (1 << 20):.0f}MB). "
                      "이만한 것은 터미널에서 at 명령으로 다루세요.")
    return path.resolve()


def existing_path(payload: dict, key: str = "path") -> Path:
    """파일이든 폴더든 있기만 하면 된다."""
    raw = text(payload, key)
    if not raw:
        raise UiError("경로를 적어 주세요.")
    path = Path(raw).expanduser()
    if not path.exists():
        raise UiError(f"그런 파일이나 폴더가 없습니다: {path}")
    return path.resolve()


def command(*parts: object) -> str:
    """화면이 한 일을 터미널 명령으로 적어 준다.

    화면만 쓰다 보면 같은 일을 터미널에서 어떻게 하는지 알 수 없다. 여기서
    한 줄 보여 주면 다음부터는 스스로 칠 수 있고, 여러 폴더에 되풀이할 때는
    그쪽이 훨씬 빠르다.
    """
    out = []
    for part in parts:
        if part is None or part == "":
            continue
        out.append(_quote(str(part)))
    return " ".join(["at", *out])


# 셸이 뜻을 갖는 글자. 한글은 여기 없으므로 따옴표를 붙이지 않는다 -
# shlex.quote 는 아스키가 아니면 무조건 감싸서 명령이 지저분해진다.
_SPECIAL = set(" \t\n'\"\\$`*?[]{}();&|<>#~!")


def _quote(text_: str) -> str:
    if not text_:
        return "''"
    if not any(ch in _SPECIAL for ch in text_):
        return text_
    return "'" + text_.replace("'", "'\\''") + "'"
