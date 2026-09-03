"""JSON 구조 훑기·비교·평탄화. API 응답이 언제 어떻게 바뀌었는지 보는 용도."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

MISSING = object()


class JsonError(Exception):
    pass


def load(source: str | Path):
    """파일 경로나 '-'(표준 입력)에서 JSON 을 읽는다. JSON Lines 도 받는다."""
    if str(source) == "-":
        raw = sys.stdin.read()
        name = "표준 입력"
    else:
        path = Path(source)
        if not path.is_file():
            raise JsonError(f"파일이 없습니다: {path}")
        raw = path.read_text(encoding="utf-8-sig")
        name = str(path)

    raw = raw.strip()
    if not raw:
        raise JsonError(f"{name}: 내용이 비어 있습니다")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as first:
        lines = [l for l in raw.splitlines() if l.strip()]
        if len(lines) > 1:
            try:  # JSON Lines 로 한 번 더 시도
                return [json.loads(l) for l in lines]
            except json.JSONDecodeError:
                pass
        raise JsonError(f"{name} {first.lineno}행 {first.colno}열: {first.msg}") from None


def type_name(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def walk(value, prefix: str = ""):
    """(경로, 값) 을 훑는다. 경로는 a.b[0].c 꼴."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from walk(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from walk(v, f"{prefix}[{i}]")
    else:
        yield prefix or "(루트)", value


def flatten(value) -> list[tuple[str, object]]:
    return list(walk(value))


# --------------------------------------------------------------------- 스키마

@dataclass
class Field:
    path: str
    types: set[str] = field(default_factory=set)
    seen: int = 0
    total: int = 0          # 이 경로가 나올 수 있었던 횟수
    samples: list = field(default_factory=list)

    @property
    def optional(self) -> bool:
        return self.seen < self.total


def schema(value, *, samples: int = 2) -> list[Field]:
    """배열 인덱스를 [] 로 합쳐 구조를 요약한다. 있다 없다 하는 키도 표시한다."""
    fields: dict[str, Field] = {}

    def note(path: str, v) -> None:
        f = fields.setdefault(path, Field(path))
        f.types.add(type_name(v))
        f.seen += 1
        if not isinstance(v, (dict, list)) and len(f.samples) < samples:
            f.samples.append(v)

    def visit(v, path: str, siblings: list[str]) -> None:
        note(path, v)
        if isinstance(v, dict):
            for k, sub in v.items():
                visit(sub, f"{path}.{k}" if path else k, siblings)
        elif isinstance(v, list):
            for item in v:
                visit(item, f"{path}[]", siblings)

    visit(value, "", [])

    # 부모가 나온 횟수를 분모로 삼아 '가끔 없는 키'를 찾는다
    for path, f in fields.items():
        parent = path.rsplit(".", 1)[0] if "." in path else ""
        if parent == path:
            parent = ""
        f.total = fields[parent].seen if parent in fields else f.seen

    ordered = sorted(fields.values(), key=lambda f: f.path)
    return [f for f in ordered if f.path]


# ---------------------------------------------------------------------- 비교

@dataclass
class JsonDiff:
    added: list[tuple[str, object]] = field(default_factory=list)
    removed: list[tuple[str, object]] = field(default_factory=list)
    type_changed: list[tuple[str, str, str]] = field(default_factory=list)
    value_changed: list[tuple[str, object, object]] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.type_changed or self.value_changed)

    @property
    def breaking(self) -> list[tuple[str, object]]:
        """소비하는 쪽이 깨질 만한 변화: 사라진 키와 타입이 바뀐 키."""
        return self.removed + [(p, f"{a} -> {b}") for p, a, b in self.type_changed]


def diff(before, after, *, key: str | None = None) -> JsonDiff:
    """두 JSON 을 경로 단위로 비교한다.

    key 를 주면 객체 배열을 그 필드 값으로 짝지어 비교한다. 순서만 바뀐
    응답에서 전부 바뀐 것처럼 보이는 일을 막는다.
    """
    d = JsonDiff()

    def compare(a, b, path: str) -> None:
        if a is MISSING:
            d.added.append((path, b))
            return
        if b is MISSING:
            d.removed.append((path, a))
            return

        ta, tb = type_name(a), type_name(b)
        if ta != tb:
            d.type_changed.append((path, ta, tb))
            return

        if isinstance(a, dict):
            for k in list(a) + [k for k in b if k not in a]:
                compare(a.get(k, MISSING), b.get(k, MISSING),
                        f"{path}.{k}" if path else k)
        elif isinstance(a, list):
            compare_list(a, b, path)
        elif a != b:
            d.value_changed.append((path, a, b))

    def compare_list(a: list, b: list, path: str) -> None:
        if key and all(isinstance(x, dict) and key in x for x in a + b):
            amap = {x[key]: x for x in a}
            bmap = {x[key]: x for x in b}
            for k in list(amap) + [k for k in bmap if k not in amap]:
                compare(amap.get(k, MISSING), bmap.get(k, MISSING), f"{path}[{key}={k}]")
            return
        for i in range(max(len(a), len(b))):
            compare(a[i] if i < len(a) else MISSING,
                    b[i] if i < len(b) else MISSING, f"{path}[{i}]")

    compare(before, after, "")
    return d


def preview(value, limit: int = 60) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[: limit - 1] + "…"
