"""의존성 파일을 읽어 무엇을 얼마나 쓰는지, 버전이 고정됐는지 본다."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

REQUIREMENT_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*"
    r"(?P<spec>(?:[=<>!~^]=?|===)\s*[^;#]+)?")
GO_REQUIRE_RE = re.compile(r"^\s*(?P<name>[\w./-]+)\s+(?P<version>v[\w.+-]+)")


@dataclass
class Dependency:
    name: str
    spec: str
    source: str
    group: str = "기본"

    @property
    def pinned(self) -> bool:
        """정확히 한 버전으로 묶여 있는가."""
        spec = self.spec.strip()
        if not spec:
            return False
        if spec.startswith("=="):
            return "*" not in spec
        if spec.startswith("==="):
            return True
        if spec.startswith("=") and not spec.startswith("=="):   # Cargo
            return True
        if spec.startswith("v"):                                 # go.mod
            return True
        return bool(re.fullmatch(r"\d+(\.\d+)*", spec))          # npm 정확 버전


@dataclass
class DepFile:
    path: Path
    kind: str
    deps: list[Dependency] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _parse_requirements(path: Path) -> DepFile:
    out = DepFile(path, "requirements")
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-"):
            out.notes.append(f"다른 파일을 끌어옵니다: {line}")
            continue
        if line.startswith(("git+", "http://", "https://")):
            out.deps.append(Dependency(line.split("/")[-1], "", str(path), "URL"))
            continue
        m = REQUIREMENT_RE.match(line)
        if m and m.group("name"):
            out.deps.append(Dependency(m.group("name"),
                                       (m.group("spec") or "").strip(), str(path)))
    return out


def _load_toml(path: Path) -> dict | None:
    try:
        import tomllib
    except ImportError:      # 3.10 에는 tomllib 이 없다
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _split_spec(text: str) -> tuple[str, str]:
    m = REQUIREMENT_RE.match(text)
    if not m or not m.group("name"):
        return text.strip(), ""
    return m.group("name"), (m.group("spec") or "").strip()


def _parse_pyproject(path: Path) -> DepFile:
    out = DepFile(path, "pyproject")
    data = _load_toml(path)

    if data is None:
        # tomllib 이 없으면 dependencies 배열만 눈으로 훑는다
        text = path.read_text(encoding="utf-8", errors="replace")
        for block in re.finditer(r"dependencies\s*=\s*\[(.*?)\]", text, re.S):
            for item in re.findall(r'["\']([^"\']+)["\']', block.group(1)):
                name, spec = _split_spec(item)
                out.deps.append(Dependency(name, spec, str(path)))
        out.notes.append("tomllib 이 없어 대충 읽었습니다. Python 3.11 이상에서 정확합니다.")
        return out

    project = data.get("project", {})
    for item in project.get("dependencies", []):
        name, spec = _split_spec(item)
        out.deps.append(Dependency(name, spec, str(path)))
    for group, items in (project.get("optional-dependencies", {}) or {}).items():
        for item in items:
            name, spec = _split_spec(item)
            out.deps.append(Dependency(name, spec, str(path), group))
    return out


def _parse_package_json(path: Path) -> DepFile:
    out = DepFile(path, "package.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        out.notes.append(f"읽지 못했습니다: {e}")
        return out

    for key, group in (("dependencies", "기본"), ("devDependencies", "개발"),
                       ("peerDependencies", "peer"),
                       ("optionalDependencies", "선택")):
        for name, spec in (data.get(key) or {}).items():
            out.deps.append(Dependency(name, str(spec), str(path), group))
    return out


def _parse_go_mod(path: Path) -> DepFile:
    out = DepFile(path, "go.mod")
    inside = False
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("//", 1)[0].strip()
        if line.startswith("require ("):
            inside = True
            continue
        if inside and line == ")":
            inside = False
            continue
        target = line[len("require "):] if line.startswith("require ") else (
            line if inside else "")
        if not target:
            continue
        if m := GO_REQUIRE_RE.match(target):
            out.deps.append(Dependency(m.group("name"), m.group("version"), str(path)))
    return out


PARSERS = {
    "requirements": _parse_requirements,
    "pyproject.toml": _parse_pyproject,
    "package.json": _parse_package_json,
    "go.mod": _parse_go_mod,
}


def find_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for name in ("pyproject.toml", "package.json", "go.mod"):
        if (root / name).is_file():
            found.append(root / name)
    found += sorted(p for p in root.glob("requirements*.txt") if p.is_file())
    found += sorted(p for p in root.glob("requirements/*.txt") if p.is_file())
    return found


def read_file(path: Path) -> DepFile:
    if path.name.startswith("requirements") or path.suffix == ".txt":
        return _parse_requirements(path)
    parser = PARSERS.get(path.name)
    if parser is None:
        raise ValueError(f"어떻게 읽어야 할지 모르는 파일입니다: {path.name}")
    return parser(path)


def conflicts(files: list[DepFile]) -> list[tuple[str, list[tuple[str, str]]]]:
    """같은 이름인데 파일마다 버전 조건이 다른 것."""
    table: dict[str, list[tuple[str, str]]] = {}
    for f in files:
        for dep in f.deps:
            table.setdefault(dep.name.lower(), []).append((f.path.name, dep.spec))

    out = []
    for name, rows in sorted(table.items()):
        specs = {spec for _, spec in rows}
        if len(rows) > 1 and len(specs) > 1:
            out.append((name, rows))
    return out
