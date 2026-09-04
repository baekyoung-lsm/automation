"""화면에서 온 값을 다듬는다. 믿지 않고 한 번 더 본다."""

from __future__ import annotations

from pathlib import Path

from . import UiError


def text(payload: dict, key: str, default: str = "") -> str:
    value = payload.get(key, default)
    if not isinstance(value, str):
        raise UiError(f"{key} 값이 글자가 아닙니다.")
    return value.strip()


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


def existing_file(payload: dict, key: str = "path") -> Path:
    raw = text(payload, key)
    if not raw:
        raise UiError("파일 경로를 적어 주세요.")
    path = Path(raw).expanduser()
    if not path.exists():
        raise UiError(f"그런 파일이 없습니다: {path}")
    if path.is_dir():
        raise UiError(f"파일이 아니라 폴더입니다: {path}")
    return path.resolve()
