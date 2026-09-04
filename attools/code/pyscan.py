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
