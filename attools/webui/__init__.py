"""내 컴퓨터에서만 도는 화면. 기능마다 한 화면씩, 껍데기는 하나.

터미널이 편하지 않은 사람도 같은 기능을 쓰게 하려고 둔 것이지, 서버가
아니다. 127.0.0.1 에만 붙고, 실행할 때마다 만든 토큰을 들고 온 요청만
받는다. 다른 웹페이지가 몰래 내 컴퓨터의 파일을 옮기지 못하게 하기
위해서다.
"""

from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

from . import assets

MAX_BODY = 1 << 20  # 1MB. 화면에서 보내는 것은 작은 JSON 뿐이다.


class UiError(Exception):
    """화면에 그대로 보여줄 오류. 스택은 감춘다."""


@dataclass
class App:
    """화면 한 장. 기능 하나가 App 하나다."""

    key: str                                  # 주소와 명령에 쓰는 이름
    name: str                                 # 화면에 보이는 이름
    summary: str                              # 런처에 보이는 한 줄
    subtitle: str                             # 머리글 오른쪽 문구
    body: Callable[[], str]                   # 본문 HTML
    actions: dict[str, Callable[[dict], dict]] = field(default_factory=dict)
    aliases: tuple[str, ...] = ()             # 명령에서 부르는 다른 이름

    def names(self) -> tuple[str, ...]:
        return (self.key, self.name, self.name.replace(" ", "")) + self.aliases


def load_apps() -> list[App]:
    """apps 패키지 안의 화면을 모은다. 순서는 ORDER 를 따른다."""
    from . import apps

    return apps.all_apps()


def find_app(apps: list[App], wanted: str) -> App | None:
    key = wanted.strip().replace(" ", "").lower()
    for app in apps:
        if key in {n.replace(" ", "").lower() for n in app.names()}:
            return app
    return None


def launcher_body(apps: list[App], token: str) -> str:
    from html import escape

    items = []
    for app in apps:
        href = f"/{app.key}?t={token}"
        items.append(
            f'<li><a href="{href}"><strong>{escape(app.name)}</strong>'
            f"<span>{escape(app.summary)}</span></a></li>"
        )
    return (
        '<section class="card"><h2>어떤 일을 하시겠습니까</h2>'
        '<ul class="apps">' + "".join(items) + "</ul></section>"
        '<p class="note">터미널에서 <code>at ui 파일정리</code> 처럼 부르면 '
        "그 화면만 바로 뜹니다.</p>"
    )


def make_handler(apps: list[App], token: str, *, only: App | None = None):
    by_key = {app.key: app for app in apps}

    class Handler(BaseHTTPRequestHandler):
        server_version = "attools"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # 터미널을 접속 기록으로 채우지 않는다
            pass

        # --- 보내기 ---------------------------------------------------
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _html(self, code: int, text: str) -> None:
            self._send(code, text.encode("utf-8"), "text/html; charset=utf-8")

        def _json(self, code: int, data: dict) -> None:
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self._send(code, raw, "application/json; charset=utf-8")

        # --- 토큰 -----------------------------------------------------
        def _ok_get(self, query: dict) -> bool:
            return secrets.compare_digest(query.get("t", [""])[0], token)

        def _ok_post(self) -> bool:
            if not secrets.compare_digest(self.headers.get("X-At-Token", ""), token):
                return False
            origin = self.headers.get("Origin")
            if origin is None:
                return True
            host = urlparse(origin).netloc.split(":")[0]
            return host in {"127.0.0.1", "localhost"}

        # --- 받기 -----------------------------------------------------
        def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler 규약)
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if not self._ok_get(query):
                self._html(403, assets.page(
                    "열쇠가 없습니다", "",
                    "<section class=\"card\"><p>터미널에 찍힌 주소로 다시 "
                    "들어와 주세요. 주소 끝의 <code>?t=...</code> 까지 있어야 "
                    "합니다.</p></section>", home=False))
                return

            path = unquote(parsed.path).rstrip("/") or "/"
            if path == "/":
                if only is not None:
                    self._html(200, assets.page(
                        only.name, only.subtitle, only.body(), home=False))
                    return
                self._html(200, assets.page(
                    "attools", "내 컴퓨터에서 도는 도구",
                    launcher_body(apps, token), home=False))
                return

            app = by_key.get(path.lstrip("/"))
            if app is None or (only is not None and app is not only):
                self._html(404, assets.page(
                    "없는 화면", "", '<section class="card"><p>그런 화면은 '
                    "없습니다.</p></section>", home=only is None))
                return
            self._html(200, assets.page(
                app.name, app.subtitle, app.body(), home=only is None))

        def do_POST(self) -> None:  # noqa: N802
            if not self._ok_post():
                self._json(403, {"error": "열쇠가 맞지 않습니다."})
                return

            parts = unquote(urlparse(self.path).path).strip("/").split("/")
            if len(parts) != 3 or parts[0] != "api":
                self._json(404, {"error": "없는 주소입니다."})
                return
            app = by_key.get(parts[1])
            if app is None or (only is not None and app is not only):
                self._json(404, {"error": "없는 화면입니다."})
                return
            action = app.actions.get(parts[2])
            if action is None:
                self._json(404, {"error": "없는 동작입니다."})
                return

            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._json(413, {"error": "보낸 내용이 너무 큽니다."})
                return
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self._json(400, {"error": "요청을 읽지 못했습니다."})
                return
            if not isinstance(payload, dict):
                self._json(400, {"error": "요청 모양이 맞지 않습니다."})
                return

            try:
                self._json(200, action(payload))
            except UiError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # 화면이 통째로 멎지 않게 한다
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    return Handler


@dataclass
class Running:
    url: str
    server: ThreadingHTTPServer
    token: str


def start(app: App | None = None, *, port: int = 0,
          apps: list[App] | None = None) -> Running:
    """서버를 띄우고 주소를 돌려준다. 멈추는 것은 부른 쪽 몫이다."""
    apps = apps if apps is not None else load_apps()
    token = secrets.token_urlsafe(16)
    server = ThreadingHTTPServer(("127.0.0.1", port),
                                 make_handler(apps, token, only=app))
    server.daemon_threads = True
    host, real_port = server.server_address[:2]
    return Running(f"http://{host}:{real_port}/?t={token}", server, token)


def serve(app: App | None = None, *, port: int = 0, open_browser: bool = True,
          apps: list[App] | None = None) -> Running:
    """실제로 화면을 띄운다. Ctrl+C 까지 막힌다."""
    run = start(app, port=port, apps=apps)
    thread = threading.Thread(target=run.server.serve_forever, daemon=True)
    thread.start()
    if open_browser:
        webbrowser.open(run.url)
    return run
