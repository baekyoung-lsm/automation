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


# ------------------------------------------------------- 잠금 파일 비교

LOCK_VERSION_RE = re.compile(r'^\s*version\s*=\s*"([^"]+)"')
LOCK_NAME_RE = re.compile(r'^\s*name\s*=\s*"([^"]+)"')
YARN_ENTRY_RE = re.compile(r'^"?([^@\s"][^@\s"]*)@[^:]*:?\s*$')


def _lock_from_package_lock(data: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    packages = data.get("packages")
    if isinstance(packages, dict):                 # lockfile v2/v3
        for key, body in packages.items():
            if not key.startswith("node_modules/") or not isinstance(body, dict):
                continue
            name = key.split("node_modules/")[-1]
            if body.get("version"):
                out[name] = str(body["version"])
    if not out and isinstance(data.get("dependencies"), dict):   # v1
        def walk(node: dict) -> None:
            for name, body in node.items():
                if isinstance(body, dict):
                    if body.get("version"):
                        out.setdefault(name, str(body["version"]))
                    if isinstance(body.get("dependencies"), dict):
                        walk(body["dependencies"])
        walk(data["dependencies"])
    return out


def _lock_from_pipfile_lock(data: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for group in ("default", "develop"):
        for name, body in (data.get(group) or {}).items():
            if isinstance(body, dict) and body.get("version"):
                out[name] = str(body["version"]).lstrip("=")
    return out


def read_lock(path: Path) -> dict[str, str]:
    """잠금 파일에서 {패키지: 버전}. 형식을 모르면 빈 사전."""
    name = path.name.lower()
    text = path.read_text(encoding="utf-8", errors="replace")

    # Pipfile.lock 은 이름이 .json 으로 끝나지 않지만 안은 JSON 이다.
    if name.endswith(".json") or name == "pipfile.lock":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if name == "pipfile.lock":
            return _lock_from_pipfile_lock(data)
        return _lock_from_package_lock(data)

    if name == "poetry.lock" or name.endswith(".lock") and "[[package]]" in text:
        out: dict[str, str] = {}
        current = ""
        for line in text.splitlines():
            if line.strip() == "[[package]]":
                current = ""
            elif m := LOCK_NAME_RE.match(line):
                current = m.group(1)
            elif current and (m := LOCK_VERSION_RE.match(line)):
                out[current] = m.group(1)
                current = ""
        return out

    if name == "yarn.lock":
        out = {}
        current = ""
        for line in text.splitlines():
            if not line.startswith((" ", "\t", "#")) and line.strip():
                m = YARN_ENTRY_RE.match(line.split(",")[0].strip())
                current = m.group(1) if m else ""
            elif current and (m := LOCK_VERSION_RE.match(line.strip())):
                out[current] = m.group(1)
                current = ""
        return out

    if name.startswith("requirements") or name.endswith(".txt"):
        out = {}
        for line in text.splitlines():
            body = line.split("#", 1)[0].strip()
            if not body or body.startswith("-"):
                continue
            if "==" in body:
                head, _, version = body.partition("==")
                out[head.strip().split("[")[0]] = version.strip()
        return out

    if name == "go.mod" or name == "go.sum":
        out = {}
        for line in text.splitlines():
            if m := GO_REQUIRE_RE.match(line.replace("require ", "")):
                out.setdefault(m.group("name"), m.group("version"))
        return out
    return {}


def version_key(version: str) -> tuple:
    """숫자 부분만 견줘 올렸는지 내렸는지 본다. 못 읽으면 빈 튜플."""
    parts = re.findall(r"\d+", version)
    return tuple(int(p) for p in parts[:4])


@dataclass
class LockChange:
    name: str
    before: str
    after: str

    @property
    def kind(self) -> str:
        if not self.before:
            return "추가"
        if not self.after:
            return "삭제"
        old, new = version_key(self.before), version_key(self.after)
        if not old or not new or old == new:
            return "바뀜"
        return "올림" if new > old else "내림"

    @property
    def major(self) -> bool:
        """맨 앞 숫자가 달라졌는가. 대개 호환이 깨지는 자리다."""
        old, new = version_key(self.before), version_key(self.after)
        return bool(old and new and old[0] != new[0])


def lock_diff(before: dict[str, str], after: dict[str, str]) -> list[LockChange]:
    """두 잠금 파일의 차이. 이름 순으로 돌려준다."""
    out: list[LockChange] = []
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name, ""), after.get(name, "")
        if old != new:
            out.append(LockChange(name, old, new))
    return out
