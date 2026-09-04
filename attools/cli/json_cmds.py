"""at json - JSON 훑기와 비교."""

from __future__ import annotations

import sys
from pathlib import Path

from .. import files, text
from ..code import jsonkit
from .common import _p, _grid


def _json_load(a, source):
    try:
        return jsonkit.load(source)
    except jsonkit.JsonError as e:
        _p(str(e))
        return None


def cmd_json_get(a) -> int:
    data = _json_load(a, a.file)
    if data is None:
        return 1
    try:
        value = jsonkit.get_path(data, a.path)
    except jsonkit.JsonError as e:
        _p(str(e))
        return 1

    import json as _json

    if a.raw and isinstance(value, str):
        sys.stdout.write(value + "\n")
    elif isinstance(value, (dict, list)):
        _p(_json.dumps(value, ensure_ascii=False, indent=2))
    else:
        _p(_json.dumps(value, ensure_ascii=False))
    return 0


def cmd_json_set(a) -> int:
    import json as _json

    path, sep, raw_value = a.assignment.partition("=")
    if not sep:
        _p("'경로=값' 형태로 적으세요. 예: version=\"2.0.0\"  또는  config.port=8080")
        return 1

    source = Path(a.file)
    data = _json_load(a, a.file)
    if data is None:
        return 1

    value = raw_value if a.string else jsonkit.parse_value(raw_value)
    try:
        before, after = jsonkit.set_path(data, path.strip(), value, create=a.create)
    except jsonkit.JsonError as e:
        _p(str(e))
        return 1

    _p(f"{path.strip()}")
    _p(f"  이전  {jsonkit.preview(before, 80)}")
    _p(f"  이후  {jsonkit.preview(after, 80)}")

    if before == after:
        _p("\n값이 같아 바꿀 것이 없습니다.")
        return 0

    text_out = _json.dumps(data, ensure_ascii=False,
                           indent=None if a.compact else a.indent) + "\n"
    if not a.apply:
        _p("\n실제로 쓰려면 --apply 를 붙이세요. (원본은 백업합니다)")
        _p("파일 전체를 다시 쓰므로 들여쓰기와 키 순서가 통일됩니다. "
           "--indent 로 칸 수를 맞출 수 있습니다.")
        return 0

    if a.out:
        target = Path(a.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text_out, encoding="utf-8")
        _p(f"\n저장: {target}")
        return 0

    original, encoding = text.read_text_any(source)
    change = text.Change(source, original, text_out, encoding, hits=1,
                         note=f"{path.strip()} 변경")
    journal = text.apply_changes([change])
    _p(f"\n{source} 를 고쳤습니다.")
    _p(f"되돌리기: at text undo {journal}")
    return 0


def cmd_json_show(a) -> int:
    data = _json_load(a, a.file)
    if data is None:
        return 1
    import json as _json

    if a.compact:
        _p(_json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=a.sort))
    else:
        _p(_json.dumps(data, ensure_ascii=False, indent=2, sort_keys=a.sort))
    return 0


def cmd_json_schema(a) -> int:
    data = _json_load(a, a.file)
    if data is None:
        return 1

    fields = jsonkit.schema(data)
    if not fields:
        _p(f"단일 값입니다: {jsonkit.type_name(data)}")
        return 0

    _grid(["경로", "타입", "있음", "예시"],
          [[f.path, "|".join(sorted(f.types)),
            "선택" if f.optional else "필수",
            ", ".join(jsonkit.preview(s, 20) for s in f.samples)]
           for f in fields[:a.limit]], limit=a.width)
    if len(fields) > a.limit:
        _p(f"  ... {len(fields) - a.limit}개 더")
    optional = sum(1 for f in fields if f.optional)
    _p(f"\n키 {len(fields)}개  ·  가끔 없는 키 {optional}개")
    return 0


def cmd_json_diff(a) -> int:
    before, after = _json_load(a, a.before), _json_load(a, a.after)
    if before is None or after is None:
        return 1

    d = jsonkit.diff(before, after, key=a.key)
    if d.empty:
        _p("차이가 없습니다.")
        return 0

    if a.breaking:
        rows = d.breaking
        if not rows:
            _p("깨질 만한 변화는 없습니다. (사라진 키, 타입 변경 없음)")
            return 0
        _p(f"깨질 만한 변화 {len(rows)}건")
        for path, what in rows:
            _p(f"  {path}  {jsonkit.preview(what)}")
        return 1

    def section(title: str, rows: list[str]) -> None:
        if rows:
            _p(f"{title} {len(rows)}건")
            for r in rows[:a.limit]:
                _p(f"  {r}")
            if len(rows) > a.limit:
                _p(f"  ... {len(rows) - a.limit}건 더")
            _p("")

    section("사라진 키", [f"- {p}  {jsonkit.preview(v)}" for p, v in d.removed])
    section("타입 바뀜", [f"! {p}  {x} -> {y}" for p, x, y in d.type_changed])
    section("새 키", [f"+ {p}  {jsonkit.preview(v)}" for p, v in d.added])
    if not a.no_values:
        section("값 바뀜",
                [f"  {p}  {jsonkit.preview(x, 28)} -> {jsonkit.preview(y, 28)}"
                 for p, x, y in d.value_changed])

    if d.breaking:
        _p(f"이 중 {len(d.breaking)}건은 쓰는 쪽이 깨질 수 있습니다 (사라진 키·타입 변경).")
    return 1


def cmd_json_merge(a) -> int:
    import json as _json

    values = []
    for source in a.files:
        data = _json_load(a, source)
        if data is None:
            return 1
        values.append(data)

    try:
        merged, notes = jsonkit.merge_all(values, list_mode=a.list)
    except jsonkit.JsonError as e:
        _p(str(e))
        return 1

    overwritten = [n for n in notes if n.kind == "덮어씀"]
    added = [n for n in notes if n.kind == "추가"]
    joined = [n for n in notes if n.kind == "이어붙임"]

    _p(f"파일 {len(values)}개를 겹쳤습니다. 뒤에 오는 파일이 이깁니다.")
    _p(f"  덮어쓴 값 {len(overwritten)} · 새로 생긴 키 {len(added)}"
       + (f" · 이어붙인 배열 {len(joined)}" if joined else ""))
    for n in overwritten[:a.limit]:
        _p(f"  덮어씀  {n.path}: {jsonkit.preview(n.before)} -> "
           f"{jsonkit.preview(n.after)}")
    for n in added[:a.limit]:
        _p(f"  추가    {n.path}: {jsonkit.preview(n.after)}")
    if len(overwritten) + len(added) > a.limit * 2:
        _p("  ... 더 있습니다 (--limit 로 늘리세요)")

    body = _json.dumps(merged, ensure_ascii=False,
                       indent=None if a.compact else 2, sort_keys=a.sort)
    if a.out:
        out = Path(a.out)
        if out.exists() and not a.overwrite:
            _p(f"\n이미 있는 파일입니다: {out} (--overwrite 로 덮어씁니다)")
            return 1
        out.write_text(body + "\n", encoding="utf-8")
        _p(f"\n저장: {out}")
    else:
        _p("")
        _p(body)
    return 0


def cmd_json_flat(a) -> int:
    data = _json_load(a, a.file)
    if data is None:
        return 1

    rows = jsonkit.flatten(data)
    if a.grep:
        import re as _re

        try:
            pattern = _re.compile(a.grep, _re.I)
        except _re.error as e:
            _p(f"정규식이 잘못됐습니다: {e}")
            return 1
        rows = [(p, v) for p, v in rows if pattern.search(p) or pattern.search(str(v))]

    if not rows:
        _p("맞는 항목이 없습니다.")
        return 1
    for path, value in rows[:a.limit]:
        _p(f"{path}\t{jsonkit.preview(value, a.width)}")
    if len(rows) > a.limit:
        _p(f"... {len(rows) - a.limit}개 더")
    return 0


def add_commands(sub) -> None:
    """json 하위 명령을 붙인다."""
    jp = sub.add_parser("json", help="JSON 훑기·비교").add_subparsers(dest="cmd", required=True)

    js = jp.add_parser("show", help="한글 안 깨지게 예쁘게 출력")
    js.add_argument("file", nargs="?", default="-")
    js.add_argument("--sort", action="store_true", help="키 이름 순으로 정렬")
    js.add_argument("--compact", action="store_true", help="한 줄로")
    js.set_defaults(func=cmd_json_show)

    jc = jp.add_parser("schema", help="키 경로·타입·선택 여부 요약")
    jc.add_argument("file", nargs="?", default="-")
    jc.add_argument("--limit", type=int, default=60)
    jc.add_argument("--width", type=int, default=34, metavar="칸")
    jc.set_defaults(func=cmd_json_schema)

    jd = jp.add_parser("diff", help="두 JSON 을 경로 단위로 비교")
    jd.add_argument("before")
    jd.add_argument("after")
    jd.add_argument("--key", metavar="필드",
                    help="객체 배열을 이 필드 값으로 짝지어 비교 (예: --key id)")
    jd.add_argument("--breaking", action="store_true",
                    help="사라진 키와 타입 변경만 (CI 용, 있으면 exit 1)")
    jd.add_argument("--no-values", action="store_true", help="값만 바뀐 것은 생략")
    jd.add_argument("--limit", type=int, default=25)
    jd.set_defaults(func=cmd_json_diff)

    jg = jp.add_parser("get", help="경로가 가리키는 값 하나 꺼내기")
    jg.add_argument("file")
    jg.add_argument("path", metavar="경로", help="예: users[0].name")
    jg.add_argument("--raw", action="store_true", help="문자열이면 따옴표 없이")
    jg.set_defaults(func=cmd_json_get)

    jst = jp.add_parser("set", help="경로의 값 바꾸기 (설정 파일 편집)")
    jst.add_argument("file")
    jst.add_argument("assignment", metavar="경로=값",
                     help='예: version="2.0.0"  ·  config.port=8080  ·  flags[0]=true')
    jst.add_argument("--string", action="store_true", help="값을 무조건 문자열로")
    jst.add_argument("--create", action="store_true", help="없는 키는 만든다")
    jst.add_argument("--indent", type=int, default=2, metavar="칸")
    jst.add_argument("--compact", action="store_true", help="한 줄로 저장")
    jst.add_argument("-o", "--out", metavar="파일", help="원본 대신 여기에 저장")
    jst.add_argument("--apply", action="store_true")
    jst.set_defaults(func=cmd_json_set)

    jf = jp.add_parser("flat", help="경로=값 한 줄씩 (grep 하기 좋게)")
    jf.add_argument("file", nargs="?", default="-")
    jf.add_argument("--grep", metavar="정규식")
    jf.add_argument("--limit", type=int, default=200)
    jf.add_argument("--width", type=int, default=60, metavar="칸")
    jf.set_defaults(func=cmd_json_flat)

    jm = jp.add_parser("merge", help="설정 JSON 겹치기 (뒤엣것이 이긴다)")
    jm.add_argument("files", nargs="+", metavar="파일")
    jm.add_argument("--list", default="replace", choices=["replace", "append"],
                    help="배열을 통째로 바꿀지 이어붙일지 (기본 replace)")
    jm.add_argument("-o", "--out", metavar="파일")
    jm.add_argument("--overwrite", action="store_true")
    jm.add_argument("--sort", action="store_true", help="키 이름 순으로 정렬")
    jm.add_argument("--compact", action="store_true", help="한 줄로")
    jm.add_argument("--limit", type=int, default=15)
    jm.set_defaults(func=cmd_json_merge)
