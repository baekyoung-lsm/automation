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


# ----------------------------------------------------------------- 대기

def wait_for(target: str, *, timeout: float = 60.0, interval: float = 1.0,
             on_try=None) -> tuple[bool, float, str]:
    """host:port 나 http(s) URL 이 응답할 때까지 기다린다. (성공, 걸린 초, 마지막 오류)"""
    import socket
    import time as _time
    import urllib.error
    import urllib.request

    started = _time.monotonic()
    attempt = 0
    last = ""

    while True:
        attempt += 1
        try:
            if target.startswith(("http://", "https://")):
                with urllib.request.urlopen(target, timeout=interval + 2) as r:
                    if r.status < 500:
                        return True, _time.monotonic() - started, ""
                    last = f"HTTP {r.status}"
            else:
                host, _, port = target.rpartition(":")
                if not port.isdigit():
                    raise ValueError("host:port 형식이 필요합니다.")
                with socket.create_connection((host or "127.0.0.1", int(port)),
                                              timeout=interval + 2):
                    return True, _time.monotonic() - started, ""
        except urllib.error.HTTPError as e:
            if e.code < 500:  # 401/404 도 서버가 살아 있다는 뜻
                return True, _time.monotonic() - started, ""
            last = f"HTTP {e.code}"
        except ValueError:
            raise
        except Exception as e:  # 연결 거부, DNS 실패, 타임아웃
            last = f"{type(e).__name__}: {e}"

        elapsed = _time.monotonic() - started
        if on_try:
            on_try(attempt, elapsed, last)
        if elapsed + interval > timeout:
            return False, elapsed, last
        _time.sleep(interval)


# --------------------------------------------------------------- 생성기

AMBIGUOUS = "0OoIl1"


def gen_secret(kind: str = "token", length: int = 32, *, count: int = 1,
               readable: bool = False) -> list[str]:
    """비밀번호·토큰·UUID·hex 키를 CSPRNG 로 만든다."""
    import secrets
    import string
    import uuid

    out = []
    for _ in range(count):
        if kind == "uuid":
            out.append(str(uuid.uuid4()))
        elif kind == "hex":
            out.append(secrets.token_hex(max(1, length // 2)))
        elif kind == "token":
            out.append(secrets.token_urlsafe(length)[:length])
        elif kind == "pin":
            out.append("".join(secrets.choice(string.digits) for _ in range(length)))
        elif kind == "password":
            pool = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
            if readable:
                pool = "".join(c for c in pool if c not in AMBIGUOUS)
            while True:
                cand = "".join(secrets.choice(pool) for _ in range(length))
                if (any(c.islower() for c in cand) and any(c.isupper() for c in cand)
                        and any(c.isdigit() for c in cand)
                        and any(not c.isalnum() for c in cand)):
                    out.append(cand)
                    break
        else:
            raise ValueError(f"알 수 없는 종류: {kind}")
    return out


# ------------------------------------------------------- 인코딩 변환

def encodings(value: str) -> dict[str, str]:
    """문자열의 여러 표현을 한 번에 보여준다. 디코드 가능한 것은 디코드도 시도한다."""
    import binascii
    import hashlib
    import urllib.parse

    raw = value.encode("utf-8")
    out = {
        "원본": value,
        "base64": base64.b64encode(raw).decode(),
        "base64url": base64.urlsafe_b64encode(raw).decode().rstrip("="),
        "hex": raw.hex(),
        "URL 인코딩": urllib.parse.quote(value, safe=""),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "md5": hashlib.md5(raw).hexdigest(),
    }

    unquoted = urllib.parse.unquote(value)
    if unquoted != value:
        out["URL 디코딩"] = unquoted

    stripped = value.strip()
    if re.fullmatch(r"[A-Za-z0-9+/=_-]{4,}", stripped):
        try:
            decoded = base64.urlsafe_b64decode(stripped + "=" * (-len(stripped) % 4))
            out["base64 디코딩"] = decoded.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            pass
    if re.fullmatch(r"(?:[0-9a-fA-F]{2})+", stripped):
        try:
            out["hex 디코딩"] = bytes.fromhex(stripped).decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            pass
    return out


# ----------------------------------------------------------------- 측정

@dataclass
class BenchResult:
    label: str
    times: list[float] = field(default_factory=list)
    failures: int = 0

    @property
    def runs(self) -> int:
        return len(self.times)

    @property
    def mean(self) -> float:
        return sum(self.times) / len(self.times) if self.times else 0.0

    @property
    def median(self) -> float:
        if not self.times:
            return 0.0
        ordered = sorted(self.times)
        mid = len(ordered) // 2
        return (ordered[mid] if len(ordered) % 2
                else (ordered[mid - 1] + ordered[mid]) / 2)

    @property
    def stdev(self) -> float:
        if len(self.times) < 2:
            return 0.0
        avg = self.mean
        return (sum((t - avg) ** 2 for t in self.times) / (len(self.times) - 1)) ** 0.5

    @property
    def fastest(self) -> float:
        return min(self.times) if self.times else 0.0

    @property
    def slowest(self) -> float:
        return max(self.times) if self.times else 0.0


def run_bench(command, *, label: str = "", runs: int = 10, warmup: int = 1,
              shell: bool = False, on_run=None) -> BenchResult:
    """명령을 여러 번 돌려 걸린 시간을 잰다. 출력은 버린다."""
    import time as _time

    result = BenchResult(label or (command if isinstance(command, str)
                                   else " ".join(command)))
    for i in range(warmup + runs):
        started = _time.perf_counter()
        proc = subprocess.run(command, shell=shell, capture_output=True)
        elapsed = _time.perf_counter() - started

        if i < warmup:            # 첫 실행은 캐시가 비어 있어 느리다
            continue
        if proc.returncode != 0:
            result.failures += 1
        result.times.append(elapsed)
        if on_run:
            on_run(i - warmup + 1, elapsed, proc.returncode)
    return result


def format_seconds(value: float) -> str:
    if value < 1:
        return f"{value * 1000:.1f}ms"
    if value < 60:
        return f"{value:.2f}초"
    return f"{int(value // 60)}분 {value % 60:.1f}초"


def build_example(actual: Path, *, existing: Path | None = None,
                  keep_values: bool = False) -> tuple[str, list[str]]:
    """.env 에서 .env.example 을 만든다. 값은 지우거나 자리표시자로 바꾼다.

    (내용, 새로 들어간 키). 기존 example 이 있으면 주석과 순서를 살린다.
    """
    values = parse_env(actual)
    previous = parse_env(existing) if existing and existing.is_file() else {}
    added = [k for k in values if k not in previous]

    def placeholder(key: str, value: str) -> str:
        if keep_values and not SECRET_HINT.search(key):
            return value
        if not value:
            return ""
        if SECRET_HINT.search(key):
            return f"<{key.lower()}>"
        if re.fullmatch(r"\d+", value):
            return value            # 포트·타임아웃 같은 숫자는 그대로 두는 편이 낫다
        if value.lower() in ("true", "false"):
            return value
        return f"<{key.lower()}>"

    lines: list[str] = []
    if existing and existing.is_file():
        # 기존 파일의 주석·빈 줄·순서를 그대로 두고 값만 손본다
        for raw in existing.read_text(encoding="utf-8").splitlines():
            m = _ENV_LINE.match(raw)
            if not m:
                lines.append(raw)
                continue
            key = m.group(1)
            if key in values:
                lines.append(f"{key}={placeholder(key, values[key])}")
            else:
                lines.append(f"# (지워진 키) {raw}")
        if added:
            lines.append("")
            lines.append("# 새로 생긴 키")
    else:
        lines.append("# .env 에서 만든 예시입니다. 값은 실제 값으로 바꿔 쓰세요.")

    for key in added:
        lines.append(f"{key}={placeholder(key, values[key])}")

    return "\n".join(lines).rstrip() + "\n", added


@dataclass
class OpenPort:
    port: int
    pid: int
    name: str
    address: str = ""


def listening_ports() -> list[OpenPort]:
    """지금 열려 있는 TCP 포트 전부. lsof -> ss 순으로 시도한다."""
    if shutil.which("lsof"):
        proc = subprocess.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-F", "pcn"],
                              capture_output=True, text=True)
        found: list[OpenPort] = []
        pid, name = 0, "?"
        for line in proc.stdout.splitlines():
            tag, value = line[:1], line[1:]
            if tag == "p":
                pid = int(value) if value.isdigit() else 0
            elif tag == "c":
                name = value
            elif tag == "n":
                address, _, port = value.rpartition(":")
                if port.isdigit():
                    found.append(OpenPort(int(port), pid, name, address))
        return sorted(found, key=lambda p: (p.port, p.pid))

    if shutil.which("ss"):
        proc = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True)
        found = []
        for line in proc.stdout.splitlines()[1:]:
            cells = line.split()
            if len(cells) < 4:
                continue
            address, _, port = cells[3].rpartition(":")
            if not port.isdigit():
                continue
            m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
            found.append(OpenPort(int(port), int(m.group(2)) if m else 0,
                                  m.group(1) if m else "?", address))
        return sorted(found, key=lambda p: (p.port, p.pid))

    raise RuntimeError("lsof 또는 ss 가 필요합니다.")
