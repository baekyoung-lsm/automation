"""attools CLI 진입점."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from . import (__version__, devkit, files, gitkit, jsonkit, keys, life, logkit,
               manuscript, mdkit, names, report, sheet, text, todo)
from .schedule import Cron, CronError
from . import hangul
from .hangul import is_decomposed

DRY = "[미리보기]"


def _pad(text: str, width: int) -> str:
    """한글처럼 두 칸을 차지하는 문자를 고려한 왼쪽 정렬."""
    import unicodedata

    shown = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    return text + " " * max(0, width - shown)


def _p(*args, **kwargs):
    print(*args, **kwargs)


def _confirm(question: str) -> bool:
    if not sys.stdin.isatty():
        return False
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def _read_input(target: str) -> str:
    return sys.stdin.read() if target == "-" else manuscript.read_text(Path(target))


# ===================================================================== file

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
        candidates = sorted(files.JOURNAL_DIR.glob("*.jsonl")) if files.JOURNAL_DIR.is_dir() else []
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


# ====================================================================== dev

def cmd_dev_env(a) -> int:
    example, actual = Path(a.example), Path(a.actual)

    if a.sync:
        if not actual.is_file():
            _p(f"파일이 없습니다: {actual}")
            return 1
        text, added = devkit.build_example(
            actual, existing=example if example.is_file() else None,
            keep_values=a.keep_values)

        if not a.apply:
            _p(f"{actual} -> {example} (미리보기)\n")
            _p(text)
            if added:
                _p(f"새로 들어갈 키 {len(added)}개: {', '.join(added)}")
            _p("\n실제로 쓰려면 --apply 를 붙이세요.")
            return 0

        example.write_text(text, encoding="utf-8")
        _p(f"{example} 를 갱신했습니다." + (f"  새 키 {len(added)}개" if added else ""))
        _p("비밀값은 <이름> 자리표시자로 바꿨습니다. 커밋 전에 한 번 확인하세요.")
        return 0

    for p in (example, actual):
        if not p.is_file():
            _p(f"파일이 없습니다: {p}")
            return 1

    d = devkit.env_diff(example, actual)
    if d.missing:
        _p(f"빠진 키 ({len(d.missing)}개) - {actual.name} 에 추가해야 합니다")
        for k in d.missing:
            _p(f"  - {k}")
    if d.empty:
        _p(f"\n값이 비어 있음 ({len(d.empty)}개)")
        for k in d.empty:
            _p(f"  - {k}")
    if d.placeholder:
        _p(f"\n예시 값 그대로 ({len(d.placeholder)}개) - 실제 값으로 바꾸세요")
        for k in d.placeholder:
            _p(f"  - {k}")
    if d.extra and a.show_extra:
        _p(f"\n{example.name} 에 없는 키 ({len(d.extra)}개) - 예시 파일에 추가할지 확인")
        for k in d.extra:
            _p(f"  - {k}")

    if a.show_values:
        _p(f"\n{actual.name} 현재 값 (마스킹)")
        for k, v in devkit.parse_env(actual).items():
            shown = devkit.mask_value(v) if devkit.SECRET_HINT.search(k) else (v or "(비어 있음)")
            _p(f"  {k} = {shown}")

    if d.ok:
        _p("문제 없습니다.")
    return 0 if d.ok else 1


def cmd_dev_port(a) -> int:
    try:
        listeners = devkit.who_listens(a.port)
    except RuntimeError as e:
        _p(str(e))
        return 1

    if not listeners:
        _p(f"{a.port} 포트는 비어 있습니다.")
        return 0

    for l in listeners:
        _p(f"pid {l.pid}  {l.name}")

    if not a.kill:
        _p(f"\n종료하려면: at dev port {a.port} --kill")
        return 0
    if not a.yes and not _confirm(f"위 {len(listeners)}개 프로세스를 종료할까요?"):
        _p("취소했습니다.")
        return 1

    killed = devkit.kill_listeners(a.port, force=a.force)
    _p(f"{len(killed)}개 프로세스에 {'SIGKILL' if a.force else 'SIGTERM'} 을 보냈습니다.")
    return 0


def cmd_dev_jwt(a) -> int:
    token = sys.stdin.read().strip() if a.token == "-" else a.token
    try:
        info = devkit.decode_jwt(token)
    except Exception as e:
        _p(f"디코드 실패: {e}")
        return 1

    import json as _json
    _p("헤더")
    _p(_json.dumps(info["header"], ensure_ascii=False, indent=2))
    _p("\n페이로드")
    _p(_json.dumps(info["payload"], ensure_ascii=False, indent=2))
    if info["times"]:
        _p("\n시각 (KST)")
        for k, dt in info["times"].items():
            rel = devkit.humanize_delta(devkit.datetime.now(devkit.KST) - dt)
            _p(f"  {_pad(k, 10)}{dt:%Y-%m-%d %H:%M:%S}  ({rel})")
    if info["expired"] is not None:
        _p(f"\n만료 여부: {'만료됨' if info['expired'] else '유효'}")
    _p("서명은 검증하지 않았습니다. 내용 확인용으로만 쓰세요.")
    return 0


def cmd_dev_time(a) -> int:
    try:
        dt = devkit.parse_when(a.when)
    except ValueError as e:
        _p(f"해석 실패: {e}")
        return 1
    for k, v in devkit.when_report(dt).items():
        _p(f"{_pad(k, 10)}{v}")
    return 0


def cmd_dev_mask(a) -> int:
    text = _read_input(a.file)
    masked, counts = devkit.mask_text(text)

    if a.in_place and a.file != "-":
        Path(a.file).write_text(masked, encoding="utf-8")
        _p(f"{a.file} 을(를) 덮어썼습니다.")
    else:
        sys.stdout.write(masked)

    if counts:
        summary = ", ".join(f"{k} {v}건" for k, v in counts.items())
        print(f"\n[마스킹] {summary}", file=sys.stderr)
    else:
        print("\n[마스킹] 걸린 항목 없음", file=sys.stderr)
    return 0


# ==================================================================== novel

def _print_stats(s: manuscript.Stats, *, name: str | None = None) -> None:
    _p(f"{name or s.path}")
    _p(f"  글자수(공백 포함)  {s.chars:,}")
    _p(f"  글자수(공백 제외)  {s.chars_no_space:,}")
    _p(f"  원고지(200자)      {s.wongoji:,.1f}매")
    _p(f"  어절 / 문장 / 문단  {s.words:,} / {s.sentences:,} / {s.paragraphs:,}")
    _p(f"  평균 문장 길이     {s.avg_sentence:.1f}자")
    _p(f"  대사 비율          {s.dialogue_ratio:.1%}")
    _p(f"  읽는 시간          약 {s.read_minutes:.0f}분")
    _p(f"  단행본 환산        약 {s.book_ratio:.2f}권 (10만자 기준 어림값)")


def cmd_novel_stats(a) -> int:
    targets = manuscript.collect([Path(p) for p in a.paths])
    if not targets:
        _p("텍스트 파일을 찾지 못했습니다.")
        return 1

    stats = [manuscript.analyze(p) for p in targets]
    if a.each or len(stats) == 1:
        for s in stats:
            _print_stats(s)
            _p("")
    if len(stats) > 1:
        _print_stats(manuscript.total(stats))
    return 0


def cmd_novel_check(a) -> int:
    text = _read_input(a.file)
    f = manuscript.inspect(text, top=a.top, long_limit=a.long,
                           run_threshold=a.run)
    empty = True

    def section(title: str, rows: list[str]) -> None:
        nonlocal empty
        if not rows:
            return
        empty = False
        _p(title)
        for r in rows:
            _p(f"  {r}")
        _p("")

    section("상투 표현", [f"{c} x{n}" for c, n in f.cliches])
    section("군더더기 부사", [f"{c} x{n}" for c, n in f.adverbs])
    section("반복 어구(2어절)", [f"{c} x{n}" for c, n in f.phrases])
    section(f"종결 어미 {a.run}회 이상 연속",
            [f"'{e}' {n}문장 연속 (문장 {i}~{i + n - 1})" for e, n, i in f.ending_runs])
    section("같은 말로 시작하는 문장 연속",
            [f"'{w}' {n}문장 연속 (문장 {i}~{i + n - 1})" for w, n, i in f.start_runs])
    section(f"{a.long}자 넘는 문장",
            [f"문장 {i} ({n}자) {prev}" for i, n, prev in f.long_sentences[:a.top]])

    if empty:
        _p("걸리는 항목이 없습니다.")
    return 0


def cmd_novel_snap(a) -> int:
    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    snaps = manuscript.list_snapshots(root)
    if a.list:
        if not snaps:
            _p("스냅샷이 없습니다.")
            return 0
        prev = None
        for s in snaps:
            delta = f"  ({s['total'] - prev:+,}자)" if prev is not None else ""
            note = f"  {s['note']}" if s.get("note") else ""
            _p(f"{s['id']}  {s['total']:,}자{delta}{note}")
            prev = s["total"]
        return 0

    before = snaps[-1]["total"] if snaps else None
    dest = manuscript.snapshot(root, note=a.note)
    after = manuscript.list_snapshots(root)[-1]["total"]
    _p(f"스냅샷 저장: {dest}")
    _p(f"현재 분량: {after:,}자" + (f" ({after - before:+,}자)" if before is not None else ""))
    return 0



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


# ================================================================ file 추가

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


# ================================================================= dev 추가

def cmd_dev_wait(a) -> int:
    def progress(attempt, elapsed, last):
        print(f"  {elapsed:5.1f}초 경과, {attempt}회 시도 ({last})", file=sys.stderr)

    _p(f"{a.target} 기다리는 중 (최대 {a.timeout:.0f}초)")
    try:
        ok, elapsed, last = devkit.wait_for(
            a.target, timeout=a.timeout, interval=a.interval,
            on_try=None if a.quiet else progress)
    except ValueError as e:
        _p(str(e))
        return 2

    if ok:
        _p(f"준비됨: {a.target} ({elapsed:.1f}초)")
        return 0
    _p(f"시간 초과: {a.target} ({elapsed:.1f}초) 마지막 오류 - {last}")
    return 1


def cmd_dev_cron(a) -> int:
    try:
        cron = Cron(a.expression)
    except CronError as e:
        _p(f"해석 실패: {e}")
        return 1

    now = devkit.datetime.now(devkit.KST)
    _p(f"{cron.expression}")
    _p(f"  뜻: {cron.describe()}")
    _p(f"\n다음 실행 (KST)")
    for dt in cron.next_runs(now.replace(tzinfo=None), a.count):
        rel = devkit.humanize_delta(now.replace(tzinfo=None) - dt)
        _p(f"  {dt:%Y-%m-%d}({life.weekday_ko(dt.date())}) {dt:%H:%M}  {rel}")
    return 0


def cmd_dev_gen(a) -> int:
    try:
        values = devkit.gen_secret(a.kind, a.length, count=a.count, readable=a.readable)
    except ValueError as e:
        _p(str(e))
        return 1
    for v in values:
        _p(v)
    return 0


def cmd_dev_enc(a) -> int:
    value = sys.stdin.read().strip() if a.value == "-" else a.value
    for k, v in devkit.encodings(value).items():
        _p(f"{_pad(k, 16)}{v}")
    return 0


# ==================================================================== git

def _repo(a) -> Path | None:
    try:
        return gitkit.repo_root(Path(getattr(a, "dir", ".") or "."))
    except RuntimeError:
        _p("git 저장소가 아닙니다.")
        return None


def cmd_git_sweep(a) -> int:
    root = _repo(a)
    if root is None:
        return 1

    if a.fetch:
        _p("origin 에서 최신 정보를 가져오는 중...")
        try:
            gitkit.run(["fetch", "--prune", "origin"], root)
        except RuntimeError as e:
            _p(f"  fetch 실패(무시하고 진행): {e}")

    sweep = gitkit.find_stale_branches(root, a.base)
    _p(f"기준 브랜치: {sweep.base}   현재: {sweep.current}\n")

    if sweep.merged:
        _p(f"{sweep.base} 에 병합 완료 ({len(sweep.merged)}개)")
        for b in sweep.merged:
            _p(f"  {b}")
    if sweep.gone:
        _p(f"\n원격이 사라짐 ({len(sweep.gone)}개) - 삭제하려면 --force 필요")
        for b in sweep.gone:
            _p(f"  {b}")
    if not sweep.merged and not sweep.gone:
        _p("정리할 브랜치가 없습니다.")
        return 0

    targets = sweep.merged + (sweep.gone if a.force else [])
    if not a.apply:
        _p(f"\n{len(targets)}개를 지웁니다. 실제로 지우려면 --apply 를 붙이세요.")
        return 0

    _p("")
    for name, result in gitkit.delete_branches(root, targets, force=a.force):
        _p(f"  {name}: {result}")
    return 0


def cmd_git_scan(a) -> int:
    root = _repo(a)
    if root is None:
        return 1

    if a.install_hook:
        hook = gitkit.install_hook(root, a.install_hook)
        _p(f"pre-commit 훅을 설치했습니다: {hook}")
        _p("커밋할 때마다 스테이징된 파일에서 시크릿을 검사합니다.")
        return 0

    findings = gitkit.scan_paths(root, staged=a.staged, tracked=not a.all,
                                 entropy_threshold=a.entropy)
    if not findings:
        if not a.staged and not a.all and gitkit.tracked_count(root) == 0:
            if not a.quiet:
                _p("git 이 추적하는 파일이 없어 아무것도 검사하지 않았습니다.")
                _p("추적 안 되는 파일까지 보려면 --all 을 붙이세요.")
            return 0
        if not a.quiet:
            _p("시크릿으로 보이는 값이 없습니다.")
        return 0

    _p(f"의심 항목 {len(findings)}건")
    for f in findings:
        _p(f"\n  {f.path}:{f.line}  [{f.kind}]")
        _p(f"    {f.excerpt}")
    _p("\n실제 시크릿이면 커밋하지 말고 값을 폐기·재발급하세요.")
    _p("이미 커밋했다면 히스토리에서도 지워야 합니다 (git filter-repo 등).")
    return 1


def cmd_git_todo(a) -> int:
    root = _repo(a)
    if root is None:
        root = Path(a.dir or ".").resolve()
        if not root.is_dir():
            _p(f"디렉터리가 아닙니다: {root}")
            return 1

    markers = [m.upper() for m in a.marker] if a.marker else None
    if markers:
        unknown = [m for m in markers if m not in todo.MARKERS]
        if unknown:
            _p(f"모르는 표시입니다: {', '.join(unknown)}")
            _p(f"쓸 수 있는 것: {', '.join(todo.MARKERS)}")
            return 1

    found = todo.collect(root, tracked=not a.all, markers=markers, glob=a.glob)
    if not found:
        if not a.all and gitkit.tracked_count(root) == 0:
            _p("git 이 추적하는 파일이 없습니다. (아직 add 하지 않았습니까?)")
            _p("추적 안 되는 파일까지 보려면 --all 을 붙이세요.")
            return 0
        _p("TODO 가 없습니다.")
        return 0

    if not a.no_blame:
        todo.add_blame(root, found)

    counts = todo.summarize(found)
    _p(f"{len(found)}건  ·  " + "  ".join(f"{k} {v}" for k, v in counts.items()))
    aged = [t for t in found if t.age_days is not None]
    if aged:
        oldest = max(aged, key=lambda t: t.age_days)
        _p(f"가장 오래된 것 {oldest.age_days}일  ·  "
           f"평균 {sum(t.age_days for t in aged) // len(aged)}일\n")
    else:
        _p("")

    rows = todo.sort_todos(found, a.sort)[:a.limit]
    header = ["표시", "내용", "위치", "담당·작성자", "방치"]
    body = []
    for t in rows:
        who = t.owner or t.author or "-"
        age = f"{t.age_days}일" if t.age_days is not None else "-"
        body.append([t.marker, t.text, f"{t.path}:{t.line}", who, age])
    _grid(header, body, limit=a.width)

    if len(found) > a.limit:
        _p(f"\n... {len(found) - a.limit}건 더 (--limit 로 조절)")
    return 0


def cmd_git_stats(a) -> int:
    root = _repo(a)
    if root is None:
        return 1

    try:
        commits = gitkit.read_log(root, since=a.since, until=a.until,
                                  paths=a.path, limit=a.max_commits)
    except RuntimeError as e:
        _p(str(e))
        return 1

    if not commits:
        _p("해당 기간에 커밋이 없습니다.")
        return 0

    first, last = commits[-1].when, commits[0].when
    added = sum(c.added for c in commits)
    deleted = sum(c.deleted for c in commits)
    _p(f"커밋 {len(commits):,}개  ·  {first:%Y-%m-%d} ~ {last:%Y-%m-%d}"
       f"  ·  +{added:,} -{deleted:,}줄\n")

    _p("사람별")
    _grid(["이름", "커밋", "추가", "삭제"],
          [[name, f"{n:,}", f"+{a2:,}", f"-{d:,}"]
           for name, n, a2, d in gitkit.by_author(commits)[:a.limit]], limit=20)
    _p("")

    churn = gitkit.churn_by_file(commits)
    _p("자주 바뀐 파일 - 손이 많이 가는 곳이다")
    _grid(["파일", "커밋", "변경 줄", "사람"],
          [[f.path, f"{f.commits:,}", f"{f.churn:,}", str(len(f.authors))]
           for f in churn[:a.limit]], limit=44)
    _p("")

    if a.weekday:
        counts = gitkit.by_weekday(commits)
        peak = max(n for _, n in counts) or 1
        _p("요일별")
        for day, n in counts:
            _p(f"  {day}  {n:>5,}  {'█' * round(n / peak * 28)}")
        _p("")

    if a.by:
        try:
            series = gitkit.by_period(commits, unit=a.by)
        except ValueError as e:
            _p(str(e))
            return 1
        peak = max(n for _, n in series) or 1
        _p(f"{a.by} 단위")
        for label, n in series[-a.rows:]:
            _p(f"  {label:>12}  {n:>5,}  {'█' * round(n / peak * 28)}")
    return 0


def cmd_git_release(a) -> int:
    root = _repo(a)
    if root is None:
        return 1

    since = a.since
    if since is None:
        since = gitkit.latest_tag(root)
        if since:
            _p(f"최근 태그 {since} 이후를 봅니다. (--since 로 바꿀 수 있습니다)")
        else:
            _p("태그가 없어 전체 이력을 봅니다.")

    try:
        changes = gitkit.collect_changes(root, since=since, until=a.until)
    except RuntimeError as e:
        _p(str(e))
        return 1

    if not changes:
        _p("해당 범위에 커밋이 없습니다.")
        return 0

    groups = gitkit.group_changes(changes)
    text = gitkit.render_changelog(groups, title=a.title, link_prefix=a.link or "")

    authors = sorted({c.author for c in changes})
    touched = sorted({f for c in changes for f in c.files})
    breaking = [c for c in changes if c.breaking]

    if a.out:
        target = Path(a.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        head = target.read_text(encoding="utf-8") if target.is_file() else ""
        target.write_text(text + ("\n" + head if head else ""), encoding="utf-8")
        _p(f"저장: {target}  (기존 내용 위에 붙였습니다)")
    else:
        _p("")
        sys.stdout.write(text)

    _p(f"\n커밋 {len(changes)}개  ·  사람 {len(authors)}명  ·  파일 {len(touched)}개")
    if breaking:
        _p(f"호환성 주의 {len(breaking)}건: "
           + ", ".join(_cut(c.title, 40) for c in breaking[:5]))
    if a.authors:
        _p(f"기여: {', '.join(authors)}")
    return 0


# =================================================================== life

def cmd_life_dday(a) -> int:
    from datetime import date as _date

    today = life.parse_date(a.today) if a.today else _date.today()
    for text in a.dates:
        try:
            target = life.parse_date(text)
        except ValueError:
            _p(f"날짜를 해석하지 못했습니다: {text} (예: 2024-03-15, 20240315)")
            return 1

        d = life.DDay(target, today)
        _p(f"{target:%Y-%m-%d}({life.weekday_ko(target)})")
        if d.delta > 0:
            _p(f"  D-{d.delta}  ({d.delta}일 남음)")
        elif d.delta == 0:
            _p("  D-Day  오늘입니다")
        else:
            _p(f"  D+{-d.delta}  (지난 지 {-d.delta}일, 당일 포함 {d.nth_day}일째)")
            _p(f"  만 {life.korean_age(target, today)}년 경과 (생일이면 만 나이)")

        if not a.no_milestones:
            _p("  다가올 기념일")
            for name, when, left in d.milestones()[:a.count]:
                _p(f"    {name:>6}  {when:%Y-%m-%d}({life.weekday_ko(when)})  D-{left}")
        _p("")
    return 0


def cmd_life_split(a) -> int:
    paid: dict[str, float] = {}
    for item in a.paid:
        name, _, amount = item.partition("=")
        if not amount:
            _p(f"'이름=금액' 형태로 적으세요: {item}")
            return 1
        try:
            paid[name] = paid.get(name, 0.0) + life.parse_amount(amount)
        except ValueError as e:
            _p(str(e))
            return 1

    try:
        share, balance, transfers = life.settle(paid, extra=a.extra)
    except ValueError as e:
        _p(str(e))
        return 1

    total = sum(paid.values())
    _p(f"총액 {life.format_won(total)}, {len(balance)}명")
    _p(f"1인당 {life.format_won(share)}\n")

    for name in sorted(balance, key=lambda n: -balance[n]):
        v = balance[name]
        state = "받을 돈" if v > 0 else ("낼 돈" if v < 0 else "정산 완료")
        _p(f"  {_pad(name, 12)}낸 돈 {paid.get(name, 0):>12,.0f}   "
           f"{_pad(state, 8)}{abs(v):>10,.0f}")

    _p("\n송금")
    if not transfers:
        _p("  주고받을 것이 없습니다.")
    for t in transfers:
        _p(f"  {t.payer} -> {t.payee}  {t.amount:,.0f}원")
    return 0


def cmd_life_loan(a) -> int:
    try:
        principal = life.parse_amount(a.principal)
    except ValueError as e:
        _p(str(e))
        return 1

    months = int(round(a.years * 12)) if a.years else a.months
    if not months:
        _p("기간을 --years 또는 --months 로 지정하세요.")
        return 1

    try:
        rows = life.amortize(principal, a.rate, months, kind=a.kind, grace=a.grace)
    except ValueError as e:
        _p(str(e))
        return 1

    interest = sum(r.interest for r in rows)
    _p(f"{life.format_won(principal)}  연 {a.rate}%  {months}개월({months / 12:.1f}년)  {a.kind}"
       + (f"  거치 {a.grace}개월" if a.grace else ""))
    _p("")
    first, last = rows[a.grace], rows[-1]
    if a.kind == "원리금균등":
        _p(f"  매달 상환액   {life.format_won(first.payment)}")
    else:
        _p(f"  첫 달 상환액  {life.format_won(first.payment)}")
        _p(f"  마지막 상환액 {life.format_won(last.payment)}")
    _p(f"  총 이자       {life.format_won(interest)}")
    _p(f"  총 상환액     {life.format_won(principal + interest)}")
    _p(f"  이자 비율     {interest / principal:.1%}")

    if a.table:
        _p(f"\n  회차  {'상환액':>14}{'이자':>14}{'원금':>14}{'잔액':>16}")
        shown = rows if a.table < 0 else rows[:a.table]
        for r in shown:
            _p(f"  {r.no:>4}  {r.payment:>14,.0f}{r.interest:>14,.0f}"
               f"{r.principal:>14,.0f}{r.balance:>16,.0f}")
        if len(shown) < len(rows):
            _p(f"  ... 총 {len(rows)}회차 (--table -1 로 전체 출력)")
    return 0


def cmd_life_unit(a) -> int:
    try:
        group, value, unit, results = life.convert(" ".join(a.value))
    except ValueError as e:
        _p(str(e))
        return 1

    _p(f"[{group}] {value:g}{unit}")
    for name, converted in results:
        _p(f"  {_pad(name, 8)}{converted:,.4g}")
    return 0


# ================================================================== sheet

def _width(text: str) -> int:
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _cut(text: str, limit: int) -> str:
    if _width(text) <= limit:
        return text
    out = ""
    for ch in text:
        if _width(out + ch) > limit - 1:
            return out + "…"
        out += ch
    return out


def _grid(headers: list[str], rows: list[list[str]], *, limit: int = 24) -> None:
    """터미널에 표를 정렬해 찍는다."""
    cells = [[_cut(h, limit) for h in headers]] + [[_cut(c, limit) for c in r] for r in rows]
    widths = [max(_width(row[i]) for row in cells if i < len(row))
              for i in range(len(headers))]
    line = "  ".join(_pad(h, w) for h, w in zip(cells[0], widths))
    _p("  " + line.rstrip())
    _p("  " + "  ".join("-" * w for w in widths))
    for row in cells[1:]:
        _p("  " + "  ".join(_pad(c, w) for c, w in zip(row, widths)).rstrip())


def _load(a, path: str | None = None) -> sheet.Table | None:
    try:
        return sheet.load(Path(path or a.file), sheet=getattr(a, "sheet", None),
                          header_row=getattr(a, "header_row", 1) - 1)
    except (sheet.SheetError, OSError) as e:
        _p(f"읽지 못했습니다: {e}")
        return None


def cmd_sheet_peek(a) -> int:
    path = Path(a.file)
    if path.suffix.lower() in sheet.XLSX_SUFFIXES:
        names = sheet.xlsx.sheet_names(path)
        _p(f"시트 {len(names)}개: {', '.join(names)}")

    t = _load(a)
    if t is None:
        return 1
    _p(f"{path.name}" + (f" [{t.sheet}]" if t.sheet else "")
       + f"  {len(t.rows):,}행 x {t.width}열\n")

    header = ["열", "타입", "결측", "고유", "최소", "최대", "예시"]
    body = []
    for c in sheet.profile(t):
        ratio = f"{c.missing / len(t.rows):.0%}" if t.rows else "-"
        body.append([
            c.name,
            c.main_kind + ("(혼재)" if c.mixed else ""),
            f"{c.missing}({ratio})" if c.missing else "-",
            f"{c.unique:,}",
            sheet.to_text(c.minimum) if c.minimum is not None else "-",
            sheet.to_text(c.maximum) if c.maximum is not None else "-",
            " | ".join(c.samples),
        ])
    _grid(header, body, limit=a.width)

    if a.rows:
        _p(f"\n앞 {a.rows}행")
        _grid(t.headers, [[sheet.to_text(v) for v in r] for r in t.rows[:a.rows]],
              limit=a.width)
    return 0


def cmd_sheet_check(a) -> int:
    t = _load(a)
    if t is None:
        return 1

    issues = sheet.validate(t, key=a.key, required=a.required)
    if not issues:
        _p(f"{Path(a.file).name}: 문제 없습니다. ({len(t.rows):,}행)")
        return 0

    _p(f"{Path(a.file).name}: {len(issues)}건\n")
    for issue in issues:
        where = f"  해당 행: {', '.join(str(n) for n in issue.rows)}" if issue.rows else ""
        _p(f"  [{issue.kind}] {issue.column}")
        _p(f"    {issue.detail}")
        if where:
            _p(f"  {where.strip()}")
        _p("")
    _p("행 번호는 헤더를 1행으로 센 엑셀 기준입니다.")
    return 1


def cmd_sheet_clean(a) -> int:
    t = _load(a)
    if t is None:
        return 1

    cleaned, rep = sheet.clean(t, drop_duplicates=a.dedupe)
    _p(f"{Path(a.file).name}  {len(t.rows):,}행 -> {len(cleaned.rows):,}행")
    facts = [
        (rep.trimmed, "공백 정리"),
        (rep.fullwidth, "전각 공백 치환"),
        (rep.numbers, "문자 -> 숫자"),
        (rep.dates, "문자 -> 날짜"),
        (rep.dropped_rows, "빈 행 제거"),
        (rep.duplicate_rows, "중복 행 제거"),
    ]
    for n, label in facts:
        if n:
            _p(f"  {label} {n:,}건")
    if rep.dropped_cols:
        _p(f"  빈 열 제거: {', '.join(rep.dropped_cols)}")

    if not a.out:
        _p("\n저장하려면 -o 로 출력 파일을 지정하세요.")
        return 0
    out = sheet.save(cleaned, Path(a.out))
    _p(f"\n저장: {out}")
    return 0


def cmd_sheet_merge(a) -> int:
    tables = []
    for name in a.files:
        t = _load(a, name)
        if t is None:
            return 1
        tables.append(t)

    try:
        merged, warnings = sheet.merge(tables, add_source=not a.no_source, strict=a.strict)
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    for w in warnings:
        _p(f"  주의 {w}")
    _p(f"{len(tables)}개 파일 -> {len(merged.rows):,}행 x {merged.width}열")

    if not a.out:
        _grid(merged.headers, [[sheet.to_text(v) for v in r] for r in merged.rows[:5]])
        _p("\n저장하려면 -o 로 출력 파일을 지정하세요.")
        return 0
    _p(f"저장: {sheet.save(merged, Path(a.out))}")
    return 0


def cmd_sheet_diff(a) -> int:
    before, after = _load(a, a.before), _load(a, a.after)
    if before is None or after is None:
        return 1

    try:
        d = sheet.diff(before, after, a.key)
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    if d.empty:
        _p("차이가 없습니다.")
        return 0

    if d.columns_added or d.columns_removed:
        _p(f"열 변화  추가 {d.columns_added or '-'}  삭제 {d.columns_removed or '-'}\n")

    key_i = after.index_of(a.key)
    if d.added:
        _p(f"추가된 행 {len(d.added)}건")
        for row in d.added[:a.limit]:
            _p(f"  + {sheet.to_text(row[key_i]) or '(빈 키)'}")
        _p("")
    if d.removed:
        bkey = before.index_of(a.key)
        _p(f"삭제된 행 {len(d.removed)}건")
        for row in d.removed[:a.limit]:
            _p(f"  - {sheet.to_text(row[bkey]) or '(빈 키)'}")
        _p("")
    if d.changed:
        _p(f"바뀐 값 {len(d.changed)}건")
        # 앞뒤 공백 차이도 눈에 보이도록 따옴표로 감싼다
        _grid([a.key, "열", "이전", "이후"],
              [[k, col, f'"{sheet.to_text(b)}"', f'"{sheet.to_text(x)}"']
               for k, col, b, x in d.changed[:a.limit]])
    return 1


def cmd_sheet_pivot(a) -> int:
    t = _load(a)
    if t is None:
        return 1
    try:
        result = sheet.pivot(t, rows=a.rows, values=a.values, agg=a.agg, cols=a.cols)
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    _grid(result.headers,
          [[sheet.to_text(v) if not isinstance(v, float) else f"{v:,.2f}" for v in r]
           for r in result.rows])
    _p(f"\n{len(result.rows)}개 그룹")
    if a.out:
        _p(f"저장: {sheet.save(result, Path(a.out))}")
    return 0


def cmd_sheet_convert(a) -> int:
    t = _load(a)
    if t is None:
        return 1
    out = sheet.save(t, Path(a.out), excel_bom=not a.no_bom, sheet_name=a.name)
    _p(f"{Path(a.file).name} -> {out}  ({len(t.rows):,}행 x {t.width}열)")
    if out.suffix.lower() == ".csv" and not a.no_bom:
        _p("엑셀에서 한글이 깨지지 않도록 UTF-8 BOM 을 붙였습니다.")
    return 0


def cmd_novel_outline(a) -> int:
    targets = manuscript.collect([Path(p) for p in a.paths])
    if not targets:
        _p("텍스트 파일을 찾지 못했습니다.")
        return 1

    scenes: list[manuscript.Scene] = []
    for path in targets:
        body = manuscript.strip_headings(manuscript.read_text(path)) \
            if a.no_headings else manuscript.read_text(path)
        found = manuscript.split_scenes(body, min_chars=a.min)
        for scene in found:
            scene.number = len(scenes) + 1
            scene.title = scene.title or (path.stem if len(targets) > 1 else "")
            scenes.append(scene)

    if not scenes:
        _p(f"{a.min}자 이상인 장면이 없습니다. --min 을 낮춰 보세요.")
        return 1

    whole = "\n".join(s.text for s in scenes)
    people = list(a.name or []) or [n.text for n in names.extract(whole, min_count=a.people)]
    manuscript.tag_people(scenes, people)

    lengths = [s.chars for s in scenes]
    total = sum(lengths)
    _p(f"장면 {len(scenes)}개  ·  {total:,}자  ·  평균 {total // len(scenes):,}자"
       f"  ·  원고지 {total / manuscript.WONGOJI_CHARS:,.0f}매")
    longest, shortest = max(scenes, key=lambda s: s.chars), min(scenes, key=lambda s: s.chars)
    _p(f"가장 긴 장면 {longest.number}번 {longest.chars:,}자  ·  "
       f"가장 짧은 장면 {shortest.number}번 {shortest.chars:,}자\n")

    header = ["번호", "제목", "행", "분량", "대사", "인물", "첫 문장"]
    body_rows = [[str(s.number), s.title or "-", str(s.line), f"{s.chars:,}",
                  f"{s.dialogue_ratio:.0%}", ", ".join(s.people[:3]) or "-", s.opening]
                 for s in scenes]
    _grid(header, body_rows[:a.limit], limit=a.width)
    if len(scenes) > a.limit:
        _p(f"  ... {len(scenes) - a.limit}개 더 (--limit 로 조절)")

    if a.out:
        table = sheet.Table(header, body_rows)
        _p(f"\n저장: {sheet.save(table, Path(a.out), sheet_name='장면')}")
    return 0


def cmd_novel_find(a) -> int:
    import re as _re

    targets = manuscript.collect([Path(p) for p in a.paths])
    if not targets:
        _p("텍스트 파일을 찾지 못했습니다.")
        return 1

    body = a.query if a.regex else _re.escape(a.query)
    try:
        pattern = _re.compile(body, _re.I if a.ignore_case else 0)
    except _re.error as e:
        _p(f"정규식이 잘못됐습니다: {e}")
        return 1

    found: list[manuscript.Mention] = []
    for path in targets:
        raw = manuscript.read_text(path)
        # 장면 경계는 원문에서 잡고(구분선이 살아 있어야 한다),
        # 찾기는 제목만 지운 본문에서 한다. 줄 수가 같아 행 번호가 맞는다.
        scenes = manuscript.split_scenes(raw, min_chars=a.min)
        found += manuscript.find_mentions(manuscript.strip_headings(raw), pattern,
                                          path=path.name, context=a.context,
                                          scenes=scenes)

    if not found:
        _p(f"'{a.query}' 를 찾지 못했습니다.")
        return 1

    _p(f"'{a.query}'  {len(found)}번  (파일 {len({m.path for m in found})}개)")
    first, last = found[0], found[-1]
    _p(f"처음 {first.path}:{first.line}행" + (f" 장면 {first.scene}" if first.scene else "")
       + f"  ·  마지막 {last.path}:{last.line}행"
       + (f" 장면 {last.scene}" if last.scene else "") + "\n")

    for m in found[:a.limit]:
        where = f"{m.path}:{m.line}행" + (f"  장면 {m.scene}" if m.scene else "")
        _p(f"  {where}")
        _p(f"    {_cut(m.context(), a.width)}")
    if len(found) > a.limit:
        _p(f"  ... {len(found) - a.limit}번 더 (--limit 로 조절)")
    return 0


def cmd_novel_timeline(a) -> int:
    targets = manuscript.collect([Path(p) for p in a.paths])
    if not targets:
        _p("텍스트 파일을 찾지 못했습니다.")
        return 1

    marks: list[manuscript.TimeMark] = []
    conflicts: list[tuple[str, manuscript.TimeConflict]] = []
    for path in targets:
        raw = manuscript.read_text(path)
        scenes = manuscript.split_scenes(raw, min_chars=a.min)
        found = manuscript.find_time_marks(manuscript.strip_headings(raw), scenes=scenes)
        for m in found:
            m.sentence = f"{path.name}|{m.sentence}"
        marks += found
        conflicts += [(path.name, c) for c in manuscript.time_conflicts(found)]

    if not marks:
        _p("시간을 가리키는 표현을 찾지 못했습니다.")
        return 0

    kinds = Counter(m.kind for m in marks)
    _p(f"시간 표현 {len(marks)}개  ·  "
       + "  ".join(f"{k} {v}" for k, v in kinds.most_common()) + "\n")

    shown = [m for m in marks if not a.kind or m.kind in a.kind]
    for m in shown[:a.limit]:
        name, _, sentence = m.sentence.partition("|")
        where = f"{name}:{m.line}행" + (f" 장면 {m.scene}" if m.scene else "")
        _p(f"  {_pad(m.text, 16)}[{m.kind}]  {where}")
        if a.context:
            _p(f"      {_cut(sentence, a.width)}")
    if len(shown) > a.limit:
        _p(f"  ... {len(shown) - a.limit}개 더")

    if not conflicts:
        _p("\n한 장면 안에서 시간대·계절이 어긋난 곳은 없습니다.")
        return 0

    _p(f"\n같은 장면에서 어긋난 곳 {len(conflicts)}건")
    for name, c in conflicts:
        _p(f"  {name} 장면 {c.scene}: {c.kind} 이 {', '.join(c.values)} 로 섞였습니다"
           f"  ({', '.join(str(n) for n in c.lines)}행)")
    _p("\n회상이나 시간 경과를 일부러 넣은 것일 수 있으니 눈으로 확인하세요.")
    return 1


def cmd_novel_style(a) -> int:
    targets = manuscript.collect([Path(p) for p in a.paths])
    if not targets:
        _p("텍스트 파일을 찾지 못했습니다.")
        return 1

    rows: list[manuscript.Style] = []
    if a.by == "scene":
        for path in targets:
            raw = manuscript.read_text(path)
            for scene in manuscript.split_scenes(raw, min_chars=a.min):
                label = f"{path.stem}#{scene.number}"
                rows.append(manuscript.style_metrics(scene.text, label,
                                                     long_limit=a.long))
    else:
        for path in targets:
            rows.append(manuscript.style_metrics(manuscript.read_text(path),
                                                 path.stem, long_limit=a.long))

    rows = [r for r in rows if r.sentences]
    if not rows:
        _p("잴 만한 내용이 없습니다.")
        return 1

    _grid(manuscript.STYLE_COLUMNS, [r.as_row() for r in rows[:a.limit]], limit=14)
    if len(rows) > a.limit:
        _p(f"  ... {len(rows) - a.limit}개 더")

    _p("\n평균/중앙 = 문장 길이(자)  ·  긴문장 = "
       f"{a.long}자 초과 비율  ·  어미쏠림 = 종결 어미 상위 3개 비중")
    _p("어휘 = 고유 어절 / 전체 어절. 낮을수록 같은 말이 반복된다는 뜻입니다.")

    outliers = manuscript.style_outliers(rows, sigma=a.sigma)
    if not outliers:
        _p("\n다른 것들과 크게 다른 곳은 없습니다."
           if len(rows) >= 3 else "\n비교하려면 대상이 셋 이상 있어야 합니다.")
        return 0

    _p(f"\n튀는 곳 {len(outliers)}개")
    for name, reasons in outliers.items():
        _p(f"  {_pad(name, 16)}{', '.join(reasons)}")
    _p("\n의도한 것일 수 있습니다. 어느 화가 다른지 짚어 줄 뿐입니다.")
    return 0


def cmd_novel_export(a) -> int:
    targets = manuscript.collect([Path(p) for p in a.paths])
    # 내보낸 파일이 원고 디렉터리 안에 있으면 다음 실행에서 원고로 다시 잡힌다.
    # 형식을 바꿔 가며 내보내면 투고본.txt 가 투고본.html 의 원고가 되는 식이다.
    if a.out:
        out_path = Path(a.out).resolve()
        before = len(targets)
        targets = [p for p in targets
                   if p.resolve() != out_path and p.stem != out_path.stem]
        dropped = before - len(targets)
        if dropped:
            _p(f"앞서 내보낸 '{out_path.stem}' 파일 {dropped}개는 원고에서 뺐습니다.")
    if not targets:
        _p("텍스트 파일을 찾지 못했습니다.")
        return 1

    chapters: list[tuple[str, str]] = []
    total = 0
    for path in targets:
        raw = manuscript.read_text(path)
        name = manuscript.chapter_title(path, raw)
        # HTML 은 CSS 로 들여쓰므로 본문에 공백 문자를 넣지 않는다
        body = manuscript.normalize_body(raw,
                                         indent=a.indent and a.format != "html",
                                         scene_mark=a.scene_mark,
                                         join_lines=a.join)
        total += len("".join(body.split()))   # 공백 제외 글자수
        chapters.append((name, body))

    note = a.note or (f"{total:,}자  ·  원고지 {total / manuscript.WONGOJI_CHARS:,.0f}매"
                      f"  ·  {len(chapters)}편")

    if a.format == "html":
        text = manuscript.export_html(chapters, title=a.title, author=a.author,
                                      note=note, indent=a.indent)
    else:
        text = manuscript.export_text(chapters, title=a.title, author=a.author,
                                      note=note, markdown=a.format == "md")

    if not a.out:
        _p(note)
        for name, body in chapters:
            _p(f"  {_pad(name, 24)}{len(''.join(body.split())):,}자")
        _p("\n저장하려면 -o 로 출력 파일을 지정하세요.")
        return 0

    target = Path(a.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    _p(f"저장: {target}  ({note})")
    if a.format == "html":
        _p("브라우저에서 열어 인쇄하면 화마다 쪽이 나뉩니다.")
    return 0


def cmd_novel_dialogue(a) -> int:
    targets = manuscript.collect([Path(p) for p in a.paths])
    if not targets:
        _p("텍스트 파일을 찾지 못했습니다.")
        return 1

    body = "\n".join(manuscript.strip_headings(manuscript.read_text(p))
                     for p in targets)
    # 대사 화자는 대부분 '이름이 말했다' 꼴이라 조사 종류가 하나뿐이다.
    # 이름 후보를 뽑을 때 조사 다양성 조건을 걸면 주요 인물이 통째로 빠진다.
    people = list(a.name or []) or [n.text for n in names.extract(body, min_count=a.min,
                                                                  min_variety=1)]
    if not people:
        _p(f"{a.min}회 이상 나오는 인물을 찾지 못했습니다. --min 을 낮추거나 "
           "--name 으로 지정하세요.")
        return 1

    speeches = names.extract_speech(body, people)
    if not speeches:
        _p("대사를 찾지 못했습니다. 따옴표로 묶인 부분을 대사로 봅니다.")
        return 1

    profiles, unknown = names.voice_profiles(speeches)
    total = len(speeches)
    _p(f"대사 {total:,}개  ·  인물 {len(profiles)}명"
       f"  ·  화자 못 찾음 {unknown:,}개 ({unknown / total:.0%})\n")

    _grid(["인물", "대사", "비중", "평균", "존댓말", "자주 쓰는 어미"],
          [[p.name, f"{p.count:,}", f"{p.count / total:.0%}",
            f"{p.avg_length:.0f}자", f"{p.polite_ratio:.0%}",
            " ".join(f"{e}{n}" for e, n in p.top_endings) or "-"]
           for p in profiles[:a.limit]], limit=22)

    if unknown / total > 0.3:
        _p(f"\n화자를 못 찾은 대사가 {unknown / total:.0%} 입니다. 같은 줄에 이름이 "
           "없으면 비워 둡니다 - 억지로 채우면 집계가 어긋나서입니다.")

    if a.samples:
        _p("")
        for profile in profiles[:a.limit]:
            lines = [s.text for s in speeches if s.speaker == profile.name][:a.samples]
            _p(f"{profile.name}")
            for line in lines:
                _p(f"  \"{_cut(line, a.width)}\"")
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


# =================================================================== keys

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

    _p(f"\n{filled}개를 채웠습니다. 저장: {keys.USER_DATA}")
    return 0


def cmd_keys(a) -> int:
    try:
        groups, sources = keys.load_groups()
    except keys.KeysError as e:
        _p(str(e))
        return 1
    state = keys.State.load()

    if a.html:
        from . import keyhtml

        out = keyhtml.write(Path(a.html), groups, sources)
        _p(f"저장: {out}")
        _p("브라우저로 열면 탭 전환·검색·정렬이 되고, 조회 횟수는 그 브라우저에 남습니다.")
        return 0

    if a.list:
        _p(f"단축키 {sum(len(g.items) for g in groups)}개\n")
        for g in groups:
            _p(f"  {_pad(g.id, 8)}{_pad(g.name, 14)}{g.desc}  ({len(g.items)}개)")
        _p(f"\n사용자 파일: {keys.USER_DATA}")
        _p(f"조회 기록:   {keys.STATE_FILE}")
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
        _p(f"내 것만 채우려면 {keys.USER_DATA} 에 적으면 됩니다.")
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
            from . import keytui

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


def _keys_edit(groups) -> int:
    """사용자 단축키 파일 틀을 만들어 준다."""
    import json as _json

    path = keys.USER_DATA
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


# =================================================================== text

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


def cmd_novel_names(a) -> int:
    targets = manuscript.collect([Path(p) for p in a.paths])
    if not targets:
        _p("텍스트 파일을 찾지 못했습니다.")
        return 1

    body = manuscript.strip_markup("\n".join(manuscript.read_text(p) for p in targets))
    found = names.extract(body, min_count=a.min, min_variety=a.variety)
    known = [n.text for n in found] + list(a.name or [])

    if not found and not a.name:
        _p(f"{a.min}회 이상 나오는 이름 후보가 없습니다. --min 을 낮춰 보세요.")
        return 0

    speakers = names.dialogue_speakers(body, known)
    _p(f"이름 후보 {len(found)}개  (파일 {len(targets)}개)")
    _grid(["이름", "등장", "붙은 조사", "대사 뒤"],
          [[n.text, f"{n.count}회",
            " ".join(f"{p}{c}" for p, c in n.particles.most_common(4)),
            f"{speakers[n.text]}회" if speakers.get(n.text) else "-"]
           for n in found[:a.limit]], limit=a.width)
    if len(found) > a.limit:
        _p(f"  ... {len(found) - a.limit}개 더")
    _p("")

    shaky = names.variants(found, names.all_stems(body), distance=a.distance)
    if shaky:
        _p(f"표기 흔들림 의심 {len(shaky)}건")
        for confirmed, rare, dist in shaky[:a.limit]:
            _p(f"  {confirmed.text}({confirmed.count}회)  vs  "
               f"{rare.text}({rare.count}회)")
        _p("  드물게 나오는 쪽이 오타일 가능성이 큽니다.\n")

    if a.no_josa:
        return 0

    errors = names.check_josa(body, known)
    if not errors:
        _p("이름 뒤 조사는 문제 없습니다.")
        return 0

    _p(f"이름 뒤 조사 오류 {len(errors)}건")
    for e in errors[:a.limit]:
        _p(f"  {e.line}행  {e.name}{e.wrong} -> {e.name}{e.right}")
        _p(f"        …{e.excerpt}…")
    if len(errors) > a.limit:
        _p(f"  ... {len(errors) - a.limit}건 더")
    _p("\n행 번호는 파일을 이어 붙인 기준입니다.")
    return 1


def cmd_dev_log(a) -> int:
    lines: list[str] = []
    for source in a.files:
        if source == "-":
            lines += sys.stdin.read().splitlines()
            continue
        path = Path(source)
        if not path.is_file():
            _p(f"파일이 없습니다: {path}")
            return 1
        lines += manuscript.read_text(path).splitlines()

    if not lines:
        _p("읽을 내용이 없습니다.")
        return 1

    entries = logkit.parse(lines)
    levels = {l.upper() for l in a.level} if a.level else None
    if levels:
        unknown = levels - set(logkit.LEVELS) - {"WARN", "FATAL"}
        if unknown:
            _p(f"모르는 레벨입니다: {', '.join(unknown)}")
            return 1

    counts = logkit.level_counts(entries)
    first, last = logkit.span(entries)
    _p(f"{len(entries):,}줄" + (f"  ·  {first:%m-%d %H:%M} ~ {last:%m-%d %H:%M}"
                                if first and last else "  ·  시각 없음"))
    if counts:
        _p("  " + "  ".join(f"{k} {v:,}" for k, v in counts.items()))
    severe = sum(v for k, v in counts.items() if k in logkit.SEVERE)
    if severe and len(entries):
        _p(f"  심각 {severe:,}건 ({severe / len(entries):.1%})")
    _p("")

    series = logkit.histogram(entries, bucket=a.bucket, levels=levels)
    if series:
        peak = max(v for _, v in series)
        title = f"{a.bucket} 단위 분포" + (f" ({'/'.join(sorted(levels))})" if levels else "")
        _p(title)
        for when, count in series[-a.rows:]:
            bar = "█" * max(1, round(count / peak * 32))
            _p(f"  {when:%m-%d %H:%M}  {count:>6,}  {bar}")
        _p("")

        for when, count, ratio in logkit.spikes(series):
            _p(f"  급증: {when:%m-%d %H:%M} 에 {count:,}건 (평소의 {ratio:.1f}배)")
        _p("")

    groups = logkit.group_messages(entries, levels=levels or logkit.SEVERE, top=a.top)
    if not groups:
        _p("묶을 메시지가 없습니다.")
        return 0

    label = "/".join(sorted(levels)) if levels else "심각한 것"
    _p(f"반복되는 메시지 ({label}) 상위 {len(groups)}개")
    for g in groups:
        when = f"  {g.first:%m-%d %H:%M}~{g.last:%H:%M}" if g.first and g.last else ""
        _p(f"  {g.count:>5,}회  [{g.level or '-'}]{when}")
        _p(f"         {_cut(g.sample, a.width)}")
        if a.lines:
            _p(f"         줄 {', '.join(str(n) for n in g.lines)}")
    _p("\n숫자·UUID·IP·경로 같은 값은 <n>, <uuid> 처럼 바꿔서 같은 사고끼리 묶었습니다.")
    return 0


def _sheet_result(a, table, headline: str) -> int:
    _p(f"{headline}  {len(table.rows):,}행 x {table.width}열")
    if not table.rows:
        _p("맞는 행이 없습니다.")
        return 1

    _grid(table.headers,
          [[sheet.to_text(v) for v in r] for r in table.rows[:a.rows]],
          limit=a.width)
    if len(table.rows) > a.rows:
        _p(f"  ... {len(table.rows) - a.rows:,}행 더")

    if a.out:
        _p(f"\n저장: {sheet.save(table, Path(a.out))}")
    else:
        _p("\n저장하려면 -o 로 출력 파일을 지정하세요.")
    return 0


def cmd_sheet_cut(a) -> int:
    t = _load(a)
    if t is None:
        return 1
    try:
        result = sheet.cut(t, a.col, drop=a.drop)
    except sheet.SheetError as e:
        _p(str(e))
        return 1
    return _sheet_result(a, result, "열 " + ("빼기" if a.drop else "고르기"))


def cmd_sheet_where(a) -> int:
    t = _load(a)
    if t is None:
        return 1

    conditions = []
    try:
        for op in ("eq", "ne", "gt", "gte", "lt", "lte", "has"):
            for spec in getattr(a, op) or []:
                conditions.append(sheet.Condition.parse(op, spec))
        if not conditions:
            _p("조건을 하나 이상 주세요. 예: --eq 부서=영업  --gte 연봉=5000만")
            return 1
        result = sheet.where(t, conditions, any_match=a.any)
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    words = {"eq": "=", "ne": "≠", "gt": ">", "gte": "≥", "lt": "<", "lte": "≤",
             "has": "포함"}
    joined = (" 또는 " if a.any else " 그리고 ").join(
        f"{c.column} {words[c.op]} {c.value}" for c in conditions)
    return _sheet_result(a, result, f"{len(t.rows):,}행 중  {joined}  ->")


def cmd_sheet_sort(a) -> int:
    t = _load(a)
    if t is None:
        return 1
    try:
        result = sheet.sort_rows(t, a.by, descending=a.desc)
    except sheet.SheetError as e:
        _p(str(e))
        return 1
    order = "내림차순" if a.desc else "오름차순"
    return _sheet_result(a, result, f"{', '.join(a.by)} {order} 정렬")


def cmd_sheet_sample(a) -> int:
    t = _load(a)
    if t is None:
        return 1
    result = sheet.sample(t, a.number, seed=a.seed, head=a.head)
    how = "앞에서" if a.head else "무작위로"
    return _sheet_result(a, result, f"{len(t.rows):,}행에서 {how} {len(result.rows):,}행")


def cmd_sheet_split(a) -> int:
    t = _load(a)
    if t is None:
        return 1
    if bool(a.rows_per) == bool(a.by):
        _p("--rows 나 --by 중 하나만 주세요.")
        return 1

    source = Path(a.file)
    out_dir = Path(a.out) if a.out else source.parent
    suffix = a.format or (source.suffix.lower() if source.suffix.lower() in
                          (sheet.CSV_SUFFIXES | sheet.XLSX_SUFFIXES) else ".csv")
    if not suffix.startswith("."):
        suffix = "." + suffix

    try:
        pieces = ({f"{source.stem}-{i:03d}": part
                   for i, part in enumerate(sheet.split_rows(t, a.rows_per), 1)}
                  if a.rows_per else
                  {f"{source.stem}-{k}": part
                   for k, part in sheet.split_by(t, a.by).items()})
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    _p(f"{len(t.rows):,}행 -> 파일 {len(pieces)}개")
    for name, part in pieces.items():
        safe = hangul.sanitize_filename(f"{name}{suffix}")
        target = out_dir / safe
        if not a.apply:
            _p(f"  [미리보기] {target.name}  {len(part.rows):,}행")
            continue
        sheet.save(part, target, sheet_name=part.sheet or "Sheet1")
        _p(f"  {target}  {len(part.rows):,}행")

    if not a.apply:
        _p("\n실제로 저장하려면 --apply 를 붙이세요.")
    return 0


def cmd_sheet_fill(a) -> int:
    t = _load(a)
    if t is None:
        return 1

    template_path = Path(a.template)
    if not template_path.is_file():
        _p(f"틀 파일이 없습니다: {template_path}")
        return 1
    template = template_path.read_text(encoding=sheet.sniff_encoding(template_path))

    used = sheet.placeholders(template)
    if not used:
        _p(f"{template_path} 에 {{열이름}} 자리표시자가 없습니다.")
        _p(f"쓸 수 있는 열: {', '.join(t.headers)}, 번호")
        return 1

    default_name = a.name or f"{{번호:03d}}{template_path.suffix or '.txt'}"
    results, missing = sheet.fill(t, template, name_template=default_name)

    if missing:
        _p(f"표에 없는 자리표시자 {len(missing)}개: {', '.join(sorted(missing))}")
        _p(f"  있는 열: {', '.join(t.headers)}, 번호")
        if not a.force:
            _p("  그래도 진행하려면 --force 를 붙이세요. 빈칸으로 채웁니다.")
            return 1
        _p("")

    if a.single or a.stdout:
        joined = ("\n" + a.separator + "\n").join(r.text for r in results)
        if a.stdout:
            sys.stdout.write(joined)
            return 0
        target = Path(a.out or f"합본{template_path.suffix or '.txt'}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(joined, encoding="utf-8")
        _p(f"{len(results)}건을 한 파일로 저장: {target}")
        return 0

    out_dir = Path(a.out or "채운문서")
    _p(f"{len(results)}건  ·  틀 {template_path.name}  ·  {out_dir}/")
    for r in results[:a.limit]:
        name = hangul.sanitize_filename(r.name)
        if not a.apply:
            _p(f"  [미리보기] {name}")
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / name).write_text(r.text, encoding="utf-8")
        _p(f"  {name}")
    if len(results) > a.limit and not a.apply:
        _p(f"  ... {len(results) - a.limit}건 더")
    elif a.apply and len(results) > a.limit:
        for r in results[a.limit:]:
            (out_dir / hangul.sanitize_filename(r.name)).write_text(r.text, encoding="utf-8")
        _p(f"  ... 그 밖에 {len(results) - a.limit}건")

    if not a.apply:
        _p(f"\n첫 건 미리보기\n{'-' * 40}")
        _p(_cut(results[0].text, 600))
        _p("-" * 40)
        _p("실제로 만들려면 --apply 를 붙이세요.")
    return 0


def cmd_life_workday(a) -> int:
    from datetime import date as _date

    extra = life.load_user_holidays(a.holidays)

    if a.list:
        year = int(a.list)
        table = life.holidays_for(year, extra)
        _p(f"{year}년 공휴일 {len(table)}일")
        for when, name in table.items():
            mark = "  (주말)" if when.weekday() >= 5 else ""
            _p(f"  {when:%Y-%m-%d}({life.weekday_ko(when)})  {name}{mark}")
        warning = life.missing_lunar_warning(table, [year])
        if warning:
            _p("")
            for line in warning:
                _p(line)
        return 0

    if not a.start:
        _p("시작일을 주세요. 예: at life workday 2026-08-14 +5")
        return 1

    try:
        start = life.parse_date(a.start)
    except ValueError:
        _p(f"날짜를 해석하지 못했습니다: {a.start}")
        return 1

    target = (a.target or "").strip()
    years = {start.year}
    if target and (target[0] in "+-" and target[1:].isdigit()):
        days = int(target)
        years.add((start + life.timedelta(days=days * 2 + 14)).year)
        holidays = {}
        for y in sorted(years) + [max(years) + 1]:
            holidays.update(life.holidays_for(y, extra))
        end = life.add_workdays(start, days, holidays)
        _p(f"{start:%Y-%m-%d}({life.weekday_ko(start)}) 에서 "
           f"{abs(days)}영업일 {'뒤' if days > 0 else '앞'}")
        _p(f"  -> {end:%Y-%m-%d}({life.weekday_ko(end)})")
        _p(f"  달력으로는 {abs((end - start).days)}일")
    else:
        try:
            end = life.parse_date(target) if target else _date.today()
        except ValueError:
            _p(f"날짜나 +N/-N 형태로 주세요: {target}")
            return 1
        years.add(end.year)
        holidays = {}
        for y in range(min(years), max(years) + 1):
            holidays.update(life.holidays_for(y, extra))
        count = life.count_workdays(start, end, holidays, include_start=not a.exclusive)
        first, last = min(start, end), max(start, end)
        _p(f"{first:%Y-%m-%d}({life.weekday_ko(first)}) ~ "
           f"{last:%Y-%m-%d}({life.weekday_ko(last)})")
        _p(f"  영업일 {count}일  ·  달력 {(last - first).days + 1}일")
        blocked = [f"{d:%m-%d} {n}" for d, n in sorted(holidays.items())
                   if first <= d <= last and d.weekday() < 5]
        if blocked:
            _p(f"  낀 공휴일: {', '.join(blocked)}")

    for line in life.missing_lunar_warning(holidays, sorted(years)):
        _p(f"  {line}")
    return 0


def cmd_sheet_report(a) -> int:
    from datetime import date as _date, datetime as _datetime

    t = _load(a)
    if t is None:
        return 1
    if not t.rows:
        _p("행이 없습니다.")
        return 1

    source = Path(a.file)
    profiles = sheet.profile(t)
    blanks = sum(p.missing for p in profiles)
    cells = len(t.rows) * t.width

    tiles = [report.Tile("행", f"{len(t.rows):,}"),
             report.Tile("열", f"{t.width:,}"),
             report.Tile("빈 칸", f"{blanks / cells:.1%}" if cells else "-",
                         f"{blanks:,}칸")]

    sections: list[str] = []

    if a.value:
        try:
            numbers = [v for v in t.column(a.value)
                       if isinstance(v, (int, float)) and not isinstance(v, bool)]
        except sheet.SheetError as e:
            _p(str(e))
            return 1
        if numbers:
            tiles.append(report.Tile(f"{a.value} 합계", f"{sum(numbers):,.0f}",
                                     f"평균 {sum(numbers) / len(numbers):,.0f}"))
    sections.append(f"<section>{report.tiles_html(tiles)}</section>")

    if a.by:
        try:
            grouped = sheet.pivot(t, rows=[a.by], values=a.value, agg=a.agg)
        except sheet.SheetError as e:
            _p(str(e))
            return 1
        pairs = [(str(r[0]), float(r[1])) for r in grouped.rows
                 if isinstance(r[1], (int, float))]
        pairs.sort(key=lambda x: -x[1])
        top = pairs[:a.top]
        agg_names = {"sum": "합계", "avg": "평균", "count": "건수",
                     "min": "최소", "max": "최대"}
        label = f"{a.value} {agg_names[a.agg]}" if a.value else "건수"
        note = f"상위 {len(top)}개" + (f" / 전체 {len(pairs)}개" if len(pairs) > len(top) else "")
        sections.append(
            f'<section><h2>{escape_html(a.by)}별 {escape_html(label)}'
            f'<span class="note">{escape_html(note)}</span></h2>'
            + report.bar_chart(top)
            + '<details><summary>값을 표로 보기</summary>'
            + report.table_html([a.by, label],
                                [[name, f"{value:,.0f}"] for name, value in top],
                                numeric={1})
            + "</details></section>")

    if a.date:
        try:
            index = t.index_of(a.date)
        except sheet.SheetError as e:
            _p(str(e))
            return 1
        buckets: dict[str, float] = {}
        fmt = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}[a.period]
        period_name = {"day": "일", "month": "월", "year": "연"}[a.period]
        for row in t.rows:
            when = row[index] if index < len(row) else None
            if isinstance(when, _datetime):
                when = when.date()
            if not isinstance(when, _date):
                continue
            key = when.strftime(fmt)
            if a.value:
                cell = row[t.index_of(a.value)]
                buckets[key] = buckets.get(key, 0.0) + (
                    float(cell) if isinstance(cell, (int, float))
                    and not isinstance(cell, bool) else 0.0)
            else:
                buckets[key] = buckets.get(key, 0.0) + 1

        series = sorted(buckets.items())
        if series:
            label = f"{a.value} 합계" if a.value else "건수"
            sections.append(
                f'<section><h2>{escape_html(a.date)} 기준 {escape_html(label)} 추이'
                f'<span class="note">{period_name} 단위 · {len(series)}구간</span></h2>'
                + report.line_chart(series)
                + '<details><summary>값을 표로 보기</summary>'
                + report.table_html([a.date, label],
                                    [[k, f"{v:,.0f}"] for k, v in series], numeric={1})
                + "</details></section>")
        else:
            _p(f"'{a.date}' 열에서 날짜를 찾지 못해 추이는 넣지 않았습니다.")

    sections.append(
        "<section><h2>열 요약</h2>"
        + report.table_html(
            ["열", "타입", "빈 칸", "고유", "최소", "최대"],
            [[p.name, p.main_kind + ("(혼재)" if p.mixed else ""),
              f"{p.missing:,}", f"{p.unique:,}",
              _report_value(p.minimum), _report_value(p.maximum)]
             for p in profiles], numeric={2, 3})
        + "</section>")

    preview = t.rows[:a.rows]
    sections.append(
        f'<section><h2>데이터<span class="note">앞 {len(preview):,}행</span></h2>'
        + report.table_html(t.headers,
                            [[sheet.to_text(v) for v in row] for row in preview])
        + "</section>")

    title = a.title or source.stem
    subtitle = (f"{source.name}"
                + (f" · {t.sheet}" if t.sheet else "")
                + f" · {len(t.rows):,}행 × {t.width}열"
                + f" · {devkit.datetime.now():%Y-%m-%d %H:%M} 기준")
    html = report.page(title, subtitle, sections,
                       note="attools 로 만든 보고서입니다.")

    out = Path(a.out or f"{source.stem}-보고서.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    _p(f"저장: {out}")
    _p(f"  {len(sections)}개 절 · {len(t.rows):,}행에서 뽑았습니다.")
    return 0


def _report_value(value) -> str:
    """보고서 표에 넣을 값. 큰 숫자는 천 단위를 넣어야 읽힌다."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return sheet.to_text(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return sheet.to_text(value)


def escape_html(text: str) -> str:
    from html import escape

    return escape(str(text))


# ==================================================================== doc

MD_SUFFIXES = {".md", ".markdown"}


def _md_files(paths) -> list[Path]:
    out: list[Path] = []
    for name in paths:
        p = Path(name)
        if p.is_dir():
            out += [q for q in sorted(p.rglob("*"))
                    if q.suffix.lower() in MD_SUFFIXES
                    and not any(d in q.parts for d in files.IGNORE_DIRS)]
        elif p.is_file():
            out.append(p)
    return out


def cmd_doc_toc(a) -> int:
    targets = _md_files(a.paths)
    if not targets:
        _p("마크다운 파일을 찾지 못했습니다.")
        return 1

    touched = 0
    for path in targets:
        body = path.read_text(encoding="utf-8", errors="replace")
        toc = mdkit.build_toc(mdkit.headings(body), depth=a.depth,
                              skip_first_h1=not a.keep_h1)
        if not toc:
            continue

        if not a.apply:
            _p(f"{path}")
            _p(toc + "\n")
            continue

        new_body, changed = mdkit.update_toc(body, toc)
        if not changed:
            marker = mdkit.TOC_START in body
            _p(f"{path}: " + ("이미 최신입니다." if marker
                              else f"표시가 없습니다. 넣을 자리에 {mdkit.TOC_START} 와 "
                                   f"{mdkit.TOC_END} 를 적어 두세요."))
            continue
        path.write_text(new_body, encoding="utf-8")
        _p(f"{path}: 목차를 갱신했습니다.")
        touched += 1

    if not a.apply:
        _p(f"{mdkit.TOC_START} 와 {mdkit.TOC_END} 사이에 넣으려면 --apply 를 붙이세요.")
    return 0


def cmd_doc_links(a) -> int:
    targets = _md_files(a.paths)
    if not targets:
        _p("마크다운 파일을 찾지 못했습니다.")
        return 1

    total = 0
    for path in targets:
        issues = mdkit.check_links(path)
        if not issues:
            continue
        total += len(issues)
        _p(f"{path}  {len(issues)}건")
        for i in issues[:a.limit]:
            _p(f"  {i.line}행  [{i.kind}] {i.detail}")
        _p("")

    if not total:
        _p(f"파일 {len(targets)}개, 깨진 링크 없습니다.")
        return 0
    _p(f"모두 {total}건. 외부 URL 은 확인하지 않았습니다.")
    return 1


def cmd_doc_check(a) -> int:
    targets = _md_files(a.paths)
    if not targets:
        _p("마크다운 파일을 찾지 못했습니다.")
        return 1

    total = 0
    for path in targets:
        body = path.read_text(encoding="utf-8", errors="replace")
        issues = mdkit.check_headings(body)
        items = mdkit.headings(body)
        if a.outline:
            _p(f"{path}  제목 {len(items)}개")
            for h in items[:a.limit]:
                _p(f"  {'  ' * (h.level - 1)}H{h.level} {h.title}")
            _p("")
        if not issues:
            continue
        total += len(issues)
        _p(f"{path}  {len(issues)}건")
        for i in issues:
            _p(f"  {i.line}행  [{i.kind}] {i.detail}")
        _p("")

    if not total:
        _p(f"파일 {len(targets)}개, 제목 구조에 문제 없습니다.")
        return 0
    return 1


def cmd_dev_bench(a) -> int:
    commands: list[tuple[object, bool, str]] = []
    for text in a.cmd or []:
        commands.append((text, True, text))
    if a.command:
        commands.append((a.command, False, " ".join(a.command)))
    if not commands:
        _p("측정할 명령을 주세요.")
        _p('  at dev bench -n 10 -- python3 a.py')
        _p('  at dev bench --cmd "python3 a.py" --cmd "python3 b.py"')
        return 1

    results = []
    for command, shell, label in commands:
        _p(f"측정 중: {label}  ({a.warmup}회 예열 + {a.runs}회)")
        results.append(devkit.run_bench(command, label=label, runs=a.runs,
                                        warmup=a.warmup, shell=shell))
    _p("")

    fmt = devkit.format_seconds
    for n, r in enumerate(results, 1):
        _p(f"{n}) {r.label}")
        if not r.times:
            _p("   실행하지 못했습니다.")
            continue
        _p(f"   평균 {fmt(r.mean)}  중앙 {fmt(r.median)}  "
           f"최소 {fmt(r.fastest)}  최대 {fmt(r.slowest)}  편차 {fmt(r.stdev)}")
        if r.failures:
            _p(f"   실패 {r.failures}/{r.runs}회 - 시간을 믿기 어렵습니다.")

    usable = [r for r in results if r.times]
    if len(usable) > 1:
        best = min(usable, key=lambda r: r.median)
        _p(f"\n가장 빠름: {best.label}")
        for r in usable:
            if r is best:
                continue
            ratio = r.median / best.median if best.median else 0
            spread = max(r.stdev, best.stdev)
            note = "  (편차가 커서 차이가 뚜렷하지 않습니다)" if abs(
                r.median - best.median) < spread else ""
            _p(f"  {r.label}: {ratio:.2f}배 느림{note}")
    return 0


def cmd_dev_ports(a) -> int:
    try:
        ports = devkit.listening_ports()
    except RuntimeError as e:
        _p(str(e))
        return 1

    if a.filter:
        needle = a.filter.lower()
        ports = [p for p in ports
                 if needle in p.name.lower() or needle == str(p.port)]
    if not ports:
        _p("열려 있는 포트가 없습니다." if not a.filter else "맞는 포트가 없습니다.")
        return 0

    _grid(["포트", "프로세스", "PID", "주소"],
          [[str(p.port), p.name, str(p.pid) if p.pid else "-", p.address or "-"]
           for p in ports[:a.limit]], limit=24)
    if len(ports) > a.limit:
        _p(f"  ... {len(ports) - a.limit}개 더")
    _p(f"\n{len(ports)}개.  하나를 종료하려면: at dev port <번호> --kill")
    return 0


def cmd_git_branches(a) -> int:
    root = _repo(a)
    if root is None:
        return 1
    try:
        branches = gitkit.list_branches(root, remote=a.remote)
    except RuntimeError as e:
        _p(str(e))
        return 1

    if not branches:
        _p("브랜치가 없습니다.")
        return 0
    if a.stale:
        branches = [b for b in branches
                    if b.age_days is not None and b.age_days >= a.stale]
        if not branches:
            _p(f"{a.stale}일 넘게 손대지 않은 브랜치가 없습니다.")
            return 0

    rows = []
    for b in branches[:a.limit]:
        mark = "*" if b.current else ""
        track = "원격 사라짐" if b.gone else (
            " ".join(filter(None, [f"앞 {b.ahead}" if b.ahead else "",
                                   f"뒤 {b.behind}" if b.behind else ""]))
            or ("맞춰짐" if b.upstream else "-"))
        rows.append([mark + b.name,
                     f"{b.age_days}일" if b.age_days is not None else "-",
                     b.author, track, b.subject])
    _grid(["브랜치", "마지막", "사람", "원격", "마지막 커밋"], rows, limit=34)
    if len(branches) > a.limit:
        _p(f"  ... {len(branches) - a.limit}개 더")

    gone = [b for b in branches if b.gone]
    _p(f"\n{len(branches)}개" + (f"  ·  원격이 사라진 것 {len(gone)}개"
                                  "  ·  정리하려면 at git sweep --fetch" if gone else ""))
    return 0


# =================================================================== json

def _json_load(a, source):
    try:
        return jsonkit.load(source)
    except jsonkit.JsonError as e:
        _p(str(e))
        return None


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


# ===================================================================== main

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="at", description="파일 / 텍스트 / JSON / 개발 / git / 엑셀 / 단축키 / 일상 / 소설 자동화 도구")
    ap.add_argument("-V", "--version", action="version", version=f"attools {__version__}")
    sub = ap.add_subparsers(dest="group", required=True)

    # ---- file
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

    # ---- dev
    dp = sub.add_parser("dev", help="백엔드 개발 잡일").add_subparsers(dest="cmd", required=True)

    e = dp.add_parser("env", help=".env 와 .env.example 대조")
    e.add_argument("example", nargs="?", default=".env.example")
    e.add_argument("actual", nargs="?", default=".env")
    e.add_argument("--show-extra", action="store_true")
    e.add_argument("--show-values", action="store_true", help="값을 마스킹해 출력")
    e.add_argument("--sync", action="store_true",
                   help=".env 에서 .env.example 을 만든다 (비밀값은 자리표시자로)")
    e.add_argument("--keep-values", action="store_true",
                   help="--sync 에서 비밀이 아닌 값은 그대로 둔다")
    e.add_argument("--apply", action="store_true", help="--sync 결과를 실제로 쓴다")
    e.set_defaults(func=cmd_dev_env)

    pt = dp.add_parser("port", help="포트 점유 프로세스 확인/종료")
    pt.add_argument("port", type=int)
    pt.add_argument("--kill", action="store_true")
    pt.add_argument("--force", action="store_true", help="SIGKILL")
    pt.add_argument("-y", "--yes", action="store_true", help="확인 없이 종료")
    pt.set_defaults(func=cmd_dev_port)

    pl = dp.add_parser("ports", help="열려 있는 포트 전부 보기")
    pl.add_argument("filter", nargs="?", metavar="이름|번호",
                    help="프로세스 이름이나 포트 번호로 거르기")
    pl.add_argument("--limit", type=int, default=40)
    pl.set_defaults(func=cmd_dev_ports)

    j = dp.add_parser("jwt", help="JWT 내용 확인 (서명 검증 안 함)")
    j.add_argument("token", nargs="?", default="-")
    j.set_defaults(func=cmd_dev_jwt)

    t = dp.add_parser("time", help="epoch <-> KST/UTC 변환")
    t.add_argument("when", nargs="?", default="now", help="epoch, ISO 문자열, now")
    t.set_defaults(func=cmd_dev_time)

    wt = dp.add_parser("wait", help="포트/URL 이 열릴 때까지 대기")
    wt.add_argument("target", help="host:port 또는 http(s):// URL")
    wt.add_argument("-t", "--timeout", type=float, default=60.0, metavar="초")
    wt.add_argument("-i", "--interval", type=float, default=1.0, metavar="초")
    wt.add_argument("-q", "--quiet", action="store_true")
    wt.set_defaults(func=cmd_dev_wait)

    cr = dp.add_parser("cron", help="cron 표현식 해석과 다음 실행 시각")
    cr.add_argument("expression", help='예: "0 9 * * 1-5", @daily')
    cr.add_argument("-n", "--count", type=int, default=5)
    cr.set_defaults(func=cmd_dev_cron)

    g = dp.add_parser("gen", help="비밀번호·토큰·UUID 생성")
    g.add_argument("kind", nargs="?", default="password",
                   choices=["password", "token", "hex", "uuid", "pin"])
    g.add_argument("-l", "--length", type=int, default=20)
    g.add_argument("-n", "--count", type=int, default=1)
    g.add_argument("--readable", action="store_true", help="0/O/l/1 처럼 헷갈리는 문자 제외")
    g.set_defaults(func=cmd_dev_gen)

    en = dp.add_parser("enc", help="base64/hex/URL 인코딩·디코딩 한 번에")
    en.add_argument("value", nargs="?", default="-")
    en.set_defaults(func=cmd_dev_enc)

    bn = dp.add_parser("bench", help="명령 실행 시간 측정·비교")
    bn.add_argument("-n", "--runs", type=int, default=10, metavar="회")
    bn.add_argument("-w", "--warmup", type=int, default=1, metavar="회",
                    help="측정에 넣지 않고 먼저 돌릴 횟수")
    bn.add_argument("--cmd", action="append", metavar="명령",
                    help="셸로 실행. 여러 번 주면 서로 비교한다")
    bn.epilog = ('예: at dev bench -n 20 -- pytest -q\n'
                 '    at dev bench --cmd "sort a.txt" --cmd "sort -S1M a.txt"')
    bn.set_defaults(func=cmd_dev_bench, command=[])

    lg = dp.add_parser("log", help="로그 레벨 집계·시간대 분포·반복 에러 묶기")
    lg.add_argument("files", nargs="+", metavar="파일")
    lg.add_argument("-l", "--level", action="append", metavar="레벨",
                    help="예: -l ERROR -l WARN")
    lg.add_argument("-b", "--bucket", default="1h", choices=list(logkit.BUCKETS))
    lg.add_argument("--top", type=int, default=10)
    lg.add_argument("--rows", type=int, default=24, metavar="개",
                help="분포는 최근 이만큼만 보여준다")
    lg.add_argument("--width", type=int, default=90, metavar="칸")
    lg.add_argument("--lines", action="store_true", help="해당 줄 번호도 표시")
    lg.set_defaults(func=cmd_dev_log)

    m = dp.add_parser("mask", help="로그의 개인정보·시크릿 가리기")
    m.add_argument("file", nargs="?", default="-")
    m.add_argument("--in-place", action="store_true")
    m.set_defaults(func=cmd_dev_mask)

    # ---- git
    gp = sub.add_parser("git", help="git 저장소 정리·검사").add_subparsers(dest="cmd", required=True)

    br = gp.add_parser("branches", help="브랜치 목록 - 마지막 커밋·사람·원격 차이")
    br.add_argument("dir", nargs="?", default=".")
    br.add_argument("--remote", action="store_true", help="원격 브랜치를 본다")
    br.add_argument("--stale", type=int, default=0, metavar="일",
                    help="이만큼 손대지 않은 것만")
    br.add_argument("--limit", type=int, default=40)
    br.set_defaults(func=cmd_git_branches)

    sw = gp.add_parser("sweep", help="병합 끝난 브랜치, 원격 사라진 브랜치 정리")
    sw.add_argument("dir", nargs="?", default=".")
    sw.add_argument("--base", help="기준 브랜치 (기본: origin/HEAD)")
    sw.add_argument("--fetch", action="store_true", help="먼저 fetch --prune")
    sw.add_argument("--apply", action="store_true")
    sw.add_argument("--force", action="store_true", help="원격이 사라진 브랜치도 강제 삭제")
    sw.set_defaults(func=cmd_git_sweep)

    td = gp.add_parser("todo", help="코드의 TODO·FIXME 를 작성자·방치 기간과 함께 모으기")
    td.add_argument("dir", nargs="?", default=".")
    td.add_argument("-m", "--marker", action="append", metavar="표시",
                    help="예: -m FIXME -m BUG (기본 전체)")
    td.add_argument("-g", "--glob", action="append", metavar="패턴")
    td.add_argument("-s", "--sort", default="age",
                    choices=["age", "severity", "file", "author"])
    td.add_argument("--limit", type=int, default=30)
    td.add_argument("--width", type=int, default=46, metavar="칸")
    td.add_argument("--all", action="store_true", help="추적 안 되는 파일까지")
    td.add_argument("--no-blame", action="store_true", help="git blame 생략 (빠름)")
    td.set_defaults(func=cmd_git_todo)

    st = gp.add_parser("stats", help="커밋 통계와 자주 바뀌는 파일")
    st.add_argument("dir", nargs="?", default=".")
    st.add_argument("--since", default="", metavar="기간",
                    help="예: '30 days ago', '2026-01-01'")
    st.add_argument("--until", default="", metavar="기간")
    st.add_argument("--path", action="append", metavar="경로", help="이 경로만")
    st.add_argument("--by", choices=["day", "week", "month", "hour"],
                    help="기간별 분포도 함께")
    st.add_argument("--weekday", action="store_true", help="요일별 분포도 함께")
    st.add_argument("--limit", type=int, default=15)
    st.add_argument("--rows", type=int, default=20, metavar="개")
    st.add_argument("--max-commits", type=int, default=0, metavar="개")
    st.set_defaults(func=cmd_git_stats)

    rl = gp.add_parser("release", help="태그 사이 커밋으로 변경 로그 초안 만들기")
    rl.add_argument("dir", nargs="?", default=".")
    rl.add_argument("--since", metavar="리비전", help="기본: 최근 태그")
    rl.add_argument("--until", default="HEAD", metavar="리비전")
    rl.add_argument("--title", default="", metavar="제목", help="예: 0.11.0")
    rl.add_argument("--link", metavar="주소",
                    help="커밋 링크 앞부분 (예: https://github.com/A/B/commit/)")
    rl.add_argument("--authors", action="store_true", help="기여자 목록도")
    rl.add_argument("-o", "--out", metavar="파일", help="CHANGELOG.md 맨 위에 붙인다")
    rl.set_defaults(func=cmd_git_release)

    sc = gp.add_parser("scan", help="코드에 하드코딩된 시크릿·개인정보 찾기")
    sc.add_argument("dir", nargs="?", default=".")
    sc.add_argument("--staged", action="store_true", help="스테이징된 파일만 (훅용)")
    sc.add_argument("--all", action="store_true", help="추적 안 되는 파일까지")
    sc.add_argument("--entropy", type=float, default=0.0, metavar="비트",
                    help="무작위해 보이는 문자열도 신고 (예: 4.0)")
    sc.add_argument("-q", "--quiet", action="store_true", help="문제 없으면 아무것도 출력 안 함")
    sc.add_argument("--install-hook", nargs="?", const="at", metavar="명령경로",
                    help="pre-commit 훅으로 설치")
    sc.set_defaults(func=cmd_git_scan)

    # ---- life
    lp = sub.add_parser("life", help="일상 계산기").add_subparsers(dest="cmd", required=True)

    dd = lp.add_parser("dday", help="D-day, 만 나이, 기념일")
    dd.add_argument("dates", nargs="+", metavar="날짜")
    dd.add_argument("--today", help="기준일 (기본 오늘)")
    dd.add_argument("-n", "--count", type=int, default=4)
    dd.add_argument("--no-milestones", action="store_true")
    dd.set_defaults(func=cmd_life_dday)

    sp = lp.add_parser("split", help="더치페이 정산")
    sp.add_argument("paid", nargs="+", metavar="이름=금액")
    sp.add_argument("--extra", action="append", metavar="이름",
                    help="돈은 안 냈지만 나눠 낼 사람")
    sp.set_defaults(func=cmd_life_split)

    ln = lp.add_parser("loan", help="대출 상환액 계산")
    ln.add_argument("principal", metavar="원금", help="예: 3억5000만, 250000000")
    ln.add_argument("rate", type=float, metavar="연이율")
    ln.add_argument("years", type=float, nargs="?", metavar="년")
    ln.add_argument("--months", type=int, default=0)
    ln.add_argument("--kind", default="원리금균등",
                    choices=["원리금균등", "원금균등", "만기일시"])
    ln.add_argument("--grace", type=int, default=0, metavar="개월", help="거치기간")
    ln.add_argument("--table", type=int, default=0, metavar="회차",
                    help="상환표 출력 (-1 이면 전체)")
    ln.set_defaults(func=cmd_life_loan)

    wd = lp.add_parser("workday", help="영업일 계산과 공휴일 목록")
    wd.add_argument("start", nargs="?", metavar="시작일")
    wd.add_argument("target", nargs="?", metavar="끝날짜|+N|-N",
                    help="날짜면 그 사이 영업일 수, +5 면 5영업일 뒤")
    wd.add_argument("--list", metavar="연도", help="그 해 공휴일 목록")
    wd.add_argument("--holidays", metavar="파일",
                    help="음력 명절 등을 적어 둔 파일 (기본 ~/.attools/holidays.txt)")
    wd.add_argument("--exclusive", action="store_true", help="시작일을 세지 않는다")
    wd.set_defaults(func=cmd_life_workday)

    un = lp.add_parser("unit", help="단위 변환 (평/㎡, 근/돈, 마일, 화씨…)")
    un.add_argument("value", nargs="+", metavar="값+단위", help="예: 84㎡, 30평, 1근, 100F")
    un.set_defaults(func=cmd_life_unit)

    # ---- sheet
    sh = sub.add_parser("sheet", help="엑셀·CSV 실무 보조").add_subparsers(dest="cmd", required=True)

    def common(parser):
        parser.add_argument("--sheet", help="xlsx 시트 이름")
        parser.add_argument("--header-row", type=int, default=1, metavar="행",
                            help="헤더가 있는 행 번호 (기본 1)")
        return parser

    pk = common(sh.add_parser("peek", help="열 구성·타입·결측 훑어보기"))
    pk.add_argument("file")
    pk.add_argument("-n", "--rows", type=int, default=5, help="미리보기 행 수 (0이면 생략)")
    pk.add_argument("--width", type=int, default=24, metavar="칸", help="열 표시 폭")
    pk.set_defaults(func=cmd_sheet_peek)

    ck = common(sh.add_parser("check", help="중복 키·결측·타입 혼재 검증"))
    ck.add_argument("file")
    ck.add_argument("--key", help="중복을 보면 안 되는 열 (사번, 주문번호 등)")
    ck.add_argument("--required", action="append", metavar="열", help="비면 안 되는 열")
    ck.set_defaults(func=cmd_sheet_check)

    cl = common(sh.add_parser("clean", help="공백·숫자·날짜 정리"))
    cl.add_argument("file")
    cl.add_argument("-o", "--out", help="저장 경로 (.csv 또는 .xlsx)")
    cl.add_argument("--dedupe", action="store_true", help="완전히 같은 행 제거")
    cl.set_defaults(func=cmd_sheet_clean)

    mg = common(sh.add_parser("merge", help="여러 파일을 세로로 합치기"))
    mg.add_argument("files", nargs="+")
    mg.add_argument("-o", "--out")
    mg.add_argument("--no-source", action="store_true", help="출처 열을 넣지 않는다")
    mg.add_argument("--strict", action="store_true", help="열 구성이 다르면 중단")
    mg.set_defaults(func=cmd_sheet_merge)

    df = common(sh.add_parser("diff", help="두 파일을 키 기준으로 비교"))
    df.add_argument("before")
    df.add_argument("after")
    df.add_argument("--key", required=True, metavar="열")
    df.add_argument("--limit", type=int, default=20)
    df.set_defaults(func=cmd_sheet_diff)

    pv = common(sh.add_parser("pivot", help="그룹별 집계·교차표"))
    pv.add_argument("file")
    pv.add_argument("--rows", action="append", required=True, metavar="열")
    pv.add_argument("--cols", metavar="열", help="교차표 열 기준")
    pv.add_argument("--values", metavar="열", help="집계할 값 (없으면 건수)")
    pv.add_argument("--agg", default="sum", choices=list(sheet.AGGS))
    pv.add_argument("-o", "--out")
    pv.set_defaults(func=cmd_sheet_pivot)

    def sheet_out(parser):
        parser.add_argument("-o", "--out", metavar="파일")
        parser.add_argument("--rows", type=int, default=10, metavar="개",
                            dest="rows", help="미리보기 행 수")
        parser.add_argument("--width", type=int, default=20, metavar="칸")
        return parser

    ct = sheet_out(common(sh.add_parser("cut", help="열 고르기 · 빼기")))
    ct.add_argument("file")
    ct.add_argument("-c", "--col", action="append", required=True, metavar="열")
    ct.add_argument("--drop", action="store_true", help="고른 열을 빼고 나머지를 남긴다")
    ct.set_defaults(func=cmd_sheet_cut)

    wh = sheet_out(common(sh.add_parser("where", help="조건에 맞는 행만")))
    wh.add_argument("file")
    for op, help_text in (("eq", "같다"), ("ne", "다르다"), ("gt", "크다"), ("gte", "크거나 같다"),
                          ("lt", "작다"), ("lte", "작거나 같다"), ("has", "포함한다")):
        wh.add_argument(f"--{op}", action="append", metavar="열=값", help=help_text)
    wh.add_argument("--any", action="store_true", help="하나만 맞아도 통과 (기본은 전부)")
    wh.set_defaults(func=cmd_sheet_where)

    so = sheet_out(common(sh.add_parser("sort", help="정렬")))
    so.add_argument("file")
    so.add_argument("--by", action="append", required=True, metavar="열")
    so.add_argument("--desc", action="store_true", help="내림차순")
    so.set_defaults(func=cmd_sheet_sort)

    sp2 = sheet_out(common(sh.add_parser("sample", help="표본 뽑기")))
    sp2.add_argument("file")
    sp2.add_argument("-n", "--number", type=int, default=20, metavar="행")
    sp2.add_argument("--head", action="store_true", help="무작위 대신 앞에서")
    sp2.add_argument("--seed", type=int, help="같은 표본을 다시 뽑을 때")
    sp2.set_defaults(func=cmd_sheet_sample)

    sl = common(sh.add_parser("split", help="여러 파일로 나누기"))
    sl.add_argument("file")
    sl.add_argument("--rows", type=int, dest="rows_per", metavar="행",
                    help="이만큼씩 잘라서")
    sl.add_argument("--by", metavar="열", help="이 열의 값마다 (부서별·월별)")
    sl.add_argument("-o", "--out", metavar="디렉터리")
    sl.add_argument("--format", metavar="확장자", help="csv 또는 xlsx")
    sl.add_argument("--apply", action="store_true")
    sl.set_defaults(func=cmd_sheet_split)

    fl = common(sh.add_parser("fill", help="명단 + 틀 -> 개인별 문서 (메일 머지)"))
    fl.add_argument("file", metavar="명단파일")
    fl.add_argument("-t", "--template", required=True, metavar="틀파일")
    fl.add_argument("-o", "--out", metavar="디렉터리/파일")
    fl.add_argument("--name", metavar="틀", help="파일명 틀 (예: '{사번}_{이름}.txt')")
    fl.add_argument("--single", action="store_true", help="한 파일에 이어 붙인다")
    fl.add_argument("--separator", default="\f", metavar="구분",
                    help="--single 일 때 사이에 넣을 것 (기본: 페이지 나눔). "
                         "-로 시작하는 값은 --separator=--- 처럼 붙여 쓴다")
    fl.add_argument("--stdout", action="store_true", help="파일 대신 화면으로")
    fl.add_argument("--force", action="store_true", help="없는 자리표시자를 빈칸으로 두고 진행")
    fl.add_argument("--limit", type=int, default=10)
    fl.add_argument("--apply", action="store_true")
    fl.set_defaults(func=cmd_sheet_fill)

    rp2 = common(sh.add_parser("report", help="표를 HTML 보고서로 (요약·그래프·표)"))
    rp2.add_argument("file")
    rp2.add_argument("-o", "--out", metavar="파일", help="기본: <파일이름>-보고서.html")
    rp2.add_argument("--title", default="", metavar="제목")
    rp2.add_argument("--by", metavar="열", help="이 열로 묶어 막대 그래프")
    rp2.add_argument("--value", metavar="열", help="집계할 숫자 열 (없으면 건수)")
    rp2.add_argument("--agg", default="sum", choices=list(sheet.AGGS))
    rp2.add_argument("--date", metavar="열", help="이 날짜 열로 추이 그래프")
    rp2.add_argument("--period", default="month", choices=["day", "month", "year"])
    rp2.add_argument("--top", type=int, default=12, metavar="개")
    rp2.add_argument("--rows", type=int, default=30, metavar="행", help="데이터 표에 넣을 행")
    rp2.set_defaults(func=cmd_sheet_report)

    cv = common(sh.add_parser("convert", help="csv <-> xlsx 변환 (인코딩 정리)"))
    cv.add_argument("file")
    cv.add_argument("-o", "--out", required=True)
    cv.add_argument("--name", default="", metavar="시트명")
    cv.add_argument("--no-bom", action="store_true", help="CSV 에 BOM 을 넣지 않는다")
    cv.set_defaults(func=cmd_sheet_convert)

    # ---- text
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

    tu = tp.add_parser("undo", help="text 명령 되돌리기")
    tu.add_argument("journal", nargs="?")
    tu.set_defaults(func=cmd_text_undo)

    # ---- doc
    dc = sub.add_parser("doc", help="마크다운 목차·링크 관리").add_subparsers(
        dest="cmd", required=True)

    dt = dc.add_parser("toc", help="제목에서 목차 만들기·갱신")
    dt.add_argument("paths", nargs="+", metavar="경로")
    dt.add_argument("--depth", type=int, default=3, metavar="단계")
    dt.add_argument("--keep-h1", action="store_true", help="맨 앞 H1 도 목차에 넣는다")
    dt.add_argument("--apply", action="store_true")
    dt.set_defaults(func=cmd_doc_toc)

    dl = dc.add_parser("links", help="깨진 상대 링크·앵커 찾기")
    dl.add_argument("paths", nargs="+", metavar="경로")
    dl.add_argument("--limit", type=int, default=20)
    dl.set_defaults(func=cmd_doc_links)

    dh = dc.add_parser("check", help="제목 단계 건너뜀·중복 점검")
    dh.add_argument("paths", nargs="+", metavar="경로")
    dh.add_argument("--outline", action="store_true", help="제목 구조도 출력")
    dh.add_argument("--limit", type=int, default=40)
    dh.set_defaults(func=cmd_doc_check)

    # ---- json
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

    jf = jp.add_parser("flat", help="경로=값 한 줄씩 (grep 하기 좋게)")
    jf.add_argument("file", nargs="?", default="-")
    jf.add_argument("--grep", metavar="정규식")
    jf.add_argument("--limit", type=int, default=200)
    jf.add_argument("--width", type=int, default=60, metavar="칸")
    jf.set_defaults(func=cmd_json_flat)

    # ---- keys
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

    # ---- novel
    np_ = sub.add_parser("novel", help="소설 원고").add_subparsers(dest="cmd", required=True)

    s = np_.add_parser("stats", help="분량 집계 (원고지·단행본 환산)")
    s.add_argument("paths", nargs="+")
    s.add_argument("--each", action="store_true", help="파일별로도 출력")
    s.set_defaults(func=cmd_novel_stats)

    c = np_.add_parser("check", help="반복·상투구·긴 문장 점검")
    c.add_argument("file", nargs="?", default="-")
    c.add_argument("--top", type=int, default=10)
    c.add_argument("--long", type=int, default=100, metavar="자")
    c.add_argument("--run", type=int, default=4, metavar="회")
    c.set_defaults(func=cmd_novel_check)

    nm = np_.add_parser("names", help="인물·지명 표기 흔들림과 이름 뒤 조사 오류")
    nm.add_argument("paths", nargs="+")
    nm.add_argument("--min", type=int, default=3, metavar="회",
                    help="이름으로 볼 최소 등장 횟수")
    nm.add_argument("--variety", type=int, default=2, metavar="개",
                    help="붙은 조사 종류가 이만큼 이상일 때만 이름으로 본다")
    nm.add_argument("--name", action="append", metavar="이름",
                    help="검사할 이름을 직접 지정 (여러 번)")
    nm.add_argument("--distance", type=int, default=1, choices=[1, 2])
    nm.add_argument("--limit", type=int, default=20)
    nm.add_argument("--width", type=int, default=20, metavar="칸")
    nm.add_argument("--no-josa", action="store_true", help="조사 검사 생략")
    nm.set_defaults(func=cmd_novel_names)

    ol = np_.add_parser("outline", help="장면 목록 - 분량·대사 비율·등장인물·첫 문장")
    ol.add_argument("paths", nargs="+")
    ol.add_argument("--min", type=int, default=100, metavar="자",
                    help="이보다 짧은 덩어리는 장면으로 세지 않는다")
    ol.add_argument("--people", type=int, default=3, metavar="회",
                    help="인물로 볼 최소 등장 횟수")
    ol.add_argument("--name", action="append", metavar="이름", help="인물을 직접 지정")
    ol.add_argument("--no-headings", action="store_true",
                    help="마크다운 제목을 장면 제목으로 쓰지 않는다")
    ol.add_argument("--limit", type=int, default=50)
    ol.add_argument("--width", type=int, default=30, metavar="칸")
    ol.add_argument("-o", "--out", metavar="파일", help="csv 또는 xlsx 로 저장")
    ol.set_defaults(func=cmd_novel_outline)

    fd = np_.add_parser("find", help="원고에서 문맥과 함께 찾기 (복선·소재 추적)")
    fd.add_argument("query", metavar="찾을것")
    fd.add_argument("paths", nargs="+")
    fd.add_argument("-e", "--regex", action="store_true")
    fd.add_argument("-i", "--ignore-case", action="store_true")
    fd.add_argument("-c", "--context", type=int, default=1, metavar="문장",
                    help="앞뒤로 붙일 문장 수")
    fd.add_argument("--min", type=int, default=100, metavar="자", help="장면 최소 분량")
    fd.add_argument("--limit", type=int, default=30)
    fd.add_argument("--width", type=int, default=110, metavar="칸")
    fd.set_defaults(func=cmd_novel_find)

    tl = np_.add_parser("timeline", help="시간 표현 모아 보기와 장면 안 시간 충돌")
    tl.add_argument("paths", nargs="+")
    tl.add_argument("-k", "--kind", action="append", metavar="종류",
                    choices=["날짜", "시각", "요일", "상대", "기간", "시간대", "계절"])
    tl.add_argument("--context", action="store_true", help="문장도 함께")
    tl.add_argument("--min", type=int, default=100, metavar="자", help="장면 최소 분량")
    tl.add_argument("--limit", type=int, default=60)
    tl.add_argument("--width", type=int, default=100, metavar="칸")
    tl.set_defaults(func=cmd_novel_timeline)

    sy = np_.add_parser("style", help="화별 문체 지표 비교 - 튀는 화 찾기")
    sy.add_argument("paths", nargs="+")
    sy.add_argument("--by", default="file", choices=["file", "scene"])
    sy.add_argument("--long", type=int, default=80, metavar="자",
                    help="긴 문장으로 볼 기준")
    sy.add_argument("--sigma", type=float, default=1.5, metavar="배",
                    help="표준편차 이만큼 벗어나면 튀는 것으로 본다")
    sy.add_argument("--min", type=int, default=100, metavar="자", help="장면 최소 분량")
    sy.add_argument("--limit", type=int, default=40)
    sy.set_defaults(func=cmd_novel_style)

    ex = np_.add_parser("export", help="여러 화를 한 파일로 - 투고·인쇄용")
    ex.add_argument("paths", nargs="+")
    ex.add_argument("-o", "--out", metavar="파일")
    ex.add_argument("-f", "--format", default="html", choices=["html", "txt", "md"])
    ex.add_argument("--title", default="", metavar="제목")
    ex.add_argument("--author", default="", metavar="필명")
    ex.add_argument("--note", default="", metavar="설명", help="기본: 분량 요약")
    ex.add_argument("--indent", action="store_true", help="문단 첫 줄을 한 칸 들여쓴다")
    ex.add_argument("--join", action="store_true",
                    help="여러 줄에 접힌 문단을 한 문단으로 합친다")
    ex.add_argument("--scene-mark", default="", metavar="표시",
                    help="장면 구분선을 이걸로 바꾼다 (예: ＊)")
    ex.set_defaults(func=cmd_novel_export)

    dg = np_.add_parser("dialogue", help="인물별 대사량과 말투 (존댓말·어미)")
    dg.add_argument("paths", nargs="+")
    dg.add_argument("--name", action="append", metavar="이름", help="인물 직접 지정")
    dg.add_argument("--min", type=int, default=3, metavar="회",
                    help="인물로 볼 최소 등장 횟수")
    dg.add_argument("--samples", type=int, default=0, metavar="개",
                    help="인물마다 대사 예시를 이만큼 보여준다")
    dg.add_argument("--limit", type=int, default=20)
    dg.add_argument("--width", type=int, default=70, metavar="칸")
    dg.set_defaults(func=cmd_novel_dialogue)

    sn = np_.add_parser("snap", help="원고 스냅샷 저장/목록")
    sn.add_argument("dir", nargs="?", default=".")
    sn.add_argument("--note", default="")
    sn.add_argument("-l", "--list", action="store_true")
    sn.set_defaults(func=cmd_novel_snap)

    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # '--' 뒤는 파싱하지 않고 그대로 하위 명령에 넘긴다 (at file watch ... -- pytest -q)
    tail: list[str] = []
    if "--" in argv:
        cut = argv.index("--")
        argv, tail = argv[:cut], argv[cut + 1:]

    ap = build_parser()
    args = ap.parse_args(argv)
    if tail:
        args.command = tail
    try:
        return args.func(args)
    except KeyboardInterrupt:
        _p("\n중단했습니다.")
        return 130
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
