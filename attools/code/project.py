"""새로 받은 저장소를 한 번에 훑는다. «뭐부터 해야 하나» 를 대신 찾아 준다.

찾은 것만 말한다. 없는 것은 «없음», 알 수 없는 것은 «확인 못 함» 이다.
그럴듯한 실행 방법을 지어내면 되지도 않는 명령을 치게 만든다.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import deps

# 마커 파일 -> (무엇인가, 그 다음에 보통 무엇을 하는가)
MARKERS: list[tuple[str, str, str]] = [
    ("pyproject.toml", "파이썬", "python3 -m venv .venv && .venv/bin/pip install -e ."),
    ("requirements.txt", "파이썬", "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"),
    ("package.json", "노드", "npm install"),
    ("go.mod", "Go", "go mod download"),
    ("Cargo.toml", "러스트", "cargo build"),
    ("pom.xml", "자바(메이븐)", "mvn install"),
    ("build.gradle", "자바(그레이들)", "gradle build"),
    ("Gemfile", "루비", "bundle install"),
    ("composer.json", "PHP", "composer install"),
]

# 설치 흔적 -> 무엇의 흔적인가
INSTALLED = [(".venv", "파이썬 가상환경"), ("venv", "파이썬 가상환경"),
             ("node_modules", "노드 패키지"), ("vendor", "vendor 폴더"),
             ("target", "빌드 결과")]

RUNNERS = ("Makefile", "makefile", "justfile", "Taskfile.yml", "docker-compose.yml",
           "compose.yaml", "docker-compose.yaml", "Dockerfile")


@dataclass
class Finding:
    kind: str                 # 언어 · 의존성 · 환경 · 실행 · git
    name: str
    detail: str
    ok: bool | None = True    # None 이면 확인 못 함


@dataclass
class Report:
    root: Path
    findings: list[Finding] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)      # 해 볼 만한 것

    def add(self, kind: str, name: str, detail: str, ok: bool | None = True) -> None:
        self.findings.append(Finding(kind, name, detail, ok))


def _tool_version(command: list[str]) -> str | None:
    """명령이 있으면 그 판, 없으면 None. 확인 못 한 것과 없는 것을 가른다."""
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    out = (done.stdout + done.stderr).strip().splitlines()
    return out[0].strip() if out else None


def _requires_python(root: Path) -> str:
    path = root / "pyproject.toml"
    if not path.is_file():
        return ""
    try:
        body = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    hit = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', body)
    return hit.group(1) if hit else ""


def _package_json(root: Path) -> dict:
    path = root / "package.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _make_targets(path: Path) -> list[str]:
    """Makefile 의 목표 이름. .PHONY 와 변수 대입은 뺀다."""
    try:
        body = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for line in body.splitlines():
        hit = re.match(r"^([A-Za-z0-9_.\-/]+)\s*:(?!=)", line)
        if hit and not hit.group(1).startswith("."):
            out.append(hit.group(1))
    return out


def _git(root: Path) -> list[Finding]:
    found: list[Finding] = []
    try:
        # rev-parse HEAD 는 커밋이 하나도 없는 저장소에서 실패한다. 방금 init 한
        # 저장소를 «git 저장소가 아니다» 라고 하면 사람이 자기 눈을 의심한다.
        inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                                cwd=root, capture_output=True, text=True, timeout=5)
        branch = subprocess.run(["git", "branch", "--show-current"],
                                cwd=root, capture_output=True, text=True, timeout=5)
        status = subprocess.run(["git", "status", "--porcelain"],
                                cwd=root, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return [Finding("git", "저장소", "확인 못 함", None)]
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return [Finding("git", "저장소", "git 저장소가 아닙니다", None)]
    dirty = [l for l in status.stdout.splitlines() if l.strip()]
    found.append(Finding("git", "브랜치",
                         branch.stdout.strip() or "(HEAD 가 브랜치에 없습니다)"))
    # 커밋 안 된 변경은 «빠진 것» 이 아니다. 그냥 지금 상태다.
    found.append(Finding("git", "커밋 안 된 변경",
                         f"{len(dirty)}개" if dirty else "없음"))
    return found


def inspect(root: Path) -> Report:
    """저장소를 훑어 무엇으로 만들어졌고 무엇부터 하면 되는지 모은다."""
    root = Path(root)
    report = Report(root)

    kinds: list[str] = []
    for marker, kind, how in MARKERS:
        if (root / marker).is_file():
            report.add("언어", kind, marker)
            if kind not in kinds:
                kinds.append(kind)
                report.steps.append(how)

    if not kinds:
        report.add("언어", "알 수 없음",
                   "아는 마커 파일이 없습니다 " + f"({', '.join(m for m, _k, _h in MARKERS[:4])} …)",
                   None)

    wanted = _requires_python(root)
    if wanted:
        now = _tool_version(["python3", "--version"])
        report.add("언어", "파이썬 요구 판", wanted, True)
        report.add("언어", "여기 깔린 파이썬", now or "없음", now is not None)
    node_engine = (_package_json(root).get("engines") or {}).get("node")
    if node_engine:
        now = _tool_version(["node", "--version"])
        report.add("언어", "노드 요구 판", str(node_engine))
        report.add("언어", "여기 깔린 노드", now or "없음", now is not None)

    for name, what in INSTALLED:
        if (root / name).is_dir():
            report.add("의존성", what, f"{name}/ 있음")

    dep_files = deps.find_files(root)
    if dep_files:
        report.add("의존성", "의존성 파일",
                   ", ".join(p.name for p in dep_files))

    example = root / ".env.example"
    actual = root / ".env"
    if example.is_file():
        if actual.is_file():
            report.add("환경", ".env", "있음")
        else:
            report.add("환경", ".env", ".env.example 은 있는데 .env 가 없습니다", False)
            report.steps.append("cp .env.example .env  # 그 뒤 at dev env")
    elif actual.is_file():
        report.add("환경", ".env", "있음 (.env.example 은 없음)")

    scripts = _package_json(root).get("scripts") or {}
    if isinstance(scripts, dict) and scripts:
        report.add("실행", "npm 스크립트", ", ".join(list(scripts)[:8]))
    for name in RUNNERS:
        path = root / name
        if not path.is_file():
            continue
        if name.lower().startswith(("makefile", "justfile")):
            targets = _make_targets(path)
            report.add("실행", name, ", ".join(targets[:8]) or "(목표를 못 읽었습니다)",
                       True if targets else None)
        else:
            report.add("실행", name, "있음")

    report.findings += _git(root)
    return report
