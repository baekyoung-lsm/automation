"""at git - 저장소 정리와 검사."""

from __future__ import annotations

import sys
from pathlib import Path

from .. import files, gitkit, text, todo
from .common import _p, _cut, _grid


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


def add_commands(sub) -> None:
    """git 하위 명령을 붙인다."""
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
