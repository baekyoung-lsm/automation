"""at ui - 브라우저 화면. 기능마다 한 화면씩 띄운다."""

from __future__ import annotations

import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor

from .. import webui
from ..webui import check as uicheck
from .common import _grid, _p


def _check(apps, port: int, *, timeout: float = 60.0) -> int:
    """화면을 브라우저로 하나씩 열어 자바스크립트 오류를 본다."""
    browser = uicheck.find_browser()
    if browser is None:
        _p("크로미움 계열 브라우저를 찾지 못했습니다.")
        _p(f"  {uicheck.BROWSER_ENV} 에 실행 파일 경로를 넣어 주면 씁니다.")
        return 2

    run = webui.start(port=port, apps=apps)
    thread = threading.Thread(target=run.server.serve_forever,
                              kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    base = run.url.split("/?")[0]
    token = run.token

    _p(f"브라우저: {browser}")
    results = [uicheck.ScreenCheck("", "런처")] + [
        uicheck.ScreenCheck(app.key, app.name) for app in apps]
    try:
        # 브라우저를 한 번 띄우는 데 몇 초씩 걸린다. 화면이 열둘이면 그것만으로
        # 1분이 넘으므로 몇 개씩 같이 띄운다. 프로필은 따로 줘야 서로 잠금을
        # 다투지 않는다.
        def look(result):
            return uicheck.check_page(browser, f"{base}/{result.key}?t={token}",
                                      timeout=timeout)

        with ThreadPoolExecutor(max_workers=4) as pool:
            for result, found in zip(results, pool.map(look, results)):
                result.messages, result.trouble = found

        for result in results:
            mark = "OK  " if result.ok else ("못 봄" if result.trouble else "오류")
            _p(f"  {mark}  {result.name}")
            for line in ([result.trouble] if result.trouble else result.messages[:5]):
                _p(f"        {line}")
    finally:
        run.server.shutdown()
        run.server.server_close()
        thread.join(timeout=5)

    broken = [r for r in results if r.messages]
    missed = [r for r in results if r.trouble]
    _p("")
    if broken:
        _p(f"화면 {len(broken)}개에 자바스크립트 오류가 있습니다.")
    if missed:
        _p(f"화면 {len(missed)}개는 열어 보지 못했습니다. "
           "(브라우저가 느리거나 실행되지 않았습니다)")
    if broken:
        return 1
    if missed:
        # 열어 보지 못한 것은 코드 문제가 아니라 환경 문제다. 부르는 쪽이
        # 구분할 수 있게 다른 값으로 끝낸다.
        return 2
    _p(f"화면 {len(results)}개 모두 깨끗합니다.")
    return 0


def cmd_ui(a) -> int:
    apps = webui.load_apps()

    if a.list:
        _grid(["갈래", "부르는 이름", "화면", "하는 일"],
              [[app.section, app.key, app.name, app.summary] for app in apps],
              limit=40)
        return 0

    if a.check:
        return _check(apps, a.port, timeout=a.timeout)

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
    up.add_argument("--check", action="store_true",
                    help="브라우저로 모든 화면을 열어 자바스크립트 오류를 본다 "
                         "(오류 1, 열어 보지 못함 2)")
    up.add_argument("--timeout", type=float, default=60.0, metavar="초",
                    help="--check 에서 화면 하나를 기다리는 시간 (느린 러너면 늘린다)")
    up.set_defaults(func=cmd_ui)
