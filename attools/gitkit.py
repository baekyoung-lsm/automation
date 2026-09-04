"""git 저장소 잡일: 병합된 브랜치 정리, 커밋 전 시크릿 검사."""

from __future__ import annotations

import math
import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
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


# git 은 기본으로 비ASCII 파일명을 "\353\263..." 처럼 8진수로 이스케이프해서 내놓는다.
# 한글 파일명이 그대로 나오게 매번 꺼 준다.
GIT_BASE = ["git", "-c", "core.quotepath=false"]


def run(args: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run([*GIT_BASE, *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} 실패")
    return proc.stdout


def tracked_count(root: Path) -> int:
    """git 이 추적하는 파일 수. 저장소가 아니면 -1.

    0 과 '찾은 게 없음'은 다르다. 아직 add 하지 않은 저장소에서 조용히
    '문제 없음'이라고 답하면 안 된다.
    """
    try:
        return len([n for n in run(["ls-files"], root).splitlines() if n.strip()])
    except RuntimeError:
        return -1


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


@dataclass
class Commit:
    sha: str
    author: str
    when: datetime
    subject: str
    files: dict[str, tuple[int, int]] = field(default_factory=dict)  # 경로 -> (추가, 삭제)

    @property
    def added(self) -> int:
        return sum(a for a, _ in self.files.values())

    @property
    def deleted(self) -> int:
        return sum(d for _, d in self.files.values())


@dataclass
class FileChurn:
    path: str
    commits: int = 0
    added: int = 0
    deleted: int = 0
    authors: set[str] = field(default_factory=set)
    last: datetime | None = None

    @property
    def churn(self) -> int:
        return self.added + self.deleted


LOG_FORMAT = "%x01%H%x02%an%x02%aI%x02%s"


def read_log(root: Path, *, since: str = "", until: str = "",
             paths: list[str] | None = None, limit: int = 0) -> list[Commit]:
    """git log --numstat 을 읽어 커밋 목록으로."""
    args = ["log", f"--pretty=format:{LOG_FORMAT}", "--numstat", "--no-merges"]
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    if limit:
        args.append(f"-n{limit}")
    if paths:
        args += ["--", *paths]

    out = run(args, root)
    commits: list[Commit] = []
    current: Commit | None = None

    for chunk in out.split("\x01"):
        if not chunk.strip():
            continue
        head, _, body = chunk.partition("\n")
        parts = head.split("\x02")
        if len(parts) < 4:
            continue
        sha, author, stamp, subject = parts[0], parts[1], parts[2], parts[3]
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        current = Commit(sha[:9], author, when.replace(tzinfo=None), subject)
        commits.append(current)

        for line in body.splitlines():
            cells = line.split("\t")
            if len(cells) != 3:
                continue
            added, deleted, name = cells
            if added == "-" or deleted == "-":   # 이진 파일
                continue
            try:
                current.files[name] = (int(added), int(deleted))
            except ValueError:
                continue
    return commits


def churn_by_file(commits: list[Commit]) -> list[FileChurn]:
    """파일마다 몇 번, 얼마나 바뀌었는지. 자주 바뀌는 파일은 대개 문제가 몰린 곳이다."""
    table: dict[str, FileChurn] = {}
    for c in commits:
        for name, (added, deleted) in c.files.items():
            f = table.setdefault(name, FileChurn(name))
            f.commits += 1
            f.added += added
            f.deleted += deleted
            f.authors.add(c.author)
            f.last = c.when if f.last is None else max(f.last, c.when)
    return sorted(table.values(), key=lambda f: (-f.commits, -f.churn))


def by_author(commits: list[Commit]) -> list[tuple[str, int, int, int]]:
    """(이름, 커밋 수, 추가 줄, 삭제 줄)"""
    table: dict[str, list[int]] = {}
    for c in commits:
        row = table.setdefault(c.author, [0, 0, 0])
        row[0] += 1
        row[1] += c.added
        row[2] += c.deleted
    return sorted(((name, *row) for name, row in table.items()), key=lambda x: -x[1])


def by_period(commits: list[Commit], *, unit: str = "day") -> list[tuple[str, int]]:
    formats = {"day": "%Y-%m-%d", "week": "%Y-%W주", "month": "%Y-%m", "hour": "%H시"}
    if unit not in formats:
        raise ValueError(f"알 수 없는 단위: {unit} ({', '.join(formats)})")
    counts: Counter = Counter(c.when.strftime(formats[unit]) for c in commits)
    return sorted(counts.items())


WEEKDAYS_KO = ["월", "화", "수", "목", "금", "토", "일"]


def by_weekday(commits: list[Commit]) -> list[tuple[str, int]]:
    counts: Counter = Counter(c.when.weekday() for c in commits)
    return [(WEEKDAYS_KO[i], counts.get(i, 0)) for i in range(7)]


# ------------------------------------------------------------------ 변경 로그

# 커밋 제목 앞에 붙는 관례적 접두사. 없는 커밋은 파일 경로로 묶는다.
CONVENTIONAL = {
    "feat": "새 기능", "fix": "고침", "perf": "성능", "refactor": "구조 정리",
    "docs": "문서", "test": "테스트", "build": "빌드", "ci": "CI",
    "style": "서식", "chore": "잡일", "revert": "되돌림",
}
PREFIX_RE = re.compile(r"^(\w+)(?:\(([^)]+)\))?(!)?:\s*(.+)$")


@dataclass
class Change:
    sha: str
    kind: str          # 관례 접두사 또는 ""
    scope: str
    breaking: bool
    title: str
    author: str
    when: datetime
    files: list[str] = field(default_factory=list)


def latest_tag(root: Path) -> str:
    try:
        return run(["describe", "--tags", "--abbrev=0"], root).strip()
    except RuntimeError:
        return ""


def list_tags(root: Path, limit: int = 20) -> list[str]:
    try:
        out = run(["tag", "--sort=-creatordate"], root)
    except RuntimeError:
        return []
    return [t for t in out.splitlines() if t.strip()][:limit]


def collect_changes(root: Path, *, since: str = "", until: str = "HEAD") -> list[Change]:
    """범위 안의 커밋을 변경 항목으로 바꾼다."""
    span = f"{since}..{until}" if since else until
    commits = read_log_range(root, span)

    out: list[Change] = []
    for c in commits:
        kind = scope = ""
        breaking = False
        title = c.subject
        if m := PREFIX_RE.match(c.subject):
            # feat/fix 같은 관례 접두사가 아니어도 'attools:' 처럼 쓰는 저장소가 많다.
            # 그런 말머리도 묶는 이름으로 살려 둔다.
            kind, scope, breaking, title = (m.group(1).lower(), m.group(2) or "",
                                            bool(m.group(3)), m.group(4))
        out.append(Change(c.sha, kind, scope, breaking, title, c.author, c.when,
                          sorted(c.files)))
    return out


def read_log_range(root: Path, span: str) -> list[Commit]:
    args = ["log", f"--pretty=format:{LOG_FORMAT}", "--numstat", "--no-merges", span]
    out = run(args, root)
    commits: list[Commit] = []
    for chunk in out.split("\x01"):
        if not chunk.strip():
            continue
        head, _, body = chunk.partition("\n")
        parts = head.split("\x02")
        if len(parts) < 4:
            continue
        try:
            when = datetime.fromisoformat(parts[2])
        except ValueError:
            continue
        commit = Commit(parts[0][:9], parts[1], when.replace(tzinfo=None), parts[3])
        for line in body.splitlines():
            cells = line.split("\t")
            if len(cells) == 3 and cells[0] != "-":
                try:
                    commit.files[cells[2]] = (int(cells[0]), int(cells[1]))
                except ValueError:
                    continue
        commits.append(commit)
    return commits


def top_directory(paths: list[str], depth: int = 1) -> str:
    """접두사가 없는 커밋을 묶을 이름. 바뀐 파일들의 공통 위치."""
    if not paths:
        return "기타"
    tops = {"/".join(p.split("/")[:depth]) or p for p in paths}
    return sorted(tops)[0] if len(tops) == 1 else "여러 곳"


def group_changes(changes: list[Change]) -> dict[str, list[Change]]:
    """관례 접두사가 있으면 그것으로, 없으면 바뀐 위치로 묶는다."""
    groups: dict[str, list[Change]] = defaultdict(list)
    for c in changes:
        label = CONVENTIONAL.get(c.kind) or c.kind or top_directory(c.files)
        groups[label].append(c)

    order = list(CONVENTIONAL.values())
    return dict(sorted(groups.items(),
                       key=lambda kv: (order.index(kv[0]) if kv[0] in order else 99,
                                       kv[0])))


def render_changelog(groups: dict[str, list[Change]], *, title: str = "",
                     link_prefix: str = "") -> str:
    lines: list[str] = []
    if title:
        lines += [f"## {title}", ""]
    for label, items in groups.items():
        lines.append(f"### {label}")
        for c in items:
            mark = "**[호환성 주의]** " if c.breaking else ""
            scope = f"({c.scope}) " if c.scope else ""
            sha = f"[`{c.sha}`]({link_prefix}{c.sha})" if link_prefix else f"`{c.sha}`"
            lines.append(f"- {mark}{scope}{c.title} {sha}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


@dataclass
class Branch:
    name: str
    current: bool
    when: datetime | None
    author: str
    subject: str
    upstream: str = ""
    ahead: int = 0
    behind: int = 0
    gone: bool = False

    @property
    def age_days(self) -> int | None:
        return (datetime.now() - self.when).days if self.when else None


BRANCH_FORMAT = ("%(HEAD)\x02%(refname:short)\x02%(committerdate:iso-strict)"
                 "\x02%(authorname)\x02%(contents:subject)\x02%(upstream:short)"
                 "\x02%(upstream:track)")


def list_branches(root: Path, *, remote: bool = False) -> list[Branch]:
    """브랜치마다 마지막 커밋 시각·사람·앞뒤 차이를 모은다."""
    ref = "refs/remotes" if remote else "refs/heads"
    out = run(["for-each-ref", f"--format={BRANCH_FORMAT}", ref], root)

    branches: list[Branch] = []
    for line in out.splitlines():
        cells = line.split("\x02")
        if len(cells) < 7:
            continue
        head, name, stamp, author, subject, upstream, track = cells[:7]
        try:
            when = datetime.fromisoformat(stamp).replace(tzinfo=None)
        except ValueError:
            when = None

        branch = Branch(name, head.strip() == "*", when, author, subject, upstream)
        if "gone" in track:
            branch.gone = True
        if m := re.search(r"ahead (\d+)", track):
            branch.ahead = int(m.group(1))
        if m := re.search(r"behind (\d+)", track):
            branch.behind = int(m.group(1))
        branches.append(branch)

    return sorted(branches, key=lambda b: (b.when is None, -(b.when.timestamp()
                                                             if b.when else 0)))


# ------------------------------------------------------------------ 충돌 표시

CONFLICT_START = re.compile(r"^<{7}(?: |$)")
CONFLICT_MID = re.compile(r"^={7}$")
CONFLICT_END = re.compile(r"^>{7}(?: |$)")
CONFLICT_BASE = re.compile(r"^\|{7}(?: |$)")


@dataclass
class Conflict:
    path: str
    line: int                 # <<<<<<< 가 있는 줄
    ours: int = 0             # 우리 쪽 줄 수
    theirs: int = 0
    label_ours: str = ""
    label_theirs: str = ""

    @property
    def one_sided(self) -> bool:
        """한쪽이 비어 있으면 '지웠는가 남겼는가'의 문제다."""
        return not self.ours or not self.theirs


def find_conflicts(text: str, path: str = "") -> list[Conflict]:
    """충돌 표시를 찾는다. 병합 중이 아니어도 남은 표시를 잡는다."""
    out: list[Conflict] = []
    current: Conflict | None = None
    side = ""
    for number, line in enumerate(text.splitlines(), 1):
        if CONFLICT_START.match(line):
            current = Conflict(path, number, label_ours=line[7:].strip())
            side = "ours"
            continue
        if current is None:
            continue
        if CONFLICT_BASE.match(line):     # diff3 방식의 공통 조상 부분
            side = "base"
        elif CONFLICT_MID.match(line):
            side = "theirs"
        elif CONFLICT_END.match(line):
            current.label_theirs = line[7:].strip()
            out.append(current)
            current, side = None, ""
        elif side == "ours":
            current.ours += 1
        elif side == "theirs":
            current.theirs += 1
    return out


def unmerged_files(root: Path) -> list[str]:
    """지금 병합 중이라 충돌난 파일들."""
    try:
        return [n for n in run(["diff", "--name-only", "--diff-filter=U"],
                               root).splitlines() if n]
    except RuntimeError:
        return []


def scan_conflicts(root: Path, *, names: list[str] | None = None) -> list[Conflict]:
    """파일마다 충돌 표시를 찾는다. names 를 안 주면 추적 파일 전부."""
    if names is None:
        names = [n for n in run(["ls-files"], root).splitlines() if n]
    found: list[Conflict] = []
    for name in names:
        path = root / name
        if not path.is_file():
            continue
        text = _readable(path)
        if text is None or "<<<<<<<" not in text:
            continue
        found.extend(find_conflicts(text, name))
    return found
