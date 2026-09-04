"""JSON 구조 훑기·비교·평탄화. API 응답이 언제 어떻게 바뀌었는지 보는 용도."""

from __future__ import annotations

import json
import re
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


# ------------------------------------------------------------------- 경로 접근

PATH_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def parse_path(path: str) -> list[str | int]:
    """'users[0].name' 을 ['users', 0, 'name'] 으로."""
    path = path.strip()
    if not path:
        raise JsonError("경로가 비어 있습니다. 예: users[0].name")

    parts: list[str | int] = []
    position = 0
    for m in PATH_TOKEN.finditer(path):
        if m.start() > position and path[position:m.start()] not in (".", ""):
            raise JsonError(f"경로를 해석하지 못했습니다: {path}")
        position = m.end()
        key, index = m.group(1), m.group(2)
        parts.append(key.strip() if key is not None else int(index))
    if position != len(path):
        raise JsonError(f"경로를 해석하지 못했습니다: {path}")
    if not parts:
        raise JsonError(f"경로를 해석하지 못했습니다: {path}")
    return parts


def get_path(data, path: str):
    """경로가 가리키는 값. 없으면 JsonError."""
    current = data
    for i, part in enumerate(parse_path(path)):
        where = path if i == 0 else f"{path} (…{part} 앞까지는 찾았습니다)"
        if isinstance(part, int):
            if not isinstance(current, list) or not -len(current) <= part < len(current):
                raise JsonError(f"{where}: [{part}] 위치가 없습니다")
            current = current[part]
        else:
            if not isinstance(current, dict):
                raise JsonError(
                    f"{where}: '{part}' 앞이 객체가 아니라 {type_name(current)} 입니다")
            if part not in current:
                raise JsonError(f"{where}: '{part}' 키가 없습니다")
            current = current[part]
    return current


def parse_value(text: str):
    """'3', 'true', '"글자"', '[1,2]' 를 JSON 값으로. 안 되면 문자열 그대로."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def set_path(data, path: str, value, *, create: bool = False):
    """경로의 값을 바꾼다. 원본을 그대로 고치고 (이전 값, 새 값) 을 돌려준다."""
    parts = parse_path(path)
    current = data

    for i, part in enumerate(parts[:-1]):
        if isinstance(part, int):
            if not isinstance(current, list) or not -len(current) <= part < len(current):
                raise JsonError(f"{path}: [{part}] 위치가 없습니다")
            current = current[part]
            continue
        if not isinstance(current, dict):
            raise JsonError(f"{path}: '{part}' 앞이 객체가 아닙니다")
        if part not in current:
            if not create:
                raise JsonError(f"{path}: '{part}' 키가 없습니다 "
                                "(--create 를 주면 만듭니다)")
            current[part] = {}
        current = current[part]

    last = parts[-1]
    if isinstance(last, int):
        if not isinstance(current, list) or not -len(current) <= last < len(current):
            raise JsonError(f"{path}: [{last}] 위치가 없습니다")
        before = current[last]
        current[last] = value
        return before, value

    if not isinstance(current, dict):
        raise JsonError(f"{path}: '{last}' 앞이 객체가 아닙니다")
    if last not in current and not create:
        raise JsonError(f"{path}: '{last}' 키가 없습니다 (--create 를 주면 만듭니다)")
    before = current.get(last, MISSING)
    current[last] = value
    return (None if before is MISSING else before), value


# ------------------------------------------------------------------- 합치기

@dataclass
class MergeNote:
    path: str
    before: object
    after: object
    kind: str          # 덮어씀 | 추가 | 이어붙임


def deep_merge(base, over, *, list_mode: str = "replace",
               notes: list[MergeNote] | None = None, path: str = ""):
    """뒤에 오는 값이 이긴다. 무엇을 덮어썼는지 notes 에 남긴다.

    설정 파일을 겹칠 때 무엇이 바뀌었는지 모르면 조용히 다른 설정으로
    배포된다. 그래서 합치는 것과 기록을 함께 한다.
    """
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for key, value in over.items():
            spot = f"{path}.{key}" if path else key
            if key in base:
                out[key] = deep_merge(base[key], value,
                                      list_mode=list_mode, notes=notes, path=spot)
            else:
                out[key] = value
                if notes is not None:
                    notes.append(MergeNote(spot, None, value, "추가"))
        return out

    if isinstance(base, list) and isinstance(over, list) and list_mode == "append":
        if notes is not None and over:
            notes.append(MergeNote(path, base, base + over, "이어붙임"))
        return base + over

    if base != over and notes is not None:
        notes.append(MergeNote(path, base, over, "덮어씀"))
    return over


def merge_all(values: list, *, list_mode: str = "replace") -> tuple[object, list[MergeNote]]:
    """앞에서부터 차례로 겹친다. 마지막 파일이 가장 세다."""
    if not values:
        raise JsonError("합칠 것이 없습니다.")
    notes: list[MergeNote] = []
    merged = values[0]
    for nxt in values[1:]:
        merged = deep_merge(merged, nxt, list_mode=list_mode, notes=notes)
    return merged, notes


# ------------------------------------------------------- 표본에서 타입 만들기

PY_SCALARS = {"문자": "str", "정수": "int", "실수": "float", "참거짓": "bool",
              "널": "None"}
TS_SCALARS = {"문자": "string", "정수": "number", "실수": "number",
              "참거짓": "boolean", "널": "null"}


@dataclass
class TypeNode:
    kind: str                      # object | array | scalar
    name: str = ""
    scalar: str = "문자"
    item: "TypeNode | None" = None
    fields: dict = field(default_factory=dict)     # 키 -> (TypeNode, 꼭 있는가)


def _camel(name: str) -> str:
    parts = re.split(r"[^0-9A-Za-z가-힣]+", name)
    return "".join(p[:1].upper() + p[1:] for p in parts if p) or "값"


def _scalar_name(value) -> str:
    if value is None:
        return "널"
    if isinstance(value, bool):
        return "참거짓"
    if isinstance(value, int):
        return "정수"
    if isinstance(value, float):
        return "실수"
    return "문자"


def infer_type(value, name: str = "Root") -> TypeNode:
    """표본 하나에서 구조를 읽는다. 표본에 없는 것은 알 수 없다."""
    if isinstance(value, dict):
        node = TypeNode("object", _camel(name))
        for key, body in value.items():
            node.fields[key] = (infer_type(body, key), True)
        return node
    if isinstance(value, list):
        node = TypeNode("array", _camel(name))
        objects = [v for v in value if isinstance(v, dict)]
        if objects:
            merged = TypeNode("object", _camel(name))
            for item in objects:
                for key, body in item.items():
                    if key not in merged.fields:
                        merged.fields[key] = (infer_type(body, key), True)
            for key in merged.fields:               # 일부에만 있으면 선택 항목
                present = all(key in item for item in objects)
                merged.fields[key] = (merged.fields[key][0], present)
            node.item = merged
        elif value:
            node.item = infer_type(value[0], name)
        return node
    return TypeNode("scalar", _camel(name), _scalar_name(value))


def _collect(node: TypeNode, out: list[TypeNode]) -> None:
    if node.kind == "object":
        for child, _ in node.fields.values():
            _collect(child, out)
        out.append(node)
    elif node.kind == "array" and node.item is not None:
        _collect(node.item, out)


def to_python(root: TypeNode) -> str:
    """dataclass 코드로. 이름이 겹치면 뒤엣것을 쓴다."""
    def render(node: TypeNode, optional: bool) -> str:
        if node.kind == "object":
            body = node.name
        elif node.kind == "array":
            body = f"list[{render(node.item, False)}]" if node.item else "list"
        else:
            body = PY_SCALARS.get(node.scalar, "str")
        return f"{body} | None" if optional and body != "None" else body

    blocks: list[TypeNode] = []
    _collect(root, blocks)
    seen: dict[str, TypeNode] = {}
    for node in blocks:
        seen[node.name] = node

    out = ["from __future__ import annotations", "", "from dataclasses import dataclass",
           "", ""]
    for node in seen.values():
        out.append("@dataclass")
        out.append(f"class {node.name}:")
        if not node.fields:
            out.append("    pass")
        for key, (child, required) in node.fields.items():
            safe = re.sub(r"\W", "_", key)
            hint = render(child, not required)
            line = f"    {safe}: {hint}"
            if not required:
                line += " = None"
            notes = []
            if safe != key:
                notes.append(f"원래 키: {key}")
            if child.kind == "scalar" and child.scalar == "널":
                notes.append("표본이 널이라 타입을 모릅니다")
            if notes:
                line += "    # " + ", ".join(notes)
            out.append(line)
        out.append("")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def to_typescript(root: TypeNode) -> str:
    def render(node: TypeNode, optional: bool) -> str:
        if node.kind == "object":
            body = node.name
        elif node.kind == "array":
            body = f"{render(node.item, False)}[]" if node.item else "unknown[]"
        else:
            body = TS_SCALARS.get(node.scalar, "string")
        return body

    blocks: list[TypeNode] = []
    _collect(root, blocks)
    seen: dict[str, TypeNode] = {}
    for node in blocks:
        seen[node.name] = node

    out: list[str] = []
    for node in seen.values():
        out.append(f"export interface {node.name} {{")
        for key, (child, required) in node.fields.items():
            mark = "" if required else "?"
            quoted = key if re.fullmatch(r"[A-Za-z_$][\w$]*", key) else f'"{key}"'
            note = ("  // 표본이 널이라 타입을 모릅니다"
                    if child.kind == "scalar" and child.scalar == "널" else "")
            out.append(f"  {quoted}{mark}: {render(child, not required)};{note}")
        out.append("}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"
