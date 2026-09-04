"""at ui - 브라우저 화면. 기능마다 한 화면씩 띄운다."""

from __future__ import annotations

import webbrowser

from .. import webui
from .common import _grid, _p


def cmd_ui(a) -> int:
    apps = webui.load_apps()

    if a.list:
        _grid(["부르는 이름", "화면", "하는 일"],
              [[app.key, app.name, app.summary] for app in apps], limit=44)
        return 0

    picked = None
    if a.app:
        picked = webui.find_app(apps, a.app)
        if picked is None:
            _p(f"'{a.app}' 이라는 화면은 없습니다. at ui --list 로 확인하세요.")
            return 1

    try:
        run = webui.start(picked, port=a.port, apps=apps)
    except OSError as exc:
        _p(f"화면을 띄우지 못했습니다: {exc}")
        return 1

    _p(f"{picked.name if picked else 'attools'} 화면을 띄웠습니다.")
    _p(f"  {run.url}")
    _p("  이 컴퓨터에서만 열립니다. 주소 끝의 열쇠(t=)까지 있어야 들어갑니다.")
    _p("  끝내려면 Ctrl+C.")

    if not a.no_open:
        webbrowser.open(run.url)

    try:
        run.server.serve_forever()
    except KeyboardInterrupt:
        _p("\n화면을 닫았습니다.")
    finally:
        run.server.server_close()
    return 0


def add_commands(sub) -> None:
    """ui 명령을 붙인다. 하위 명령 대신 화면 이름을 받는다."""
    up = sub.add_parser("ui", help="브라우저 화면 - 터미널 없이 같은 기능을")
    up.add_argument("app", nargs="?", metavar="화면",
                    help="예: 파일정리 (없으면 고르는 화면)")
    up.add_argument("--port", type=int, default=0, metavar="번호",
                    help="쓸 포트 (기본: 비어 있는 것 아무거나)")
    up.add_argument("--no-open", action="store_true", help="브라우저를 열지 않는다")
    up.add_argument("--list", action="store_true", help="어떤 화면이 있는지 본다")
    up.set_defaults(func=cmd_ui)
