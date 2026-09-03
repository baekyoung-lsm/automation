"""attools CLI 진입점."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, devkit, files, gitkit, life, manuscript, sheet
from .schedule import Cron, CronError
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


# ===================================================================== main

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="at", description="파일 정리 / 개발 / git / 엑셀 실무 / 일상 계산 / 소설 집필 자동화 도구")
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

    b = fp.add_parser("big", help="용량 차지하는 디렉터리/파일 찾기")
    b.add_argument("dir", nargs="?", default=".")
    b.add_argument("--depth", type=int, default=1)
    b.add_argument("--top", type=int, default=15)
    b.set_defaults(func=cmd_file_big)

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
    e.set_defaults(func=cmd_dev_env)

    pt = dp.add_parser("port", help="포트 점유 프로세스 확인/종료")
    pt.add_argument("port", type=int)
    pt.add_argument("--kill", action="store_true")
    pt.add_argument("--force", action="store_true", help="SIGKILL")
    pt.add_argument("-y", "--yes", action="store_true", help="확인 없이 종료")
    pt.set_defaults(func=cmd_dev_port)

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

    m = dp.add_parser("mask", help="로그의 개인정보·시크릿 가리기")
    m.add_argument("file", nargs="?", default="-")
    m.add_argument("--in-place", action="store_true")
    m.set_defaults(func=cmd_dev_mask)

    # ---- git
    gp = sub.add_parser("git", help="git 저장소 정리·검사").add_subparsers(dest="cmd", required=True)

    sw = gp.add_parser("sweep", help="병합 끝난 브랜치, 원격 사라진 브랜치 정리")
    sw.add_argument("dir", nargs="?", default=".")
    sw.add_argument("--base", help="기준 브랜치 (기본: origin/HEAD)")
    sw.add_argument("--fetch", action="store_true", help="먼저 fetch --prune")
    sw.add_argument("--apply", action="store_true")
    sw.add_argument("--force", action="store_true", help="원격이 사라진 브랜치도 강제 삭제")
    sw.set_defaults(func=cmd_git_sweep)

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

    cv = common(sh.add_parser("convert", help="csv <-> xlsx 변환 (인코딩 정리)"))
    cv.add_argument("file")
    cv.add_argument("-o", "--out", required=True)
    cv.add_argument("--name", default="", metavar="시트명")
    cv.add_argument("--no-bom", action="store_true", help="CSV 에 BOM 을 넣지 않는다")
    cv.set_defaults(func=cmd_sheet_convert)

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
