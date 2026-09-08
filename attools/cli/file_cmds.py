"""at file - 파일 분류·개명·중복·감시·압축."""

from __future__ import annotations

from pathlib import Path

from .. import files
from ..code import devkit
from ..hangul import is_decomposed
from .common import _pad, _p, _confirm, _grid, _cut, _may_write


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


def cmd_file_docs(a) -> int:
    """워드·엑셀·슬라이드 파일의 속성을 표로. 누가 만든 문서인지 본다."""
    from .. import sheet

    root = Path(a.dir)
    if not root.exists():
        _p(f"없는 경로입니다: {root}")
        return 1

    metas = files.scan_documents(root, recursive=not a.flat, include_hidden=a.hidden)
    if not metas:
        _p("워드·엑셀·슬라이드 파일이 없습니다. "
           f"({', '.join(sorted(files.OOXML_KINDS))})")
        return 0

    def number(value) -> str:
        return f"{value:,}" if isinstance(value, int) else ""

    def moment(value: str) -> str:
        """문서 속성의 시각은 세계시(UTC)다. 한국 시각인 척 적지 않는다."""
        if value.endswith("Z") and "T" in value:
            return value[:-1].replace("T", " ")[:16] + " UTC"
        return value.replace("T", " ")

    headers = ["이름", "종류", "제목", "만든 사람", "마지막 저장", "만든 날짜",
               "고친 날짜", "회사", "만든 프로그램", "쪽", "낱말", "장",
               "크기(바이트)", "못 읽은 까닭"]
    table = sheet.Table(headers, [
        [m.path.name, m.kind, m.title, m.author, m.last_by, moment(m.created),
         moment(m.modified), m.company, m.program, m.pages, m.words, m.slides,
         m.size, m.error] for m in metas], source=str(root))

    if a.out:
        if not _may_write(a, Path(a.out)):
            return 1
        out = sheet.save(table, Path(a.out))
        _p(f"저장: {out}  (문서 {len(metas):,}개)")
        return 0

    _grid(["이름", "종류", "제목", "만든 사람", "고친 날짜", "쪽/장"],
          [[_pad(m.path.name, 0), m.kind, _cut(m.title or m.error, 20),
            _cut(m.author or m.last_by, 12), m.modified[:10],
            number(m.pages if m.pages is not None else m.slides)]
           for m in metas[:a.limit]], limit=30)
    if len(metas) > a.limit:
        _p(f"... {len(metas) - a.limit:,}개 더 (--limit 로 조절)")

    left = [m for m in metas if m.personal]
    unread = [m for m in metas if m.error]
    _p(f"\n문서 {len(metas):,}개")
    if left:
        _p(f"사람·회사 이름이 남아 있는 문서 {len(left):,}개 - "
           "밖으로 보내기 전에 보세요:")
        for m in left[:a.limit]:
            _p(f"  {m.path.name}  {', '.join(m.personal)}")
        if len(left) > a.limit:
            _p(f"  ... {len(left) - a.limit:,}개 더")
    if unread:
        _p(f"속성을 읽지 못한 파일 {len(unread):,}개 (표의 «못 읽은 까닭» 칸)")
    _p("속성만 읽었습니다. 문서 내용은 열지 않았습니다. "
       "(내용은 at doc from-docx, at sheet from-docx)")
    if any(m.kind == "PDF" for m in metas):
        _p("PDF 는 속성과 쪽 수만 봅니다. 본문 글자는 꺼내지 않습니다 - "
           "글꼴에 따라 조용히 틀린 글자가 나오기 때문입니다.")
    return 0


def cmd_file_pdf(a) -> int:
    """사진·스캔 이미지를 PDF 한 장으로 묶는다. 제출용."""
    from .. import pdf

    targets: list[Path] = []
    for raw in a.paths:
        path = Path(raw)
        if path.is_dir():
            targets += sorted(p for p in path.iterdir()
                              if p.is_file()
                              and p.suffix.lower() in pdf.IMAGE_SUFFIXES)
        elif path.is_file():
            targets.append(path)
        else:
            _p(f"없는 경로입니다: {path}")
            return 1
    if not targets:
        _p("이미지를 찾지 못했습니다. "
           f"({', '.join(sorted(pdf.IMAGE_SUFFIXES))} 만 넣을 수 있습니다)")
        return 1

    pages = []
    skipped: list[tuple[Path, str]] = []
    for path in targets:
        try:
            pages.append(pdf.read_image(path))
        except pdf.PdfError as e:
            skipped.append((path, str(e)))

    _grid(["차례", "파일", "크기(px)"],
          [[str(i), _pad(page.path.name, 0), f"{page.width}x{page.height}"]
           for i, page in enumerate(pages[:a.limit], 1)], limit=40)
    if len(pages) > a.limit:
        _p(f"... {len(pages) - a.limit:,}장 더")
    if skipped:
        _p(f"\n넣지 못한 파일 {len(skipped)}개:")
        for path, why in skipped[:a.limit]:
            _p(f"  {path.name}  {why}")
        if len(skipped) > a.limit:
            _p(f"  ... {len(skipped) - a.limit}개 더")

    if not pages:
        _p("\n넣을 수 있는 이미지가 없습니다.")
        return 1

    if not a.out:
        _p(f"\n{len(pages):,}장. 파일로 묶으려면 -o 문서.pdf 를 주세요. "
           "(이름 순으로 담습니다)")
        return 0

    out = Path(a.out)
    if not _may_write(a, out):
        return 1
    try:
        made = pdf.images_to_pdf(pages, out, page=a.page,
                                 margin_mm=a.margin, landscape=a.landscape,
                                 rotate=not a.no_rotate, title=a.title or "")
    except pdf.PdfError as e:
        _p(str(e))
        return 1

    _p(f"\n저장: {made}  ({len(pages):,}쪽, {files.human_size(made.stat().st_size)})")
    _p(f"쪽 크기는 {a.page}{' 가로' if a.landscape else ''} 이고, "
       "이미지는 비율을 지켜 가운데에 넣었습니다.")
    if not a.no_rotate and any(p.width > p.height for p in pages):
        _p("가로로 긴 이미지는 눕혀 담았습니다 (--no-rotate 로 끕니다).")
    _p("이미지를 다시 그리지 않습니다. JPEG 은 그대로 넣어 화질이 그대로입니다.")
    return 0


def cmd_file_exif(a) -> int:
    """사진에 남은 촬영 정보(위치·기기·날짜)를 보고, 지운 사본을 만든다."""
    root = Path(a.dir)
    if not root.exists():
        _p(f"없는 경로입니다: {root}")
        return 1

    metas = files.scan_photos(root, recursive=not a.flat)
    if not metas:
        _p("jpg 파일이 없습니다. (EXIF 는 jpg 에서만 읽습니다)")
        return 0

    _grid(["파일", "찍은 날", "기기", "위치", "방향"],
          [[_pad(m.path.name, 0),
            m.taken.strftime("%Y-%m-%d %H:%M") if m.taken else "",
            _cut(f"{m.make} {m.model}".strip(), 18), m.where,
            "" if m.orientation in (None, 1) else str(m.orientation)]
           for m in metas[:a.limit]], limit=30)
    if len(metas) > a.limit:
        _p(f"... {len(metas) - a.limit:,}장 더 (--limit 로 조절)")

    located = [m for m in metas if m.where]
    dirty = [m for m in metas if m.personal]
    _p(f"\n사진 {len(metas):,}장  ·  위치가 남은 사진 {len(located):,}장")
    if located:
        _p("위치는 찍은 자리의 좌표입니다. 집·사무실이 그대로 드러납니다.")

    if not a.strip:
        if dirty:
            _p(f"지우려면 --strip 을 붙이세요 (사본을 만듭니다).")
        return 0

    if not dirty:
        _p("지울 정보가 없습니다.")
        return 0

    if not a.apply:
        _p(f"\n미리보기입니다. 사진 {len(dirty):,}장에서 아래를 지운 사본을 "
           "만들려면 --apply 를 붙이세요.")
        for m in dirty[:a.limit]:
            _p(f"  {m.path.name}  {', '.join(m.personal)}")
        if len(dirty) > a.limit:
            _p(f"  ... {len(dirty) - a.limit:,}장 더")
        return 0

    made = 0
    kept = 0
    for m in dirty:
        target = files.unique_path(
            m.path.with_name(f"{m.path.stem} (정보지움){m.path.suffix}"))
        try:
            _out, _removed = files.strip_exif(m.path, target,
                                              keep_orientation=not a.all)
        except (OSError, ValueError) as e:
            _p(f"만들지 못했습니다: {m.path.name}  {e}")
            continue
        made += 1
        if not a.all and m.orientation not in (None, 1):
            kept += 1
    _p(f"\n사본 {made:,}장을 만들었습니다. 원본은 그대로입니다.")
    if kept:
        _p(f"그 가운데 {kept:,}장은 방향 정보만 남겼습니다 - 그것까지 지우면 "
           "폰으로 찍은 사진이 눕혀 보입니다. (--all 로 그것도 지웁니다)")
    _p("그림 자체는 다시 누르지 않았습니다. 화질이 그대로입니다.")
    return 0


def cmd_file_sync(a) -> int:
    """원본에서 백업 폴더로 새것·바뀐 것만 넣는다. 기본은 미리보기."""
    source, backup = Path(a.source), Path(a.backup)
    if not source.is_dir():
        _p(f"디렉터리가 아닙니다: {source}")
        return 1
    if not backup.exists():
        if not a.apply:
            _p(f"백업 폴더가 아직 없습니다: {backup}  (--apply 로 만듭니다)")
        else:
            backup.mkdir(parents=True)
    elif not backup.is_dir():
        _p(f"디렉터리가 아닙니다: {backup}")
        return 1

    # 백업 폴더가 아직 없으면 «빈 폴더» 로 보고 센다 (rglob 이 빈 목록을 준다)
    plan = files.plan_sync(source, backup, include_hidden=a.hidden,
                           glob=a.glob, quick=a.quick)
    _p(f"{source}  ->  {backup}")
    _p(f"새로 넣을 것 {len(plan.new):,}개  ·  덮어쓸 것 {len(plan.changed):,}개  ·  "
       f"그대로 {plan.same:,}개  ·  백업에만 있는 것 {len(plan.extra):,}개")
    if plan.new or plan.changed:
        _p(f"옮길 용량 {files.human_size(plan.bytes)}")

    for label, names in (("새로", plan.new), ("덮어씀", plan.changed),
                         ("백업에만", plan.extra)):
        if not names:
            continue
        _p("")
        for name in names[:a.limit]:
            _p(f"  [{label}] {name}")
        if len(names) > a.limit:
            _p(f"  ... {len(names) - a.limit:,}개 더")

    if plan.empty and not (a.remove_extra and plan.extra):
        _p("\n넣을 것이 없습니다.")
        return 0

    if not a.apply:
        _p("\n미리보기입니다. 실제로 넣으려면 --apply 를 붙이세요.")
        if plan.extra and not a.remove_extra:
            _p("백업에만 있는 파일은 그대로 둡니다. "
               "지우려면 --remove-extra 까지 붙이세요.")
        return 0

    copied, removed, failed = files.apply_sync(
        source, backup, plan, keep_old=not a.no_keep,
        remove_extra=a.remove_extra)
    _p(f"\n넣은 파일 {copied:,}개" + (f", 뺀 파일 {removed:,}개" if removed else ""))
    if failed:
        _p(f"하지 못한 것 {len(failed)}개:")
        for name, why in failed[:a.limit]:
            _p(f"  {name}  {why}")
    if not a.no_keep and (plan.changed or removed):
        _p(f"덮어쓰거나 뺀 파일의 예전 판은 "
           f"{backup / files.OLD_VERSIONS_DIR} 아래에 남겨 두었습니다.")
    return 0


def cmd_file_scrub(a) -> int:
    """문서 속성에서 사람·회사 이름을 지운 사본을 만든다. 원본은 그대로."""
    root = Path(a.dir)
    if not root.exists():
        _p(f"없는 경로입니다: {root}")
        return 1

    if root.is_file():
        targets = [root]
    else:
        targets = [m.path for m in files.scan_documents(
            root, recursive=not a.flat, pdf=False)]
    if not targets:
        _p("워드·엑셀·슬라이드 파일이 없습니다.")
        return 0

    plans = [files.plan_scrub(p) for p in targets]
    dirty = [p for p in plans if p.ok]
    broken = [p for p in plans if p.error]

    if not dirty:
        _p(f"문서 {len(plans):,}개  ·  속성에 남은 사람·회사 이름이 없습니다.")
        if broken:
            _p(f"열지 못한 파일 {len(broken):,}개:")
            for plan in broken[:a.limit]:
                _p(f"  {plan.path.name}  {plan.error}")
        return 0

    _grid(["파일", "지울 자리", "값"],
          [[_pad(plan.path.name, 0), label, _cut(value, 24)]
           for plan in dirty[:a.limit] for label, value in plan.removed],
          limit=32)
    if len(dirty) > a.limit:
        _p(f"... {len(dirty) - a.limit:,}개 더 (--limit 로 조절)")

    if not a.apply:
        _p(f"\n미리보기입니다. 문서 {len(dirty):,}개에서 위 값을 지운 "
           "사본을 만들려면 --apply 를 붙이세요.")
        return 0

    made = []
    for plan in dirty:
        target = files.unique_path(
            plan.path.with_name(f"{plan.path.stem} (이름지움){plan.path.suffix}"))
        try:
            made.append(files.apply_scrub(plan.path, target))
        except OSError as e:
            _p(f"만들지 못했습니다: {plan.path.name}  {e}")
    _p(f"\n사본 {len(made):,}개를 만들었습니다. 원본은 그대로입니다.")
    for path in made[:a.limit]:
        _p(f"  {path}")
    if len(made) > a.limit:
        _p(f"  ... {len(made) - a.limit:,}개 더")

    others = sorted({part for plan in dirty for part in plan.others})
    if others:
        _p("\n메모·변경 내역이 든 문서가 있습니다. 거기 남은 이름은 지우지 "
           "못합니다 (내용이라 여기서 손대면 문서가 달라집니다):")
        for part in others[:5]:
            _p(f"  {part}")
    _p("\n문서 속성(docProps)만 지웠습니다. 본문에 적힌 이름은 그대로입니다.")
    return 0


def cmd_file_list(a) -> int:
    """폴더 안 파일 목록을 표로. 제출 자료 목록을 손으로 적지 않게."""
    from .. import sheet

    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    try:
        rows = files.list_files(root, recursive=not a.flat, include_hidden=a.hidden,
                                glob=a.glob, sort=a.sort)
    except ValueError as e:
        _p(str(e))
        return 1
    if not rows:
        _p("파일이 없습니다.")
        return 0

    headers = ["이름", "폴더", "확장자", "크기(바이트)", "크기", "수정일", "수정시각"]
    table = sheet.Table(headers, [
        [r.name, r.folder, r.suffix, r.size, files.human_size(r.size),
         r.modified.strftime("%Y-%m-%d"), r.modified.strftime("%H:%M")]
        for r in rows], source=str(root))

    total = sum(r.size for r in rows)
    if a.out:
        if not _may_write(a, Path(a.out)):
            return 1
        out = sheet.save(table, Path(a.out))
        _p(f"저장: {out}  (파일 {len(rows):,}개, 모두 {files.human_size(total)})")
        return 0

    _grid(["이름", "폴더", "크기", "수정일"],
          [[_pad(r.name, 0), r.folder, files.human_size(r.size),
            r.modified.strftime("%Y-%m-%d %H:%M")] for r in rows[:a.limit]],
          limit=40)
    if len(rows) > a.limit:
        _p(f"... {len(rows) - a.limit:,}개 더 (--limit 로 조절)")
    _p(f"\n파일 {len(rows):,}개, 모두 {files.human_size(total)}")
    _p("-o 목록.xlsx 로 저장하면 엑셀에서 그대로 씁니다.")
    return 0


def cmd_file_photos(a) -> int:
    """사진을 찍은 날짜별로 묶는다. 수정 시각이 아니라 EXIF 촬영 시각을 쓴다."""
    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    try:
        plan = files.plan_photos(root, by=a.by, recursive=not a.flat,
                                 include_hidden=a.hidden, use_mtime=a.mtime)
    except ValueError as e:
        _p(str(e))
        return 1

    if plan.left:
        _p(f"촬영 시각을 못 읽어 두고 온 사진 {len(plan.left)}개")
        for path in plan.left[:a.limit]:
            _p(f"  {path.relative_to(root.resolve())}")
        if len(plan.left) > a.limit:
            _p(f"  ... {len(plan.left) - a.limit}개 더")
        _p("  (JPEG 의 EXIF 만 읽습니다. HEIC·RAW 는 못 읽습니다.)")
        _p("  수정 시각으로라도 묶으려면 --mtime 을 붙이세요.\n")

    if not plan.moves:
        _p("옮길 사진이 없습니다.")
        return 0

    buckets: dict[str, int] = {}
    for mv in plan.moves:
        rel = str(Path(mv.dst).parent.relative_to(root.resolve()))
        buckets[rel] = buckets.get(rel, 0) + 1

    prefix = "" if a.apply else DRY + " "
    for bucket in sorted(buckets):
        _p(f"{prefix}{bucket}/  <- {buckets[bucket]}개")

    _p(f"\n촬영 시각으로 {plan.from_exif}개"
       + (f", 수정 시각으로 {len(plan.from_mtime)}개" if plan.from_mtime else ""))
    if plan.from_mtime:
        _p("  수정 시각은 파일을 복사한 날일 수 있어 실제 촬영일과 다를 수 있습니다.")

    if not a.apply:
        _p(f"\n총 {len(plan.moves)}개. 실제로 옮기려면 --apply 를 붙이세요.")
        return 0

    journal = files.apply_moves(plan.moves)
    _p(f"\n{len(plan.moves)}개를 옮겼습니다.")
    _p(f"되돌리기: at file undo {journal}")
    return 0


def cmd_file_route(a) -> int:
    import json as _json

    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    if a.example:
        _p(_json.dumps({"규칙": [
            {"이름": "세금계산서", "패턴": "세금계산서*.pdf",
             "정규식": r"(?P<연>\d{4})-(?P<달>\d{2})", "폴더": "회계/{연}/{달}"},
            {"이름": "사진", "패턴": "*.jpg", "폴더": "사진/{년}-{월}"},
            {"이름": "나머지 문서", "패턴": "*.pdf", "폴더": "문서/{년}"},
        ]}, ensure_ascii=False, indent=2))
        _p("\n쓸 수 있는 자리: {년} {월} {일} {이름} {확장자} {분류}, "
           "정규식의 이름 그룹")
        return 0

    rules_path = Path(a.rules) if a.rules else None
    if rules_path is None or not rules_path.is_file():
        _p(f"규칙 파일을 주세요: --rules 규칙.json  (--example 로 예시를 봅니다)")
        return 1
    try:
        rules = files.load_rules(_json.loads(rules_path.read_text(encoding="utf-8")))
        routed, missed = files.plan_route(root, rules, recursive=a.recursive,
                                          include_hidden=a.hidden,
                                          min_age_days=a.min_age)
    except (ValueError, _json.JSONDecodeError) as e:
        _p(f"규칙을 읽지 못했습니다: {e}")
        return 1

    if not routed:
        _p("규칙에 걸린 파일이 없습니다.")
        if missed:
            _p(f"어느 규칙에도 안 걸린 파일 {len(missed)}개")
        return 0

    prefix = "" if a.apply else DRY + " "
    counts: dict[str, int] = {}
    for r in routed[:a.limit]:
        counts[r.rule.label()] = counts.get(r.rule.label(), 0) + 1
        _p(f"{prefix}[{r.rule.label()}] {Path(r.move.src).name}  ->  "
           f"{Path(r.move.dst).relative_to(root.resolve())}")
    for r in routed[a.limit:]:
        counts[r.rule.label()] = counts.get(r.rule.label(), 0) + 1
    if len(routed) > a.limit:
        _p(f"... {len(routed) - a.limit}개 더")

    _p("")
    _grid(["규칙", "파일"], [[name, f"{n:,}"] for name, n in counts.items()])
    if missed:
        _p(f"\n어느 규칙에도 안 걸린 파일 {len(missed)}개 (그대로 둡니다)")
        for path in missed[:5]:
            _p(f"  {path.relative_to(root.resolve())}")
        if len(missed) > 5:
            _p(f"  ... {len(missed) - 5}개 더")

    if not a.apply:
        _p(f"\n총 {len(routed)}개. 실제로 옮기려면 --apply 를 붙이세요.")
        return 0

    journal = files.apply_moves([r.move for r in routed])
    _p(f"\n{len(routed)}개를 옮겼습니다.")
    _p(f"되돌리기: at file undo {journal}")
    return 0


def cmd_file_flatten(a) -> int:
    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    dest = Path(a.out) if a.out else None
    moves = files.plan_flatten(root, dest=dest, keep_path=a.keep_path,
                               sep=a.sep, include_hidden=a.hidden)
    if not moves:
        _p("하위 폴더에 옮길 파일이 없습니다.")
        return 0

    base = (dest or root).resolve()
    prefix = "" if a.apply else DRY + " "
    for mv in moves[:a.limit]:
        src = Path(mv.src).relative_to(root.resolve())
        _p(f"{prefix}{src}  ->  {Path(mv.dst).relative_to(base)}")
    if len(moves) > a.limit:
        _p(f"... {len(moves) - a.limit}개 더")

    renamed = len([m for m in moves
                   if Path(m.src).name != Path(m.dst).name])
    _p(f"\n파일 {len(moves)}개" + (f", 이름이 겹쳐 바뀐 것 {renamed}개" if renamed else ""))
    if renamed and not a.keep_path:
        _p("--keep-path 를 주면 폴더 이름을 앞에 붙여 겹침을 줄입니다.")

    if not a.apply:
        _p("실제로 옮기려면 --apply 를 붙이세요.")
        return 0

    journal = files.apply_moves(moves)
    _p(f"\n{len(moves)}개를 옮겼습니다.")
    if a.prune:
        removed = 0
        # 안쪽을 지우면 바깥이 비므로 더 지울 것이 없을 때까지 되풀이한다
        while True:
            found = files.empty_dirs(root)
            if not found:
                break
            gone = 0
            for path in found:
                try:
                    path.rmdir()
                    gone += 1
                except OSError:
                    continue
            removed += gone
            if not gone:
                break
        _p(f"빈 폴더 {removed}개를 지웠습니다. (비어 있는 것만 지웁니다)")
    _p(f"되돌리기: at file undo {journal}")
    if a.prune:
        _p("되돌리면 파일이 있던 폴더는 다시 생깁니다. 원래부터 비어 "
           "있던 폴더는 돌아오지 않습니다.")
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

    try:
        keepers = {id(group): files.pick_keeper(group, a.keep) for group in groups}
    except ValueError as e:
        _p(str(e))
        return 1

    wasted = 0
    for i, group in enumerate(groups, 1):
        size = group[0].stat().st_size
        wasted += size * (len(group) - 1)
        keeper = keepers[id(group)]
        _p(f"[{i}] {size / 1024:,.1f} KiB x {len(group)}개")
        for p in sorted(group):
            _p(f"    {'남김' if p == keeper else '중복'}  {p}")

    _p(f"\n중복 {len(groups)}그룹, 회수 가능 용량 {wasted / 1024 / 1024:,.1f} MiB")
    _p(f"남길 기준: {a.keep} ({files.KEEP_MODES[a.keep]})")

    if a.collect:
        root = Path(a.dir)
        moves = files.plan_collect_dupes(root, groups, Path(a.collect), keep=a.keep)
        if not moves:
            _p("\n모을 것이 없습니다.")
            return 0
        _p(f"\n{'' if a.apply else DRY + ' '}{a.collect}/ 로 {len(moves)}개를 모읍니다."
           " (지우지 않습니다)")
        if not a.apply:
            _p("실제로 옮기려면 --apply 를 붙이세요.")
            return 0
        journal = files.apply_moves(moves)
        _p(f"{len(moves)}개를 옮겼습니다. 눈으로 확인한 뒤 폴더째 지우세요.")
        _p(f"되돌리기: at file undo {journal}")
        return 0

    if a.script:
        _p("\n# 확인 후 실행할 삭제 스크립트")
        for group in groups:
            keeper = keepers[id(group)]
            for p in sorted(group):
                if p != keeper:
                    _p(f'rm -i "{p}"')
    else:
        _p("\n--collect <폴더> 로 한곳에 모으면 at file undo 로 되돌릴 수 있습니다.")
        _p("삭제 명령만 보려면 --script 를 붙이세요. (직접 지우지 않습니다)")
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

    if not journal.is_file():
        _p(f"저널 파일이 아닙니다: {journal}")
        _p(f"  기록은 {files.journal_dir()} 에 .jsonl 로 남습니다.")
        return 1

    try:
        restored, errors = files.undo(journal)
    except (OSError, ValueError) as e:
        _p(f"저널을 읽지 못했습니다: {e}")
        return 1
    _p(f"{restored}개를 되돌렸습니다.")
    for e in errors:
        _p(f"  건너뜀: {e}")
    return 0 if not errors else 1


def _rename_by_map(a, root: Path) -> int:
    """목록 파일(csv·xlsx)대로 이름 바꾸기. 제출 파일명 규칙 맞출 때."""
    from .. import sheet

    try:
        table = sheet.load(Path(a.map))
    except (sheet.SheetError, OSError) as e:
        _p(f"목록을 읽지 못했습니다: {e}")
        return 1
    if table.width < 2:
        _p("목록에 열이 두 개는 있어야 합니다. (현재 이름, 새 이름)")
        return 1

    try:
        old_i = table.index_of(a.map_from) if a.map_from else 0
        new_i = table.index_of(a.map_to) if a.map_to else 1
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    pairs = [(sheet.to_text(r[old_i]), sheet.to_text(r[new_i]))
             for r in table.rows if len(r) > max(old_i, new_i)]
    plan = files.plan_rename_map(root, pairs, recursive=a.recursive)

    _p(f"목록 {Path(a.map).name}  ({table.headers[old_i]} -> {table.headers[new_i]})")
    for mv in plan.moves[:a.limit]:
        _p(f"  {Path(mv.src).name}")
        _p(f"    -> {Path(mv.dst).name}")
    if len(plan.moves) > a.limit:
        _p(f"  ... {len(plan.moves) - a.limit}개 더")

    if plan.missing:
        _p(f"\n목록에는 있는데 폴더에 없는 파일 {len(plan.missing)}개")
        for name in plan.missing[:a.limit]:
            _p(f"  {name}")
    if plan.untouched:
        _p(f"\n폴더에는 있는데 목록에 없는 파일 {len(plan.untouched)}개 "
           "- 그대로 둡니다")
        for name in plan.untouched[:a.limit]:
            _p(f"  {name}")
    if plan.same:
        _p(f"\n이미 그 이름인 파일 {len(plan.same)}개")

    if not plan.moves:
        _p("\n바꿀 이름이 없습니다.")
        return 1
    if not a.apply:
        _p(f"\n총 {len(plan.moves)}개. 실제로 바꾸려면 --apply 를 붙이세요.")
        return 0

    journal = files.apply_moves(plan.moves)
    _p(f"\n{len(plan.moves)}개 이름을 바꿨습니다.")
    _p(f"되돌리기: at file undo {journal}")
    return 0


def cmd_file_rename(a) -> int:
    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    if a.map:
        return _rename_by_map(a, root)

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
        plan = files.plan_rename_report(
            root, template, glob=a.glob, recursive=a.recursive,
            include_hidden=a.hidden, sort=a.sort, start=a.start,
            date_format=a.date_format, replacements=replacements,
            regex=a.regex, case=a.case)
    except ValueError as e:
        _p(str(e))
        return 1

    moves = plan.moves
    if plan.skipped:
        _p(f"촬영 시각(EXIF)을 못 읽어 건너뛴 파일 {len(plan.skipped)}개")
        for path in plan.skipped[:a.limit]:
            _p(f"  {path.relative_to(root.resolve())}")
        if len(plan.skipped) > a.limit:
            _p(f"  ... {len(plan.skipped) - a.limit}개 더")
        _p("  (JPEG 의 EXIF 만 읽습니다. 수정 시각을 쓰려면 {date} 를 쓰세요.)\n")

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


def cmd_file_audit(a) -> int:
    """받은 폴더를 한 번에 훑는다. 고치지 않고 볼 만한 곳만 모은다."""
    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    rep = files.audit_folder(root, recursive=not a.no_recursive,
                             include_hidden=a.hidden, dupes=not a.no_dupes,
                             samples=a.limit)
    _p(f"{root}  파일 {rep.files:,}개  ·  {files.human_size(rep.total)}")
    if not rep.notes:
        _p("\n볼 것이 없습니다.")
    for note in rep.notes:
        _p(f"\n[{note.kind}] {note.detail}")
        for line in note.samples:
            _p(f"  {_cut(line, 76)}")

    _p("\n본 것: " + " · ".join(rep.looked))
    for line in rep.skipped:
        _p(f"  못 본 것 - {line}")
    _p("  고치지는 않았습니다. 여기 없는 문제가 없다는 뜻은 아닙니다.")
    return 0


def cmd_file_pack(a) -> int:
    """메일 첨부 한도에 맞춰 여러 zip 으로 나눠 담는다."""
    import zipfile

    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1
    try:
        limit = files.parse_size(a.max)
    except ValueError as e:
        _p(str(e))
        return 1

    targets = files.plan_archive(root, glob=a.glob, include_hidden=a.hidden,
                                 recursive=not a.no_recursive)
    if not targets:
        _p("담을 파일이 없습니다.")
        return 0

    packs, too_big = files.plan_packs(targets, max_bytes=limit)
    total = sum(p.size for p in packs)
    _p(f"{root}  파일 {len(targets)}개  ·  묶음 {len(packs)}개  "
       f"(한도 {files.human_size(limit)})")

    out_dir = Path(a.out) if a.out else root.parent
    stem = a.name or root.name
    for pack in packs:
        target = out_dir / f"{stem}-{pack.index}.zip"
        _p(f"\n{target.name}  {files.human_size(pack.size)}  "
           f"파일 {len(pack.files)}개")
        for path in pack.files[:a.limit]:
            _p(f"  {path.relative_to(root)}  {files.human_size(path.stat().st_size)}")
        if len(pack.files) > a.limit:
            _p(f"  ... {len(pack.files) - a.limit}개 더")

    if too_big:
        _p(f"\n혼자서 한도를 넘는 파일 {len(too_big)}개 - 담지 않았습니다")
        for path, size in too_big[:a.limit]:
            _p(f"  {path.relative_to(root)}  {files.human_size(size)}")
        _p("  나눠 담을 수 없습니다. 파일 자체를 줄이거나 따로 보내세요.")

    if not a.apply:
        _p(f"\n모두 {files.human_size(total)}. 실제로 만들려면 --apply 를 붙이세요.")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    _p("")
    for pack in packs:
        target = files.unique_path(out_dir / f"{stem}-{pack.index}.zip")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            for path in pack.files:
                z.write(path, str(path.relative_to(root)))
        made = target.stat().st_size
        mark = "  (한도를 넘었습니다)" if made > limit else ""
        _p(f"{target}  {files.human_size(made)}{mark}")
    _p("\n원본은 그대로 두었습니다.")
    return 1 if too_big and a.strict else 0


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


def cmd_file_image(a) -> int:
    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    found, unknown = files.scan_images(root, recursive=not a.no_recursive,
                                       hidden=a.hidden)
    if not found and not unknown:
        _p("이미지 파일을 찾지 못했습니다.")
        return 0

    order = {"size": lambda i: -i.size, "pixel": lambda i: -i.pixels,
             "name": lambda i: str(i.path)}
    rows = sorted(found, key=order[a.sort])
    if a.over:
        rows = [i for i in rows if i.width > a.over or i.height > a.over]

    _grid(["파일", "형식", "크기", "비율", "용량"],
          [[str(i.path.relative_to(root)), i.kind, f"{i.width:,}x{i.height:,}",
            i.ratio, files.human_size(i.size)] for i in rows[:a.limit]])
    if len(rows) > a.limit:
        _p(f"  ... {len(rows) - a.limit}개 더")

    total = sum(i.size for i in found)
    _p(f"\n이미지 {len(found)}개  ·  {files.human_size(total)}")
    if a.over:
        _p(f"긴 변이 {a.over:,}px 를 넘는 것 {len(rows)}개")
    if unknown:
        _p(f"\n헤더를 읽지 못한 파일 {len(unknown)}개 (형식이 다르거나 깨졌을 수 있습니다)")
        for path in unknown[:5]:
            _p(f"  {path.relative_to(root)}")
    _p("크기는 헤더만 읽어 봅니다. 화질이나 회전 정보는 보지 않습니다.")
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
        if not _may_write(a, target):
            return 1
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

    dcs = fp.add_parser("docs",
                        help="워드·엑셀·슬라이드·한글·PDF 속성 목록 "
                             "(누가 만든 문서인가)")
    dcs.add_argument("dir", nargs="?", default=".", metavar="경로")
    dcs.add_argument("-o", "--out", metavar="파일", help="저장 경로 (.csv, .xlsx, .md)")
    dcs.add_argument("--overwrite", action="store_true",
                     help="이미 있는 파일을 덮어쓴다")
    dcs.add_argument("--flat", action="store_true", help="하위 폴더는 보지 않는다")
    dcs.add_argument("--hidden", action="store_true", help="숨김 파일도")
    dcs.add_argument("--limit", type=int, default=30, metavar="개")
    dcs.set_defaults(func=cmd_file_docs)

    pdfp = fp.add_parser("pdf", help="사진·스캔 이미지를 PDF 한 장으로 묶기")
    pdfp.add_argument("paths", nargs="+", metavar="경로", help="이미지 또는 폴더")
    pdfp.add_argument("-o", "--out", metavar="파일.pdf")
    pdfp.add_argument("--overwrite", action="store_true",
                      help="이미 있는 파일을 덮어쓴다")
    pdfp.add_argument("--page", default="a4", metavar="크기",
                      help="a4, a5, b5, letter, legal (기본 a4)")
    pdfp.add_argument("--margin", type=float, default=0.0, metavar="mm",
                      help="쪽 여백 (기본 0)")
    pdfp.add_argument("--landscape", action="store_true", help="가로 쪽으로")
    pdfp.add_argument("--no-rotate", action="store_true",
                      help="가로로 긴 이미지를 눕히지 않는다")
    pdfp.add_argument("--title", metavar="제목", help="PDF 속성의 제목")
    pdfp.add_argument("--limit", type=int, default=30, metavar="개")
    pdfp.set_defaults(func=cmd_file_pdf)

    exf = fp.add_parser("exif",
                        help="사진에 남은 촬영 정보 보기·지우기 (위치·기기)")
    exf.add_argument("dir", nargs="?", default=".", metavar="경로")
    exf.add_argument("--strip", action="store_true",
                     help="촬영 정보를 지운 사본을 만든다")
    exf.add_argument("--apply", action="store_true", help="실제로 만든다")
    exf.add_argument("--all", action="store_true",
                     help="방향 정보까지 지운다 (사진이 눕혀 보일 수 있다)")
    exf.add_argument("--flat", action="store_true", help="하위 폴더는 보지 않는다")
    exf.add_argument("--limit", type=int, default=30, metavar="개")
    exf.set_defaults(func=cmd_file_exif)

    syn = fp.add_parser("sync",
                        help="원본에서 백업 폴더로 새것·바뀐 것만 넣기")
    syn.add_argument("source", metavar="원본")
    syn.add_argument("backup", metavar="백업")
    syn.add_argument("--apply", action="store_true", help="실제로 넣는다")
    syn.add_argument("--remove-extra", action="store_true",
                     help="원본에 없는 파일을 백업에서도 뺀다")
    syn.add_argument("--no-keep", action="store_true",
                     help="덮어쓰기 전의 판을 남기지 않는다")
    syn.add_argument("-g", "--glob", action="append", metavar="패턴")
    syn.add_argument("--hidden", action="store_true", help="숨김 파일도")
    syn.add_argument("--quick", action="store_true",
                     help="크기만 견준다 (빠르지만 크기 같은 변경은 못 잡는다)")
    syn.add_argument("--limit", type=int, default=20, metavar="개")
    syn.set_defaults(func=cmd_file_sync)

    scb = fp.add_parser("scrub",
                        help="문서 속성에서 사람·회사 이름 지우기 (밖으로 보내기 전)")
    scb.add_argument("dir", nargs="?", default=".", metavar="경로")
    scb.add_argument("--apply", action="store_true",
                     help="사본을 실제로 만든다 (원본은 그대로)")
    scb.add_argument("--flat", action="store_true", help="하위 폴더는 보지 않는다")
    scb.add_argument("--limit", type=int, default=30, metavar="개")
    scb.set_defaults(func=cmd_file_scrub)

    ls = fp.add_parser("list", help="파일 목록을 표로 (엑셀에 붙일 자료 목록)")
    ls.add_argument("dir")
    ls.add_argument("-o", "--out", help="저장 경로 (.csv, .xlsx, .md)")
    ls.add_argument("--overwrite", action="store_true",
                    help="이미 있는 파일을 덮어쓴다")
    ls.add_argument("-g", "--glob", action="append", metavar="패턴",
                    help="예: -g '*.pdf' (여러 번)")
    ls.add_argument("--flat", action="store_true", help="하위 폴더는 보지 않는다")
    ls.add_argument("--hidden", action="store_true", help="숨김 파일도")
    ls.add_argument("--sort", default="name", choices=list(files.LIST_SORTS),
                    help="정렬 기준 (기본 name)")
    ls.add_argument("--limit", type=int, default=40, metavar="개")
    ls.set_defaults(func=cmd_file_list)

    ph = fp.add_parser("photos", help="사진을 촬영 날짜별로 (EXIF)")
    ph.add_argument("dir")
    ph.add_argument("--by", default="month", choices=["year", "month", "day"],
                    help="폴더 단위 (기본 month)")
    ph.add_argument("--apply", action="store_true", help="실제로 옮긴다 (기본은 미리보기)")
    ph.add_argument("--flat", action="store_true", help="하위 폴더는 보지 않는다")
    ph.add_argument("--hidden", action="store_true", help="숨김 파일도 포함")
    ph.add_argument("--mtime", action="store_true",
                    help="촬영 시각이 없으면 수정 시각으로라도 묶는다")
    ph.add_argument("--limit", type=int, default=10, metavar="개",
                    help="두고 온 사진을 몇 개까지 보일지")
    ph.set_defaults(func=cmd_file_photos)

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
                         "쓸 수 있는 항목: {seq} {date} {time} {taken} "
                         "{taken_time} {stem} {ext} {name} {parent} {size}  "
                         "({taken} 은 사진 촬영 시각(EXIF), {date} 는 수정 시각)")
    rn.add_argument("--date", action="store_true", help="수정 날짜를 앞에 붙인다")
    rn.add_argument("--seq", action="store_true", help="번호를 붙인다")
    rn.add_argument("--digits", type=int, default=3, metavar="자리")
    rn.add_argument("--start", type=int, default=1, metavar="번호")
    rn.add_argument("--join", default="_", metavar="글자", help="항목 사이 구분자")
    rn.add_argument("--prefix", metavar="문자열")
    rn.add_argument("--suffix", metavar="문자열", help="확장자 앞에 붙인다")
    rn.add_argument("--replace", action="append", metavar="옛것=새것")
    rn.add_argument("--map", metavar="목록파일",
                    help="csv·xlsx 목록대로 바꾼다 (첫 열 현재 이름, 둘째 열 새 이름)")
    rn.add_argument("--map-from", metavar="열", help="--map 에서 현재 이름 열")
    rn.add_argument("--map-to", metavar="열", help="--map 에서 새 이름 열")
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
    d.add_argument("--keep", default="shortest", choices=list(files.KEEP_MODES),
                   help="무리마다 남길 하나를 고르는 기준 (기본 shortest)")
    d.add_argument("--collect", metavar="폴더",
                   help="지우지 않고 이 폴더로 모은다 (at file undo 로 되돌아온다)")
    d.add_argument("--apply", action="store_true",
                   help="--collect 을 실제로 실행 (기본은 미리보기)")
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

    au = fp.add_parser("audit", help="받은 폴더 한 번에 훑기 (구성·이름·중복·찌꺼기)")
    au.add_argument("dir")
    au.add_argument("--hidden", action="store_true", help="숨김 파일도 본다")
    au.add_argument("--no-recursive", action="store_true", help="아래 폴더는 안 본다")
    au.add_argument("--no-dupes", action="store_true",
                    help="내용이 같은 파일은 찾지 않는다 (큰 폴더에서 빠르게)")
    au.add_argument("--limit", type=int, default=5, metavar="개",
                    help="갈래마다 예시를 몇 개 보일지")
    au.set_defaults(func=cmd_file_audit)

    pk2 = fp.add_parser("pack", help="메일 첨부 한도에 맞춰 여러 zip 으로 나눠 담기")
    pk2.add_argument("dir")
    pk2.add_argument("--max", default="25MB", metavar="크기",
                     help="한 묶음의 한도 (기본 25MB. 단위 없으면 MB)")
    pk2.add_argument("-o", "--out", metavar="폴더", help="기본은 그 폴더 옆")
    pk2.add_argument("--overwrite", action="store_true",
                     help="이미 있는 파일을 덮어쓴다")
    pk2.add_argument("--name", metavar="이름", help="zip 이름 앞부분 (기본 폴더 이름)")
    pk2.add_argument("-g", "--glob", action="append", metavar="패턴")
    pk2.add_argument("--hidden", action="store_true")
    pk2.add_argument("--no-recursive", action="store_true")
    pk2.add_argument("--limit", type=int, default=10, metavar="개",
                     help="묶음마다 몇 개까지 보일지")
    pk2.add_argument("--strict", action="store_true",
                     help="혼자 한도를 넘는 파일이 있으면 1 로 끝낸다")
    pk2.add_argument("--apply", action="store_true", help="실제로 zip 을 만든다")
    pk2.set_defaults(func=cmd_file_pack)

    ar = fp.add_parser("archive", help="오래된 파일을 zip 으로 보관")
    ar.add_argument("dir")
    ar.add_argument("-o", "--out", metavar="파일", help="기본: <디렉터리이름>-<날짜>.zip")
    ar.add_argument("--overwrite", action="store_true",
                    help="이미 있는 파일을 덮어쓴다")
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

    im = fp.add_parser("image", help="이미지 크기·용량 훑기 (png·jpg·gif·bmp·webp)")
    im.add_argument("dir", nargs="?", default=".")
    im.add_argument("--sort", default="size", choices=["size", "pixel", "name"])
    im.add_argument("--over", type=int, default=0, metavar="px",
                    help="긴 변이 이보다 큰 것만 (예: 2000)")
    im.add_argument("--hidden", action="store_true")
    im.add_argument("--no-recursive", action="store_true")
    im.add_argument("--limit", type=int, default=20)
    im.set_defaults(func=cmd_file_image)

    rt = fp.add_parser("route", help="규칙 파일대로 폴더에 나눠 담기")
    rt.add_argument("dir", nargs="?", default=".")
    rt.add_argument("--rules", metavar="파일", help="규칙을 적어 둔 JSON")
    rt.add_argument("--example", action="store_true", help="규칙 파일 예시를 출력")
    rt.add_argument("-r", "--recursive", action="store_true")
    rt.add_argument("--hidden", action="store_true")
    rt.add_argument("--min-age", type=float, default=0.0, metavar="일",
                    help="이만큼 오래된 파일만")
    rt.add_argument("--limit", type=int, default=20)
    rt.add_argument("--apply", action="store_true")
    rt.set_defaults(func=cmd_file_route)

    ft = fp.add_parser("flatten", help="하위 폴더의 파일을 한 곳으로 모으기")
    ft.add_argument("dir", nargs="?", default=".")
    ft.add_argument("-o", "--out", metavar="디렉터리", help="기본은 그 디렉터리 자신")
    ft.add_argument("--overwrite", action="store_true",
                    help="이미 있는 파일을 덮어쓴다")
    ft.add_argument("--keep-path", action="store_true",
                    help="폴더 이름을 파일명 앞에 붙인다")
    ft.add_argument("--sep", default="_", metavar="구분자")
    ft.add_argument("--hidden", action="store_true")
    ft.add_argument("--prune", action="store_true",
                    help="옮긴 뒤 빈 폴더를 지운다 (비어 있는 것만)")
    ft.add_argument("--limit", type=int, default=20)
    ft.add_argument("--apply", action="store_true")
    ft.set_defaults(func=cmd_file_flatten)

    hs = fp.add_parser("hash", help="체크섬 만들기·검증 (배포·백업 무결성)")
    hs.add_argument("dir", nargs="?", default=".")
    hs.add_argument("-a", "--algorithm", default="sha256",
                    choices=list(files.HASH_ALGORITHMS))
    hs.add_argument("-g", "--glob", action="append", metavar="패턴")
    hs.add_argument("--hidden", action="store_true")
    hs.add_argument("--no-recursive", action="store_true")
    hs.add_argument("-o", "--out", metavar="파일", help="예: SHA256SUMS.txt")
    hs.add_argument("--overwrite", action="store_true",
                    help="이미 있는 파일을 덮어쓴다")
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
