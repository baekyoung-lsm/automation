"""at text - 여러 파일 텍스트 처리."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from .. import files, hangul, report, sheet, text
from .common import _p, _cut, _grid


def _text_targets(a):
    paths = [Path(p) for p in (a.paths or ["."])]
    missing = [p for p in paths if not p.exists()]
    if missing:
        _p(f"경로가 없습니다: {', '.join(str(m) for m in missing)}")
        return None
    return list(text.iter_files(paths, glob=a.glob, hidden=a.hidden))


def _text_report(a, changes, headline: str) -> int:
    if not changes:
        _p("바꿀 것이 없습니다.")
        return 0

    total = sum(c.hits for c in changes)
    _p(f"{headline}  파일 {len(changes)}개, {total}곳\n")

    for c in changes[:a.limit]:
        note = f"  ({c.note})" if c.note else f"  {c.hits}곳"
        _p(f"{c.path}{note}")
        if not a.quiet:
            for line in c.diff(limit=a.context):
                mark = line[:1]
                prefix = "  " if mark not in "+-" else ("  " + mark)
                _p(f"{prefix if mark in '+-' else '   '}{line[1:] if mark in '+-' else line}")
        _p("")
    if len(changes) > a.limit:
        _p(f"... 파일 {len(changes) - a.limit}개 더 (--limit 로 조절)\n")

    if not a.apply:
        _p("실제로 고치려면 --apply 를 붙이세요. (원본은 백업합니다)")
        return 0

    target = getattr(a, "to", None) if getattr(a, "recode", False) else None
    journal = text.apply_changes(changes, target_encoding=target)
    _p(f"파일 {len(changes)}개를 고쳤습니다.")
    _p(f"되돌리기: at text undo {journal}")
    return 0


def cmd_text_lines(a) -> int:
    path = Path(a.file)
    if not path.is_file():
        _p(f"파일이 없습니다: {path}")
        return 1
    try:
        lines = text.read_lines(path, keep_blank=a.blank)
    except (text.TextError, OSError) as e:
        _p(f"읽지 못했습니다: {e}")
        return 1

    if a.compare:
        other = Path(a.compare)
        if not other.is_file():
            _p(f"파일이 없습니다: {other}")
            return 1
        result = text.compare_lines(lines, text.read_lines(other, keep_blank=a.blank),
                                    ignore_case=a.ignore_case)
        _p(f"{path.name} {len(lines):,}줄  vs  {other.name} "
           f"{len(text.read_lines(other, keep_blank=a.blank)):,}줄")
        for label, rows in result.items():
            _p(f"\n{label} {len(rows):,}줄")
            for row in rows[:a.limit]:
                _p(f"  {_cut(row, a.width)}")
            if len(rows) > a.limit:
                _p(f"  ... {len(rows) - a.limit:,}줄 더")
        if a.out:
            picked = result.get(a.pick, [])
            Path(a.out).write_text("\n".join(picked) + "\n", encoding="utf-8")
            _p(f"\n'{a.pick}' {len(picked):,}줄을 저장: {a.out}")
        return 0

    stats = text.line_stats(lines)
    _p(f"{path.name}  {stats.total:,}줄  ·  고유 {stats.unique:,}"
       f"  ·  중복된 값 {stats.duplicated:,}종류({stats.extra:,}줄 초과)"
       + (f"  ·  빈 줄 {stats.blank:,}" if stats.blank else ""))

    if a.count:
        counts = Counter(line for line in lines if line)
        _p(f"\n많이 나온 줄 상위 {min(a.count, len(counts))}개")
        for line, n in counts.most_common(a.count):
            _p(f"  {n:>6,}회  {_cut(line, a.width)}")
        return 0

    result = lines
    if a.unique:
        result = text.unique_lines(result, ignore_case=a.ignore_case)
    if a.sort or a.sort_num:
        result = text.sort_lines(result, descending=a.desc, numeric=a.sort_num)

    if result == lines and not a.out:
        _p("\n--unique, --sort, --count, --compare 중 하나를 주면 처리 결과를 냅니다.")
        return 0

    if a.out:
        Path(a.out).write_text("\n".join(result) + "\n", encoding="utf-8")
        _p(f"\n{len(result):,}줄을 저장: {a.out}")
        return 0

    _p("")
    for line in result[:a.limit]:
        _p(line)
    if len(result) > a.limit:
        _p(f"... {len(result) - a.limit:,}줄 더 (-o 로 저장하세요)")
    return 0


def cmd_text_extract(a) -> int:
    import re as _re

    sources = [Path(f) for f in a.files]
    lines: list[str] = []
    for source in sources:
        if str(source) == "-":
            lines += sys.stdin.read().splitlines()
            continue
        if not source.is_file():
            _p(f"파일이 없습니다: {source}")
            return 1
        try:
            content, _ = text.read_text_any(source)
        except text.TextError as e:
            _p(f"{source}: {e}")
            return 1
        lines += content.splitlines()

    try:
        pattern = _re.compile(a.pattern, _re.I if a.ignore_case else 0)
    except _re.error as e:
        _p(f"정규식이 잘못됐습니다: {e}")
        return 1

    result = text.extract(lines, pattern)
    if not result.rows:
        _p(f"맞는 줄이 없습니다. ({result.total_lines:,}줄 확인)")
        _p("이름 붙인 그룹을 쓰면 열 이름이 됩니다: (?P<시각>\\S+) (?P<레벨>\\w+)")
        return 1

    ratio = result.matched_lines / result.total_lines if result.total_lines else 0
    _p(f"{result.matched_lines:,}줄에서 뽑았습니다 "
       f"(전체 {result.total_lines:,}줄 중 {ratio:.0%})")
    if result.missed and not a.quiet:
        _p(f"  맞지 않은 줄 {result.missed:,}개" +
           (f", 예: {result.samples_missed[0][0]}행 "
            f"{_cut(result.samples_missed[0][1], 50)}" if result.samples_missed else ""))
    _p("")

    _grid(result.headers, result.rows[:a.rows], limit=a.width)
    if len(result.rows) > a.rows:
        _p(f"  ... {len(result.rows) - a.rows:,}행 더")

    if a.out:
        table = sheet.Table(result.headers,
                            [[sheet.parse_value(c) for c in row] for row in result.rows])
        _p(f"\n저장: {sheet.save(table, Path(a.out), sheet_name='추출')}")
    else:
        _p("\n표로 저장하려면 -o 로 csv 나 xlsx 를 지정하세요.")
    return 0


def cmd_text_replace(a) -> int:
    files = _text_targets(a)
    if files is None:
        return 1
    try:
        pattern = text.build_pattern(a.find, regex=a.regex, ignore_case=a.ignore_case,
                                     whole_word=a.word)
        changes = text.plan_replace(files, pattern, a.replace, regex=a.regex)
    except text.TextError as e:
        _p(str(e))
        return 1
    return _text_report(a, changes, f"'{a.find}' -> '{a.replace}'")


def cmd_text_encoding(a) -> int:
    files = _text_targets(a)
    if files is None:
        return 1
    a.recode = True
    changes = text.plan_encoding(files, a.to)
    return _text_report(a, changes, f"인코딩 -> {a.to}")


def cmd_text_eol(a) -> int:
    files = _text_targets(a)
    if files is None:
        return 1
    return _text_report(a, text.plan_eol(files, a.to), f"줄바꿈 -> {a.to.upper()}")


def cmd_text_trim(a) -> int:
    files = _text_targets(a)
    if files is None:
        return 1
    return _text_report(a, text.plan_trim(files, tabs=a.tabs), "공백 정리")


def cmd_text_diff(a) -> int:
    left, right = Path(a.old), Path(a.new)
    for path in (left, right):
        if not path.is_file():
            _p(f"파일이 없습니다: {path}")
            return 1
    try:
        old, _ = text.read_text_any(left)
        new, _ = text.read_text_any(right)
    except text.TextError as e:
        _p(f"읽지 못했습니다: {e}")
        return 1

    unit = {"줄": "line", "문장": "sentence", "문단": "para"}[a.unit]
    report = text.diff_units(old, new, unit=unit, similar=a.similar)
    _p(f"{left} -> {right}  ({a.unit} 단위)")

    shown = report.edits[:a.limit]
    for e in shown:
        where = f"{e.old_no or e.new_no}"
        if e.kind == "수정" and not a.full:
            _p(f"  {where:>5}  수정  {text.word_marks(e.old, e.new)}")
        elif e.kind == "수정":
            _p(f"  {where:>5}  - {e.old}")
            _p(f"  {'':>5}  + {e.new}")
        elif e.kind == "삭제":
            _p(f"  {where:>5}  - {e.old}")
        else:
            _p(f"  {where:>5}  + {e.new}")

    if len(report.edits) > len(shown):
        _p(f"  … {len(report.edits) - len(shown)}건 더 (--limit 로 늘리세요)")

    c = report.counts
    if not report.edits:
        _p(f"\n{a.unit} {report.new_total}개, 다른 곳이 없습니다.")
        return 0
    _p(f"\n같은 곳 {report.same} · 수정 {c['수정']} · 추가 {c['추가']} · "
       f"삭제 {c['삭제']} · 겹치는 정도 {report.ratio:.0%}")
    _p(f"{a.unit} {report.old_total}개 -> {report.new_total}개. "
       "자리를 옮긴 것은 추가와 삭제로 셉니다.")
    return 1


def cmd_text_typo(a) -> int:
    targets = [Path(p) for p in a.paths]
    files_list: list[Path] = []
    for path in targets:
        if path.is_dir():
            files_list += [q for q in text.iter_files([path], glob=a.glob)]
        elif path.is_file():
            files_list.append(path)
        else:
            _p(f"파일이 없습니다: {path}")
            return 1
    if not files_list:
        _p("검사할 파일이 없습니다.")
        return 1

    changes: list[text.Change] = []
    total = 0
    for path in files_list:
        try:
            body, encoding = text.read_text_any(path)
        except text.TextError:
            continue
        found = hangul.find_typos(body)
        if not found:
            continue
        total += len(found)
        _p(f"{path}  {len(found)}건")
        for t in found[:a.limit]:
            note = f"  ({t.note})" if t.note else ""
            _p(f"  {t.line}행 {t.column}칸  {t.wrong} -> {t.right}{note}")
            _p(f"      {_cut(t.context, 72)}")
        if len(found) > a.limit:
            _p(f"  ... {len(found) - a.limit}건 더")
        _p("")

        fixed, _count = hangul.fix_typos(body)
        if fixed != body:
            changes.append(text.Change(path, body, fixed, encoding, hits=len(found)))

    if not total:
        _p(f"파일 {len(files_list)}개, 걸리는 표기가 없습니다.")
        _p(f"확인한 규칙 {len(hangul.TYPO_RULES) + 1}개만 봅니다. 맞춤법 검사기가 아닙니다.")
        return 0

    _p(f"모두 {total}건")
    if not a.apply:
        _p("고치려면 --apply 를 붙이세요. 되돌리기는 at text undo 입니다.")
        return 1

    journal = text.apply_changes(changes)
    _p(f"파일 {len(changes)}개를 고쳤습니다. 되돌리려면 at text undo")
    _p(f"백업: {journal.parent if journal else '-'}")
    return 0


def cmd_text_wrap(a) -> int:
    targets: list[Path] = []
    for name in a.paths:
        path = Path(name)
        if path.is_dir():
            targets += list(text.iter_files([path], glob=a.glob))
        elif path.is_file():
            targets.append(path)
        else:
            _p(f"파일이 없습니다: {path}")
            return 1
    if not targets:
        _p("접을 파일이 없습니다.")
        return 1

    changes: list[text.Change] = []
    for path in targets:
        try:
            body, encoding = text.read_text_any(path)
        except text.TextError as e:
            _p(f"{path}: 건너뜀 ({e})")
            continue
        wrapped = text.wrap_text(body, width=a.width, skip_code=not a.all,
                                 skip_marked=not a.all)
        if wrapped != body:
            changes.append(text.Change(path, body, wrapped, encoding))

    if not changes:
        _p(f"파일 {len(targets)}개, {a.width}칸을 넘는 줄이 없습니다.")
        return 0

    for c in changes:
        _p(f"{c.path}")
        for line in c.diff(limit=a.limit):
            _p(f"  {line}")
        _p("")

    if not a.apply:
        _p(f"파일 {len(changes)}개를 고칩니다. 실제로 쓰려면 --apply 를 붙이세요.")
        if not a.all:
            _p("코드 블록·표·목록·인용은 건드리지 않습니다 (--all 로 포함).")
        return 0

    journal = text.apply_changes(changes)
    _p(f"파일 {len(changes)}개를 접었습니다. 되돌리려면 at text undo")
    _p(f"백업: {journal.parent if journal else '-'}")
    return 0


def cmd_text_undo(a) -> int:
    journal = Path(a.journal) if a.journal else text.latest_journal()
    if journal is None or not journal.is_file():
        _p("되돌릴 저널이 없습니다.")
        return 1
    if not a.journal:
        _p(f"최근 저널을 사용합니다: {journal}")
    restored, errors = text.undo(journal)
    _p(f"{restored}개 파일을 되돌렸습니다.")
    for e in errors:
        _p(f"  건너뜀: {e}")
    return 0 if not errors else 1


def add_commands(sub) -> None:
    """text 하위 명령을 붙인다."""
    tp = sub.add_parser("text", help="여러 파일 텍스트 일괄 처리").add_subparsers(
        dest="cmd", required=True)

    def text_paths(parser):
        parser.add_argument("paths", nargs="*", default=["."], metavar="경로")
        return parser

    def text_common(parser):
        parser.add_argument("-g", "--glob", action="append", metavar="패턴",
                            help="예: -g '*.py' -g '*.md' (기본 전체)")
        parser.add_argument("--hidden", action="store_true")
        parser.add_argument("--apply", action="store_true", help="실제로 고친다")
        parser.add_argument("--limit", type=int, default=20, metavar="개")
        parser.add_argument("--context", type=int, default=8, metavar="줄",
                            help="미리보기 줄 수")
        parser.add_argument("-q", "--quiet", action="store_true", help="차이 미리보기 생략")
        return parser

    rp = tp.add_parser("replace", help="여러 파일에서 찾아 바꾸기")
    rp.add_argument("find", metavar="찾을것")
    rp.add_argument("replace", metavar="바꿀것")
    text_common(text_paths(rp))
    rp.add_argument("-e", "--regex", action="store_true", help="정규식으로")
    rp.add_argument("-i", "--ignore-case", action="store_true")
    rp.add_argument("-w", "--word", action="store_true", help="단어 단위로만")
    rp.set_defaults(func=cmd_text_replace)

    ep = text_common(text_paths(tp.add_parser("encoding", help="cp949 등을 utf-8 로 통일")))
    ep.add_argument("--to", default="utf-8", metavar="인코딩")
    ep.set_defaults(func=cmd_text_encoding)

    lp2 = text_common(text_paths(tp.add_parser("eol", help="줄바꿈을 LF/CRLF 로 통일")))
    lp2.add_argument("--to", default="lf", choices=["lf", "crlf"])
    lp2.set_defaults(func=cmd_text_eol)

    tr = text_common(text_paths(tp.add_parser("trim", help="줄 끝 공백·파일 끝 개행 정리")))
    tr.add_argument("--tabs", type=int, default=0, metavar="칸",
                    help="탭을 이만큼의 공백으로 (기본: 그대로)")
    tr.set_defaults(func=cmd_text_trim)

    ln2 = tp.add_parser("lines", help="줄 단위 정리·대조 (명단 맞춰보기)")
    ln2.add_argument("file")
    ln2.add_argument("--unique", action="store_true", help="중복 줄 제거 (순서 유지)")
    ln2.add_argument("--sort", action="store_true", help="가나다 순 정렬")
    ln2.add_argument("--sort-num", action="store_true", help="줄 앞 숫자로 정렬")
    ln2.add_argument("--desc", action="store_true", help="내림차순")
    ln2.add_argument("--count", type=int, default=0, metavar="개",
                     help="많이 나온 줄 상위 N개")
    ln2.add_argument("--compare", metavar="파일", help="다른 파일과 줄 단위 대조")
    ln2.add_argument("--pick", default="왼쪽만",
                     choices=["공통", "왼쪽만", "오른쪽만"],
                     help="--compare 결과 중 -o 로 저장할 것")
    ln2.add_argument("-i", "--ignore-case", action="store_true")
    ln2.add_argument("--blank", action="store_true", help="빈 줄도 센다")
    ln2.add_argument("-o", "--out", metavar="파일")
    ln2.add_argument("--limit", type=int, default=30)
    ln2.add_argument("--width", type=int, default=80, metavar="칸")
    ln2.set_defaults(func=cmd_text_lines)

    td = tp.add_parser("diff", help="두 글을 줄·문장·문단 단위로 대조")
    td.add_argument("old", metavar="이전")
    td.add_argument("new", metavar="이후")
    td.add_argument("--unit", default="줄", choices=["줄", "문장", "문단"],
                    help="비교 단위 (기본 줄)")
    td.add_argument("--full", action="store_true",
                    help="고친 곳을 이전·이후 두 줄로 모두 보여준다")
    td.add_argument("--similar", type=float, default=0.5, metavar="비율",
                    help="이만큼 닮아야 '수정' 으로 묶는다 (기본 0.5)")
    td.add_argument("--limit", type=int, default=40)
    td.set_defaults(func=cmd_text_diff)

    ty = tp.add_parser("typo", help="흔한 한글 표기 오류 찾기 (며칠, 웬만, 됐…)")
    ty.add_argument("paths", nargs="+", metavar="경로")
    ty.add_argument("-g", "--glob", action="append", metavar="패턴")
    ty.add_argument("--limit", type=int, default=20)
    ty.add_argument("--apply", action="store_true")
    ty.set_defaults(func=cmd_text_typo)

    tw = tp.add_parser("wrap", help="긴 줄을 폭에 맞춰 접기 (한글 두 칸으로 셈)")
    tw.add_argument("paths", nargs="+", metavar="경로")
    tw.add_argument("-w", "--width", type=int, default=80, metavar="칸")
    tw.add_argument("-g", "--glob", action="append", metavar="패턴")
    tw.add_argument("--all", action="store_true",
                    help="코드 블록·표·목록도 접는다")
    tw.add_argument("--limit", type=int, default=12, metavar="줄")
    tw.add_argument("--apply", action="store_true")
    tw.set_defaults(func=cmd_text_wrap)

    ex2 = tp.add_parser("extract", help="정규식으로 뽑아 표 만들기")
    ex2.add_argument("pattern", metavar="정규식",
                     help="이름 붙인 그룹이 열이 된다: '(?P<시각>\\S+) (?P<레벨>\\w+)'")
    ex2.add_argument("files", nargs="+", metavar="파일", help="'-' 이면 표준 입력")
    ex2.add_argument("-i", "--ignore-case", action="store_true")
    ex2.add_argument("-o", "--out", metavar="파일", help="csv 또는 xlsx")
    ex2.add_argument("--rows", type=int, default=15, metavar="개")
    ex2.add_argument("--width", type=int, default=22, metavar="칸")
    ex2.add_argument("-q", "--quiet", action="store_true", help="맞지 않은 줄 안내 생략")
    ex2.set_defaults(func=cmd_text_extract)

    tu = tp.add_parser("undo", help="text 명령 되돌리기")
    tu.add_argument("journal", nargs="?")
    tu.set_defaults(func=cmd_text_undo)
