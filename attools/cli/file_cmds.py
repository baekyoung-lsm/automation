"""at file - 파일 분류·개명·중복·감시·압축."""

from __future__ import annotations

from pathlib import Path

from .. import devkit, files
from ..hangul import is_decomposed
from .common import _pad, _p, _confirm, _grid


DRY = "[미리보기]"


def cmd_file_organize(a) -> int:
    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    moves = files.plan_organize(
        root, by=a.by, recursive=a.recursive, include_hidden=a.hidden,
        min_age_days=a.min_age, fixname=a.fixname)

    if not moves:
        _p("옮길 파일이 없습니다.")
        return 0

    buckets: dict[str, int] = {}
    for mv in moves:
        rel = str(Path(mv.dst).parent.relative_to(root.resolve()))
        buckets[rel] = buckets.get(rel, 0) + 1

    prefix = "" if a.apply else DRY + " "
    for bucket in sorted(buckets):
        _p(f"{prefix}{bucket}/  <- {buckets[bucket]}개")
    if a.verbose:
        for mv in moves:
            _p(f"  {Path(mv.src).name}  ->  {Path(mv.dst).relative_to(root.resolve())}")

    if not a.apply:
        _p(f"\n총 {len(moves)}개. 실제로 옮기려면 --apply 를 붙이세요.")
        return 0

    journal = files.apply_moves(moves)
    _p(f"\n{len(moves)}개를 옮겼습니다.")
    _p(f"되돌리기: at file undo {journal}")
    return 0


def cmd_file_fixname(a) -> int:
    root = Path(a.dir)
    moves = files.plan_fixname(root, recursive=a.recursive,
                               include_hidden=a.hidden, space=a.space)
    if not moves:
        _p("고칠 파일명이 없습니다.")
        return 0

    for mv in moves:
        src, dst = Path(mv.src), Path(mv.dst)
        tag = " (자모 분리)" if is_decomposed(src.name) else ""
        _p(f"{src.name}{tag}\n  -> {dst.name}")

    if not a.apply:
        _p(f"\n총 {len(moves)}개. 실제로 바꾸려면 --apply 를 붙이세요.")
        return 0

    journal = files.apply_moves(moves)
    _p(f"\n{len(moves)}개 이름을 바꿨습니다.")
    _p(f"되돌리기: at file undo {journal}")
    return 0


def cmd_file_dupes(a) -> int:
    groups = files.find_duplicates(Path(a.dir), recursive=not a.no_recursive,
                                   include_hidden=a.hidden, min_size=a.min_size)
    if not groups:
        _p("중복 파일이 없습니다.")
        return 0

    wasted = 0
    for i, group in enumerate(groups, 1):
        size = group[0].stat().st_size
        wasted += size * (len(group) - 1)
        _p(f"[{i}] {size / 1024:,.1f} KiB x {len(group)}개")
        for j, p in enumerate(group):
            mark = "남김" if j == 0 else "중복"
            _p(f"    {mark}  {p}")

    _p(f"\n중복 {len(groups)}그룹, 회수 가능 용량 {wasted / 1024 / 1024:,.1f} MiB")
    if a.script:
        _p("\n# 확인 후 실행할 삭제 스크립트")
        for group in groups:
            for p in group[1:]:
                _p(f'rm -i "{p}"')
    else:
        _p("삭제 명령을 만들려면 --script 를 붙이세요. (직접 지우지 않습니다)")
    return 0


def cmd_file_undo(a) -> int:
    journal = Path(a.journal) if a.journal else None
    if journal is None:
        candidates = sorted(files.journal_dir().glob("*.jsonl")) if files.journal_dir().is_dir() else []
        if not candidates:
            _p("되돌릴 저널이 없습니다.")
            return 1
        journal = candidates[-1]
        _p(f"최근 저널을 사용합니다: {journal}")

    restored, errors = files.undo(journal)
    _p(f"{restored}개를 되돌렸습니다.")
    for e in errors:
        _p(f"  건너뜀: {e}")
    return 0 if not errors else 1


def cmd_file_rename(a) -> int:
    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    template = a.template
    if not template:
        # 빠른 옵션들을 조합해 템플릿을 만든다
        parts = []
        if a.date:
            parts.append("{date}")
        if a.seq:
            parts.append(f"{{seq:0{a.digits}d}}")
        parts.append("{stem}")
        template = (a.prefix or "") + a.join.join(parts) + (a.suffix or "") + "{ext}"

    replacements = []
    for spec in a.replace or []:
        old, sep, new_text = spec.partition("=")
        if not sep:
            _p(f"'옛것=새것' 형태로 적으세요: {spec}")
            return 1
        replacements.append((old, new_text))

    try:
        moves = files.plan_rename(
            root, template, glob=a.glob, recursive=a.recursive,
            include_hidden=a.hidden, sort=a.sort, start=a.start,
            date_format=a.date_format, replacements=replacements,
            regex=a.regex, case=a.case)
    except ValueError as e:
        _p(str(e))
        return 1

    if not moves:
        _p("바꿀 이름이 없습니다.")
        return 0

    _p(f"템플릿: {template}\n")
    for mv in moves[:a.limit]:
        _p(f"  {Path(mv.src).name}")
        _p(f"    -> {Path(mv.dst).name}")
    if len(moves) > a.limit:
        _p(f"  ... {len(moves) - a.limit}개 더")

    if not a.apply:
        _p(f"\n총 {len(moves)}개. 실제로 바꾸려면 --apply 를 붙이세요.")
        return 0

    journal = files.apply_moves(moves)
    _p(f"\n{len(moves)}개 이름을 바꿨습니다.")
    _p(f"되돌리기: at file undo {journal}")
    return 0


def cmd_file_archive(a) -> int:
    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    targets = files.plan_archive(root, glob=a.glob, older_days=a.older,
                                 include_hidden=a.hidden, recursive=not a.no_recursive)
    if not targets:
        _p("보관할 파일이 없습니다.")
        return 0

    total = sum(p.stat().st_size for p in targets)
    _p(f"파일 {len(targets)}개  ·  {files.human_size(total)}")
    for p in targets[:a.limit]:
        _p(f"  {p.relative_to(root)}  {files.human_size(p.stat().st_size)}")
    if len(targets) > a.limit:
        _p(f"  ... {len(targets) - a.limit}개 더")

    default = root / f"{root.name}-{devkit.datetime.now():%Y%m%d}.zip"
    archive = Path(a.out) if a.out else default
    _p(f"\n보관 파일: {archive}")

    if not a.apply:
        _p("실제로 만들려면 --apply 를 붙이세요."
           + ("  (--remove 를 함께 주면 원본을 지웁니다)" if not a.remove else ""))
        return 0

    if a.remove and not a.yes and not _confirm(
            f"압축이 온전한지 확인한 뒤 원본 {len(targets)}개를 지웁니다. 계속할까요?"):
        _p("취소했습니다. 압축만 하려면 --remove 없이 실행하세요.")
        return 1

    try:
        result = files.make_archive(root, targets, archive, remove=a.remove)
    except RuntimeError as e:
        _p(str(e))
        return 1

    _p(f"\n{len(result.stored)}개를 담았습니다."
       f"  {files.human_size(result.raw_size)} -> {files.human_size(result.packed_size)}"
       f" ({result.ratio:.0%})")
    if result.removed:
        _p(f"원본 {len(result.removed)}개를 지웠습니다.")
    for message in result.failed:
        _p(f"  문제: {message}")
    if result.failed and a.remove:
        _p("확인에 실패해서 원본은 그대로 뒀습니다.")
        return 1
    return 0


def cmd_file_diff(a) -> int:
    left, right = Path(a.left), Path(a.right)
    for path in (left, right):
        if not path.is_dir():
            _p(f"디렉터리가 아닙니다: {path}")
            return 1

    d = files.diff_dirs(left, right, include_hidden=a.hidden, glob=a.glob,
                        quick=a.quick)
    _p(f"{left}  vs  {right}")
    _p(f"  같음 {d.same:,}  ·  왼쪽만 {len(d.only_left):,}  ·  "
       f"오른쪽만 {len(d.only_right):,}  ·  다름 {len(d.changed):,}\n")

    if d.empty:
        _p("차이가 없습니다.")
        return 0

    def section(title: str, rows: list[str]) -> None:
        if not rows:
            return
        _p(f"{title} {len(rows)}개")
        for r in rows[:a.limit]:
            _p(f"  {r}")
        if len(rows) > a.limit:
            _p(f"  ... {len(rows) - a.limit}개 더")
        _p("")

    section("왼쪽에만", [f"- {n}" for n in d.only_left])
    section("오른쪽에만", [f"+ {n}" for n in d.only_right])
    section("내용이 다름",
            [f"! {n}  {files.human_size(x)} -> {files.human_size(y)}"
             for n, x, y in d.changed])

    if a.quick:
        _p("--quick 이라 크기만 비교했습니다. 크기가 같고 내용만 다른 건 못 잡습니다.")
    return 1


def cmd_file_tree(a) -> int:
    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    tree = files.build_tree(root, depth=a.depth, use_git=not a.no_git,
                            glob=a.glob, with_lines=a.lines or a.summary)
    if not tree.children:
        _p("보여줄 파일이 없습니다.")
        return 0

    rows = files.render_tree(tree, show_lines=a.lines, show_size=a.size)
    for row in rows[:a.limit]:
        _p(row)
    if len(rows) > a.limit:
        _p(f"... {len(rows) - a.limit}줄 더 (--limit 로 조절)")

    _p(f"\n파일 {tree.file_count:,}개  ·  {files.human_size(tree.total_size)}"
       + (f"  ·  {tree.total_lines:,}줄" if a.lines or a.summary else ""))
    if files.tracked_paths(root) is None and not a.no_git:
        _p("git 저장소가 아니라 숨김·빌드 디렉터리는 이름으로 걸렀습니다.")

    if a.summary:
        _p("")
        _grid(["확장자", "파일", "줄"],
              [[ext, f"{n:,}", f"{lines:,}" if lines else "-"]
               for ext, n, lines in files.language_summary(tree)[:a.limit]], limit=16)
    return 0


def cmd_file_recent(a) -> int:
    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    found = files.recent_files(root, days=a.days, glob=a.glob,
                               include_hidden=a.hidden, use_git=a.git)
    if not found:
        _p(f"{a.days:g}일 안에 바뀐 파일이 없습니다.")
        return 0

    total = sum(size for _, _, size in found)
    _p(f"{a.days:g}일 안에 바뀐 파일 {len(found):,}개  ·  {files.human_size(total)}\n")

    shown = found[:a.limit]
    current = ""
    for path, stamp, size in shown:
        label = files.day_label(stamp)
        if label != current:
            current = label
            _p(f"[{label}]")
        when = devkit.datetime.fromtimestamp(stamp)
        _p(f"  {when:%H:%M}  {_pad(files.human_size(size), 11)}"
           f"{path.relative_to(root)}")
    if len(found) > a.limit:
        _p(f"\n... {len(found) - a.limit:,}개 더 (--limit 로 조절)")
    return 0


def cmd_file_unzip(a) -> int:
    import zipfile

    archive = Path(a.file)
    if not archive.is_file():
        _p(f"파일이 없습니다: {archive}")
        return 1

    try:
        entries = files.list_zip(archive)
    except zipfile.BadZipFile:
        _p(f"zip 파일이 아니거나 깨졌습니다: {archive}")
        return 1

    dest = Path(a.out) if a.out else archive.parent / archive.stem
    fixed = [e for e in entries if e.fixed]
    unsafe = [e for e in entries if e.unsafe]
    body = [e for e in entries if not e.is_dir]

    _p(f"{archive}  ->  {dest}/")
    _p(f"  항목 {len(body)}개, 이름을 고칠 것 {len(fixed)}개")
    for e in entries[:a.limit]:
        if e.is_dir:
            continue
        mark = "  <- " + e.raw if e.fixed and a.raw else ""
        warn = f"  [건너뜀: {e.unsafe}]" if e.unsafe else ""
        _p(f"  {e.name}  {files.human_size(e.size)}{mark}{warn}")
    if len(body) > a.limit:
        _p(f"  ... {len(body) - a.limit}개 더")

    if unsafe:
        _p(f"\n압축 바깥을 가리키는 항목 {len(unsafe)}개는 풀지 않습니다.")

    if not a.apply:
        _p("\n실제로 풀려면 --apply 를 붙이세요.")
        if not fixed:
            _p("이름이 깨진 항목은 없습니다. 그냥 unzip 을 써도 됩니다.")
        return 0

    written, skipped = files.extract_zip(archive, dest, entries,
                                         overwrite=a.overwrite)
    _p(f"\n{len(written)}개를 풀었습니다: {dest}/")
    for reason in skipped[:a.limit]:
        _p(f"  건너뜀  {reason}")
    if len(skipped) > a.limit:
        _p(f"  ... {len(skipped) - a.limit}개 더")
    if skipped and not a.overwrite and any("이미 있음" in r for r in skipped):
        _p("이미 있는 파일은 덮어쓰지 않았습니다 (--overwrite 로 덮어씁니다).")
    return 0


def cmd_file_hash(a) -> int:
    root = Path(a.dir)

    if a.check:
        sums = Path(a.check)
        if not sums.is_file():
            _p(f"파일이 없습니다: {sums}")
            return 1
        base = root if root.is_dir() and str(root) != "." else sums.parent
        try:
            result = files.check_sums(
                base, sums.read_text(encoding="utf-8").splitlines(), a.algorithm)
        except ValueError as e:
            _p(str(e))
            return 1

        _p(f"{sums.name}  기준 {base}")
        _p(f"  같음 {len(result.ok):,}  ·  달라짐 {len(result.changed):,}"
           f"  ·  없음 {len(result.missing):,}"
           + (f"  ·  형식 이상 {len(result.malformed):,}" if result.malformed else ""))
        for name in result.changed[:a.limit]:
            _p(f"  달라짐  {name}")
        for name in result.missing[:a.limit]:
            _p(f"  없음    {name}")
        for number, line in result.malformed[:a.limit]:
            _p(f"  {number}행 형식 이상  {line}")

        if result.failed:
            _p("\n하나라도 다르면 배포본이 바뀐 것입니다.")
            return 1
        _p("\n모두 같습니다.")
        return 0

    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    targets = sorted(files.iter_targets(root, recursive=not a.no_recursive,
                                        include_hidden=a.hidden))
    if a.glob:
        from fnmatch import fnmatch

        targets = [p for p in targets
                   if any(fnmatch(p.name, g) for g in a.glob)]
    if not targets:
        _p("대상 파일이 없습니다.")
        return 1

    try:
        lines = files.write_sums(root, targets, a.algorithm)
    except ValueError as e:
        _p(str(e))
        return 1

    if a.out:
        target = Path(a.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _p(f"{len(lines):,}개 파일의 {a.algorithm} 를 적었습니다: {target}")
        _p(f"검증: at file hash {root} --check {target}")
        return 0

    for line in lines[:a.limit]:
        _p(line)
    if len(lines) > a.limit:
        _p(f"... {len(lines) - a.limit:,}개 더")
    _p(f"\n{len(lines):,}개.  -o 로 저장하면 나중에 --check 로 검증합니다.")
    return 0


def cmd_file_watch(a) -> int:
    import subprocess
    import time

    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1
    if not a.command:
        _p("실행할 명령을 -- 뒤에 적으세요. 예: at file watch src -- pytest")
        return 1

    patterns = a.pattern or ["*"]
    _p(f"{root} 감시 중 ({', '.join(patterns)}, {a.interval}초 간격). Ctrl-C 로 종료.")
    before = files.snapshot_mtimes(root, patterns)
    runs = 0

    if a.now:
        runs += 1
        _p(f"\n[{time.strftime('%H:%M:%S')}] 첫 실행")
        subprocess.run(a.command)

    while True:
        time.sleep(a.interval)
        after = files.snapshot_mtimes(root, patterns)
        changed = files.diff_mtimes(before, after)
        if not changed:
            continue
        before = after
        runs += 1
        _p(f"\n[{time.strftime('%H:%M:%S')}] 변경 {len(changed)}건 "
           f"({', '.join(Path(c).name for c in changed[:3])}{'…' if len(changed) > 3 else ''})"
           f" -> 실행 #{runs}")
        result = subprocess.run(a.command)
        _p(f"[종료 코드 {result.returncode}]")


def cmd_file_big(a) -> int:
    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    dirs, biggest, grand = files.dir_sizes(root, depth=a.depth)
    _p(f"전체 {files.human_size(grand)}\n")
    _p(f"용량 큰 항목 (깊이 {a.depth})")
    for path, size in dirs[:a.top]:
        share = size / grand * 100 if grand else 0
        bar = "#" * int(share / 4)
        _p(f"  {files.human_size(size):>11}  {share:5.1f}%  {bar:<25} {path.name}")

    _p(f"\n큰 파일 {a.top}개")
    for path, size in biggest[:a.top]:
        _p(f"  {files.human_size(size):>11}  {path.relative_to(root)}")
    return 0


def add_commands(sub) -> None:
    """file 하위 명령을 붙인다."""
    fp = sub.add_parser("file", help="파일 정리").add_subparsers(dest="cmd", required=True)

    o = fp.add_parser("organize", help="확장자/날짜별로 분류해 옮기기")
    o.add_argument("dir")
    o.add_argument("--by", default="ext", choices=["ext", "date", "ext-date", "date-ext"])
    o.add_argument("--apply", action="store_true", help="실제로 옮긴다 (기본은 미리보기)")
    o.add_argument("-r", "--recursive", action="store_true")
    o.add_argument("--hidden", action="store_true", help="숨김 파일도 포함")
    o.add_argument("--min-age", type=float, default=0.0, metavar="일",
                   help="이만큼 오래된 파일만 (예: 7)")
    o.add_argument("--fixname", action="store_true", help="옮기면서 파일명도 정리")
    o.add_argument("-v", "--verbose", action="store_true")
    o.set_defaults(func=cmd_file_organize)

    n = fp.add_parser("fixname", help="한글 자모 분리·특수문자 파일명 정리")
    n.add_argument("dir")
    n.add_argument("--apply", action="store_true")
    n.add_argument("-r", "--recursive", action="store_true")
    n.add_argument("--hidden", action="store_true")
    n.add_argument("--space", default="keep", choices=["keep", "underscore"])
    n.set_defaults(func=cmd_file_fixname)

    rn = fp.add_parser("rename", help="규칙에 맞춰 이름 일괄 변경")
    rn.add_argument("dir")
    rn.add_argument("-t", "--template", metavar="틀",
                    help="예: '{date}-{seq:03d}{ext}'  "
                         "쓸 수 있는 항목: {seq} {date} {time} {stem} {ext} {name} "
                         "{parent} {size}")
    rn.add_argument("--date", action="store_true", help="수정 날짜를 앞에 붙인다")
    rn.add_argument("--seq", action="store_true", help="번호를 붙인다")
    rn.add_argument("--digits", type=int, default=3, metavar="자리")
    rn.add_argument("--start", type=int, default=1, metavar="번호")
    rn.add_argument("--join", default="_", metavar="글자", help="항목 사이 구분자")
    rn.add_argument("--prefix", metavar="문자열")
    rn.add_argument("--suffix", metavar="문자열", help="확장자 앞에 붙인다")
    rn.add_argument("--replace", action="append", metavar="옛것=새것")
    rn.add_argument("-e", "--regex", action="store_true", help="--replace 를 정규식으로")
    rn.add_argument("--case", default="keep", choices=["keep", "lower", "upper"])
    rn.add_argument("--date-format", default="%Y%m%d", metavar="형식")
    rn.add_argument("--sort", default="name", choices=["name", "date", "size"],
                    help="번호를 매기는 순서")
    rn.add_argument("-g", "--glob", action="append", metavar="패턴")
    rn.add_argument("-r", "--recursive", action="store_true")
    rn.add_argument("--hidden", action="store_true")
    rn.add_argument("--limit", type=int, default=20)
    rn.add_argument("--apply", action="store_true")
    rn.set_defaults(func=cmd_file_rename)

    d = fp.add_parser("dupes", help="내용이 같은 중복 파일 찾기")
    d.add_argument("dir")
    d.add_argument("--min-size", type=int, default=1024, metavar="바이트")
    d.add_argument("--no-recursive", action="store_true")
    d.add_argument("--hidden", action="store_true")
    d.add_argument("--script", action="store_true", help="삭제 명령을 출력만 한다")
    d.set_defaults(func=cmd_file_dupes)

    w = fp.add_parser("watch", help="파일이 바뀌면 명령을 실행")
    w.add_argument("dir")
    w.add_argument("-p", "--pattern", action="append", metavar="글롭",
                   help="예: -p '*.py' -p '*.html' (기본 전체)")
    w.add_argument("-i", "--interval", type=float, default=1.0, metavar="초")
    w.add_argument("--now", action="store_true", help="시작하자마자 한 번 실행")
    w.epilog = "실행할 명령은 -- 뒤에 적는다.  예: at file watch src -p '*.py' -- pytest -q"
    w.set_defaults(func=cmd_file_watch, command=[])

    tr2 = fp.add_parser("tree", help="프로젝트 구조 - .gitignore 를 그대로 따른다")
    tr2.add_argument("dir", nargs="?", default=".")
    tr2.add_argument("-d", "--depth", type=int, default=0, metavar="단계",
                     help="이보다 깊은 곳은 접는다 (0이면 전부)")
    tr2.add_argument("-g", "--glob", action="append", metavar="패턴")
    tr2.add_argument("--lines", action="store_true", help="코드 파일의 줄 수도")
    tr2.add_argument("--size", action="store_true", help="파일 크기도")
    tr2.add_argument("--summary", action="store_true", help="확장자별 집계도")
    tr2.add_argument("--no-git", action="store_true",
                     help="git 에 묻지 않고 이름으로만 거른다")
    tr2.add_argument("--limit", type=int, default=200)
    tr2.set_defaults(func=cmd_file_tree)

    rc = fp.add_parser("recent", help="최근에 손댄 파일 (오늘·어제별로)")
    rc.add_argument("dir", nargs="?", default=".")
    rc.add_argument("-d", "--days", type=float, default=1.0, metavar="일")
    rc.add_argument("-g", "--glob", action="append", metavar="패턴")
    rc.add_argument("--hidden", action="store_true")
    rc.add_argument("--git", action="store_true",
                    help="git 이 추적하는 파일만 (.gitignore 존중)")
    rc.add_argument("--limit", type=int, default=40)
    rc.set_defaults(func=cmd_file_recent)

    b = fp.add_parser("big", help="용량 차지하는 디렉터리/파일 찾기")
    b.add_argument("dir", nargs="?", default=".")
    b.add_argument("--depth", type=int, default=1)
    b.add_argument("--top", type=int, default=15)
    b.set_defaults(func=cmd_file_big)

    ar = fp.add_parser("archive", help="오래된 파일을 zip 으로 보관")
    ar.add_argument("dir")
    ar.add_argument("-o", "--out", metavar="파일", help="기본: <디렉터리이름>-<날짜>.zip")
    ar.add_argument("--older", type=float, default=0.0, metavar="일",
                    help="이만큼 오래된 것만 (예: 365)")
    ar.add_argument("-g", "--glob", action="append", metavar="패턴")
    ar.add_argument("--hidden", action="store_true")
    ar.add_argument("--no-recursive", action="store_true")
    ar.add_argument("--remove", action="store_true",
                    help="압축이 온전한지 확인한 뒤 원본을 지운다")
    ar.add_argument("-y", "--yes", action="store_true", help="확인 없이 진행")
    ar.add_argument("--limit", type=int, default=15)
    ar.add_argument("--apply", action="store_true")
    ar.set_defaults(func=cmd_file_archive)

    uz = fp.add_parser("unzip", help="한글 이름이 깨지는 zip 을 제대로 풀기")
    uz.add_argument("file", metavar="zip파일")
    uz.add_argument("-o", "--out", metavar="디렉터리", help="기본: zip 이름과 같은 폴더")
    uz.add_argument("--overwrite", action="store_true", help="이미 있는 파일도 덮어쓴다")
    uz.add_argument("--raw", action="store_true", help="고치기 전 이름도 함께 보여준다")
    uz.add_argument("--limit", type=int, default=20)
    uz.add_argument("--apply", action="store_true")
    uz.set_defaults(func=cmd_file_unzip)

    hs = fp.add_parser("hash", help="체크섬 만들기·검증 (배포·백업 무결성)")
    hs.add_argument("dir", nargs="?", default=".")
    hs.add_argument("-a", "--algorithm", default="sha256",
                    choices=list(files.HASH_ALGORITHMS))
    hs.add_argument("-g", "--glob", action="append", metavar="패턴")
    hs.add_argument("--hidden", action="store_true")
    hs.add_argument("--no-recursive", action="store_true")
    hs.add_argument("-o", "--out", metavar="파일", help="예: SHA256SUMS.txt")
    hs.add_argument("--check", metavar="파일", help="적어 둔 체크섬과 맞춰본다")
    hs.add_argument("--limit", type=int, default=20)
    hs.set_defaults(func=cmd_file_hash)

    fd2 = fp.add_parser("diff", help="두 디렉터리 비교 (배포·백업 검증)")
    fd2.add_argument("left", metavar="왼쪽")
    fd2.add_argument("right", metavar="오른쪽")
    fd2.add_argument("-g", "--glob", action="append", metavar="패턴")
    fd2.add_argument("--hidden", action="store_true")
    fd2.add_argument("--quick", action="store_true",
                     help="크기만 비교 (빠르지만 크기 같은 변경은 못 잡는다)")
    fd2.add_argument("--limit", type=int, default=25)
    fd2.set_defaults(func=cmd_file_diff)

    u = fp.add_parser("undo", help="organize/fixname 되돌리기")
    u.add_argument("journal", nargs="?", help="생략하면 가장 최근 저널")
    u.set_defaults(func=cmd_file_undo)
