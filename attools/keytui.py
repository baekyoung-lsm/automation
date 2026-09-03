"""단축키 찾기 터미널 화면. Tab 으로 앱 그룹을 넘기며 본다."""

from __future__ import annotations

import unicodedata

from .keys import Group, State, next_sort, search, sort_items, SORTS

HELP = [
    ("Tab / Shift+Tab", "그룹 넘기기"),
    ("← →", "그룹 넘기기"),
    ("↑ ↓ / PgUp PgDn", "항목 이동"),
    ("/", "검색 (Esc 로 해제)"),
    ("Enter", "찾아본 것으로 기록 (자주 찾는 순에 반영)"),
    ("p", "맨 위에 고정 / 해제"),
    ("K / J", "사용자 순서에서 위 · 아래로 옮기기"),
    ("s", "정렬 바꾸기"),
    ("r", "이 그룹의 사용자 순서 초기화"),
    ("q", "끝내기"),
]


def width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def pad(text: str, size: int) -> str:
    return text + " " * max(0, size - width(text))


def cut(text: str, size: int) -> str:
    if width(text) <= size:
        return text
    out = ""
    for ch in text:
        if width(out + ch) > size - 1:
            return out + "…"
        out += ch
    return out


class Screen:
    def __init__(self, groups: list[Group], state: State, *,
                 group_index: int = 0, sort: str = "freq", query: str = ""):
        self.groups = groups
        self.state = state
        self.gi = group_index
        self.sort = sort
        self.query = query
        self.cursor = 0
        self.top = 0
        self.message = ""
        self.show_help = False
        self.dirty = False

    @property
    def group(self) -> Group:
        return self.groups[self.gi]

    def visible(self) -> list:
        return sort_items(self.group, self.state, self.sort,
                          search(self.group, self.query))

    def clamp(self, count: int, height: int) -> None:
        self.cursor = max(0, min(self.cursor, count - 1)) if count else 0
        if self.cursor < self.top:
            self.top = self.cursor
        elif self.cursor >= self.top + height:
            self.top = self.cursor - height + 1
        self.top = max(0, min(self.top, max(0, count - height)))


def run(groups: list[Group], state: State, *, sort: str = "freq",
        group_index: int = 0, query: str = "") -> None:
    import curses
    import locale

    # 한글을 입력받고 그리려면 로캘이 잡혀 있어야 한다
    locale.setlocale(locale.LC_ALL, "")

    screen = Screen(groups, state, group_index=group_index, sort=sort, query=query)
    curses.wrapper(lambda stdscr: _loop(stdscr, screen))
    if screen.dirty:
        state.save()


def _columns(group: Group, total: int) -> tuple[int, list[int]]:
    """기능 열 너비와 앱별 열 너비를 화면 폭에 맞춰 정한다."""
    apps = group.apps
    name_w = min(24, max(10, total - 6 - len(apps) * 14))
    rest = total - name_w - 6
    each = max(10, rest // max(1, len(apps)))
    return name_w, [each] * len(apps)


def _loop(stdscr, s: Screen) -> None:
    import curses

    curses.curs_set(0)
    stdscr.keypad(True)
    try:
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.init_pair(3, curses.COLOR_GREEN, -1)
    except curses.error:
        pass

    while True:
        height, total = stdscr.getmaxyx()
        body_h = max(1, height - 7)
        items = s.visible()
        s.clamp(len(items), body_h)
        _draw(stdscr, s, items, height, total, body_h)

        key = stdscr.getch()
        if s.show_help:
            s.show_help = False
            continue

        if key in (ord("q"), 27):
            return
        elif key == ord("?"):
            s.show_help = True
        elif key in (curses.KEY_RIGHT, 9):            # Tab
            s.gi = (s.gi + 1) % len(s.groups)
            s.cursor = s.top = 0
        elif key in (curses.KEY_LEFT, curses.KEY_BTAB, 353):
            s.gi = (s.gi - 1) % len(s.groups)
            s.cursor = s.top = 0
        elif key == curses.KEY_DOWN:
            s.cursor += 1
        elif key == curses.KEY_UP:
            s.cursor -= 1
        elif key == curses.KEY_NPAGE:
            s.cursor += body_h
        elif key == curses.KEY_PPAGE:
            s.cursor -= body_h
        elif key == curses.KEY_HOME:
            s.cursor = 0
        elif key == curses.KEY_END:
            s.cursor = len(items) - 1
        elif key == ord("s"):
            s.sort = next_sort(s.sort)
            s.message = f"정렬: {SORTS[s.sort]}"
        elif key == ord("/"):
            s.query = _prompt(stdscr, height, total, "검색: ", s.query)
            s.cursor = s.top = 0
        elif key in (10, 13, curses.KEY_ENTER):
            if items:
                s.state.hit(items[s.cursor].uid)
                s.dirty = True
                s.message = f"기록: {items[s.cursor].name}"
        elif key == ord("p"):
            if items:
                on = s.state.toggle_pin(items[s.cursor].uid)
                s.dirty = True
                s.message = ("고정" if on else "고정 해제") + f": {items[s.cursor].name}"
        elif key in (ord("K"), ord("J")):
            if items:
                item = items[s.cursor]
                s.state.move(s.group, item, -1 if key == ord("K") else 1)
                s.sort = "custom"
                s.dirty = True
                s.cursor += -1 if key == ord("K") else 1
                s.message = f"사용자 순서 변경: {item.name}"
        elif key == ord("r"):
            s.state.order.pop(s.group.id, None)
            s.dirty = True
            s.message = f"{s.group.name} 사용자 순서를 지웠습니다."


def _draw(stdscr, s: Screen, items, height: int, total: int, body_h: int) -> None:
    import curses

    stdscr.erase()

    def put(y, x, text, attr=0):
        if y >= height or x >= total:
            return
        try:
            stdscr.addstr(y, x, cut(text, total - x - 1), attr)
        except curses.error:
            pass

    if s.show_help:
        put(0, 0, "단축키 조작법", curses.A_BOLD)
        for n, (key, desc) in enumerate(HELP, 2):
            put(n, 2, f"{pad(key, 20)}{desc}")
        put(len(HELP) + 3, 2, "아무 키나 누르면 돌아갑니다.", curses.color_pair(2))
        stdscr.refresh()
        return

    # 탭 줄
    x = 0
    for n, g in enumerate(s.groups):
        label = f" {g.name} "
        attr = curses.A_REVERSE | curses.A_BOLD if n == s.gi else curses.color_pair(1)
        put(0, x, label, attr)
        x += width(label) + 1

    right = f"정렬: {SORTS[s.sort]}"
    put(0, max(0, total - width(right) - 1), right, curses.color_pair(2))

    head = s.group.desc
    if s.query:
        head += f"    검색 '{s.query}' → {len(items)}건"
    put(1, 0, head, curses.color_pair(1))

    name_w, app_ws = _columns(s.group, total)
    line = pad("기능", name_w) + "  "
    for app, w in zip(s.group.apps, app_ws):
        line += pad(cut(app["name"], w), w)
    put(3, 0, "  " + line, curses.A_BOLD | curses.A_UNDERLINE)

    if not items:
        put(5, 2, "맞는 항목이 없습니다. / 를 눌러 검색어를 지우세요.", curses.color_pair(2))
    for row, item in enumerate(items[s.top:s.top + body_h]):
        y = 4 + row
        selected = s.top + row == s.cursor
        mark = "★" if item.uid in s.state.pins else " "
        line = pad(cut(item.name, name_w), name_w) + "  "
        for app, w in zip(s.group.apps, app_ws):
            line += pad(cut(item.shortcut(app["id"]), w), w)
        hits = s.state.hits.get(item.uid, 0)
        if hits:
            line += f" {hits}회"
        attr = curses.A_REVERSE if selected else 0
        put(y, 0, mark + " " + line, attr)

    footer = ("[Tab] 그룹  [↑↓] 이동  [/] 검색  [Enter] 기록  [p] 고정  "
              "[K/J] 순서  [s] 정렬  [?] 도움말  [q] 종료")
    if width(footer) + 30 < total:
        footer += "   — 없음  ? 확인 못 함"
    put(height - 2, 0, cut(footer, total - 1), curses.color_pair(1))
    if s.message:
        put(height - 1, 0, s.message, curses.color_pair(3))
    stdscr.refresh()


def _prompt(stdscr, height: int, total: int, label: str, initial: str = "") -> str:
    """한 줄 입력. 한글이 들어오므로 바이트가 아니라 문자 단위로 받는다."""
    import curses

    curses.curs_set(1)
    buffer = initial
    while True:
        stdscr.move(height - 1, 0)
        stdscr.clrtoeol()
        try:
            stdscr.addstr(height - 1, 0, cut(label + buffer, total - 1))
        except curses.error:
            pass
        stdscr.refresh()

        try:
            key = stdscr.get_wch()
        except curses.error:
            continue

        if isinstance(key, int):
            if key in (curses.KEY_BACKSPACE, curses.KEY_ENTER):
                if key == curses.KEY_ENTER:
                    break
                buffer = buffer[:-1]
            continue

        if key in ("\n", "\r"):
            break
        if key == "\x1b":
            buffer = ""
            break
        if key in ("\x7f", "\b"):
            buffer = buffer[:-1]
            continue
        if key.isprintable():
            buffer += key
    curses.curs_set(0)
    return buffer
