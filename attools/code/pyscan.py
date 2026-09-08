"""파이썬 소스를 ast 로 훑어 안 쓰는 import 와 아무도 안 부르는 모듈을 찾는다."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache",
             ".pytest_cache", "build", "dist", ".tox"}
IGNORE_MARK = "attools:ignore"


@dataclass
class UnusedImport:
    path: Path
    line: int
    name: str          # 코드에서 쓰이는 이름
    source: str        # import 문 원문


@dataclass
class ModuleUse:
    module: str        # 점 표기 모듈 이름
    path: Path
    imported_by: set = field(default_factory=set)

    @property
    def orphan(self) -> bool:
        return not self.imported_by


def iter_python(root: Path):
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def _bound_names(tree: ast.AST) -> list[tuple[str, int, str, bool]]:
    """(이름, 줄, 원문 조각, 별표인지). 별표 import 는 확인할 수 없다."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                out.append((name, node.lineno, f"import {alias.name}", False))
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue
            for alias in node.names:
                if alias.name == "*":
                    out.append(("*", node.lineno,
                                f"from {node.module or '.'} import *", True))
                    continue
                out.append((alias.asname or alias.name, node.lineno,
                            f"from {node.module or '.'} import {alias.name}", False))
    return out


def _used_names(tree: ast.AST) -> set[str]:
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            spot = node
            while isinstance(spot, ast.Attribute):
                spot = spot.value
            if isinstance(spot, ast.Name):
                used.add(spot.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # __all__ = ["이름"] 이나 문자열 타입 주석에 적힌 이름도 쓴 것으로 본다
            used.add(node.value.strip())
    return used


def unused_imports(path: Path, *, skip_init: bool = True) -> list[UnusedImport]:
    """한 파일에서 쓰지 않는 import 를 찾는다.

    __init__.py 는 기본으로 건너뛴다. 거기의 import 는 대개 다시 내보내기라
    파일 안에서 쓰이지 않는 것이 정상이다.
    """
    if skip_init and path.name == "__init__.py":
        return []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return []

    lines = source.splitlines()
    used = _used_names(tree)
    out: list[UnusedImport] = []
    for name, line, text, star in _bound_names(tree):
        if star:
            continue                       # 별표 import 는 판단하지 않는다
        if name in used:
            continue
        if line <= len(lines) and IGNORE_MARK in lines[line - 1]:
            continue
        out.append(UnusedImport(path, line, name, text))
    return out


def module_name(path: Path, root: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = [p for p in rel.parts if p != "__init__"]
    return ".".join([root.name, *parts]) if parts else root.name


def module_uses(root: Path) -> list[ModuleUse]:
    """어떤 모듈이 어디서 import 되는지. 아무도 안 부르는 모듈을 찾는다."""
    files = list(iter_python(root))
    uses = {module_name(p, root): ModuleUse(module_name(p, root), p) for p in files}
    leaf = {name.split(".")[-1]: name for name in uses}

    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        me = module_name(path, root)
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                targets = [base] + [f"{base}.{a.name}" if base else a.name
                                    for a in node.names]
            for target in targets:
                for piece in (target, target.split(".")[-1]):
                    found = uses.get(piece) or uses.get(leaf.get(piece, ""))
                    if found and found.module != me:
                        found.imported_by.add(me)
    return sorted(uses.values(), key=lambda u: u.module)


def import_graph(root: Path) -> dict[str, set[str]]:
    """모듈 -> 그 모듈이 부르는 모듈들. module_uses 를 뒤집어 만든다.

    같은 판정을 두 번 쓰지 않으려고 뒤집기만 한다. 한쪽은 «누가 나를»,
    다른 쪽은 «내가 누구를» 인데 서로 다르게 세면 그림이 어긋난다.
    """
    uses = module_uses(root)
    graph: dict[str, set[str]] = {u.module: set() for u in uses}
    for use in uses:
        for caller in use.imported_by:
            graph.setdefault(caller, set()).add(use.module)
    return graph


def find_cycles(graph: dict[str, set[str]], *, limit: int = 20) -> list[list[str]]:
    """서로 물고 있는 고리를 찾는다. 같은 고리는 한 번만 낸다.

    고리가 있으면 어느 쪽을 먼저 읽어야 할지 알 수 없고, 나중에 한쪽을
    떼어내려 할 때 반드시 걸린다.
    """
    found: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def walk(node: str, path: list[str], visiting: set[str]) -> None:
        if len(found) >= limit:
            return
        for nxt in sorted(graph.get(node, ())):
            if nxt in visiting:
                cycle = path[path.index(nxt):]
                start = cycle.index(min(cycle))       # 어디서 시작해도 같은 고리다
                key = tuple(cycle[start:] + cycle[:start])
                if key not in seen:
                    seen.add(key)
                    found.append(list(key))
                continue
            if len(path) > 12:                        # 너무 깊으면 접는다
                continue
            walk(nxt, path + [nxt], visiting | {nxt})

    for module in sorted(graph):
        walk(module, [module], {module})
        if len(found) >= limit:
            break
    return found


# ------------------------------------------------------------- 소스 구조 훑기

@dataclass
class Symbol:
    name: str
    kind: str          # 클래스 | 함수 | 메서드
    line: int
    end: int
    doc: bool = False
    parent: str = ""
    branches: int = 1  # 갈림길 수(순환 복잡도)

    @property
    def lines(self) -> int:
        return max(1, self.end - self.line + 1)

    @property
    def public(self) -> bool:
        return not self.name.startswith("_")


@dataclass
class FileOutline:
    path: Path
    lines: int = 0
    symbols: list = field(default_factory=list)
    error: str = ""

    @property
    def classes(self) -> list:
        return [s for s in self.symbols if s.kind == "클래스"]

    @property
    def functions(self) -> list:
        return [s for s in self.symbols if s.kind != "클래스"]

    @property
    def longest(self):
        body = self.functions
        return max(body, key=lambda s: s.lines) if body else None

    @property
    def branchy(self):
        """갈림길이 가장 많은 함수."""
        body = self.functions
        return max(body, key=lambda s: s.branches) if body else None

    @property
    def undocumented(self) -> list:
        """설명이 없는 공개 함수·클래스. 남이 읽을 때 먼저 막히는 자리다."""
        return [s for s in self.symbols if s.public and not s.doc]


BRANCH_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
                ast.IfExp, ast.Assert, ast.comprehension)


def branch_count(node: ast.AST) -> int:
    """갈림길 수. if·for·while·except·and/or 를 센다(순환 복잡도).

    읽기 어려움을 재는 여러 방법 중 계산이 분명한 것만 쓴다. 정확한 지표라기
    보다 '어느 함수부터 볼까'를 정하는 눈금이다.
    """
    total = 1
    for child in ast.walk(node):
        if isinstance(child, ast.comprehension):
            total += 1 + len(child.ifs)     # for 하나와 걸러내는 조건들
        elif isinstance(child, BRANCH_NODES):
            total += 1
        elif isinstance(child, ast.BoolOp):
            total += len(child.values) - 1
        elif hasattr(ast, "match_case") and isinstance(child, ast.match_case):
            total += 1
    return total


def outline(path: Path) -> FileOutline:
    """한 파일의 클래스·함수를 훑는다. 실행하지 않고 ast 로만 읽는다."""
    result = FileOutline(path)
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError) as e:
        result.error = str(e)
        return result

    result.lines = len(source.splitlines())
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            result.symbols.append(Symbol(node.name, "클래스", node.lineno,
                                         node.end_lineno or node.lineno,
                                         bool(ast.get_docstring(node))))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    result.symbols.append(Symbol(
                        child.name, "메서드", child.lineno,
                        child.end_lineno or child.lineno,
                        bool(ast.get_docstring(child)), node.name,
                        branch_count(child)))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.symbols.append(Symbol(node.name, "함수", node.lineno,
                                         node.end_lineno or node.lineno,
                                         bool(ast.get_docstring(node)), "",
                                         branch_count(node)))
    return result


def outlines(roots: list[Path]) -> list[FileOutline]:
    out: list[FileOutline] = []
    for root in roots:
        if root.is_file():
            out.append(outline(root))
            continue
        out += [outline(p) for p in iter_python(root)]
    return out


# ------------------------------------------------- 어느 파이썬부터 도는 코드인가

PY_MODULES = {                      # 모듈이 표준 라이브러리에 들어온 판
    "zoneinfo": (3, 9), "graphlib": (3, 9), "tomllib": (3, 11),
}
PY_NAMES = {                        # from <모듈> import <이름> 으로 들어온 것
    ("typing", "ParamSpec"): (3, 10), ("typing", "TypeAlias"): (3, 10),
    ("typing", "TypeGuard"): (3, 10), ("typing", "Concatenate"): (3, 10),
    ("typing", "Self"): (3, 11), ("typing", "Never"): (3, 11),
    ("typing", "LiteralString"): (3, 11), ("typing", "assert_type"): (3, 11),
    ("typing", "assert_never"): (3, 11), ("typing", "TypeVarTuple"): (3, 11),
    ("typing", "Unpack"): (3, 11), ("typing", "dataclass_transform"): (3, 11),
    ("typing", "override"): (3, 12), ("typing", "TypeIs"): (3, 13),
    ("enum", "StrEnum"): (3, 11), ("enum", "ReprEnum"): (3, 11),
    ("enum", "verify"): (3, 11),
    ("datetime", "UTC"): (3, 11),
    ("asyncio", "TaskGroup"): (3, 11), ("asyncio", "timeout"): (3, 11),
    ("asyncio", "Runner"): (3, 11),
    ("contextlib", "chdir"): (3, 11),
    ("itertools", "pairwise"): (3, 10), ("itertools", "batched"): (3, 12),
    ("hashlib", "file_digest"): (3, 11),
    ("inspect", "get_annotations"): (3, 10),
    ("dataclasses", "KW_ONLY"): (3, 10),
    ("unittest", "enterModuleContext"): (3, 11),
    ("warnings", "deprecated"): (3, 13),
}
PY_ATTRS = {                        # 이름만 보고 짐작하는 것 (오탐이 날 수 있다)
    "removeprefix": (3, 9), "removesuffix": (3, 9), "bit_count": (3, 10),
    "pairwise": (3, 10), "batched": (3, 12), "file_digest": (3, 11),
    "get_annotations": (3, 10), "walk": (3, 12), "cache": (3, 9),
}
PY_ATTR_OWNERS = {                  # 그 이름이 «이 모듈의 것» 일 때만 본다
    "pairwise": "itertools", "batched": "itertools",
    "file_digest": "hashlib", "get_annotations": "inspect",
    "walk": "Path", "cache": "functools",
}


@dataclass
class CompatHit:
    path: Path
    line: int
    version: tuple          # (3, 11)
    what: str               # 무엇이 걸렸나
    kind: str               # 문법 / 가져오기 / 이름
    sure: bool              # 이름만 보고 짐작한 것은 False
    guarded: bool = False   # try/except ImportError 로 감싼 자리

    @property
    def label(self) -> str:
        return f"{self.version[0]}.{self.version[1]}"


def parse_version(text: str) -> tuple:
    """«3.10» 을 (3, 10) 으로. 못 읽으면 ValueError."""
    parts = text.strip().split(".")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"파이썬 판을 읽지 못했습니다: {text} (예: 3.10)")
    return (int(parts[0]), int(parts[1]))


def _guarded_lines(tree: ast.AST) -> set:
    """try/except ImportError 로 감싼 줄 번호.

    없으면 없는 대로 도는 코드는 «낮은 판에서 안 돈다» 가 아니다. 이걸
    섞어 신고하면 진짜로 막히는 자리가 묻힌다.
    """
    lines: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        catches = False
        for handler in node.handlers:
            names = []
            if isinstance(handler.type, ast.Name):
                names = [handler.type.id]
            elif isinstance(handler.type, ast.Tuple):
                names = [e.id for e in handler.type.elts
                         if isinstance(e, ast.Name)]
            elif handler.type is None:
                catches = True
            if {"ImportError", "ModuleNotFoundError", "Exception"} & set(names):
                catches = True
        if not catches:
            continue
        for stmt in node.body:
            lines.update(range(stmt.lineno, (stmt.end_lineno or stmt.lineno) + 1))
    return lines


def _annotation_nodes(tree: ast.AST):
    """주석(annotation) 자리에 있는 식만 고른다. X | None 은 여기서만 문제다."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.AnnAssign, ast.arg)) and node.annotation:
            yield node.annotation
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns:
                yield node.returns


def compat_hits(path: Path, text: str | None = None) -> list[CompatHit]:
    """이 파일이 어느 파이썬부터 도는지 걸리는 자리를 모은다.

    문법은 ast 로 확실히 안다. 이름(«.removeprefix(»)은 무엇의 메서드인지
    알 수 없어 «짐작» 으로 따로 표시한다 - 확실한 것과 섞으면 목록 전체를
    안 믿게 된다.
    """
    body = text if text is not None else path.read_text(encoding="utf-8",
                                                        errors="replace")
    tree = ast.parse(body)
    hits: list[CompatHit] = []

    future = any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
                 and any(a.name == "annotations" for a in n.names)
                 for n in ast.walk(tree))
    modules: dict[str, str] = {}          # 별칭 -> 진짜 모듈 이름
    guarded = _guarded_lines(tree)

    for node in ast.walk(tree):
        if isinstance(node, ast.Match):
            hits.append(CompatHit(path, node.lineno, (3, 10), "match 문",
                                  "문법", True))
        elif isinstance(node, getattr(ast, "TryStar", ())):
            hits.append(CompatHit(path, node.lineno, (3, 11), "except* 문",
                                  "문법", True))
        elif isinstance(node, getattr(ast, "TypeAlias", ())):
            hits.append(CompatHit(path, node.lineno, (3, 12), "type 문",
                                  "문법", True))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)) and getattr(node, "type_params",
                                                          None):
            hits.append(CompatHit(path, node.lineno, (3, 12),
                                  f"제네릭 문법 def {node.name}[…]", "문법", True))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                modules[alias.asname or top] = top
                if version := PY_MODULES.get(alias.name):
                    hits.append(CompatHit(path, node.lineno, version,
                                          f"import {alias.name}", "가져오기",
                                          True))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if version := PY_MODULES.get(node.module):
                hits.append(CompatHit(path, node.lineno, version,
                                      f"from {node.module}", "가져오기", True))
            for alias in node.names:
                if version := PY_NAMES.get((node.module, alias.name)):
                    hits.append(CompatHit(
                        path, node.lineno, version,
                        f"from {node.module} import {alias.name}",
                        "가져오기", True))
        elif isinstance(node, ast.Attribute):
            version = PY_ATTRS.get(node.attr)
            if version is None:
                continue
            owner = PY_ATTR_OWNERS.get(node.attr)
            base = node.value.id if isinstance(node.value, ast.Name) else None
            if owner and base and modules.get(base, base) != owner \
                    and base != owner:
                continue                  # 다른 것의 같은 이름이다
            sure = bool(owner and base)
            hits.append(CompatHit(path, node.lineno, version,
                                  f".{node.attr}", "이름", sure))

    if not future:
        for annotation in _annotation_nodes(tree):
            for node in ast.walk(annotation):
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                    hits.append(CompatHit(
                        path, node.lineno, (3, 10), "주석의 X | Y",
                        "문법", True))
                    break

    for hit in hits:
        if hit.line in guarded:
            hit.guarded = True
    return sorted(hits, key=lambda h: (h.line, h.what))


@dataclass
class CompatReport:
    files: int = 0
    hits: list = field(default_factory=list)
    failed: list = field(default_factory=list)     # [(파일, 까닭)]

    @property
    def needed(self):
        """확실한 것만으로 잡은 «이 판부터 돈다». 걸리는 게 없으면 None.

        아무것도 안 걸렸다고 «3.0 부터 돈다» 고 적으면 안 된다 - 여기서
        보는 것 밖의 이유로 안 돌 수 있고, 그 판을 시험해 본 적도 없다.
        """
        sure = [h.version for h in self.hits if h.sure and not h.guarded]
        return max(sure) if sure else None

    def over(self, target: tuple) -> list:
        return [h for h in self.hits if h.version > target and not h.guarded]


def compat_scan(roots: list[Path]) -> CompatReport:
    """여러 경로를 훑는다. 문법이 깨진 파일은 세지 않고 따로 알려 준다."""
    report = CompatReport()
    seen: set = set()
    for root in roots:
        paths = [root] if root.is_file() else list(iter_python(root))
        for path in paths:
            if path in seen or path.suffix != ".py":
                continue
            seen.add(path)
            report.files += 1
            try:
                report.hits += compat_hits(path)
            except (SyntaxError, OSError) as e:
                report.failed.append((path, str(e)))
    return report
