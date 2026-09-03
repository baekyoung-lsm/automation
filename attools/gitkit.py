"""git 저장소 잡일: 병합된 브랜치 정리, 커밋 전 시크릿 검사."""

from __future__ import annotations

import math
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

PROTECTED = {"main", "master", "develop", "dev", "release", "HEAD"}

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build",
             ".next", ".idea", ".mypy_cache", ".pytest_cache", "vendor", "target"}
SKIP_SUFFIX = {".lock", ".min.js", ".map", ".png", ".jpg", ".jpeg", ".gif", ".pdf",
               ".zip", ".gz", ".woff", ".woff2", ".ttf", ".ico", ".svg"}

# 값이 진짜 시크릿일 때만 걸리도록, 형태가 뚜렷한 것 위주로 둔다.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS 액세스 키", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub 토큰", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("Slack 토큰", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("Google API 키", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Stripe 키", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{20,}\b")),
    ("개인 키 파일", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("웹훅 URL", re.compile(r"https://hooks\.slack\.com/services/\S+"
                            r"|https://discord(?:app)?\.com/api/webhooks/\S+")),
    ("접속 문자열 비밀번호", re.compile(
        r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:/\s]+:[^@\s]{3,}@")),
    ("주민등록번호", re.compile(r"\b\d{6}-[1-4]\d{6}\b")),
    ("하드코딩된 비밀값", re.compile(
        r"""(?i)\b(?:api[_-]?key|secret[_-]?key|secret|password|passwd|access[_-]?token)"""
        r"""\s*[:=]\s*["']([^"'\s]{8,})["']""")),
]

# 예시·플레이스홀더는 걸러 낸다. 값 전체가 이 꼴이거나 안에 표식이 있으면 무시한다.
PLACEHOLDER = re.compile(
    r"(?i)^(?:x{3,}|\*{3,}|\.{3,}|none|null|todo|secret|password|passwd|"
    r"[a-z_]+|\d+)$")
PLACEHOLDER_MARK = re.compile(
    r"(?i)your[_-]?|change[_-]?me|example|sample|dummy|placeholder|redacted|"
    r"xxxx|\$\{|\{\{|<[a-z_]+>|process\.env|os\.environ|getenv|"
    r"^env\.|^[A-Z_]+$")


# 테스트 픽스처처럼 일부러 넣은 값은 주석으로 넘길 수 있다.
IGNORE_MARK = re.compile(r"attools:\s*ignore|noqa:\s*secret")


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    excerpt: str


def run(args: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} 실패")
    return proc.stdout


def repo_root(start: Path) -> Path:
    return Path(run(["rev-parse", "--show-toplevel"], start).strip())


# ------------------------------------------------------------ 브랜치 정리

@dataclass
class Sweep:
    base: str
    current: str
    merged: list[str]
    gone: list[str]


def find_stale_branches(root: Path, base: str | None = None) -> Sweep:
    """병합이 끝난 로컬 브랜치와, 원격이 사라진 추적 브랜치를 찾는다."""
    current = run(["rev-parse", "--abbrev-ref", "HEAD"], root).strip()

    if base is None:
        try:
            head = run(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], root).strip()
            base = head.rsplit("/", 1)[-1]
        except RuntimeError:
            names = {l.strip() for l in run(["branch", "--format=%(refname:short)"], root).splitlines()}
            base = next((b for b in ("main", "master", "develop") if b in names), current)

    merged = []
    try:
        for line in run(["branch", "--merged", base, "--format=%(refname:short)"], root).splitlines():
            name = line.strip()
            if name and name not in PROTECTED and name != current and name != base:
                merged.append(name)
    except RuntimeError:
        pass  # base 브랜치가 없는 저장소

    gone = []
    for line in run(["branch", "-vv", "--format=%(refname:short)%09%(upstream:track)"],
                    root).splitlines():
        name, _, track = line.partition("\t")
        name = name.strip()
        if "gone" in track and name not in PROTECTED and name != current:
            gone.append(name)

    return Sweep(base=base, current=current, merged=merged,
                 gone=[g for g in gone if g not in merged])


def delete_branches(root: Path, names: list[str], *, force: bool = False) -> list[tuple[str, str]]:
    """(브랜치, 결과) 목록을 돌려준다."""
    results = []
    for name in names:
        try:
            run(["branch", "-D" if force else "-d", name], root)
            results.append((name, "삭제"))
        except RuntimeError as e:
            results.append((name, f"실패: {e}"))
    return results


# ------------------------------------------------------------- 시크릿 검사

def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    return -sum((n / len(s)) * math.log2(n / len(s)) for n in counts.values())


def _is_placeholder(value: str) -> bool:
    value = value.strip()
    return bool(PLACEHOLDER.match(value) or PLACEHOLDER_MARK.search(value))


def scan_text(text: str, path: str, *, entropy_threshold: float = 0.0) -> list[Finding]:
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 4000 or IGNORE_MARK.search(line):
            continue
        for kind, pattern in SECRET_PATTERNS:
            m = pattern.search(line)
            if not m:
                continue
            # 형태가 뚜렷한 키(AKIA..., ghp_... )는 그대로 신고하고,
            # 일반 대입문에서 뽑은 값만 플레이스홀더인지 확인한다.
            if m.groups() and _is_placeholder(m.group(1)):
                continue
            findings.append(Finding(path, lineno, kind, line.strip()[:160]))
            break
        else:
            if entropy_threshold:
                for token in re.findall(r"['\"]([A-Za-z0-9+/=_\-]{24,})['\"]", line):
                    if _is_placeholder(token):
                        continue
                    if shannon_entropy(token) >= entropy_threshold:
                        findings.append(Finding(path, lineno, "엔트로피 높은 문자열",
                                                line.strip()[:160]))
                        break
    return findings


def _readable(path: Path) -> str | None:
    if path.suffix.lower() in SKIP_SUFFIX or any(p in SKIP_DIRS for p in path.parts):
        return None
    try:
        if path.stat().st_size > 2_000_000:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8000]:
        return None
    return data.decode("utf-8", errors="replace")


def scan_paths(root: Path, *, staged: bool = False, tracked: bool = True,
               entropy_threshold: float = 0.0) -> list[Finding]:
    if staged:
        names = [n for n in run(["diff", "--cached", "--name-only", "--diff-filter=ACM"],
                                root).splitlines() if n]
    elif tracked:
        names = [n for n in run(["ls-files"], root).splitlines() if n]
    else:
        names = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]

    findings: list[Finding] = []
    for name in names:
        p = root / name
        if not p.is_file():
            continue
        text = _readable(p)
        if text is None:
            continue
        findings.extend(scan_text(text, name, entropy_threshold=entropy_threshold))
    return findings


HOOK = """#!/bin/sh
# attools: 커밋 전 시크릿 검사
exec {cmd} git scan --staged --quiet
"""


def install_hook(root: Path, command: str) -> Path:
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(HOOK.format(cmd=command), encoding="utf-8")
    hook.chmod(0o755)
    return hook
