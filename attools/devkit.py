"""백엔드 개발용 잡일 모음: .env 대조, 포트 점유, JWT, 시각 변환, 로그 마스킹."""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:  # 표준 tz 데이터가 있으면 그걸 쓴다
    from zoneinfo import ZoneInfo

    KST = ZoneInfo("Asia/Seoul")
except Exception:  # pragma: no cover - tzdata 없는 최소 환경
    KST = timezone(timedelta(hours=9), "KST")


# --------------------------------------------------------------------- .env

_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")

SECRET_HINT = re.compile(
    r"(SECRET|PASSWORD|PASSWD|TOKEN|API_?KEY|PRIVATE|CREDENTIAL|DSN|SALT)", re.I)


def parse_env(path: Path) -> dict[str, str]:
    """.env 파일을 dict로 읽는다. 주석·빈 줄 무시, 따옴표 제거."""
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = _ENV_LINE.match(raw)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        quoted = re.match(r"""^(["'])(.*?)\1\s*(?:#.*)?$""", val, re.S)
        out[key] = quoted.group(2) if quoted else val.split(" #", 1)[0].strip()
    return out


def mask_value(value: str, keep: int = 2) -> str:
    if not value:
        return "(비어 있음)"
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}{'*' * (len(value) - keep * 2)}{value[-keep:]}"


@dataclass
class EnvDiff:
    missing: list[str] = field(default_factory=list)   # 예시엔 있는데 실제엔 없음
    extra: list[str] = field(default_factory=list)     # 실제에만 있음
    empty: list[str] = field(default_factory=list)     # 값이 비어 있음
    placeholder: list[str] = field(default_factory=list)  # 예시 값 그대로

    @property
    def ok(self) -> bool:
        return not (self.missing or self.empty or self.placeholder)


def env_diff(example: Path, actual: Path) -> EnvDiff:
    ex, ac = parse_env(example), parse_env(actual)
    d = EnvDiff()
    for key, ex_val in ex.items():
        if key not in ac:
            d.missing.append(key)
        elif not ac[key]:
            d.empty.append(key)
        elif ex_val and ac[key] == ex_val and SECRET_HINT.search(key):
            d.placeholder.append(key)
    d.extra = [k for k in ac if k not in ex]
    return d


# ---------------------------------------------------------------------- 포트

@dataclass
class Listener:
    pid: int
    name: str
    command: str = ""


def who_listens(port: int) -> list[Listener]:
    """해당 포트를 LISTEN 중인 프로세스. lsof → ss 순으로 시도."""
    if shutil.which("lsof"):
        proc = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-F", "pcn"],
            capture_output=True, text=True)
        found: dict[int, Listener] = {}
        pid = None
        for line in proc.stdout.splitlines():
            tag, val = line[:1], line[1:]
            if tag == "p":
                pid = int(val)
                found.setdefault(pid, Listener(pid, "?"))
            elif tag == "c" and pid is not None:
                found[pid].name = val
        return list(found.values())

    if shutil.which("ss"):
        proc = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True)
        out = []
        for line in proc.stdout.splitlines()[1:]:
            if f":{port} " not in line + " ":
                continue
            m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
            if m:
                out.append(Listener(int(m.group(2)), m.group(1)))
        return out

    raise RuntimeError("lsof 또는 ss 가 필요합니다.")


def kill_listeners(port: int, *, force: bool = False) -> list[Listener]:
    import os
    import signal

    victims = who_listens(port)
    for v in victims:
        os.kill(v.pid, signal.SIGKILL if force else signal.SIGTERM)
    return victims


# ---------------------------------------------------------------------- JWT

def _b64url(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def decode_jwt(token: str) -> dict:
    """서명 검증 없이 헤더/페이로드만 디코드한다. 신뢰 판단에 쓰면 안 된다."""
    parts = token.strip().split(".")
    if len(parts) < 2:
        raise ValueError("JWT 형식이 아닙니다 (점으로 구분된 3부분).")
    header = json.loads(_b64url(parts[0]))
    payload = json.loads(_b64url(parts[1]))

    times = {}
    for claim in ("iat", "nbf", "exp", "auth_time"):
        if isinstance(payload.get(claim), (int, float)):
            times[claim] = datetime.fromtimestamp(payload[claim], KST)

    expired = None
    if "exp" in times:
        expired = times["exp"] < datetime.now(KST)

    return {"header": header, "payload": payload, "times": times, "expired": expired,
            "signed": len(parts) == 3 and bool(parts[2])}


# --------------------------------------------------------------------- 시각

def parse_when(text: str) -> datetime:
    """epoch(초/밀리초) 또는 ISO 문자열 또는 'now' 를 KST datetime으로."""
    text = text.strip()
    if text in ("now", "지금", ""):
        return datetime.now(KST)
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        num = float(text)
        if abs(num) > 1e11:  # 밀리초로 간주
            num /= 1000
        return datetime.fromtimestamp(num, KST)
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def when_report(dt: datetime) -> dict[str, str]:
    utc = dt.astimezone(timezone.utc)
    delta = datetime.now(KST) - dt
    return {
        "KST": dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "UTC": utc.strftime("%Y-%m-%d %H:%M:%S"),
        "epoch": str(int(dt.timestamp())),
        "epoch_ms": str(int(dt.timestamp() * 1000)),
        "ISO": dt.isoformat(),
        "상대": humanize_delta(delta),
    }


def humanize_delta(delta: timedelta) -> str:
    secs = delta.total_seconds()
    past = secs >= 0
    secs = abs(secs)
    for limit, unit, name in ((60, 1, "초"), (3600, 60, "분"), (86400, 3600, "시간"),
                              (2592000, 86400, "일"), (31536000, 2592000, "개월")):
        if secs < limit:
            return f"{int(secs // unit)}{name} {'전' if past else '후'}"
    return f"{secs / 31536000:.1f}년 {'전' if past else '후'}"


# ----------------------------------------------------------------- 마스킹

MASK_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("주민등록번호", re.compile(r"\b(\d{6})-?([1-4]\d{6})\b"), r"\1-*******"),
    ("카드번호", re.compile(r"\b(\d{4})[- ]?\d{4}[- ]?\d{4}[- ]?(\d{4})\b"), r"\1-****-****-\2"),
    ("휴대전화", re.compile(r"\b(01[016789])[- ]?(\d{3,4})[- ]?(\d{4})\b"), r"\1-****-\3"),
    ("이메일", re.compile(r"\b([\w.+-]{1,2})[\w.+-]*@([\w-]+\.[\w.-]+)\b"), r"\1***@\2"),
    ("계좌번호", re.compile(r"\b\d{2,3}-\d{2,6}-\d{2,6}(-\d{1,3})?\b"), "***-****-****"),
    ("Bearer 토큰", re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{10,}"), r"\1 ***"),
    ("시크릿", re.compile(
        r"(?i)\b(pw|pass(?:word|wd)?|secret|token|api[_-]?key|access[_-]?key"
        r"|authorization|credential)"
        r"(\"?\s*[:=]\s*\"?)([^\s\"',&]{3,})"), r"\1\2***"),
]


def mask_text(text: str, *, rules: list[str] | None = None) -> tuple[str, dict[str, int]]:
    """로그·덤프를 공유하기 전에 개인정보/시크릿을 가린다."""
    counts: dict[str, int] = {}
    for name, pattern, repl in MASK_RULES:
        if rules and name not in rules:
            continue
        text, n = pattern.subn(repl, text)
        if n:
            counts[name] = n
    return text, counts
