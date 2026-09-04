"""at keys - 단축키 찾기."""

from __future__ import annotations

import sys
from pathlib import Path

from .. import keys, names
from .common import _pad, _p, _cut, _grid


def _keys_rows(group, items, state) -> tuple[list[str], list[list[str]]]:
    header = ["기능", "분류"] + [a["name"] for a in group.apps] + ["횟수"]
    body = []
    for item in items:
        hits = state.hits.get(item.uid, 0)
        mark = "★" if item.uid in state.pins else ""
        body.append([mark + item.name, item.cat]
                    + [item.shortcut(a["id"]) for a in group.apps]
                    + [str(hits) if hits else ""])
    return header, body


def _keys_set(groups, spec: str) -> int:
    """'doc/표 만들기/word=Alt+N,T' 를 해석해 사용자 파일에 적는다."""
    target, sep, value = spec.partition("=")
    if not sep:
        _p("'그룹/기능/앱=값' 형태로 적으세요. 예: doc/표 만들기/word=Alt+N,T")
        return 1

    parts = [p.strip() for p in target.split("/")]
    if len(parts) != 3 or not all(parts):
        _p("'그룹/기능/앱=값' 형태로 적으세요. 예: doc/표 만들기/word=Alt+N,T")
        return 1

    group_name, item_name, app_id = parts
    value = value.strip()
    try:
        group = keys.find_group(groups, group_name)
        path, is_new = keys.set_shortcut(
            group, item_name, app_id,
            None if value in ("없음", "none", "") else value)
    except keys.KeysError as e:
        _p(str(e))
        return 1

    shown = "기본 단축키 없음" if value in ("없음", "none", "") else value
    _p(f"{group.name} · {item_name} · {group.app_name(app_id)} = {shown}")
    _p(f"저장: {path}" + ("  (새 항목)" if is_new else ""))
    return 0


def _keys_fill(groups) -> int:
    """확인 못 한 칸을 하나씩 물어 채운다."""
    rows = keys.gaps(groups)
    if not rows:
        _p("확인하지 못한 칸이 없습니다.")
        return 0

    _p(f"확인 못 한 칸 {sum(len(m) for _, _, m in rows)}개를 채웁니다.")
    _p("단축키를 입력하거나, 기본 단축키가 없으면 '없음', 건너뛰려면 엔터, "
       "끝내려면 q 를 누르세요.\n")

    filled = 0
    for group, item, missing in rows:
        for app_id in missing:
            prompt = f"[{group.name}] {item.name} · {group.app_name(app_id)} > "
            try:
                answer = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                _p("\n중단했습니다.")
                return 0 if filled else 1
            if answer.lower() in ("q", "quit", "종료"):
                _p(f"\n{filled}개를 채웠습니다.")
                return 0
            if not answer:
                continue
            try:
                keys.set_shortcut(group, item.name, app_id,
                                  None if answer in ("없음", "none") else answer)
                filled += 1
            except keys.KeysError as e:
                _p(f"  {e}")

    _p(f"\n{filled}개를 채웠습니다. 저장: {keys.user_data_path()}")
    return 0


def _keys_edit(groups) -> int:
    """사용자 단축키 파일 틀을 만들어 준다."""
    import json as _json

    path = keys.user_data_path()
    if path.exists():
        _p(f"이미 있습니다: {path}")
        _p("이 파일의 항목이 기본 데이터를 덮어씁니다. 같은 이름이면 사용자 값이 이깁니다.")
        return 0

    sample = {
        "groups": [{
            "id": groups[0].id,
            "items": [{"name": "내가 자주 쓰는 기능", "cat": "편집", "freq": 5,
                       "keys": {a["id"]: "Ctrl+Shift+예" for a in groups[0].apps}}],
        }],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(sample, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    _p(f"틀을 만들었습니다: {path}")
    _p(f"그룹 id: {', '.join(g.id for g in groups)}")
    for g in groups:
        _p(f"  {g.id} 의 앱 id: {', '.join(a['id'] for a in g.apps)}")
    _p("\n새 그룹을 통째로 추가하려면 apps 와 items 를 함께 적으면 됩니다.")
    return 0


def cmd_keys(a) -> int:
    try:
        groups, sources = keys.load_groups()
    except keys.KeysError as e:
        _p(str(e))
        return 1
    state = keys.State.load()

    if a.html:
        from .. import keyhtml

        out = keyhtml.write(Path(a.html), groups, sources)
        _p(f"저장: {out}")
        _p("브라우저로 열면 탭 전환·검색·정렬이 되고, 조회 횟수는 그 브라우저에 남습니다.")
        return 0

    if a.list:
        _p(f"단축키 {sum(len(g.items) for g in groups)}개\n")
        for g in groups:
            _p(f"  {_pad(g.id, 8)}{_pad(g.name, 14)}{g.desc}  ({len(g.items)}개)")
        _p(f"\n사용자 파일: {keys.user_data_path()}")
        _p(f"조회 기록:   {keys.state_path()}")
        _p("\n출처")
        for name, url in sources.items():
            _p(f"  {name}: {url}")
        return 0

    if a.gaps:
        rows = keys.gaps(groups)
        if not rows:
            _p("확인하지 못한 칸이 없습니다.")
            return 0
        cells = sum(len(m) for _, _, m in rows)
        _p(f"아직 확인하지 못한 칸 {cells}개 (항목 {len(rows)}개)\n")
        for g, item, missing in rows:
            names = ", ".join(g.app_name(a) for a in missing)
            _p(f"  [{_pad(g.name, 8)}] {_pad(_cut(item.name, 24), 26)}{names}")
        _p("\n확인하면 attools/data/shortcuts.json 을 고치거나,")
        _p(f"내 것만 채우려면 {keys.user_data_path()} 에 적으면 됩니다.")
        _p('기본 단축키가 없는 기능이면 "없음" 이라고 적어 두세요.')
        return 0

    if a.set:
        return _keys_set(groups, a.set)

    if a.fill:
        if not sys.stdin.isatty():
            _p("--fill 은 터미널에서만 됩니다. --set 을 쓰세요.")
            return 1
        return _keys_fill(groups)

    if a.edit:
        return _keys_edit(groups)

    try:
        chosen = [keys.find_group(groups, a.group)] if a.group else groups
    except keys.KeysError as e:
        _p(str(e))
        return 1

    query = " ".join(a.query)
    interactive = not query and not a.no_tui and sys.stdin.isatty() and sys.stdout.isatty()
    if interactive:
        try:
            from .. import keytui

            keytui.run(chosen if a.group else groups, state, sort=a.sort,
                       group_index=groups.index(chosen[0]) if a.group else 0)
            return 0
        except ImportError:
            _p("curses 를 쓸 수 없어 표로 출력합니다.\n")

    shown = 0
    matched: list = []
    for g in chosen:
        items = keys.sort_items(g, state, a.sort, keys.search(g, query))
        if not items:
            continue
        matched += [(g, i) for i in items]
        _p(f"[{g.name}] {g.desc}")
        header, body = _keys_rows(g, items[:a.limit], state)
        _grid(header, body, limit=a.width)
        if len(items) > a.limit:
            _p(f"  ... {len(items) - a.limit}개 더 (--limit 로 조절)")
        _p("")
        shown += len(items)

    if not shown:
        _p(f"'{query}' 에 맞는 단축키가 없습니다.")
        return 1

    # 하나만 걸린 검색은 실제로 찾아본 것으로 보고 기록한다
    if query and len(matched) == 1:
        state.hit(matched[0][1].uid)
        state.save()

    _p(f"{shown}개  ·  정렬: {keys.SORTS[a.sort]}"
       f"  ·  {keys.MARK_NONE} 기본 단축키 없음  {keys.MARK_UNKNOWN} 확인 못 함")
    if not query:
        _p("터미널에서 그냥 `at keys` 만 치면 탭으로 넘겨 보는 화면이 열립니다.")
    return 0


def add_commands(sub) -> None:
    """keys 하위 명령을 붙인다."""
    ky = sub.add_parser("keys", help="단축키 찾기 (한글·Word·엑셀·PPT·구글)")
    ky.add_argument("query", nargs="*", metavar="검색어",
                    help="기능 이름이나 키 조합 (예: 붙여넣기, ctrl+shift+v)")
    ky.add_argument("-g", "--group", metavar="그룹", help="doc / slide / calc / os")
    ky.add_argument("-s", "--sort", default="freq", choices=list(keys.SORTS))
    ky.add_argument("--limit", type=int, default=40)
    ky.add_argument("--width", type=int, default=18, metavar="칸")
    ky.add_argument("--html", metavar="경로", help="브라우저용 HTML 로 저장")
    ky.add_argument("-l", "--list", action="store_true", help="그룹·앱 목록과 출처")
    ky.add_argument("--gaps", action="store_true", help="아직 확인하지 못한 칸 보기")
    ky.add_argument("--edit", action="store_true", help="사용자 단축키 파일 틀 만들기")
    ky.add_argument("--set", metavar="지정",
                    help="한 칸 채우기. 예: --set 'doc/표 만들기/word=Alt+N,T' "
                         "(기본 단축키가 없으면 값에 '없음')")
    ky.add_argument("--fill", action="store_true",
                    help="확인 못 한 칸을 하나씩 물어 채운다")
    ky.add_argument("--no-tui", action="store_true", help="화면 대신 표로 출력")
    ky.set_defaults(func=cmd_keys)
