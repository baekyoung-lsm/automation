"""파일 정리 화면. 어질러진 폴더를 종류별·날짜별로 묶고, 되돌린다."""

from __future__ import annotations

from pathlib import Path

from ... import files
from .. import App, UiError, form

MODES = {
    "ext": "종류별 (문서·사진·압축…)",
    "date": "날짜별 (2026-09)",
    "ext-date": "종류별 → 날짜별",
    "date-ext": "날짜별 → 종류별",
    "photo-month": "사진을 찍은 달별 (EXIF)",
    "photo-year": "사진을 찍은 해별 (EXIF)",
    "fixname": "옮기지 않고 이름만 다듬기",
}


def _plan(payload: dict) -> tuple[Path, list[files.Move], list[str]]:
    """계획과 함께 «못 한 것»을 돌려준다. 조용히 빼놓지 않기 위해서다."""
    root = form.folder(payload)
    mode = form.choice(payload, "mode", MODES, "ext")
    recursive = form.flag(payload, "recursive")
    hidden = form.flag(payload, "hidden")
    notes: list[str] = []

    if mode == "fixname":
        moves = files.plan_fixname(
            root, recursive=recursive, include_hidden=hidden,
            space="underscore" if form.flag(payload, "underscore") else "keep")
    elif mode.startswith("photo-"):
        plan = files.plan_photos(
            root, by=mode.split("-", 1)[1], recursive=recursive,
            include_hidden=hidden, use_mtime=form.flag(payload, "mtime"))
        moves = plan.moves
        if plan.from_exif:
            notes.append(f"촬영 시각으로 {plan.from_exif}개")
        if plan.from_mtime:
            notes.append(f"수정 시각으로 {len(plan.from_mtime)}개 "
                         "(복사한 날일 수 있습니다)")
        if plan.left:
            notes.append(f"촬영 시각을 못 읽어 두고 온 사진 {len(plan.left)}개 "
                         "(JPEG 의 EXIF 만 읽습니다)")
    else:
        moves = files.plan_organize(
            root, by=mode, recursive=recursive, include_hidden=hidden,
            min_age_days=form.number(payload, "min_age", 0.0, low=0.0, high=36500.0),
            fixname=form.flag(payload, "fixname"))
    return root, moves, notes


def _rows(root: Path, moves: list[files.Move]) -> list[list[str]]:
    rows = []
    for mv in moves:
        src, dst = Path(mv.src), Path(mv.dst)
        try:
            here = str(src.relative_to(root))
            there = str(dst.relative_to(root))
        except ValueError:  # 뿌리 밖으로 나가는 계획은 그대로 보여준다
            here, there = str(src), str(dst)
        rows.append([here, there])
    return rows


def _command(payload: dict, root: Path, *, apply: bool = False) -> str:
    mode = form.choice(payload, "mode", MODES, "ext")
    args: list[object] = ["file"]
    if mode == "fixname":
        args += ["fixname", root]
    elif mode.startswith("photo-"):
        args += ["photos", root, "--by", mode.split("-", 1)[1]]
        if form.flag(payload, "mtime"):
            args.append("--mtime")
        if not form.flag(payload, "recursive"):
            args.append("--flat")
    else:
        args += ["organize", root, "--by", mode]
        if form.flag(payload, "fixname"):
            args.append("--fixname")
    if form.flag(payload, "recursive") and not mode.startswith("photo-"):
        args.append("-r")
    if form.flag(payload, "hidden"):
        args.append("--hidden")
    if apply:
        args.append("--apply")
    return form.command(*args)


def preview(payload: dict) -> dict:
    root, moves, notes = _plan(payload)
    return {"root": str(root), "count": len(moves),
            "rows": _rows(root, moves), "notes": notes,
            "command": _command(payload, root, apply=True)}


def apply(payload: dict) -> dict:
    """계획을 여기서 다시 세운다. 화면이 보낸 경로를 그대로 옮기지 않는다."""
    root, moves, notes = _plan(payload)
    if not moves:
        raise UiError("옮길 것이 없습니다. 먼저 미리보기로 확인해 주세요.")
    journal = files.apply_moves(moves)
    return {"applied": len(moves), "root": str(root),
            "journal": journal.name if journal else "",
            "rows": _rows(root, moves), "notes": notes,
            "command": form.command("file", "undo")}


DUPE_DEST = "_중복"


def _dupe_groups(payload: dict):
    root = form.folder(payload)
    groups = files.find_duplicates(
        root, recursive=not form.flag(payload, "flat"),
        include_hidden=form.flag(payload, "hidden"),
        min_size=int(form.number(payload, "min_size", 1024, low=1,
                                 high=1 << 40)))
    keep = form.choice(payload, "keep", files.KEEP_MODES, "shortest")
    return root, groups, keep


def dupes(payload: dict) -> dict:
    root, groups, keep = _dupe_groups(payload)
    rows, wasted = [], 0
    for number, group in enumerate(groups[:40], 1):
        size = group[0].stat().st_size
        wasted += size * (len(group) - 1)
        keeper = files.pick_keeper(group, keep)
        for path in sorted(group):
            rows.append([str(number), "남김" if path == keeper else "중복",
                         str(path.relative_to(root)), files.human_size(size)])
    return {"rows": rows, "groups": len(groups),
            "wasted": files.human_size(wasted),
            "keep": files.KEEP_MODES[keep],
            "shown": min(len(groups), 40)}


def _collect_plan(payload: dict):
    root, groups, keep = _dupe_groups(payload)
    if not groups:
        raise UiError("중복 파일이 없습니다.")
    moves = files.plan_collect_dupes(root, groups, root / DUPE_DEST, keep=keep)
    if not moves:
        raise UiError("모을 것이 없습니다. 이미 다 모아 두었습니다.")
    return root, moves


def collect_preview(payload: dict) -> dict:
    root, moves = _collect_plan(payload)
    return {"count": len(moves), "dest": str(root / DUPE_DEST),
            "rows": _rows(root, moves)}


def collect_apply(payload: dict) -> dict:
    """지우지 않고 옮긴다. 저널에 남아 되돌리기에서 함께 보인다."""
    root, moves = _collect_plan(payload)
    journal = files.apply_moves(moves)
    return {"applied": len(moves), "dest": str(root / DUPE_DEST),
            "journal": journal.name if journal else "",
            "rows": _rows(root, moves)}


MAX_DIFF = 200


def compare(payload: dict) -> dict:
    """두 폴더를 견준다. 백업이 제대로 됐는지 확인하는 자리다."""
    left = form.folder(payload)
    other = form.text(payload, "other")
    if not other:
        raise UiError("견줄 폴더 경로를 적어 주세요.")
    right = form.folder({"path": other})
    if left == right:
        raise UiError("같은 폴더입니다. 다른 폴더를 골라 주세요.")

    result = files.diff_dirs(left, right,
                             include_hidden=form.flag(payload, "hidden"),
                             quick=form.flag(payload, "quick"))
    rows = []
    for name in result.only_left[:MAX_DIFF]:
        rows.append(["왼쪽에만", name, "", ""])
    for name in result.only_right[:MAX_DIFF]:
        rows.append(["오른쪽에만", name, "", ""])
    for name, left_size, right_size in result.changed[:MAX_DIFF]:
        rows.append(["내용이 다름", name, files.human_size(left_size),
                     files.human_size(right_size)])

    return {"rows": rows, "same": result.same, "total": result.total,
            "equal": result.empty, "left": str(left), "right": str(right),
            "note": "크기가 같아도 내용을 해시로 한 번 더 봅니다. "
                    "«빠르게»를 켜면 크기와 수정 시각만 봅니다 - 큰 폴더는 "
                    "빠르지만 내용이 바뀐 것을 놓칠 수 있습니다."}


LIST_ROWS = 200


def listing(payload: dict) -> dict:
    """폴더 안 파일 목록. 엑셀에 붙일 자료 목록을 손으로 안 적게."""
    root = form.folder(payload)
    globs = [g.strip() for g in form.text(payload, "glob").split(",") if g.strip()]
    try:
        rows = files.list_files(
            root, recursive=not form.flag(payload, "flat"),
            include_hidden=form.flag(payload, "hidden"), glob=globs or None,
            sort=form.choice(payload, "sort", files.LIST_SORTS, "name"))
    except ValueError as exc:
        raise UiError(str(exc)) from None
    if not rows:
        raise UiError("파일이 없습니다.")

    return {
        "rows": [[r.name, r.folder, r.suffix, files.human_size(r.size),
                  r.modified.strftime("%Y-%m-%d %H:%M")]
                 for r in rows[:LIST_ROWS]],
        "count": len(rows), "shown": min(len(rows), LIST_ROWS),
        "total": files.human_size(sum(r.size for r in rows)),
        "command": form.command("file", "list", root, "-o", "목록.xlsx"),
    }


def listing_save(payload: dict) -> dict:
    """목록을 파일로 낸다. 원본 폴더는 건드리지 않는다."""
    from ... import sheet

    root = form.folder(payload)
    globs = [g.strip() for g in form.text(payload, "glob").split(",") if g.strip()]
    rows = files.list_files(
        root, recursive=not form.flag(payload, "flat"),
        include_hidden=form.flag(payload, "hidden"), glob=globs or None,
        sort=form.choice(payload, "sort", files.LIST_SORTS, "name"))
    if not rows:
        raise UiError("파일이 없습니다.")

    suffix = form.choice(payload, "format", {".xlsx", ".csv", ".md"}, ".xlsx")
    table = sheet.Table(
        ["이름", "폴더", "확장자", "크기(바이트)", "크기", "수정일", "수정시각"],
        [[r.name, r.folder, r.suffix, r.size, files.human_size(r.size),
          r.modified.strftime("%Y-%m-%d"), r.modified.strftime("%H:%M")]
         for r in rows])
    out = files.unique_path(root.parent / f"{root.name} 목록{suffix}")
    sheet.save(table, out)
    return {"saved": str(out), "count": len(rows),
            "command": form.command("file", "list", root, "-o", out)}


def audit(payload: dict) -> dict:
    """받은 폴더를 한 번에 훑는다. 고치지 않고 볼 만한 곳만."""
    root = form.folder(payload, "aroot")
    rep = files.audit_folder(root, include_hidden=form.flag(payload, "ahidden"),
                             dupes=not form.flag(payload, "anodupes"))
    args: list[object] = ["file", "audit", root]
    if form.flag(payload, "ahidden"):
        args.append("--hidden")
    if form.flag(payload, "anodupes"):
        args.append("--no-dupes")
    return {"notes": [{"kind": n.kind, "detail": n.detail, "samples": n.samples}
                      for n in rep.notes],
            "files": rep.files, "total": files.human_size(rep.total),
            "looked": rep.looked, "skipped": rep.skipped,
            "command": form.command(*args)}


def _scrub_targets(payload: dict, *, pdf: bool = False):
    raw = form.text(payload, "docroot")
    if not raw:
        raise UiError("폴더 또는 파일 경로를 적어 주세요.")
    root = Path(raw).expanduser()
    if not root.exists():
        raise UiError(f"없는 경로입니다: {root}")
    if root.is_file():
        return root, [root]
    return root, [m.path for m in files.scan_documents(root, pdf=pdf)]


def _scrub_command(payload: dict, root, *, apply: bool = False) -> str:
    args: list[object] = ["file", "scrub", root]
    return form.command(*args, *(["--apply"] if apply else []))


def documents(payload: dict) -> dict:
    """문서 속성만 읽어 «누가 만든 문서인가» 를 본다. 내용은 열지 않는다."""
    root, targets = _scrub_targets(payload, pdf=True)   # 속성 보기는 PDF 도 본다
    metas = [files.meta_of(p) for p in targets]
    rows = [[m.path.name, m.kind, m.title, m.author, m.last_by,
             m.modified[:10], "" if m.pages is None else f"{m.pages:,}",
             m.error] for m in metas]
    left = [[m.path.name, ", ".join(m.personal)] for m in metas if m.personal]
    return {"rows": rows, "left": left, "count": len(metas),
            "command": form.command("file", "docs", root)}


def scrub_preview(payload: dict) -> dict:
    root, targets = _scrub_targets(payload)
    plans = [files.plan_scrub(p) for p in targets]
    dirty = [p for p in plans if p.ok]
    return {"rows": [[plan.path.name, label, value]
                     for plan in dirty for label, value in plan.removed],
            "count": len(dirty), "looked": len(plans),
            "others": sorted({part for plan in dirty for part in plan.others}),
            "broken": [[p.path.name, p.error] for p in plans if p.error],
            "command": _scrub_command(payload, root)}


def scrub_apply(payload: dict) -> dict:
    """이름을 지운 사본을 만든다. 원본은 건드리지 않는다."""
    root, targets = _scrub_targets(payload)
    out = scrub_preview(payload)
    made: list[str] = []
    for path in targets:
        plan = files.plan_scrub(path)
        if not plan.ok:
            continue
        target = files.unique_path(
            path.with_name(f"{path.stem} (이름지움){path.suffix}"))
        files.apply_scrub(path, target)
        made.append(str(target))
    out["made"] = made
    out["command"] = _scrub_command(payload, root, apply=True)
    return out


def _sync_plan(payload: dict):
    source = form.folder(payload, "syncfrom")
    raw = form.text(payload, "syncto")
    if not raw:
        raise UiError("백업 폴더를 적어 주세요.")
    backup = Path(raw).expanduser()
    if backup.exists() and not backup.is_dir():
        raise UiError(f"폴더가 아닙니다: {backup}")
    plan = files.plan_sync(source, backup,
                           include_hidden=form.flag(payload, "synchidden"))
    return source, backup, plan


def _sync_command(payload: dict, source, backup, *, apply: bool = False) -> str:
    args: list = ["file", "sync", source, backup]
    if form.flag(payload, "synchidden"):
        args.append("--hidden")
    if apply:
        args.append("--apply")
    return form.command(*args)


def _sync_result(plan, source, backup) -> dict:
    return {"new": plan.new[:200], "changed": plan.changed[:200],
            "extra": plan.extra[:200], "same": plan.same,
            "count": len(plan.new) + len(plan.changed),
            "size": files.human_size(plan.bytes),
            "backup": str(backup), "source": str(source)}


def sync_preview(payload: dict) -> dict:
    source, backup, plan = _sync_plan(payload)
    out = _sync_result(plan, source, backup)
    out["command"] = _sync_command(payload, source, backup)
    return out


def sync_apply(payload: dict) -> dict:
    """새것·바뀐 것만 넣는다. 원본에 없는 파일은 건드리지 않는다."""
    source, backup, plan = _sync_plan(payload)
    if plan.empty:
        raise UiError("넣을 것이 없습니다.")
    backup.mkdir(parents=True, exist_ok=True)
    copied, _removed, failed = files.apply_sync(source, backup, plan)
    out = _sync_result(plan, source, backup)
    out["copied"] = copied
    out["failed"] = [[name, why] for name, why in failed[:20]]
    out["command"] = _sync_command(payload, source, backup, apply=True)
    return out


def _photo_targets(payload: dict):
    raw = form.text(payload, "photoroot")
    if not raw:
        raise UiError("폴더 또는 사진 경로를 적어 주세요.")
    root = Path(raw).expanduser()
    if not root.exists():
        raise UiError(f"없는 경로입니다: {root}")
    return root, files.scan_photos(root)


def _photo_rows(metas) -> list[list[str]]:
    return [[m.path.name,
             m.taken.strftime("%Y-%m-%d %H:%M") if m.taken else "",
             f"{m.make} {m.model}".strip(), m.where,
             "" if m.orientation in (None, 1) else str(m.orientation),
             m.error] for m in metas]


def photos(payload: dict) -> dict:
    """사진에 남은 촬영 정보를 본다. 지우지는 않는다."""
    root, metas = _photo_targets(payload)
    return {"rows": _photo_rows(metas), "count": len(metas),
            "located": sum(1 for m in metas if m.where),
            "dirty": sum(1 for m in metas if m.personal),
            "command": form.command("file", "exif", root)}


def photos_strip(payload: dict) -> dict:
    """촬영 정보를 지운 사본을 만든다. 원본은 그대로 둔다."""
    root, metas = _photo_targets(payload)
    keep = not form.flag(payload, "photoall")
    made: list[str] = []
    for meta in metas:
        if not meta.personal:
            continue
        target = files.unique_path(meta.path.with_name(
            f"{meta.path.stem} (정보지움){meta.path.suffix}"))
        try:
            files.strip_exif(meta.path, target, keep_orientation=keep)
        except (OSError, ValueError):
            continue
        made.append(str(target))
    if not made:
        raise UiError("지울 촬영 정보가 없습니다.")

    args: list[object] = ["file", "exif", root, "--strip", "--apply"]
    if not keep:
        args.append("--all")
    return {"rows": _photo_rows(metas), "count": len(metas),
            "located": sum(1 for m in metas if m.where),
            "dirty": len(made), "made": made,
            "kept": sum(1 for m in metas
                        if keep and m.personal and m.orientation not in (None, 1)),
            "command": form.command(*args)}


def _pdf_images(payload: dict):
    from ... import pdf

    root = form.folder(payload, "pdfroot")
    targets = sorted(p for p in root.iterdir()
                     if p.is_file() and p.suffix.lower() in pdf.IMAGE_SUFFIXES)
    pages, skipped = [], []
    for path in targets:
        try:
            pages.append(pdf.read_image(path))
        except pdf.PdfError as exc:
            skipped.append([path.name, str(exc)])
    return root, pages, skipped


def _pdf_command(payload: dict, root, out=None) -> str:
    args: list[object] = ["file", "pdf", root]
    page = form.text(payload, "pdfpage") or "a4"
    if page != "a4":
        args += ["--page", page]
    if form.flag(payload, "pdfmargin"):
        args += ["--margin", 10]
    return form.command(*args, *(["-o", out] if out else []))


def pdf_preview(payload: dict) -> dict:
    root, pages, skipped = _pdf_images(payload)
    return {"rows": [[p.path.name, f"{p.width}x{p.height}",
                      "jpg (그대로)" if p.filter == "DCTDecode" else "png"]
                     for p in pages],
            "count": len(pages), "skipped": skipped,
            "command": _pdf_command(payload, root)}


def pdf_make(payload: dict) -> dict:
    """폴더 옆에 «폴더이름.pdf» 를 만든다. 원본 이미지는 그대로 둔다."""
    from ... import pdf

    root, pages, skipped = _pdf_images(payload)
    if not pages:
        raise UiError("넣을 수 있는 이미지가 없습니다. (jpg·png 만 넣습니다)")
    page = form.choice(payload, "pdfpage", pdf.PAGE_SIZES, "a4")
    out = files.unique_path(root.with_suffix(".pdf"))
    try:
        made = pdf.images_to_pdf(pages, out, page=page,
                                 margin_mm=10.0 if form.flag(payload, "pdfmargin")
                                 else 0.0,
                                 title=form.text(payload, "pdftitle"))
    except pdf.PdfError as exc:
        raise UiError(str(exc)) from None
    return {"rows": [[p.path.name, f"{p.width}x{p.height}",
                      "jpg (그대로)" if p.filter == "DCTDecode" else "png"]
                     for p in pages],
            "count": len(pages), "skipped": skipped, "saved": str(made),
            "size": files.human_size(made.stat().st_size),
            "command": _pdf_command(payload, root, made)}


def _cut_plan(payload: dict):
    """고른 PDF 와 뽑을 쪽을 정한다. 계획은 언제나 서버에서 다시 세운다."""
    from ... import pdf

    path = form.existing_file(payload, "cutfile", max_bytes=0)
    try:
        doc = pdf.open_pdf(path)
        total = len(doc.pages())
        keep = (pdf.page_numbers(form.text(payload, "cutpages"), total)
                if form.text(payload, "cutpages") else list(range(1, total + 1)))
        if form.text(payload, "cutdrop"):
            drop = set(pdf.page_numbers(form.text(payload, "cutdrop"), total))
            keep = [n for n in keep if n not in drop]
    except (pdf.PdfError, OSError, ValueError) as exc:
        raise UiError(str(exc)) from None
    if not keep:
        raise UiError("남는 쪽이 없습니다. 뺀 쪽을 다시 보세요.")
    return doc, path, total, keep


def _cut_command(payload: dict, path, out=None) -> str:
    args: list[object] = ["file", "pdfcut", path]
    if form.text(payload, "cutpages"):
        args += ["--pages", form.text(payload, "cutpages")]
    if form.text(payload, "cutdrop"):
        args += ["--drop", form.text(payload, "cutdrop")]
    return form.command(*args, *(["-o", out] if out else []))


def _cut_rows(path, total: int, keep: list[int]) -> list[list[str]]:
    return [[path.name, f"{total:,}쪽", f"{len(keep):,}쪽",
             ", ".join(str(n) for n in keep[:40])
             + (" ..." if len(keep) > 40 else "")]]


def cut_preview(payload: dict) -> dict:
    _doc, path, total, keep = _cut_plan(payload)
    return {"rows": _cut_rows(path, total, keep), "count": len(keep),
            "command": _cut_command(payload, path)}


def cut_make(payload: dict) -> dict:
    """원본 옆에 «이름(쪽뽑음).pdf» 를 만든다. 원본은 건드리지 않는다."""
    from ... import pdf

    doc, path, total, keep = _cut_plan(payload)
    out = files.unique_path(path.with_name(f"{path.stem}(쪽뽑음).pdf"))
    try:
        result = pdf.join_pdfs([(doc, keep)], out)
    except (pdf.PdfError, OSError) as exc:
        raise UiError(str(exc)) from None
    return {"rows": _cut_rows(path, total, keep), "count": result.pages,
            "saved": str(out), "size": files.human_size(out.stat().st_size),
            "missing": result.missing,
            "command": _cut_command(payload, path, out)}


def _join_plan(payload: dict):
    """폴더 안의 PDF 를 이름 순으로. 스캔은 대개 그 차례가 맞다."""
    from ... import pdf

    root = form.folder(payload, "joinroot")
    targets = sorted(p for p in root.iterdir()
                     if p.is_file() and p.suffix.lower() == ".pdf")
    picks, rows, skipped = [], [], []
    for path in targets:
        try:
            doc = pdf.open_pdf(path)
            count = len(doc.pages())
        except (pdf.PdfError, OSError, ValueError) as exc:
            skipped.append([path.name, str(exc)])
            continue
        picks.append((doc, list(range(1, count + 1))))
        rows.append([str(len(rows) + 1), path.name, f"{count:,}"])
    return root, targets, picks, rows, skipped


def _join_command(payload: dict, targets, out=None) -> str:
    return form.command("file", "pdfjoin", *targets,
                        *(["-o", out] if out else []))


def join_preview(payload: dict) -> dict:
    _root, targets, picks, rows, skipped = _join_plan(payload)
    return {"rows": rows, "skipped": skipped,
            "count": sum(len(n) for _doc, n in picks),
            "files": len(picks),
            "command": _join_command(payload, targets)}


def join_make(payload: dict) -> dict:
    """폴더 옆에 «폴더이름.pdf» 를 만든다. 원본은 그대로 둔다."""
    from ... import pdf

    root, targets, picks, rows, skipped = _join_plan(payload)
    if len(picks) < 2:
        raise UiError("합칠 PDF 가 두 개 넘게 있어야 합니다. "
                      f"({root} 안에서 {len(picks)}개를 찾았습니다)")
    out = files.unique_path(root.with_name(f"{root.name}(합본).pdf"))
    try:
        result = pdf.join_pdfs(picks, out)
    except (pdf.PdfError, OSError) as exc:
        raise UiError(str(exc)) from None
    return {"rows": rows, "skipped": skipped, "count": result.pages,
            "files": len(picks), "saved": str(out),
            "size": files.human_size(out.stat().st_size),
            "missing": result.missing,
            "command": _join_command(payload, targets, out)}


def _pack_plan(payload: dict):
    root = form.folder(payload, "packroot")
    try:
        limit = files.parse_size(form.text(payload, "packmax") or "25MB")
    except ValueError as exc:
        raise UiError(str(exc)) from None
    globs = [g.strip() for g in form.text(payload, "packglob").split(",") if g.strip()]
    targets = files.plan_archive(root, glob=globs or None,
                                 include_hidden=form.flag(payload, "packhidden"))
    if not targets:
        raise UiError("담을 파일이 없습니다.")
    packs, too_big = files.plan_packs(targets, max_bytes=limit)
    return root, limit, packs, too_big


def _pack_command(payload: dict, root: Path, *, apply: bool = False) -> str:
    args: list[object] = ["file", "pack", root, "--max",
                          form.text(payload, "packmax") or "25MB"]
    for glob in [g.strip() for g in form.text(payload, "packglob").split(",") if g.strip()]:
        args += ["-g", glob]
    if apply:
        args.append("--apply")
    return form.command(*args)


def _pack_result(root: Path, limit: int, packs, too_big) -> dict:
    return {
        "rows": [[f"{root.name}-{p.index}.zip", str(len(p.files)),
                  files.human_size(p.size)] for p in packs],
        "limit": files.human_size(limit),
        "count": len(packs),
        "big": [[str(path.relative_to(root)), files.human_size(size)]
                for path, size in too_big[:20]],
    }


def pack_preview(payload: dict) -> dict:
    root, limit, packs, too_big = _pack_plan(payload)
    out = _pack_result(root, limit, packs, too_big)
    out["command"] = _pack_command(payload, root)
    return out


def pack_apply(payload: dict) -> dict:
    """zip 은 폴더 «옆» 에 만든다. 안에 만들면 다음번에 자기 자신을 담는다."""
    import zipfile

    root, limit, packs, too_big = _pack_plan(payload)
    made = []
    for pack in packs:
        target = files.unique_path(root.parent / f"{root.name}-{pack.index}.zip")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            for path in pack.files:
                z.write(path, str(path.relative_to(root)))
        made.append([target.name, str(len(pack.files)),
                     files.human_size(target.stat().st_size)])
    out = _pack_result(root, limit, packs, too_big)
    out["rows"] = made
    out["saved"] = str(root.parent)
    out["command"] = _pack_command(payload, root, apply=True)
    return out


def journals(payload: dict) -> dict:
    base = files.journal_dir()
    if not base.exists():
        return {"rows": []}
    rows = []
    for path in sorted(base.glob("*.jsonl"), reverse=True)[:20]:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        rows.append([path.name, str(len(lines))])
    return {"rows": rows}


def undo(payload: dict) -> dict:
    name = form.text(payload, "journal")
    if not name or "/" in name or name.startswith("."):
        raise UiError("되돌릴 기록을 골라 주세요.")
    path = files.journal_dir() / name
    if not path.exists():
        raise UiError(f"그런 기록이 없습니다: {name}")
    restored, errors = files.undo(path)
    if not errors:
        path.unlink()
    return {"restored": restored, "errors": errors}


BODY = """
<section class="card">
  <h2>무엇을 정리할까요</h2>
  <div class="row">
    <div style="flex:2 1 22rem">
      <label for="path">폴더 경로</label>
      <input type="text" id="path" placeholder="예: ~/다운로드" data-browse="dir" spellcheck="false">
    </div>
    <div>
      <label for="mode">정리 방식</label>
      <select id="mode">%(modes)s</select>
    </div>
    <div style="flex:0 1 8rem">
      <label for="min_age">며칠 지난 것만</label>
      <input type="text" id="min_age" placeholder="0" spellcheck="false">
    </div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="recursive"> 하위 폴더까지</label>
    <label><input type="checkbox" id="hidden"> 숨김 파일도</label>
    <label><input type="checkbox" id="fixname"> 옮기면서 이름도 다듬기</label>
    <label><input type="checkbox" id="mtime"> 사진: 촬영 시각이 없으면 수정 시각으로</label>
  </div>
  <div class="actions">
    <button class="primary" id="btn-preview">미리보기</button>
    <button id="btn-apply" disabled>이대로 옮기기</button>
    <span class="spacer"></span>
    <span class="note">미리보기 없이는 아무것도 바뀌지 않습니다.</span>
  </div>
  <div id="msg"></div>
</section>

<section class="card">
  <h2>계획</h2>
  <div id="plan"><div class="empty">폴더를 넣고 미리보기를 눌러 주세요.</div></div>
</section>

<section class="card">
  <h2>파일 목록 만들기</h2>
  <p class="note">이름·폴더·크기·수정일을 표로 뽑습니다. 저장하면 폴더 옆에
     «&lt;폴더이름&gt; 목록» 파일이 생깁니다. <b>읽기만 합니다.</b></p>
  <div class="row">
    <div><label for="glob">파일 이름 조건 (쉼표로 여러 개)</label>
      <input type="text" id="glob" placeholder="*.pdf, *.xlsx" spellcheck="false"></div>
    <div style="flex:0 1 10rem"><label for="sort">정렬</label>
      <select id="sort"><option value="name">이름</option><option value="size">크기</option><option value="date">수정일</option><option value="ext">확장자</option></select></div>
    <div style="flex:0 1 8rem"><label for="format">저장 형식</label>
      <select id="format"><option value=".xlsx">xlsx</option>
        <option value=".csv">csv</option>
        <option value=".md">마크다운</option></select></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="flat"> 하위 폴더는 빼고</label>
  </div>
  <div class="actions">
    <button class="primary" id="btn-list">목록 보기</button>
    <button id="btn-list-save">파일로 저장</button>
  </div>
  <div id="listmsg"></div>
  <div id="listout"></div>
</section>

<section class="card">
  <h2>중복 찾기</h2>
  <p class="note">내용이 똑같은 파일을 찾습니다. <b>지우지 않고</b>
     무리마다 하나만 남긴 뒤 나머지를 <code>_중복/</code> 으로 옮깁니다.
     옮긴 것은 아래 되돌리기에서 통째로 되돌아옵니다.</p>
  <div class="row">
    <div><label for="keep">무리마다 남길 것</label>
      <select id="keep"><option value="shortest">경로가 가장 짧은 것 (대개 원본 자리)</option><option value="first">이름 순으로 첫 번째</option><option value="oldest">수정 시각이 가장 이른 것</option></select></div>
    <div style="flex:0 1 10rem"><label for="min_size">최소 크기(바이트)</label>
      <input type="text" id="min_size" value="1024" spellcheck="false"></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="flat"> 하위 폴더는 보지 않기</label>
  </div>
  <div class="actions">
    <button class="primary" id="btn-dupes">찾기</button>
    <button id="btn-collect">모으면 어떻게 되나</button>
    <button id="btn-collect-apply" disabled>_중복/ 으로 옮기기</button>
  </div>
  <div id="dupemsg"></div>
  <div id="dupes"></div>
</section>

<section class="card">
  <h2>두 폴더 견주기</h2>
  <p class="note">백업이 제대로 됐는지, 옮긴 것이 다 갔는지 봅니다.
     <b>읽기만 합니다.</b> 위쪽 «폴더 경로»가 왼쪽입니다.</p>
  <div class="row">
    <div style="flex:3 1 20rem"><label for="other">견줄 폴더 (오른쪽)</label>
      <input type="text" id="other" placeholder="예: /Volumes/백업/사진" data-browse="dir" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-compare">견주기</button></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="quick"> 빠르게 (크기·시각만 본다)</label>
  </div>
  <div id="cmpmsg"></div>
  <div id="cmp"></div>
</section>

<section class="card">
  <h2>받은 폴더 한 번에 훑기</h2>
  <p class="note">납품·제출 자료를 받았을 때 <b>무엇부터 봐야 하는지</b> 모아 줍니다 -
     구성, 손볼 이름(맥에서 만든 자모 분리 한글·윈도우 금지 문자), 빈 파일,
     딸려 온 찌꺼기(.DS_Store, ~$문서.xlsx), 큰 파일, 내용이 같은 파일.
     <b>고치지는 않습니다.</b></p>
  <div class="row">
    <div style="flex:3 1 20rem"><label for="aroot">폴더</label>
      <input type="text" id="aroot" data-browse="dir" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-audit">훑어보기</button></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="ahidden"> 숨김 파일도</label>
    <label><input type="checkbox" id="anodupes"> 같은 파일 찾기는 건너뛰기 (큰 폴더)</label>
  </div>
  <div id="auditmsg"></div>
  <div id="auditout"></div>
</section>

<section class="card">
  <h2>문서에 남은 이름</h2>
  <p class="note">워드·엑셀·슬라이드 파일의 <b>속성만</b> 읽습니다(내용은 열지 않습니다).
     밖으로 보내는 문서에 만든 사람·마지막 저장한 사람·회사 이름이 그대로 남아 있는
     일이 잦습니다. 지울 때는 <b>«…(이름지움)» 사본</b>을 만들고 원본은 그대로 둡니다.
     메모·변경 내역·본문에 적힌 이름은 지우지 못합니다 - 그건 내용입니다.</p>
  <div class="row">
    <div style="flex:3 1 20rem"><label for="docroot">폴더 또는 파일</label>
      <input type="text" id="docroot" data-browse="dir" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-docs">속성 보기</button></div>
    <div style="flex:0 0 auto"><button id="btn-scrub">무엇이 지워지나</button></div>
    <div style="flex:0 0 auto"><button id="btn-scrub-save" disabled>사본 만들기</button></div>
  </div>
  <div id="docsmsg"></div>
  <div id="docsout"></div>
</section>

<section class="card">
  <h2>백업 폴더에 넣기</h2>
  <p class="note">작업 폴더에서 백업 폴더로 <b>새것과 바뀐 것만</b> 넣습니다.
     무엇이 들어갈지 먼저 보여 주고, 넣기는 따로 누릅니다. 덮어쓰기 전의 판은
     백업 폴더 안 <code>.이전 (attools)</code> 로 옮겨 둡니다 - 사람이 찾는 것은
     대개 그 예전 판입니다. <b>원본에 없는 파일은 그대로 둡니다</b>(지우는 것은
     터미널에서 --remove-extra 로만).</p>
  <div class="row">
    <div style="flex:2 1 16rem"><label for="syncfrom">원본 폴더</label>
      <input type="text" id="syncfrom" data-browse="dir" spellcheck="false"></div>
    <div style="flex:2 1 16rem"><label for="syncto">백업 폴더</label>
      <input type="text" id="syncto" data-browse="dir" spellcheck="false"></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="synchidden"> 숨김 파일도</label>
  </div>
  <div class="actions">
    <button class="primary" id="btn-sync">무엇이 들어가나</button>
    <button id="btn-sync-apply" disabled>넣기</button>
  </div>
  <div id="syncmsg"></div>
  <div id="syncout"></div>
</section>

<section class="card">
  <h2>사진에 남은 위치</h2>
  <p class="note">폰으로 찍은 사진에는 <b>찍은 자리의 좌표</b>가 들어 있습니다. 그대로
     보내면 집·사무실이 드러납니다. 찍은 날·기기·위치를 보여 주고, 지울 때는
     <b>«…(정보지움).jpg» 사본</b>을 만듭니다(원본은 그대로).
     <b>방향은 남깁니다</b> - 그것까지 지우면 사진이 눕혀 보입니다.</p>
  <div class="row">
    <div style="flex:3 1 20rem"><label for="photoroot">폴더 또는 사진</label>
      <input type="text" id="photoroot" data-browse="dir" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-photos">무엇이 남았나</button></div>
    <div style="flex:0 0 auto"><button id="btn-photos-strip" disabled>지운 사본 만들기</button></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="photoall"> 방향 정보까지 지우기</label>
  </div>
  <div id="photomsg"></div>
  <div id="photoout"></div>
</section>

<section class="card">
  <h2>이미지를 PDF 로 묶기</h2>
  <p class="note">폴더 안의 사진·스캔 이미지를 <b>이름 순으로</b> 한 장에 하나씩 담은
     PDF 로 묶습니다. jpg 는 다시 누르지 않고 그대로 넣어 화질이 그대로입니다.
     비율은 지키고 쪽 가운데에 놓습니다. 넣을 수 없는 파일(프로그레시브 jpg,
     인터레이스 png)은 <b>조용히 빼지 않고</b> 까닭과 함께 알려 줍니다.
     <b>원본은 그대로 두고</b> 폴더 옆에 새 PDF 를 만듭니다.</p>
  <div class="row">
    <div style="flex:3 1 18rem"><label for="pdfroot">이미지가 있는 폴더</label>
      <input type="text" id="pdfroot" data-browse="dir" spellcheck="false"></div>
    <div style="flex:0 1 8rem"><label for="pdfpage">쪽 크기</label>
      <select id="pdfpage"><option value="a4">A4</option><option value="a5">A5</option><option value="b5">B5</option><option value="letter">Letter</option><option value="legal">Legal</option></select></div>
    <div style="flex:1 1 10rem"><label for="pdftitle">제목 (속성에 넣습니다)</label>
      <input type="text" id="pdftitle" spellcheck="false"></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="pdfmargin"> 여백 10mm</label>
  </div>
  <div class="actions">
    <button class="primary" id="btn-pdf">무엇이 들어가나</button>
    <button id="btn-pdf-save" disabled>PDF 만들기</button>
  </div>
  <div id="pdfmsg"></div>
  <div id="pdfout"></div>
</section>

<section class="card">
  <h2>PDF 쪽 뽑기</h2>
  <p class="note">계약서 몇 쪽만 보내야 할 때. <b>이 컴퓨터 안에서</b> 끝나므로
     문서를 모르는 웹사이트에 올리지 않아도 됩니다. 글자·그림은 눌린 그대로
     옮겨 화질과 글꼴이 원본 그대로입니다. <b>원본은 그대로 두고</b> 옆에
     «이름(쪽뽑음).pdf» 를 만듭니다. 책갈피·양식·서명은 따라가지 않습니다.</p>
  <div class="row">
    <div style="flex:3 1 18rem"><label for="cutfile">PDF 파일</label>
      <input type="text" id="cutfile" data-browse="file" spellcheck="false"></div>
    <div style="flex:0 1 9rem"><label for="cutpages">뽑을 쪽</label>
      <input type="text" id="cutpages" placeholder="1-3,7" spellcheck="false"></div>
    <div style="flex:0 1 9rem"><label for="cutdrop">뺄 쪽</label>
      <input type="text" id="cutdrop" placeholder="2" spellcheck="false"></div>
  </div>
  <div class="actions">
    <button class="primary" id="btn-cut">몇 쪽이 나오나</button>
    <button id="btn-cut-save" disabled>뽑아 만들기</button>
  </div>
  <div id="cutmsg"></div>
  <div id="cutout"></div>
</section>

<section class="card">
  <h2>PDF 합치기</h2>
  <p class="note">폴더 안의 PDF 를 <b>이름 순으로</b> 이어 붙입니다. 나눠 스캔한
     것을 하나로 묶을 때 씁니다. 무엇이 어떤 차례로 붙는지 먼저 보여 줍니다.
     못 여는 파일(암호가 걸렸거나 망가진 것)은 <b>조용히 빼지 않고</b> 까닭과
     함께 알려 줍니다. <b>원본은 그대로 두고</b> 폴더 옆에 «폴더이름(합본).pdf»
     를 만듭니다.</p>
  <div class="row">
    <div style="flex:3 1 18rem"><label for="joinroot">PDF 가 있는 폴더</label>
      <input type="text" id="joinroot" data-browse="dir" spellcheck="false"></div>
  </div>
  <div class="actions">
    <button class="primary" id="btn-join">어떤 차례로 붙나</button>
    <button id="btn-join-save" disabled>합쳐 만들기</button>
  </div>
  <div id="joinmsg"></div>
  <div id="joinout"></div>
</section>

<section class="card">
  <h2>메일 첨부로 나눠 담기</h2>
  <p class="note">첨부 한도에 맞춰 여러 zip 으로 나눕니다. <b>압축한 크기가 아니라
     원본 크기로 묶습니다</b> - jpg 처럼 이미 눌린 파일은 압축해도 안 줄어들어서,
     압축 결과를 낙관하면 한도를 넘긴 첨부가 나옵니다. 혼자서 한도를 넘는 파일은
     담지 않고 이름을 알려 줍니다. <b>원본은 그대로 둡니다.</b></p>
  <div class="row">
    <div style="flex:3 1 18rem"><label for="packroot">보낼 파일이 있는 폴더</label>
      <input type="text" id="packroot" data-browse="dir" spellcheck="false"></div>
    <div style="flex:0 1 8rem"><label for="packmax">한 통의 한도</label>
      <input type="text" id="packmax" value="25MB" spellcheck="false"></div>
    <div style="flex:0 1 9rem"><label for="packglob">고를 무늬</label>
      <input type="text" id="packglob" placeholder="*.pdf" spellcheck="false"></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="packhidden"> 숨김 파일도</label>
  </div>
  <div class="actions">
    <button class="primary" id="btn-pack">어떻게 나뉘나</button>
    <button id="btn-pack-save" disabled>zip 만들기</button>
  </div>
  <div id="packmsg"></div>
  <div id="packout"></div>
</section>

<section class="card">
  <h2>되돌리기</h2>
  <p class="note">옮긴 기록은 <code>~/.attools/journal/</code> 에 남습니다.
     고른 기록을 되돌리면 파일이 원래 자리로 갑니다.</p>
  <div class="row">
    <div><label for="journal">기록</label><select id="journal"></select></div>
    <div style="flex:0 0 auto">
      <button id="btn-undo" class="danger">되돌리기</button>
    </div>
  </div>
  <div id="undomsg"></div>
</section>

<script>
(function () {
  const $ = (id) => document.getElementById(id);
  const plan = $("plan"), msg = $("msg");
  let ready = false;

  function values() {
    return {
      path: $("path").value,
      mode: $("mode").value,
      min_age: $("min_age").value,
      recursive: $("recursive").checked,
      hidden: $("hidden").checked,
      fixname: $("fixname").checked,
      mtime: $("mtime").checked,
    };
  }

  function draw(data) {
    plan.innerHTML = AT.table(["지금 이름", "옮길 곳"], data.rows) +
      (data.notes && data.notes.length
        ? '<p class="note">' + data.notes.map(AT.esc).join(" · ") + "</p>"
        : "") + AT.command(data.command);
  }

  function lock(state) {
    $("btn-apply").disabled = !state;
    ready = state;
  }

  ["path", "mode", "min_age"].forEach(function (id) {
    $(id).addEventListener("input", function () { lock(false); });
  });
  ["recursive", "hidden", "fixname", "mtime"].forEach(function (id) {
    $(id).addEventListener("change", function () { lock(false); });
  });

  $("btn-preview").addEventListener("click", async function () {
    try {
      const data = await AT.call("/api/files/preview", values());
      draw(data);
      if (data.count) {
        AT.message(msg, "<b>" + data.count + "개</b>를 옮길 수 있습니다. " +
                   AT.esc(data.root), "ok");
        lock(true);
      } else {
        AT.message(msg, "옮길 것이 없습니다.", "");
        lock(false);
      }
    } catch (e) { AT.message(msg, AT.esc(e.message), "bad"); lock(false); }
  });

  $("btn-apply").addEventListener("click", async function () {
    if (!ready) return;
    if (!confirm("파일을 실제로 옮깁니다. 계속할까요?")) return;
    try {
      const data = await AT.call("/api/files/apply", values());
      draw(data);
      AT.message(msg, "<b>" + data.applied + "개</b>를 옮겼습니다. 기록: " +
                 AT.esc(data.journal), "ok");
      lock(false);
      await loadJournals();
    } catch (e) { AT.message(msg, AT.esc(e.message), "bad"); }
  });

  function dupeValues() {
    return {
      path: $("path").value, keep: $("keep").value,
      min_size: $("min_size").value, flat: $("flat").checked,
      hidden: $("hidden").checked,
    };
  }

  function lockCollect(state) { $("btn-collect-apply").disabled = !state; }
  ["keep", "min_size", "flat"].forEach(function (id) {
    $(id).addEventListener("change", function () { lockCollect(false); });
  });

  $("btn-dupes").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/files/dupes", dupeValues());
      $("dupes").innerHTML = d.groups
        ? AT.table(["무리", "", "파일", "크기"], d.rows,
                   ["num", null, null, "num"]) +
          (d.groups > d.shown ? '<p class="note">무리 ' + (d.groups - d.shown) +
            "개는 줄였습니다.</p>" : "")
        : '<div class="empty">중복 파일이 없습니다.</div>';
      AT.message($("dupemsg"), d.groups
        ? "<b>" + d.groups + "무리</b>, 되찾을 수 있는 용량 " + AT.esc(d.wasted) +
          " · 남길 기준: " + AT.esc(d.keep)
        : "중복 파일이 없습니다.", d.groups ? "ok" : "");
      lockCollect(false);
    } catch (e) { AT.message($("dupemsg"), AT.esc(e.message), "bad"); }
  });

  $("btn-collect").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/files/collect_preview", dupeValues());
      $("dupes").innerHTML = AT.table(["지금 이름", "옮길 곳"], d.rows);
      AT.message($("dupemsg"), "<b>" + d.count + "개</b>를 " +
                 AT.esc(d.dest) + " 로 옮깁니다. 지우지 않습니다.", "ok");
      lockCollect(true);
    } catch (e) {
      AT.message($("dupemsg"), AT.esc(e.message), "bad");
      lockCollect(false);
    }
  });

  $("btn-collect-apply").addEventListener("click", async function () {
    if (!confirm("중복 파일을 _중복/ 으로 옮깁니다. 계속할까요?")) return;
    try {
      const d = await AT.call("/api/files/collect_apply", dupeValues());
      $("dupes").innerHTML = AT.table(["지금 이름", "옮긴 곳"], d.rows);
      AT.message($("dupemsg"), "<b>" + d.applied + "개</b>를 옮겼습니다. 기록: " +
                 AT.esc(d.journal) + " · 눈으로 확인한 뒤 폴더째 지우세요.", "ok");
      lockCollect(false);
      await loadJournals();
    } catch (e) { AT.message($("dupemsg"), AT.esc(e.message), "bad"); }
  });

  $("btn-audit").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/files/audit", {
        aroot: $("aroot").value, ahidden: $("ahidden").checked,
        anodupes: $("anodupes").checked });
      $("auditout").innerHTML = d.notes.map(function (n) {
        return "<h2>" + AT.esc(n.kind) + "</h2><p>" + AT.esc(n.detail) + "</p>" +
          (n.samples.length ? '<pre class="diff">' +
            n.samples.map(AT.esc).join("<br>") + "</pre>" : "");
      }).join("") +
        '<p class="note">본 것: ' + d.looked.map(AT.esc).join(" · ") +
        (d.skipped.length ? "<br>못 본 것: " + d.skipped.map(AT.esc).join("<br>") : "") +
        "<br>고치지는 않았습니다. 여기 없는 문제가 없다는 뜻은 아닙니다.</p>" +
        AT.command(d.command);
      AT.remember("files", "aroot", $("aroot").value);
      AT.message($("auditmsg"), "파일 <b>" + d.files + "개</b> · " +
                 AT.esc(d.total) + " · 볼 만한 곳 " + d.notes.length + "가지", "ok");
    } catch (e) { AT.message($("auditmsg"), AT.esc(e.message), "bad"); }
  });

  function docValues() { return { docroot: $("docroot").value }; }

  $("btn-docs").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/files/documents", docValues());
      $("docsout").innerHTML =
        AT.table(["파일", "종류", "제목", "만든 사람", "마지막 저장",
                  "고친 날짜", "쪽", "못 읽은 까닭"], d.rows,
                 [null, null, null, null, null, null, "num", null]) +
        (d.left.length
          ? "<h2>남아 있는 이름</h2>" +
            AT.table(["파일", "이름"], d.left)
          : '<p class="note">속성에 남은 사람·회사 이름이 없습니다.</p>') +
        AT.command(d.command);
      AT.remember("files", "docroot", $("docroot").value);
      AT.message($("docsmsg"), "문서 <b>" + d.count + "개</b>" +
        (d.left.length ? " · 이름이 남은 문서 " + d.left.length + "개" : ""),
        "ok");
      $("btn-scrub-save").disabled = true;
    } catch (e) { AT.message($("docsmsg"), AT.esc(e.message), "bad"); }
  });

  function drawScrub(d) {
    $("docsout").innerHTML =
      AT.table(["파일", "지울 자리", "값"], d.rows) +
      (d.broken.length
        ? "<h2>열지 못한 파일</h2>" + AT.table(["파일", "까닭"], d.broken) : "") +
      (d.others.length
        ? '<p class="note">메모·변경 내역이 든 문서가 있습니다. 거기 남은 이름은 ' +
          "지우지 못합니다: " + d.others.map(AT.esc).join(" · ") + "</p>"
        : "") +
      (d.made
        ? "<h2>만든 사본</h2>" +
          AT.table(["파일"], d.made.map(function (x) { return [x]; }))
        : "") + AT.command(d.command);
  }

  $("btn-scrub").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/files/scrub_preview", docValues());
      drawScrub(d);
      AT.message($("docsmsg"), "문서 " + d.looked + "개 가운데 <b>" + d.count +
        "개</b>에 이름이 남아 있습니다. 아직 아무것도 만들지 않았습니다.", "ok");
      $("btn-scrub-save").disabled = d.count === 0;
    } catch (e) {
      AT.message($("docsmsg"), AT.esc(e.message), "bad");
      $("btn-scrub-save").disabled = true;
    }
  });

  $("btn-scrub-save").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/files/scrub_apply", docValues());
      drawScrub(d);
      AT.message($("docsmsg"), "사본 <b>" + d.made.length +
        "개</b>를 만들었습니다. 원본은 그대로입니다.", "ok");
      $("btn-scrub-save").disabled = true;
    } catch (e) { AT.message($("docsmsg"), AT.esc(e.message), "bad"); }
  });

  function syncValues() {
    return { syncfrom: $("syncfrom").value, syncto: $("syncto").value,
             synchidden: $("synchidden").checked };
  }

  function drawSync(d) {
    const rows = d.new.map(function (n) { return ["새로", n]; })
      .concat(d.changed.map(function (n) { return ["덮어씀", n]; }))
      .concat(d.extra.map(function (n) { return ["백업에만", n]; }));
    $("syncout").innerHTML =
      AT.table(["어떻게", "파일"], rows) +
      (d.failed && d.failed.length
        ? "<h2>하지 못한 것</h2>" + AT.table(["파일", "까닭"], d.failed) : "") +
      AT.command(d.command);
  }

  async function runSync(apply) {
    try {
      const d = await AT.call(apply ? "/api/files/sync_apply"
                                    : "/api/files/sync_preview", syncValues());
      drawSync(d);
      AT.remember("files", "syncfrom", $("syncfrom").value);
      AT.message($("syncmsg"), (apply ? "넣은 파일 <b>" + d.copied + "개</b>"
                                      : "넣을 것 <b>" + d.count + "개</b> (" +
                                        AT.esc(d.size) + ")") +
        " · 그대로 " + d.same + "개 · 백업에만 " + d.extra.length + "개", "ok");
      $("btn-sync-apply").disabled = !!apply || d.count === 0;
    } catch (e) {
      AT.message($("syncmsg"), AT.esc(e.message), "bad");
      $("btn-sync-apply").disabled = true;
    }
  }

  $("btn-sync").addEventListener("click", function () { runSync(false); });
  $("btn-sync-apply").addEventListener("click", function () { runSync(true); });

  function photoValues() {
    return { photoroot: $("photoroot").value,
             photoall: $("photoall").checked };
  }

  function drawPhotos(d) {
    $("photoout").innerHTML =
      AT.table(["파일", "찍은 날", "기기", "위치", "방향", "못 읽은 까닭"],
               d.rows) +
      (d.made
        ? "<h2>만든 사본</h2>" +
          AT.table(["파일"], d.made.map(function (x) { return [x]; }))
        : "") + AT.command(d.command);
  }

  async function runPhotos(strip) {
    try {
      const d = await AT.call(strip ? "/api/files/photos_strip"
                                    : "/api/files/photos", photoValues());
      drawPhotos(d);
      AT.remember("files", "photoroot", $("photoroot").value);
      AT.message($("photomsg"), "사진 <b>" + d.count + "장</b> · 위치가 남은 것 " +
        d.located + "장" +
        (d.made ? " · 사본 " + d.made.length + "장을 만들었습니다" +
                  (d.kept ? " (" + d.kept + "장은 방향만 남겼습니다)" : "")
                : ""), "ok");
      $("btn-photos-strip").disabled = !!strip || d.dirty === 0;
    } catch (e) {
      AT.message($("photomsg"), AT.esc(e.message), "bad");
      $("btn-photos-strip").disabled = true;
    }
  }

  $("btn-photos").addEventListener("click", function () { runPhotos(false); });
  $("btn-photos-strip").addEventListener("click", function () {
    runPhotos(true);
  });

  function pdfValues() {
    return { pdfroot: $("pdfroot").value, pdfpage: $("pdfpage").value,
             pdftitle: $("pdftitle").value,
             pdfmargin: $("pdfmargin").checked };
  }

  function drawPdf(d) {
    $("pdfout").innerHTML =
      AT.table(["파일", "크기(px)", "넣는 방법"], d.rows) +
      (d.skipped.length
        ? "<h2>넣지 못한 파일</h2>" + AT.table(["파일", "까닭"], d.skipped)
        : "") + AT.command(d.command);
  }

  async function runPdf(save) {
    try {
      const d = await AT.call(save ? "/api/files/pdf_make"
                                   : "/api/files/pdf_preview", pdfValues());
      drawPdf(d);
      AT.remember("files", "pdfroot", $("pdfroot").value);
      AT.message($("pdfmsg"), "이미지 <b>" + d.count + "장</b>" +
        (d.saved ? " · 만들었습니다: <b>" + AT.esc(d.saved) + "</b> (" +
                   AT.esc(d.size) + ")"
                 : " · 아직 만들지 않았습니다."), "ok");
      $("btn-pdf-save").disabled = !!save || d.count === 0;
    } catch (e) {
      AT.message($("pdfmsg"), AT.esc(e.message), "bad");
      $("btn-pdf-save").disabled = true;
    }
  }

  $("btn-pdf").addEventListener("click", function () { runPdf(false); });
  $("btn-pdf-save").addEventListener("click", function () { runPdf(true); });

  function cutValues() {
    return { cutfile: $("cutfile").value, cutpages: $("cutpages").value,
             cutdrop: $("cutdrop").value };
  }

  function drawCut(d) {
    $("cutout").innerHTML =
      AT.table(["파일", "전체", "뽑을 쪽", "쪽 번호"], d.rows) +
      AT.command(d.command);
  }

  async function runCut(save) {
    try {
      const d = await AT.call(save ? "/api/files/cut_make"
                                   : "/api/files/cut_preview", cutValues());
      drawCut(d);
      AT.remember("files", "cutfile", $("cutfile").value);
      AT.message($("cutmsg"), "<b>" + d.count + "쪽</b>" +
        (d.saved ? " · 만들었습니다: <b>" + AT.esc(d.saved) + "</b> (" +
                   AT.esc(d.size) + ")"
                 : " · 아직 만들지 않았습니다.") +
        (d.missing ? " · 원본이 가리키는데 없던 객체 " + d.missing +
                     "개는 비워 두었습니다." : ""), "ok");
      $("btn-cut-save").disabled = !!save || d.count === 0;
    } catch (e) {
      AT.message($("cutmsg"), AT.esc(e.message), "bad");
      $("btn-cut-save").disabled = true;
    }
  }

  $("btn-cut").addEventListener("click", function () { runCut(false); });
  $("btn-cut-save").addEventListener("click", function () { runCut(true); });

  function joinValues() { return { joinroot: $("joinroot").value }; }

  function drawJoin(d) {
    $("joinout").innerHTML =
      AT.table(["차례", "파일", "쪽"], d.rows) +
      (d.skipped.length
        ? "<h2>못 연 파일</h2>" + AT.table(["파일", "까닭"], d.skipped)
        : "") + AT.command(d.command);
  }

  async function runJoin(save) {
    try {
      const d = await AT.call(save ? "/api/files/join_make"
                                   : "/api/files/join_preview", joinValues());
      drawJoin(d);
      AT.remember("files", "joinroot", $("joinroot").value);
      AT.message($("joinmsg"), "PDF <b>" + d.files + "개</b> · 모두 " +
        d.count + "쪽" +
        (d.saved ? " · 만들었습니다: <b>" + AT.esc(d.saved) + "</b> (" +
                   AT.esc(d.size) + ")"
                 : " · 아직 만들지 않았습니다."), "ok");
      $("btn-join-save").disabled = !!save || d.files < 2;
    } catch (e) {
      AT.message($("joinmsg"), AT.esc(e.message), "bad");
      $("btn-join-save").disabled = true;
    }
  }

  $("btn-join").addEventListener("click", function () { runJoin(false); });
  $("btn-join-save").addEventListener("click", function () { runJoin(true); });

  function packValues() {
    return { packroot: $("packroot").value, packmax: $("packmax").value,
             packglob: $("packglob").value, packhidden: $("packhidden").checked };
  }

  function drawPack(d) {
    $("packout").innerHTML =
      AT.table(["파일", "담긴 개수", "크기"], d.rows, [null, "num", "num"]) +
      (d.big.length
        ? "<h2>혼자서 한도를 넘는 파일</h2>" +
          AT.table(["파일", "크기"], d.big, [null, "num"]) +
          '<p class="note">나눠 담을 수 없습니다. 파일 자체를 줄이거나 따로 보내세요.</p>'
        : "") + AT.command(d.command);
  }

  $("btn-pack").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/files/pack_preview", packValues());
      drawPack(d);
      AT.remember("files", "packroot", $("packroot").value);
      AT.message($("packmsg"), "한도 " + AT.esc(d.limit) + " 로 <b>" + d.count +
                 "통</b>이 됩니다. 아직 만들지 않았습니다.", "ok");
      $("btn-pack-save").disabled = d.count === 0;
    } catch (e) {
      AT.message($("packmsg"), AT.esc(e.message), "bad");
      $("btn-pack-save").disabled = true;
    }
  });

  $("btn-pack-save").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/files/pack_apply", packValues());
      drawPack(d);
      AT.message($("packmsg"), "만들었습니다: <b>" + AT.esc(d.saved) +
                 "</b> 밑에 " + d.count + "통. 원본은 그대로입니다.", "ok");
      $("btn-pack-save").disabled = true;
    } catch (e) { AT.message($("packmsg"), AT.esc(e.message), "bad"); }
  });

  $("btn-compare").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/files/compare", {
        path: $("path").value, other: $("other").value,
        hidden: $("hidden").checked, quick: $("quick").checked,
      });
      $("cmp").innerHTML = (d.equal
          ? '<div class="empty">다른 것이 없습니다. 같은 폴더입니다.</div>'
          : AT.table(["무엇", "경로", "왼쪽", "오른쪽"], d.rows)) +
        '<p class="note">' + AT.esc(d.note) + "</p>";
      AT.message($("cmpmsg"), d.equal
        ? "같습니다. 파일 " + d.same + "개를 맞춰 봤습니다."
        : "<b>" + d.total + "곳</b>이 다릅니다. 같은 파일 " + d.same + "개.",
        d.equal ? "ok" : "bad");
    } catch (e) { AT.message($("cmpmsg"), AT.esc(e.message), "bad"); }
  });

  function listValues() {
    return {
      path: $("path").value, glob: $("glob").value, sort: $("sort").value,
      flat: $("flat").checked, hidden: $("hidden").checked,
      format: $("format").value,
    };
  }

  function drawList(d) {
    $("listout").innerHTML = (d.rows
      ? AT.table(["이름", "폴더", "확장자", "크기", "수정"], d.rows) : "") +
      (d.count > (d.shown || 0) ? '<p class="note">' + d.count + "개 가운데 " +
        d.shown + "개만 보입니다.</p>" : "") + AT.command(d.command);
  }

  $("btn-list").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/files/listing", listValues());
      drawList(d);
      AT.message($("listmsg"), "파일 <b>" + d.count + "개</b>, 모두 " +
                 AT.esc(d.total), "ok");
    } catch (e) { AT.message($("listmsg"), AT.esc(e.message), "bad"); }
  });

  $("btn-list-save").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/files/listing_save", listValues());
      drawList(d);
      AT.message($("listmsg"), "저장했습니다: <b>" + AT.esc(d.saved) + "</b> (" +
                 d.count + "개)", "ok");
    } catch (e) { AT.message($("listmsg"), AT.esc(e.message), "bad"); }
  });

  async function loadJournals() {
    try {
      const data = await AT.call("/api/files/journals", {});
      const sel = $("journal");
      sel.innerHTML = data.rows.length
        ? data.rows.map(r => '<option value="' + AT.esc(r[0]) + '">' +
            AT.esc(r[0]) + " (" + AT.esc(r[1]) + "개)</option>").join("")
        : '<option value="">되돌릴 기록이 없습니다</option>';
    } catch (e) { /* 기록이 없어도 화면은 돈다 */ }
  }

  $("btn-undo").addEventListener("click", async function () {
    const name = $("journal").value;
    if (!name) return;
    if (!confirm(name + " 기록을 되돌립니다. 계속할까요?")) return;
    try {
      const data = await AT.call("/api/files/undo", { journal: name });
      const tail = data.errors.length
        ? " 못 되돌린 것 " + data.errors.length + "개: " +
          AT.esc(data.errors.join(", "))
        : "";
      AT.message($("undomsg"), "<b>" + data.restored + "개</b>를 되돌렸습니다." +
                 tail, data.errors.length ? "bad" : "ok");
      await loadJournals();
    } catch (e) { AT.message($("undomsg"), AT.esc(e.message), "bad"); }
  });

  loadJournals();
})();
</script>
""" % {"modes": "".join(
    f'<option value="{k}">{v}</option>' for k, v in MODES.items())}


def make() -> App:
    return App(
        key="files",
        name="파일 정리",
        summary="어질러진 폴더를 종류별·날짜별로 묶고, 되돌린다",
        subtitle="미리보기 → 옮기기 → 되돌리기",
        body=lambda: BODY,
        actions={"preview": preview, "apply": apply, "dupes": dupes,
                 "pack_preview": pack_preview, "pack_apply": pack_apply,
                 "audit": audit,
                 "documents": documents,
                 "photos": photos, "photos_strip": photos_strip,
                 "sync_preview": sync_preview, "sync_apply": sync_apply,
                 "pdf_preview": pdf_preview, "pdf_make": pdf_make,
                 "cut_preview": cut_preview, "cut_make": cut_make,
                 "join_preview": join_preview, "join_make": join_make,
                 "scrub_preview": scrub_preview, "scrub_apply": scrub_apply,
                 "listing": listing, "listing_save": listing_save,
                 "compare": compare,
                 "collect_preview": collect_preview,
                 "collect_apply": collect_apply,
                 "journals": journals, "undo": undo},
        aliases=("파일", "정리"),
        section="파일과 표",
    )
