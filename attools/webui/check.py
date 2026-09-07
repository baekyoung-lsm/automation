"""화면을 진짜 브라우저로 열어 자바스크립트 오류를 잡는다.

JSON 만 두드려 보면 화면이 통째로 깨져도 시험이 통과한다. 실제로 한 번
불러 보는 것 말고는 알 방법이 없다. 브라우저가 없으면 없다고 말하고
넘어간다 - 이것 때문에 의존성을 늘리지는 않는다.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# 콘솔에 찍힌 오류만 고른다. dbus·GPU 같은 환경 잡음은 뺀다.
CONSOLE = re.compile(r"CONSOLE|Uncaught|SyntaxError")
NOISE = re.compile(r"dbus|GPU|gpu_|Fontconfig|libva|Vulkan|DevTools listening")

BROWSER_NAMES = ("chromium", "chromium-browser", "google-chrome",
                 "google-chrome-stable", "chrome")
BROWSER_ENV = "AT_UI_BROWSER"


def find_browser() -> str | None:
    """PATH 와 흔한 자리에서 크로미움 계열을 찾는다."""
    named = os.environ.get(BROWSER_ENV)
    if named:
        return named if Path(named).is_file() else None

    for name in BROWSER_NAMES:
        found = shutil.which(name)
        if found:
            return found

    roots = [Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))]
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("chromium*/chrome-linux/chrome")):
            if path.is_file():
                return str(path)
    return None


@dataclass
class ScreenCheck:
    key: str
    name: str
    messages: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.messages


def check_page(browser: str, url: str, *, timeout: float = 30.0) -> list[str]:
    """한 화면을 열고 콘솔 오류를 모은다."""
    args = [browser, "--headless", "--no-sandbox", "--disable-gpu",
            "--enable-logging=stderr", "--v=1", "--virtual-time-budget=3000",
            "--dump-dom", url]
    try:
        done = subprocess.run(args, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return [f"브라우저가 {timeout:.0f}초 안에 끝나지 않았습니다."]
    except OSError as exc:
        return [f"브라우저를 실행하지 못했습니다: {exc}"]

    out: list[str] = []
    for line in done.stderr.splitlines():
        if not CONSOLE.search(line) or NOISE.search(line):
            continue
        # [pid:pid:시각:INFO:CONSOLE(줄)] "본문", source: ...
        body = line.split("] ", 1)[-1]
        out.append(body.strip())
    return out
