"""at doc - 마크다운 유지보수."""

from __future__ import annotations

from pathlib import Path

from .. import files, sheet, text
from ..docs import mdkit
from .common import _p, _grid, MD_SUFFIXES


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


def cmd_doc_tables(a) -> int:
    path = Path(a.file)
    if not path.is_file():
        _p(f"파일이 없습니다: {path}")
        return 1

    body = path.read_text(encoding="utf-8", errors="replace")
    blocks = mdkit.find_tables(body)
    if not blocks:
        _p("표를 찾지 못했습니다. 머리글 줄과 --- 구분줄이 있어야 표로 봅니다.")
        return 1

    if not a.number and not a.out:
        _grid(["번호", "줄", "열", "행", "머리글"],
              [[str(i), str(b.start), str(b.columns), str(len(b.rows)),
                ", ".join(b.header[:4])] for i, b in enumerate(blocks, 1)],
              limit=40)
        _p(f"\n표 {len(blocks)}개. -n 번호 로 하나를 보고, -o 로 저장합니다.")
        return 0

    picked = blocks
    if a.number:
        if not 1 <= a.number <= len(blocks):
            _p(f"표는 1~{len(blocks)}번까지 있습니다.")
            return 1
        picked = [blocks[a.number - 1]]

    tables = []
    for block in picked:
        width = block.columns
        headers = (block.header + [""] * width)[:width]
        headers = [h or f"열{i}" for i, h in enumerate(headers, 1)]
        rows = [[sheet.parse_number(c) if sheet.parse_number(c) is not None else c
                 for c in (r + [""] * width)[:width]] for r in block.rows]
        tables.append(sheet.Table(headers, rows, source=str(path)))

    if not a.out:
        table = tables[0]
        _grid(table.headers, [[sheet.to_text(v) for v in r]
                              for r in table.rows[:a.limit]], limit=40)
        _p(f"\n{len(table.rows)}행 x {table.width}열. -o 로 저장할 수 있습니다.")
        return 0

    out = Path(a.out)
    if len(tables) == 1:
        _p(f"저장: {sheet.save(tables[0], out)}")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    suffix = a.suffix if a.suffix.startswith(".") else f".{a.suffix}"
    for i, table in enumerate(tables, 1):
        _p(f"저장: {sheet.save(table, out / f'표{i}{suffix}')}")
    _p(f"\n표 {len(tables)}개를 {out}/ 에 저장했습니다.")
    return 0


def cmd_doc_images(a) -> int:
    targets = _md_files(a.paths)
    if not targets:
        _p("마크다운 파일을 찾지 못했습니다.")
        return 1

    root = Path(a.root) if a.root else Path(a.paths[0])
    root = (root if root.is_dir() else root.parent).resolve()

    rows: list[list[str]] = []
    used: set[Path] = set()
    missing = big = 0
    no_alt = 0

    for path in targets:
        body = path.read_text(encoding="utf-8", errors="replace")
        for link in mdkit.links(body):
            if link.kind != "image":
                continue
            target = link.target.split("#", 1)[0]
            if "://" in target or target.startswith("data:"):
                continue
            if not link.text.strip():
                no_alt += 1
            spot = (path.parent / target).resolve()
            rel = str(path.relative_to(root)) if root in path.parents else str(path)
            if not spot.is_file():
                missing += 1
                rows.append([rel, target, "없음", "-", "-"])
                continue
            used.add(spot)
            info = files.image_info(spot)
            size = files.human_size(spot.stat().st_size)
            if info is None:
                rows.append([rel, target, "헤더 못 읽음", "-", size])
                continue
            state = "OK"
            if a.over and max(info.width, info.height) > a.over:
                state, big = "큼", big + 1
            rows.append([rel, target, state, f"{info.width:,}x{info.height:,}", size])

    if not rows:
        _p(f"파일 {len(targets)}개, 이미지 링크가 없습니다.")
        return 0

    _grid(["문서", "이미지", "상태", "크기", "용량"],
          [r for r in rows if not a.only_bad or r[2] != "OK"][:a.limit], limit=44)
    _p(f"\n이미지 링크 {len(rows)}개 · 없는 파일 {missing}개"
       + (f" · {a.over:,}px 넘는 것 {big}개" if a.over else "")
       + (f" · 설명(alt) 없는 것 {no_alt}개" if no_alt else ""))

    if a.orphans:
        every = {p.resolve() for p in root.rglob("*")
                 if p.is_file() and p.suffix.lower() in files.IMAGE_SUFFIXES
                 and not any(d in files.IGNORE_DIRS for d in p.parts)}
        orphans = sorted(every - used)
        if orphans:
            _p(f"\n어느 문서에서도 안 쓰는 이미지 {len(orphans)}개")
            for spot in orphans[:a.limit]:
                _p(f"  {spot.relative_to(root)}  "
                   f"{files.human_size(spot.stat().st_size)}")
            _p("문서 밖에서 쓰고 있을 수 있으니 지우기 전에 확인하세요.")
        else:
            _p("\n안 쓰는 이미지가 없습니다.")

    return 1 if missing else 0


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


def cmd_doc_split(a) -> int:
    path = Path(a.file)
    if not path.is_file():
        _p(f"파일이 없습니다: {path}")
        return 1

    body = path.read_text(encoding="utf-8", errors="replace")
    preface, sections = mdkit.split_sections(body, level=a.level)
    if not sections:
        _p(f"H{a.level} 이하 제목이 없어 쪼갤 수 없습니다.")
        return 1

    out_dir = Path(a.out) if a.out else path.with_suffix("")
    plan: list[tuple[Path, str, str]] = []      # 파일, 설명, 내용
    if preface and not a.drop_preface:
        plan.append((out_dir / f"{0:0{a.digits}d}-머리말.md", "머리말", preface + "\n"))
    for s in sections:
        plan.append((out_dir / mdkit.section_filename(s, digits=a.digits),
                     f"H{s.level} {s.line}행", s.body))

    exists = [f for f, _, _ in plan if f.exists()]
    rows = [[f.name, note, f"{len(text.splitlines()):,}행",
             "이미 있음" if f.exists() else ""]
            for f, note, text in plan]
    _p(f"{path} -> {out_dir}/")
    _grid(["파일", "자리", "분량", "상태"], rows, limit=40)

    if not a.apply:
        _p(f"\n파일 {len(plan)}개를 만듭니다. 실제로 쓰려면 --apply 를 붙이세요.")
        return 0
    if exists:
        _p(f"\n이미 있는 파일 {len(exists)}개가 있어 아무것도 쓰지 않았습니다. "
           "다른 디렉터리를 -o 로 지정하세요.")
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    for f, _, text in plan:
        f.write_text(text, encoding="utf-8")
    _p(f"\n{out_dir}/ 에 {len(plan)}개를 썼습니다. 원본은 그대로 둡니다.")
    return 0


def cmd_doc_table(a) -> int:
    targets = _md_files(a.paths)
    if not targets:
        _p("마크다운 파일을 찾지 못했습니다.")
        return 1

    changes: list[text.Change] = []
    for path in targets:
        try:
            body, encoding = text.read_text_any(path)
        except text.TextError as e:
            _p(f"{path}: 건너뜀 ({e})")
            continue
        new, touched = mdkit.format_tables(body)
        if not touched or new == body:
            continue
        changes.append(text.Change(path, body, new, encoding, hits=touched))

    if not changes:
        _p(f"파일 {len(targets)}개, 이미 칸이 맞아 있습니다.")
        return 0

    for c in changes:
        _p(f"{c.path}  표 {c.hits}개")
        for line in c.diff(limit=a.limit):
            _p(f"  {line}")
        _p("")

    if not a.apply:
        _p("실제로 고치려면 --apply 를 붙이세요.")
        return 0

    journal = text.apply_changes(changes)
    _p(f"파일 {len(changes)}개를 고쳤습니다. 되돌리려면 at text undo")
    _p(f"백업: {journal.parent if journal else '-'}")
    return 0


def add_commands(sub) -> None:
    """doc 하위 명령을 붙인다."""
    dc = sub.add_parser("doc", help="마크다운 목차·링크·표 정리").add_subparsers(
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

    ds = dc.add_parser("split", help="긴 문서를 제목 단위 파일로 쪼개기")
    ds.add_argument("file", metavar="파일")
    ds.add_argument("-o", "--out", metavar="디렉터리", help="기본은 파일 이름과 같은 디렉터리")
    ds.add_argument("--level", type=int, default=2, metavar="단계",
                    help="이 단계까지의 제목에서 자른다 (기본 2)")
    ds.add_argument("--digits", type=int, default=2, metavar="자리",
                    help="파일 이름 앞 번호 자릿수 (기본 2)")
    ds.add_argument("--drop-preface", action="store_true",
                    help="첫 제목 앞 머리말을 버린다")
    ds.add_argument("--apply", action="store_true")
    ds.set_defaults(func=cmd_doc_split)

    dtb = dc.add_parser("table", help="마크다운 표의 칸 너비 맞추기 (한글 두 칸)")
    dtb.add_argument("paths", nargs="+", metavar="경로")
    dtb.add_argument("--limit", type=int, default=12, metavar="줄",
                     help="미리보기에서 보여줄 차이 줄 수")
    dtb.add_argument("--apply", action="store_true")
    dtb.set_defaults(func=cmd_doc_table)

    dg = dc.add_parser("tables", help="문서 안의 표를 csv·xlsx 로 뽑기")
    dg.add_argument("file", metavar="파일")
    dg.add_argument("-n", "--number", type=int, default=0, metavar="번호",
                    help="몇 번째 표인지 (기본: 목록만)")
    dg.add_argument("-o", "--out", metavar="파일|디렉터리",
                    help="표가 여럿이면 디렉터리로 준다")
    dg.add_argument("--suffix", default=".csv", metavar="확장자",
                    help="여러 개 저장할 때 형식 (기본 .csv)")
    dg.add_argument("--limit", type=int, default=20)
    dg.set_defaults(func=cmd_doc_tables)

    di = dc.add_parser("images", help="문서가 쓰는 이미지 점검 - 없는 파일·큰 그림·고아 파일")
    di.add_argument("paths", nargs="+", metavar="경로")
    di.add_argument("--root", metavar="디렉터리", help="고아 이미지를 찾을 기준 (기본: 첫 경로)")
    di.add_argument("--over", type=int, default=2000, metavar="px",
                    help="긴 변이 이보다 크면 표시 (0 이면 끔)")
    di.add_argument("--orphans", action="store_true",
                    help="어느 문서에서도 안 쓰는 이미지도 찾는다")
    di.add_argument("--only-bad", action="store_true", help="문제 있는 것만")
    di.add_argument("--limit", type=int, default=30)
    di.set_defaults(func=cmd_doc_images)
