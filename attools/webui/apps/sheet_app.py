"""엑셀·CSV 화면. 받은 파일을 열어 보고, 점검하고, 정리해 새 파일로 낸다."""

from __future__ import annotations

from pathlib import Path

from ... import files, sheet, xlsx
from .. import App, UiError, form

PEEK_ROWS = 30
MAX_DIFF = 100


def _open(payload: dict) -> sheet.Table:
    path = form.existing_file(payload)
    if path.suffix.lower() not in (sheet.XLSX_SUFFIXES | sheet.CSV_SUFFIXES):
        raise UiError(f"엑셀(xlsx)이나 csv 가 아닙니다: {path.suffix or '확장자 없음'}")
    name = form.text(payload, "sheet") or None
    header_row = int(form.number(payload, "header_row", 1, low=1, high=1000))
    try:
        return sheet.load(path, sheet=name, header_row=header_row - 1)
    except sheet.SheetError as exc:
        raise UiError(str(exc)) from None


def _cells(table: sheet.Table, limit: int) -> list[list[str]]:
    return [[sheet.to_text(c) for c in row] for row in table.rows[:limit]]


def peek(payload: dict) -> dict:
    table = _open(payload)
    names = []
    if Path(table.source).suffix.lower() in sheet.XLSX_SUFFIXES:
        names = xlsx.sheet_names(Path(table.source))

    columns = []
    for col in sheet.profile(table):
        columns.append([
            col.name,
            col.main_kind + (" (섞임)" if col.mixed else ""),
            str(col.missing),
            str(col.unique),
            ", ".join(col.samples)[:60],
        ])

    return {
        "sheet": table.sheet,
        "sheets": names,
        "headers": table.headers,
        "rows": _cells(table, PEEK_ROWS),
        "count": len(table.rows),
        "shown": min(len(table.rows), PEEK_ROWS),
        "columns": columns,
    }


def sheets(payload: dict) -> dict:
    """엑셀 한 파일 안의 시트를 한눈에. 어느 시트를 열지 고르기 전에 본다."""
    path = form.existing_file(payload)
    try:
        found = sheet.describe_sheets(path)
    except (sheet.SheetError, OSError) as exc:
        raise UiError(str(exc)) from None
    rows = [[i.name, str(i.rows), str(i.columns),
             ", ".join(i.headers)[:60] if i.headers else (i.error or "비어 있음")]
            for i in found]
    return {"rows": rows, "count": len(found),
            "names": [i.name for i in found]}


def check(payload: dict) -> dict:
    table = _open(payload)
    key = form.text(payload, "key") or None
    required = [c.strip() for c in form.text(payload, "required").split(",") if c.strip()]
    if key and key not in table.headers:
        raise UiError(f"'{key}' 열이 없습니다.")
    for name in required:
        if name not in table.headers:
            raise UiError(f"'{name}' 열이 없습니다.")

    rows = []
    for issue in sheet.validate(table, key=key, required=required):
        where = ", ".join(str(n) for n in issue.rows[:5])
        if len(issue.rows) > 5:
            where += " …"
        rows.append([issue.kind, issue.column, issue.detail, where])
    return {"rows": rows, "clean": not rows, "count": len(table.rows)}


def _label_spec(payload: dict) -> sheet.LabelSheet:
    def mm(key: str, default: float, low: float, high: float) -> float:
        return float(form.number(payload, key, default, low=low, high=high))

    return sheet.LabelSheet(
        cols=int(form.number(payload, "lbcols", 3, low=1, high=20)),
        rows=int(form.number(payload, "lbrows", 7, low=1, high=40)),
        width=mm("lbwidth", 63.5, 5, 210), height=mm("lbheight", 38.1, 5, 297),
        left=mm("lbleft", 7.2, 0, 200), top=mm("lbtop", 15.1, 0, 290),
        gap_x=mm("lbgapx", 2.5, 0, 50), gap_y=mm("lbgapy", 0.0, 0, 50),
        font=mm("lbfont", 10.0, 5, 30))


def _label_lines(payload: dict) -> list[str] | None:
    raw = form.raw_text(payload, "lblines")
    lines = [one.strip() for one in raw.splitlines() if one.strip()]
    return lines or None


def _label_command(payload: dict, lines, out=None) -> str:
    args: list[object] = ["sheet", "labels", *_source_args(payload)]
    for one in lines or []:
        args += ["--line", one]
    spec = _label_spec(payload)
    for key, value, default in (("--cols", spec.cols, 3), ("--rows", spec.rows, 7),
                                ("--width", spec.width, 63.5),
                                ("--height", spec.height, 38.1),
                                ("--left", spec.left, 7.2), ("--top", spec.top, 15.1)):
        if value != default:
            args += [key, f"{value:g}"]
    start = int(form.number(payload, "lbstart", 1, low=1, high=800))
    if start != 1:
        args += ["--start", start]
    if form.flag(payload, "lbguide"):
        args.append("--guide")
    return form.command(*args, *(["-o", out] if out else []))


def _label_result(payload: dict, table, made=None) -> dict:
    lines = _label_lines(payload)
    spec = _label_spec(payload)
    start = int(form.number(payload, "lbstart", 1, low=1, high=spec.per_page))
    try:
        html, pages, missing = sheet.labels_html(
            table, spec, lines=lines, start=start,
            guide=form.flag(payload, "lbguide"))
    except sheet.SheetError as exc:
        raise UiError(str(exc)) from None

    texts, _missing = sheet.label_texts(table, lines)
    out = {"rows": [[" / ".join(one)] for one in texts[:PEEK_ROWS]],
           "count": len(texts), "pages": pages, "per_page": spec.per_page,
           "missing": sorted(missing), "headers": table.headers,
           "command": _label_command(payload, lines, made)}
    if made is not None:
        made.write_text(html, encoding="utf-8")
        out["saved"] = str(made)
    return out


def labels_preview(payload: dict) -> dict:
    return _label_result(payload, _open(payload))


def labels_save(payload: dict) -> dict:
    """원본 옆에 «이름 라벨.html» 을 만든다. 원본은 건드리지 않는다."""
    table = _open(payload)
    source = form.existing_file(payload, "path")
    made = files.unique_path(source.with_name(f"{source.stem} 라벨.html"))
    return _label_result(payload, table, made)


def gaps(payload: dict) -> dict:
    """번호·날짜 열에서 빠진 것 찾기. 고치지 않고 어디가 비었는지만."""
    table = _open(payload)
    column = form.text(payload, "gcol")
    if not column:
        raise UiError("번호나 날짜가 든 열을 골라 주세요.")
    every = form.choice(payload, "gevery", sheet.GAP_EVERY, "day")
    step = int(form.number(payload, "gstep", 1, low=1, high=1000))
    holidays = form.flag(payload, "gholidays")

    try:
        report = sheet.find_gaps(table, column, step=step, every=every)
        notes = []
        if holidays and report.kind == "날짜":
            from ... import life

            years = list(range(int(report.first[:4]), int(report.last[:4]) + 1))
            rest = life.holidays_between(years[0], years[-1],
                                         life.load_user_holidays())
            notes = life.missing_lunar_warning(rest, years)
            report = sheet.find_gaps(table, column, step=step, every=every,
                                     skip=set(rest))
    except sheet.SheetError as exc:
        raise UiError(str(exc)) from None

    args: list[object] = ["sheet", "gaps", *_source_args(payload), "-c", column]
    if step != 1:
        args += ["--step", step]
    if every != "day":
        args += ["--every", every]
    if holidays:
        args.append("--holidays")

    return {"rows": [[g.start if g.start == g.end else f"{g.start} ~ {g.end}",
                      f"{g.count:,}"] for g in report.gaps[:PEEK_ROWS]],
            "kind": report.kind, "first": report.first, "last": report.last,
            "expected": report.expected, "present": report.present,
            "missing": report.missing, "count": len(report.gaps),
            "ignored": report.ignored, "samples": report.samples,
            "notes": notes, "command": form.command(*args)}


def _other(payload: dict) -> sheet.Table:
    """비교·합칠 상대 파일. 같은 시트·머리글 규칙으로 읽는다."""
    return _open({"path": form.text(payload, "other"),
                  "sheet": form.text(payload, "other_sheet"),
                  "header_row": payload.get("header_row", 1)})


def compare(payload: dict) -> dict:
    before, after = _open(payload), _other(payload)
    key = form.text(payload, "key")
    if not key:
        raise UiError("무엇을 기준으로 짝지을지 열쇠 열을 골라 주세요. "
                      "(사번·주문번호처럼 행마다 다른 값)")
    for table, label in ((before, "먼저 파일"), (after, "나중 파일")):
        if key not in table.headers:
            raise UiError(f"{label}에 '{key}' 열이 없습니다.")

    result = sheet.diff(before, after, key)
    rows = []
    for row in result.removed[:MAX_DIFF]:
        rows.append(["빠짐", sheet.to_text(row[before.index_of(key)]), "", "", ""])
    for row in result.added[:MAX_DIFF]:
        rows.append(["새로 생김", sheet.to_text(row[after.index_of(key)]), "", "", ""])
    for ident, column, was, now in result.changed[:MAX_DIFF]:
        rows.append(["값 바뀜", sheet.to_text(ident), column,
                     sheet.to_text(was), sheet.to_text(now)])

    return {"rows": rows, "same": result.empty,
            "added": len(result.added), "removed": len(result.removed),
            "changed": len(result.changed),
            "columns_added": result.columns_added,
            "columns_removed": result.columns_removed,
            "note": "열쇠 열이 같은 행끼리 맞춰 봅니다. 열쇠가 겹치는 행이 "
                    "있으면 짝짓기가 어긋날 수 있으니 점검을 먼저 돌려 보세요."}


def merge(payload: dict) -> dict:
    """두 파일을 세로로 붙여 새 파일로 낸다. 원본은 그대로 둔다."""
    first, second = _open(payload), _other(payload)
    table, warnings = sheet.merge([first, second],
                                  add_source=form.flag(payload, "add_source", True))
    if form.flag(payload, "save"):
        source = Path(first.source)
        suffix = source.suffix.lower()
        if suffix not in sheet.XLSX_SUFFIXES:
            suffix = ".csv"
        out = files.unique_path(source.with_name(f"{source.stem} (합침){suffix}"))
        sheet.save(table, out)
        saved = str(out)
    else:
        saved = ""

    return {"headers": table.headers,
            "rows": _cells(table, PEEK_ROWS),
            "count": len(table.rows), "shown": min(len(table.rows), PEEK_ROWS),
            "warnings": warnings, "saved": saved}


def _specs(payload: dict) -> list[tuple[str, str]]:
    raw = payload.get("specs")
    if not isinstance(raw, list) or not raw:
        raise UiError("어느 열을 어떤 형식으로 맞출지 골라 주세요.")
    out = []
    for item in raw:
        if not (isinstance(item, list) and len(item) == 2
                and all(isinstance(x, str) for x in item)):
            raise UiError("고른 목록이 깨졌습니다. 화면을 새로 고쳐 주세요.")
        column, kind = item[0].strip(), item[1].strip()
        if kind not in sheet.COLUMN_FORMATS:
            raise UiError(f"알 수 없는 형식: {kind}")
        out.append((column, kind))
    return out


def _formatted(payload: dict):
    table = _open(payload)
    reports = []
    for column, kind in _specs(payload):
        try:
            table, rep = sheet.format_column(table, column, kind)
        except sheet.SheetError as exc:
            raise UiError(str(exc)) from None
        reports.append(rep)
    return table, reports


def _format_rows(reports) -> list[list[str]]:
    return [[r.column, r.kind, str(r.changed), str(r.already), str(r.blank),
             str(len(r.failed)), str(len(r.invalid))] for r in reports]


def _left_alone(reports) -> list[list[str]]:
    rows = []
    for rep in reports:
        for line, value in rep.failed[:20]:
            rows.append([rep.column, str(line), value[:40], "규칙을 모름"])
        for line, value in rep.invalid[:20]:
            rows.append([rep.column, str(line), value[:40], "검증에 걸림"])
    return rows


def format_preview(payload: dict) -> dict:
    table, reports = _formatted(payload)
    return {"report": _format_rows(reports), "left": _left_alone(reports),
            "headers": table.headers,
            "rows": _cells(table, PEEK_ROWS),
            "shown": min(len(table.rows), PEEK_ROWS)}


def format_save(payload: dict) -> dict:
    """원본은 그대로 두고 옆에 새 파일을 만든다."""
    table, reports = _formatted(payload)
    source = Path(table.source)
    suffix = source.suffix.lower()
    if suffix not in sheet.XLSX_SUFFIXES:
        suffix = ".csv"
    out = files.unique_path(source.with_name(f"{source.stem} (형식){suffix}"))
    sheet.save(table, out)
    options = {"전화": "--phone", "사업자번호": "--bizno", "우편번호": "--post",
               "날짜": "--date", "숫자": "--number"}
    args: list[object] = ["sheet", "format", *_source_args(payload)]
    for column, kind in _specs(payload):
        args += [options[kind], column]
    return {"saved": str(out), "report": _format_rows(reports),
            "left": _left_alone(reports),
            "command": form.command(*args, "-o", out)}


OPS = {"eq": "같다", "ne": "다르다", "gt": "크다", "gte": "크거나 같다",
       "lt": "작다", "lte": "작거나 같다", "has": "포함한다",
       "empty": "비어 있다", "filled": "값이 있다"}


def _picked(payload: dict):
    """조건·정렬·열 고르기를 차례로 건다. 원본은 건드리지 않는다."""
    table = _open(payload)
    column = form.text(payload, "wcol")
    op = form.choice(payload, "wop", OPS, "eq")
    value = form.raw_text(payload, "wval")
    steps: list[str] = []

    if column:
        if column not in table.headers:
            raise UiError(f"'{column}' 열이 없습니다.")
        if op not in ("empty", "filled") and not value.strip():
            raise UiError("견줄 값을 적어 주세요.")
        condition = sheet.Condition(column, op, value.strip())
        table = sheet.where(table, [] if op == "has" else [condition],
                            contains=[condition] if op == "has" else None)
        steps.append(f"{column} {OPS[op]}")

    order = form.text(payload, "scol")
    if order:
        if order not in table.headers:
            raise UiError(f"'{order}' 열이 없습니다.")
        table = sheet.sort_rows(table, [order],
                                descending=form.flag(payload, "desc"))
        steps.append(f"{order} 기준 정렬")

    keep = [c.strip() for c in form.text(payload, "keep").split(",") if c.strip()]
    if keep:
        try:
            table = sheet.cut(table, keep)
        except sheet.SheetError as exc:
            raise UiError(str(exc)) from None
        steps.append(f"열 {len(keep)}개만")
    return table, steps


def _pick_commands(payload: dict, out=None) -> list[str]:
    """세 단계를 각각의 명령으로 적는다. 이어 붙이면 같은 결과가 나온다.

    한 줄로 적으면 정렬·열 고르기가 빠져 «이대로 치면 다른 결과»가 된다.
    중간 파일 이름을 드러내는 편이 낫다.
    """
    source = form.text(payload, "path")
    column = form.text(payload, "wcol")
    op = form.choice(payload, "wop", OPS, "eq")
    value = form.raw_text(payload, "wval").strip()
    order = form.text(payload, "scol")
    keep = [c.strip() for c in form.text(payload, "keep").split(",") if c.strip()]

    steps: list[list[object]] = []
    if column:
        args: list[object] = ["sheet", "where", *_source_args(payload)]
        if op in ("empty", "filled"):
            args += [f"--{op}", column]
        else:
            args += [f"--{op}", f"{column}={value}"]
        steps.append(args)
    if order:
        args = ["sheet", "sort", source, "--by", order]
        if form.flag(payload, "desc"):
            args.append("--desc")
        steps.append(args)
    if keep:
        args = ["sheet", "cut", source]
        for name in keep:
            args += ["-c", name]
        steps.append(args)
    if not steps:
        return []

    made = []
    last = str(out) if out else None
    for number, args in enumerate(steps, 1):
        if number > 1:                       # 앞 단계의 결과를 이어받는다
            args[2] = made[-1][1]
        if number == len(steps):
            target = last or "결과.csv"
        else:
            target = f"중간{number}.csv"
        made.append((form.command(*args, "-o", target), target))
    return [line for line, _target in made]


def pick_preview(payload: dict) -> dict:
    table, steps = _picked(payload)
    return {"headers": table.headers, "rows": _cells(table, PEEK_ROWS),
            "count": len(table.rows), "shown": min(len(table.rows), PEEK_ROWS),
            "steps": steps, "command": _pick_commands(payload)}


def pick_save(payload: dict) -> dict:
    table, steps = _picked(payload)
    if not table.rows:
        raise UiError("맞는 행이 없습니다. 조건을 확인해 주세요.")
    source = Path(_open(payload).source)
    suffix = source.suffix.lower()
    if suffix not in sheet.XLSX_SUFFIXES:
        suffix = ".csv"
    out = files.unique_path(source.with_name(f"{source.stem} (골라낸){suffix}"))
    sheet.save(table, out)
    return {"saved": str(out), "count": len(table.rows), "steps": steps,
            "command": _pick_commands(payload, out)}


AGGS = {"sum": "합계", "count": "건수", "avg": "평균", "min": "최소", "max": "최대"}


def _summed(payload: dict):
    table = _open(payload)
    rows = [c.strip() for c in form.text(payload, "grows").split(",") if c.strip()]
    if not rows:
        raise UiError("무엇으로 묶을지 열을 골라 주세요. (부서·월처럼 같은 값이 여럿인 열)")
    agg = form.choice(payload, "agg", AGGS, "sum")
    values = form.text(payload, "gvalues") or None
    cols = form.text(payload, "gcols") or None
    for name in rows + [n for n in (values, cols) if n]:
        if name not in table.headers:
            raise UiError(f"'{name}' 열이 없습니다.")
    if agg in ("sum", "avg") and not values:
        raise UiError(f"{AGGS[agg]}를 내려면 집계할 값 열을 골라 주세요. "
                      "(건수만 셀 거면 «건수»를 고르세요)")
    try:
        return sheet.pivot(table, rows=rows, values=values, agg=agg, cols=cols)
    except sheet.SheetError as exc:
        raise UiError(str(exc)) from None


def _sum_command(payload: dict, out=None) -> str:
    args: list[object] = ["sheet", "pivot", *_source_args(payload)]
    for name in [c.strip() for c in form.text(payload, "grows").split(",") if c.strip()]:
        args += ["--rows", name]
    if form.text(payload, "gcols"):
        args += ["--cols", form.text(payload, "gcols")]
    if form.text(payload, "gvalues"):
        args += ["--values", form.text(payload, "gvalues")]
    args += ["--agg", form.choice(payload, "agg", AGGS, "sum")]
    return form.command(*args, *(["-o", out] if out else []))


def sum_preview(payload: dict) -> dict:
    table = _summed(payload)
    return {"headers": table.headers, "rows": _cells(table, PEEK_ROWS),
            "count": len(table.rows), "shown": min(len(table.rows), PEEK_ROWS),
            "command": _sum_command(payload)}


def sum_save(payload: dict) -> dict:
    table = _summed(payload)
    if not table.rows:
        raise UiError("집계할 것이 없습니다.")
    source = Path(_open(payload).source)
    suffix = source.suffix.lower()
    if suffix not in sheet.XLSX_SUFFIXES:
        suffix = ".csv"
    out = files.unique_path(source.with_name(f"{source.stem} (집계){suffix}"))
    sheet.save(table, out)
    return {"saved": str(out), "count": len(table.rows),
            "command": _sum_command(payload, out)}


def _tidied(payload: dict):
    """빈 칸 채우기 + 합계 줄. 엑셀에서 병합을 풀면 늘 이 둘을 같이 한다."""
    table = _open(payload)
    fills = [c.strip() for c in form.text(payload, "fcols").split(",") if c.strip()]
    totals = [c.strip() for c in form.text(payload, "tcols").split(",") if c.strip()]
    want_total = form.flag(payload, "wanttotal")
    for name in fills + totals:
        if name not in table.headers:
            raise UiError(f"'{name}' 열이 없습니다.")
    if not fills and not want_total:
        raise UiError("빈 칸을 채울 열을 적거나 «합계 줄 붙이기»를 켜 주세요.")

    steps: list[str] = []
    if fills:
        table, filled = sheet.fill_down(table, fills)
        steps.append(f"{', '.join(fills)}: 빈 칸 {filled:,}개 채움")
    if want_total:
        kind = form.choice(payload, "tkind", sheet.TOTAL_KINDS, "sum")
        table, counted = sheet.with_total(table, totals or None, kind=kind,
                                          label=form.text(payload, "tlabel"))
        if not counted:
            raise UiError("셈할 숫자 열이 없습니다. 열을 적어 주거나 «정리»를 "
                          "먼저 돌려 숫자로 읽히게 하세요.")
        steps.append(f"{sheet.TOTAL_KINDS[kind]} 줄: {', '.join(counted)}")
    return table, steps


def _tidy_commands(payload: dict, out=None) -> list[str]:
    fills = [c.strip() for c in form.text(payload, "fcols").split(",") if c.strip()]
    totals = [c.strip() for c in form.text(payload, "tcols").split(",") if c.strip()]
    lines: list[str] = []
    if fills:
        args: list[object] = ["sheet", "filldown", *_source_args(payload)]
        for name in fills:
            args += ["-c", name]
        lines.append(form.command(*args, *(["-o", out] if out else [])))
    if form.flag(payload, "wanttotal"):
        args = ["sheet", "total", *_source_args(payload)]
        for name in totals:
            args += ["-c", name]
        kind = form.choice(payload, "tkind", sheet.TOTAL_KINDS, "sum")
        if kind != "sum":
            args += ["--kind", kind]
        if form.text(payload, "tlabel"):
            args += ["--label", form.text(payload, "tlabel")]
        lines.append(form.command(*args, *(["-o", out] if out else [])))
    return lines


def tidy_preview(payload: dict) -> dict:
    table, steps = _tidied(payload)
    return {"headers": table.headers, "rows": _cells(table, PEEK_ROWS),
            "count": len(table.rows), "shown": min(len(table.rows), PEEK_ROWS),
            "steps": steps, "command": _tidy_commands(payload)}


def tidy_save(payload: dict) -> dict:
    """원본은 그대로 두고 옆에 «(정돈)» 파일을 만든다."""
    table, steps = _tidied(payload)
    source = Path(_open(payload).source)
    suffix = source.suffix.lower()
    if suffix not in sheet.XLSX_SUFFIXES:
        suffix = ".csv"
    out = files.unique_path(source.with_name(f"{source.stem} (정돈){suffix}"))
    sheet.save(table, out)
    return {"saved": str(out), "count": len(table.rows), "steps": steps,
            "headers": table.headers, "rows": _cells(table, PEEK_ROWS),
            "shown": min(len(table.rows), PEEK_ROWS),
            "command": _tidy_commands(payload, out)}


def chart(payload: dict) -> dict:
    """표를 그림(SVG) 하나로. 화면에서는 그린 것을 그대로 보여 준다."""
    from ...docs import report

    table = _open(payload)
    label = form.text(payload, "clabel")
    if not label:
        raise UiError("이름이 될 열을 골라 주세요.")
    kind = form.choice(payload, "ckind", {"bar", "line"}, "bar")
    agg = form.choice(payload, "cagg", AGGS, "sum")
    value = form.text(payload, "cvalue") or None
    top = int(form.number(payload, "ctop", 15, low=1, high=100))
    try:
        grouped = sheet.pivot(table, rows=[label], values=value, agg=agg)
    except sheet.SheetError as exc:
        raise UiError(str(exc)) from None

    pairs = [(sheet.to_text(r[0]), float(r[1])) for r in grouped.rows
             if isinstance(r[1], (int, float)) and not isinstance(r[1], bool)]
    if not pairs:
        raise UiError("그릴 숫자가 없습니다. 값 열을 고르거나 «건수»로 세어 보세요.")
    if kind == "bar":
        pairs.sort(key=lambda x: -x[1])
    whole = len(pairs)
    pairs = pairs[:top]

    draw = report.bar_chart if kind == "bar" else report.line_chart
    unit = form.text(payload, "cunit")
    drawn = draw(pairs, unit=unit)
    if not drawn.startswith("<svg"):
        import re as _re

        raise UiError(_re.sub(r"<[^>]+>", "", drawn))
    svg = report.standalone_svg(drawn, title=f"{label}별 {value or '건수'}")

    args: list[object] = ["sheet", "chart", *_source_args(payload), "--label", label]
    if value:
        args += ["--value", value]
    if agg != "sum":
        args += ["--agg", agg]
    if kind != "bar":
        args += ["--kind", kind]
    if unit:
        args += ["--unit", unit]

    result = {"svg": svg, "count": len(pairs), "whole": whole,
              "rows": [[name, f"{v:,.0f}"] for name, v in pairs],
              "command": form.command(*args)}
    if form.flag(payload, "csave"):
        source = Path(table.source)
        out = files.unique_path(source.with_name(f"{source.stem} ({label}별).svg"))
        out.write_text(svg, encoding="utf-8")
        result["saved"] = str(out)
        result["command"] = form.command(*args, "-o", out)
    return result


def dday(payload: dict) -> dict:
    """마감일 열에서 남은 일수와 상태를 만든다."""
    from datetime import date as _date

    table = _open(payload)
    column = form.text(payload, "ycol")
    if not column:
        raise UiError("마감일이 든 열을 골라 주세요.")
    raw = form.text(payload, "yon")
    if raw:
        try:
            today = sheet.parse_date(raw)
        except ValueError:
            today = None
        if today is None:
            raise UiError(f"날짜를 읽지 못했습니다: {raw}")
    else:
        today = _date.today()

    try:
        result, failed = sheet.add_dday(table, column, today=today)
    except sheet.SheetError as exc:
        raise UiError(str(exc)) from None

    index = result.index_of(f"{column} 남은 일수")
    if form.flag(payload, "ysort", True):
        result = sheet.Table(
            result.headers,
            sorted(result.rows, key=lambda r: (r[index] is None,
                                               r[index] if r[index] is not None else 0)),
            source=result.source, sheet=result.sheet)

    state = result.index_of(f"{column} 상태")
    counts = {name: 0 for name in sheet.DDAY_STATES}
    for row in result.rows:
        if row[state] in counts:
            counts[row[state]] += 1

    args: list[object] = ["sheet", "dday", *_source_args(payload), "-c", column]
    if raw:
        args += ["--on", f"{today:%Y-%m-%d}"]
    if form.flag(payload, "ysort", True):
        args.append("--sort")

    out = {"headers": result.headers, "rows": _cells(result, PEEK_ROWS),
           "count": len(result.rows), "shown": min(len(result.rows), PEEK_ROWS),
           "today": f"{today:%Y-%m-%d}", "counts": [[k, str(v)] for k, v in counts.items()],
           "failed": [[str(line), value] for line, value in failed[:20]],
           "command": form.command(*args)}
    if form.flag(payload, "ysave"):
        source = Path(table.source)
        suffix = source.suffix.lower()
        if suffix not in sheet.XLSX_SUFFIXES:
            suffix = ".csv"
        saved = files.unique_path(source.with_name(f"{source.stem} (남은일수){suffix}"))
        sheet.save(result, saved)
        out["saved"] = str(saved)
        out["command"] = form.command(*args, "-o", saved)
    return out


def _dated(payload: dict):
    table = _open(payload)
    column = form.text(payload, "dcol")
    if not column:
        raise UiError("날짜가 든 열을 골라 주세요.")
    raw = payload.get("dparts")
    parts = [p for p in raw if isinstance(p, str)] if isinstance(raw, list) else []
    if not parts:
        raise UiError("만들 열을 하나 이상 고르세요. "
                      f"({', '.join(sheet.DATE_PARTS)})")
    try:
        return table, *sheet.add_date_parts(table, column, parts), column, parts
    except sheet.SheetError as exc:
        raise UiError(str(exc)) from None


def _dates_command(payload: dict, column: str, parts: list[str], out=None) -> str:
    args: list[object] = ["sheet", "dates", *_source_args(payload), "-c", column]
    for part in parts:
        args += ["--add", part]
    return form.command(*args, *(["-o", out] if out else []))


def dates_preview(payload: dict) -> dict:
    _before, table, failed, column, parts = _dated(payload)
    return {"headers": table.headers, "rows": _cells(table, PEEK_ROWS),
            "count": len(table.rows), "shown": min(len(table.rows), PEEK_ROWS),
            "failed": [[str(line), value] for line, value in failed[:20]],
            "command": _dates_command(payload, column, parts)}


def dates_save(payload: dict) -> dict:
    """원본은 그대로 두고 옆에 «(날짜)» 파일을 만든다."""
    before, table, failed, column, parts = _dated(payload)
    source = Path(before.source)
    suffix = source.suffix.lower()
    if suffix not in sheet.XLSX_SUFFIXES:
        suffix = ".csv"
    out = files.unique_path(source.with_name(f"{source.stem} (날짜){suffix}"))
    sheet.save(table, out)
    return {"saved": str(out), "headers": table.headers,
            "rows": _cells(table, PEEK_ROWS), "count": len(table.rows),
            "shown": min(len(table.rows), PEEK_ROWS),
            "failed": [[str(line), value] for line, value in failed[:20]],
            "command": _dates_command(payload, column, parts, out)}


def _aged(payload: dict):
    table = _open(payload)
    column = form.text(payload, "acol")
    if not column:
        raise UiError("생년월일이 든 열을 골라 주세요.")
    on = None
    raw = form.text(payload, "aon")
    if raw:
        on = sheet.parse_date(raw)
        if on is None:
            raise UiError(f"날짜로 읽지 못했습니다: {raw}")
    group = form.flag(payload, "agroup")
    sex = form.flag(payload, "asex")
    try:
        result, report = sheet.add_age(table, column, on=on, group=group,
                                       sex=sex)
    except sheet.SheetError as exc:
        raise UiError(str(exc)) from None
    return table, result, report, column, on, group, sex


def _age_command(payload: dict, column: str, on, group: bool, sex: bool,
                 out=None) -> str:
    args: list[object] = ["sheet", "age", *_source_args(payload), "-c", column]
    if on:
        args += ["--on", str(on)]
    if group:
        args.append("--group")
    if sex:
        args.append("--sex")
    return form.command(*args, *(["-o", out] if out else []))


def _age_result(table, report) -> dict:
    return {"headers": table.headers, "rows": _cells(table, PEEK_ROWS),
            "count": len(table.rows), "shown": min(len(table.rows), PEEK_ROWS),
            "read": report.read, "sexed": report.sexed,
            "failed": [[str(line), value] for line, value in report.failed[:20]]}


def age_preview(payload: dict) -> dict:
    _before, table, report, column, on, group, sex = _aged(payload)
    out = _age_result(table, report)
    out["command"] = _age_command(payload, column, on, group, sex)
    return out


def age_save(payload: dict) -> dict:
    """원본은 그대로 두고 옆에 «(나이)» 파일을 만든다."""
    before, table, report, column, on, group, sex = _aged(payload)
    source = Path(before.source)
    suffix = source.suffix.lower()
    if suffix not in sheet.XLSX_SUFFIXES:
        suffix = ".csv"
    target = files.unique_path(source.with_name(f"{source.stem} (나이){suffix}"))
    sheet.save(table, target)
    out = _age_result(table, report)
    out["saved"] = str(target)
    out["command"] = _age_command(payload, column, on, group, sex, target)
    return out


def _export_target(payload: dict, table, suffix: str) -> Path:
    """원본 옆에 «이름.ics» 처럼 새 파일을 만든다. 있으면 번호를 붙인다."""
    source = Path(table.source)
    return files.unique_path(source.with_name(source.stem + suffix))


def ics_preview(payload: dict) -> dict:
    table = _open(payload)
    title = form.text(payload, "ictitle")
    start = form.text(payload, "icstart")
    if not title or not start:
        raise UiError("일정 이름 열과 시작 날짜 열을 골라 주세요.")
    end = form.text(payload, "icend") or None
    place = form.text(payload, "icplace") or None
    alarm = int(form.number(payload, "icalarm", 0, low=0, high=10080))
    try:
        events, skipped = sheet.events_from_table(
            table, summary=title, start=start, end=end, location=place)
    except sheet.SheetError as exc:
        raise UiError(str(exc)) from None

    args: list[object] = ["sheet", "ics", *_source_args(payload),
                          "--title", title, "--start", start]
    if end:
        args += ["--end", end]
    if place:
        args += ["--place", place]
    if alarm:
        args += ["--alarm", alarm]
    return {"rows": [[e.summary,
                      f"{e.start}" + (f" {e.start_time:%H:%M}"
                                      if e.start_time else ""),
                      (f"{e.end}" if e.end else "")
                      + (f" {e.end_time:%H:%M}" if e.end_time else ""),
                      e.location] for e in events[:PEEK_ROWS]],
            "count": len(events),
            "skipped": [[str(line), why] for line, why in skipped[:20]],
            "events": len(events), "alarm": alarm,
            "command": form.command(*args)}


def ics_save(payload: dict) -> dict:
    table = _open(payload)
    out = ics_preview(payload)
    events, _skipped = sheet.events_from_table(
        table, summary=form.text(payload, "ictitle"),
        start=form.text(payload, "icstart"),
        end=form.text(payload, "icend") or None,
        location=form.text(payload, "icplace") or None)
    alarm = out["alarm"] or None
    target = _export_target(payload, table, ".ics")
    target.write_text(sheet.to_ics(events, alarm=alarm), encoding="utf-8",
                      newline="")
    out["saved"] = str(target)
    out["command"] = out["command"] + " -o " + target.name
    return out


def vcard_preview(payload: dict) -> dict:
    table = _open(payload)
    name = form.text(payload, "vcname")
    if not name:
        raise UiError("이름 열을 골라 주세요.")
    picks = {key: form.text(payload, "vc" + key) or None
             for key in ("company", "title", "mobile", "phone", "email")}
    try:
        people, skipped = sheet.contacts_from_table(table, name=name, **picks)
    except sheet.SheetError as exc:
        raise UiError(str(exc)) from None

    args: list[object] = ["sheet", "vcard", *_source_args(payload),
                          "--name", name]
    for key, column in picks.items():
        if column:
            args += ["--" + key, column]
    return {"rows": [[p.name, p.company, p.title,
                      " / ".join(n for _k, n in p.phones), p.email]
                     for p in people[:PEEK_ROWS]],
            "count": len(people),
            "skipped": [[str(line), why] for line, why in skipped[:20]],
            "command": form.command(*args)}


def vcard_save(payload: dict) -> dict:
    table = _open(payload)
    out = vcard_preview(payload)
    people, _skipped = sheet.contacts_from_table(
        table, name=form.text(payload, "vcname"),
        company=form.text(payload, "vccompany") or None,
        title=form.text(payload, "vctitle") or None,
        mobile=form.text(payload, "vcmobile") or None,
        phone=form.text(payload, "vcphone") or None,
        email=form.text(payload, "vcemail") or None)
    target = _export_target(payload, table, ".vcf")
    target.write_text(sheet.to_vcard(people), encoding="utf-8", newline="")
    out["saved"] = str(target)
    out["command"] = out["command"] + " -o " + target.name
    return out


def _mail_drafts(payload: dict):
    table = _open(payload)
    template_path = form.existing_file({"path": form.text(payload, "mltemplate")})
    subject = form.text(payload, "mlsubject")
    to = form.text(payload, "mlto")
    if not subject or not to:
        raise UiError("제목 틀과 받는 사람 열을 채워 주세요.")
    body = template_path.read_text(encoding=sheet.sniff_encoding(template_path))
    attach = form.text(payload, "mlattach") or None
    try:
        drafts, missing = sheet.build_mails(table, template=body,
                                            subject=subject, to=to,
                                            attach=attach)
    except sheet.SheetError as exc:
        raise UiError(str(exc)) from None
    if missing:
        raise UiError("표에 없는 자리표시자: " + ", ".join(sorted(missing))
                      + f" (있는 열: {', '.join(table.headers)}, 번호)")
    return table, template_path, drafts


def _mail_command(payload: dict, template, out=None) -> str:
    args: list[object] = ["sheet", "mail", *_source_args(payload),
                          "-t", template,
                          "--subject", form.text(payload, "mlsubject"),
                          "--to", form.text(payload, "mlto")]
    if form.text(payload, "mlattach"):
        args += ["--attach", form.text(payload, "mlattach")]
    if out:
        args += ["-o", out, "--apply"]
    return form.command(*args)


def _mail_result(drafts) -> dict:
    good = [d for d in drafts if d.ok]
    return {"rows": [[d.to, d.subject, str(len(d.attachments)) if d.attachments
                      else ""] for d in good[:PEEK_ROWS]],
            "count": len(good),
            "problems": [[str(d.line), d.problem] for d in drafts if not d.ok],
            "first": (good[0].body[:1500] if good else "")}


def mail_preview(payload: dict) -> dict:
    _table, template, drafts = _mail_drafts(payload)
    out = _mail_result(drafts)
    out["command"] = _mail_command(payload, template)
    return out


def mail_make(payload: dict) -> dict:
    """사람마다 .eml 을 만든다. 보내지는 않는다."""
    from ... import hangul

    table, template, drafts = _mail_drafts(payload)
    good = [d for d in drafts if d.ok]
    if not good:
        raise UiError("보낼 수 있는 행이 없습니다. (메일 주소·첨부를 보세요)")

    source = Path(table.source)
    folder = files.unique_path(source.with_name(source.stem + " 메일초안"))
    folder.mkdir(parents=True)
    for draft in good:
        name = hangul.sanitize_filename(
            f"{draft.row:03d}_{draft.to.split(',')[0].strip()}.eml")
        (folder / name).write_bytes(sheet.to_eml(draft))

    out = _mail_result(drafts)
    out["saved"] = str(folder)
    out["command"] = _mail_command(payload, template, folder)
    return out


def forms(payload: dict) -> dict:
    """받은 파일들의 열 구성을 견준다. 파일은 건드리지 않는다."""
    root = form.folder(payload, "ffolder")
    pattern = form.text(payload, "fglob") or "*"
    targets = [q for q in sorted(root.rglob(pattern))
               if q.is_file()
               and q.suffix.lower() in (sheet.XLSX_SUFFIXES | sheet.CSV_SUFFIXES)]
    if not targets:
        raise UiError("표 파일을 찾지 못했습니다. (xlsx, csv)")

    report = sheet.compare_forms(targets, sheet=form.text(payload, "sheet") or None)
    if not report.standard:
        raise UiError("열 구성을 읽은 파일이 없습니다.")

    def state(check) -> str:
        if check.error:
            return "못 읽음"
        if check.same:
            return "같음"
        return "순서 다름" if check.reordered else "열 다름"

    args: list = ["sheet", "forms", root]
    if pattern != "*":
        args += ["-g", pattern]
    return {"standard": report.standard, "common": report.common,
            "rows": [[c.path.name, c.sheet, f"{c.rows:,}", state(c),
                      ", ".join([f"없음: {h}" for h in c.missing]
                                + [f"더 있음: {h}" for h in c.extra])
                      or c.error]
                     for c in report.checks],
            "count": len(report.checks), "odd": len(report.odd),
            "command": form.command(*args)}


def _worked(payload: dict):
    table = _open(payload)
    start = form.text(payload, "wstart")
    end = form.text(payload, "wend")
    if not start or not end:
        raise UiError("출근 열과 퇴근 열을 골라 주세요.")
    date = form.text(payload, "wdate") or None
    raw = form.text(payload, "wrest")
    rest = int(form.number(payload, "wrest", 0, low=0, high=600)) if raw else None
    try:
        days, made = sheet.work_days(table, start=start, end=end, date=date,
                                     rest=rest)
    except sheet.SheetError as exc:
        raise UiError(str(exc)) from None
    return table, days, made, (start, end, date, rest)


def _worktime_command(payload: dict, picks, out=None) -> str:
    start, end, date, rest = picks
    args: list = ["sheet", "worktime", *_source_args(payload),
                  "--start", start, "--end", end]
    if date:
        args += ["--date", date]
    if rest is not None:
        args += ["--rest", rest]
    return form.command(*args, *(["-o", out] if out else []))


def _worktime_result(days, made) -> dict:
    good = [d for d in days if not d.problem]
    worked = sum(d.worked for d in good)
    return {"headers": made.headers, "rows": _cells(made, PEEK_ROWS),
            "count": len(made.rows), "shown": min(len(made.rows), PEEK_ROWS),
            "worked": round(worked / 60, 1), "days": len(good),
            "average": round(worked / len(good) / 60, 1) if good else 0,
            "night": sum(1 for d in good if d.overnight),
            "unread": [[str(d.line), d.problem] for d in days
                       if d.problem and d.problem != "빈 칸"][:20],
            "weeks": [[str(monday), f"{minutes / 60:.1f}"]
                      for monday, minutes in sheet.work_weeks(days)[:20]]}


def worktime_preview(payload: dict) -> dict:
    _table, days, made, picks = _worked(payload)
    out = _worktime_result(days, made)
    out["command"] = _worktime_command(payload, picks)
    return out


def worktime_save(payload: dict) -> dict:
    """원본은 그대로 두고 옆에 «(근무시간)» 파일을 만든다."""
    table, days, made, picks = _worked(payload)
    source = Path(table.source)
    suffix = source.suffix.lower()
    if suffix not in sheet.XLSX_SUFFIXES:
        suffix = ".csv"
    target = files.unique_path(source.with_name(f"{source.stem} (근무시간){suffix}"))
    sheet.save(made, target)
    out = _worktime_result(days, made)
    out["saved"] = str(target)
    out["command"] = _worktime_command(payload, picks, target)
    return out


def audit(payload: dict) -> dict:
    """받은 표를 한 번에 훑는다. 고치지 않고 볼 만한 곳만 모은다."""
    table = _open(payload)
    rep = sheet.audit(table)
    return {"rows": [[n.kind, n.column or "-", n.detail] for n in rep.notes],
            "count": len(rep.notes),
            "size": f"{rep.rows:,}행 x {rep.columns}열",
            "looked": rep.looked, "skipped": rep.skipped,
            "command": form.command("sheet", "audit", *_source_args(payload))}


def outliers(payload: dict) -> dict:
    """숫자 열에서 드문 값 찾기. 지우지 않고 어디인지만."""
    table = _open(payload)
    column = form.text(payload, "ocol")
    if not column:
        raise UiError("숫자가 든 열을 골라 주세요.")
    method = form.choice(payload, "omethod", sheet.OUTLIER_METHODS, "iqr")
    factor = float(form.number(payload, "ofactor", 1.5, low=0.1, high=10))
    try:
        rep = sheet.find_outliers(table, column, method=method, factor=factor)
    except sheet.SheetError as exc:
        raise UiError(str(exc)) from None

    def shown(value: float) -> str:
        return f"{int(value):,}" if float(value).is_integer() else f"{value:,.2f}"

    args: list[object] = ["sheet", "outliers", *_source_args(payload), "-c", column]
    if method != "iqr":
        args += ["--method", method]
    if factor != 1.5:
        args += ["--factor", f"{factor:g}"]

    return {"rows": [[str(o.row), shown(o.value), o.side] for o in rep.found[:PEEK_ROWS]],
            "count": len(rep.found), "counted": rep.counted,
            "note": rep.note,
            "middle": shown(round(rep.middle, 2)),
            "range": f"{shown(round(rep.low, 2))} ~ {shown(round(rep.high, 2))}",
            "how": sheet.OUTLIER_METHODS[method],
            "command": form.command(*args)}


def _replaced(payload: dict):
    table = _open(payload)
    find = form.raw_text(payload, "rfind")
    if not find:
        raise UiError("찾을 값을 적어 주세요.")
    columns = [c.strip() for c in form.text(payload, "rcols").split(",") if c.strip()]
    try:
        return table, *sheet.replace_values(
            table, find, form.raw_text(payload, "rto"), columns=columns or None,
            exact=form.flag(payload, "rexact"),
            ignore_case=form.flag(payload, "rcase"))
    except sheet.SheetError as exc:
        raise UiError(str(exc)) from None


def _replace_command(payload: dict, out=None) -> str:
    args: list[object] = ["sheet", "replace", *_source_args(payload),
                          form.raw_text(payload, "rfind"), form.raw_text(payload, "rto")]
    for column in [c.strip() for c in form.text(payload, "rcols").split(",") if c.strip()]:
        args += ["-c", column]
    if form.flag(payload, "rexact"):
        args.append("--exact")
    if form.flag(payload, "rcase"):
        args.append("-i")
    return form.command(*args, *(["-o", out] if out else []))


def _replace_result(table, rep) -> dict:
    return {"headers": table.headers, "rows": _cells(table, PEEK_ROWS),
            "count": len(table.rows), "shown": min(len(table.rows), PEEK_ROWS),
            "changed": rep.changed, "changed_rows": rep.rows,
            "columns": rep.columns, "skipped": rep.skipped_typed}


def replace_preview(payload: dict) -> dict:
    _before, table, rep = _replaced(payload)
    out = _replace_result(table, rep)
    out["command"] = _replace_command(payload)
    return out


def replace_save(payload: dict) -> dict:
    """원본은 그대로 두고 옆에 «(바꾼)» 파일을 만든다."""
    before, table, rep = _replaced(payload)
    if not rep.changed:
        raise UiError("바꿀 것이 없습니다.")
    source = Path(before.source)
    suffix = source.suffix.lower()
    if suffix not in sheet.XLSX_SUFFIXES:
        suffix = ".csv"
    out = files.unique_path(source.with_name(f"{source.stem} (바꾼){suffix}"))
    sheet.save(table, out)
    result = _replace_result(table, rep)
    result["saved"] = str(out)
    result["command"] = _replace_command(payload, out)
    return result


def _mask_specs(payload: dict) -> list[tuple[str, str]]:
    raw = payload.get("mspecs")
    if not isinstance(raw, list) or not raw:
        raise UiError("어느 열을 어떻게 가릴지 골라 주세요.")
    out = []
    for item in raw:
        if not (isinstance(item, list) and len(item) == 2
                and all(isinstance(x, str) for x in item)):
            raise UiError("고른 목록이 깨졌습니다. 화면을 새로 고쳐 주세요.")
        column, kind = item[0].strip(), item[1].strip()
        if kind not in sheet.MASK_KINDS:
            raise UiError(f"알 수 없는 가림: {kind}")
        out.append((column, kind))
    return out


def _masked(payload: dict):
    table = _open(payload)
    reports = []
    for column, kind in _mask_specs(payload):
        try:
            table, rep = sheet.mask_column(table, column, kind)
        except sheet.SheetError as exc:
            raise UiError(str(exc)) from None
        reports.append(rep)
    return table, reports


def _mask_command(payload: dict, out=None) -> str:
    flags = {"이름": "--name", "전화": "--phone", "이메일": "--email",
             "주민번호": "--rrn", "계좌": "--account", "주소": "--address"}
    args: list[object] = ["sheet", "mask", *_source_args(payload)]
    for column, kind in _mask_specs(payload):
        args += [flags[kind], column]
    return form.command(*args, *(["-o", out] if out else []))


def _mask_rows(reports) -> list[list[str]]:
    return [[r.column, r.kind, str(r.masked), str(r.blank), str(len(r.unclear))]
            for r in reports]


def _mask_unclear(reports) -> list[list[str]]:
    rows = []
    for rep in reports:
        for line, value in rep.unclear[:20]:
            rows.append([rep.column, str(line), value])
    return rows


def mask_preview(payload: dict) -> dict:
    table, reports = _masked(payload)
    return {"report": _mask_rows(reports), "unclear": _mask_unclear(reports),
            "headers": table.headers, "rows": _cells(table, PEEK_ROWS),
            "count": len(table.rows), "shown": min(len(table.rows), PEEK_ROWS),
            "command": _mask_command(payload)}


def mask_save(payload: dict) -> dict:
    """원본은 그대로 두고 옆에 «(가림)» 파일을 만든다."""
    table, reports = _masked(payload)
    source = Path(_open(payload).source)
    suffix = source.suffix.lower()
    if suffix not in sheet.XLSX_SUFFIXES:
        suffix = ".csv"
    out = files.unique_path(source.with_name(f"{source.stem} (가림){suffix}"))
    sheet.save(table, out)
    return {"saved": str(out), "count": len(table.rows),
            "report": _mask_rows(reports), "unclear": _mask_unclear(reports),
            "headers": table.headers, "rows": _cells(table, PEEK_ROWS),
            "shown": min(len(table.rows), PEEK_ROWS),
            "command": _mask_command(payload, out)}


def _collect_targets(payload: dict) -> tuple[Path, list[Path], str]:
    root = form.folder(payload, "cfolder")
    pattern = form.text(payload, "cglob") or "*"
    targets = [q for q in sorted(root.rglob(pattern))
               if q.is_file()
               and q.suffix.lower() in (sheet.XLSX_SUFFIXES | sheet.CSV_SUFFIXES)]
    if not targets:
        raise UiError(f"{root} 안에서 엑셀·csv 를 찾지 못했습니다.")
    return root, targets, pattern


def _collected(payload: dict):
    root, targets, _pattern = _collect_targets(payload)
    raw = form.text(payload, "cells")
    specs = []
    for piece in raw.replace("\n", ",").split(","):
        piece = piece.strip()
        if piece:
            try:
                specs.append(sheet.parse_cell(piece))
            except sheet.SheetError as exc:
                raise UiError(str(exc)) from None
    if not specs:
        raise UiError("뽑을 칸을 적어 주세요. 예: B3=담당자, C7=금액")
    table, skipped = sheet.collect_cells(targets, specs,
                                         sheet=form.text(payload, "csheet") or None)
    return root, table, skipped, specs


def _collect_command(payload: dict, out=None) -> str:
    root, _targets, pattern = _collect_targets(payload)
    args: list[object] = ["sheet", "collect", root]
    for piece in form.text(payload, "cells").replace("\n", ",").split(","):
        if piece.strip():
            args += ["--cell", piece.strip()]
    if form.text(payload, "csheet"):
        args += ["--sheet", form.text(payload, "csheet")]
    if pattern != "*":
        args += ["--glob", pattern]
    return form.command(*args, *(["-o", out] if out else []))


def _collect_result(root, table, skipped, specs) -> dict:
    empty = [r[0] for r in table.rows if all(v is None or v == "" for v in r[1:])]
    return {"headers": table.headers, "rows": _cells(table, PEEK_ROWS),
            "count": len(table.rows), "shown": min(len(table.rows), PEEK_ROWS),
            "cells": len(specs), "empty": empty[:20],
            "skipped": [[Path(name).name, why] for name, why in skipped[:20]]}


def collect_preview(payload: dict) -> dict:
    root, table, skipped, specs = _collected(payload)
    out = _collect_result(root, table, skipped, specs)
    out["command"] = _collect_command(payload)
    return out


def collect_save(payload: dict) -> dict:
    """취합 결과는 훑은 폴더 «옆» 에 만든다. 안에 넣으면 다음 취합에 딸려 온다."""
    root, table, skipped, specs = _collected(payload)
    if not table.rows:
        raise UiError("모은 것이 없습니다.")
    out = files.unique_path(root.parent / f"{root.name} 취합.csv")
    sheet.save(table, out)
    result = _collect_result(root, table, skipped, specs)
    result["saved"] = str(out)
    result["command"] = _collect_command(payload, out)
    return result


def similar(payload: dict) -> dict:
    """같은 곳으로 보이는 값 찾기. 합치지 않고 후보만 낸다."""
    table = _open(payload)
    column = form.text(payload, "simcol")
    if not column:
        raise UiError("어느 열에서 찾을지 골라 주세요.")
    threshold = form.number(payload, "threshold", 0.85, low=0.5, high=1.0)
    try:
        pairs, cut = sheet.find_similar(table, column, threshold=float(threshold))
    except sheet.SheetError as exc:
        raise UiError(str(exc)) from None

    def where(row: int, count: int) -> str:
        return f"{row}행" + (f" 외 {count - 1}" if count > 1 else "")

    rows = [[p.reason, f"{p.score:.2f}", where(p.left_row, p.left_count), p.left,
             where(p.right_row, p.right_count), p.right] for p in pairs[:PEEK_ROWS]]
    args: list[object] = ["sheet", "similar", *_source_args(payload), "-c", column]
    if float(threshold) != 0.85:
        args += ["--threshold", f"{float(threshold):g}"]
    return {"rows": rows, "count": len(pairs), "shown": len(rows), "cut": cut,
            "command": form.command(*args)}


MAX_HITS = 200


def search(payload: dict) -> dict:
    """여러 파일에서 값 찾기. 폴더를 주면 그 안의 csv·xlsx 를 다 본다."""
    needle = form.raw_text(payload, "needle")
    if not needle.strip():
        raise UiError("찾을 값을 적어 주세요.")

    where = form.text(payload, "folder") or form.text(payload, "path")
    if not where:
        raise UiError("찾아볼 폴더나 파일 경로를 적어 주세요.")
    root = Path(where).expanduser()
    if not root.exists():
        raise UiError(f"그런 경로가 없습니다: {root}")

    if root.is_dir():
        targets = [q for q in sorted(root.rglob("*"))
                   if q.is_file()
                   and q.suffix.lower() in (sheet.XLSX_SUFFIXES | sheet.CSV_SUFFIXES)
                   and not q.name.startswith("~$")]
    else:
        targets = [root]
    if not targets:
        raise UiError("찾아볼 파일이 없습니다. (csv, tsv, xlsx)")

    found, skipped = sheet.find_in_files(
        targets, needle, column=form.text(payload, "scolumn") or None,
        exact=form.flag(payload, "exact"),
        ignore_case=not form.flag(payload, "case"))

    rows = [[Path(h.path).name, h.sheet or "-", str(h.row), h.column,
             h.value[:40], h.context[:20]] for h in found[:MAX_HITS]]
    return {"rows": rows, "count": len(found), "files": len(targets),
            "shown": min(len(found), MAX_HITS),
            "skipped": [[Path(name).name, why[:60]] for name, why in skipped[:20]],
            "command": form.command("sheet", "find", needle, root),
            "note": "행 번호는 머리글을 1행으로 세어 엑셀에서 보이는 번호와 "
                    "같습니다. xlsx 는 시트를 모두 봅니다."}


def _cleaned(payload: dict):
    table = _open(payload)
    return table, sheet.clean(
        table,
        drop_duplicates=form.flag(payload, "dedupe"),
        drop_empty_cols=form.flag(payload, "drop_empty", True))


def _report_rows(before: sheet.Table, after: sheet.Table, rep) -> list[list[str]]:
    rows = [
        ["앞뒤 공백을 지운 칸", str(rep.trimmed)],
        ["전각 문자를 반각으로", str(rep.fullwidth)],
        ["숫자로 읽은 칸", str(rep.numbers)],
        ["날짜로 읽은 칸", str(rep.dates)],
        ["지운 빈 행", str(rep.dropped_rows)],
        ["지운 중복 행", str(rep.duplicate_rows)],
        ["지운 빈 열", ", ".join(rep.dropped_cols) or "0"],
        ["남은 행", f"{len(before.rows)} → {len(after.rows)}"],
    ]
    return rows


def clean_preview(payload: dict) -> dict:
    before, (after, rep) = _cleaned(payload)
    return {"report": _report_rows(before, after, rep),
            "headers": after.headers,
            "rows": _cells(after, PEEK_ROWS),
            "shown": min(len(after.rows), PEEK_ROWS),
            "count": len(after.rows)}


def _source_args(payload: dict) -> list[object]:
    args: list[object] = [form.text(payload, "path")]
    name = form.text(payload, "sheet")
    if name:
        args += ["--sheet", name]
    row = int(form.number(payload, "header_row", 1, low=1, high=1000))
    if row != 1:
        args += ["--header-row", row]
    return args


def clean_save(payload: dict) -> dict:
    """원본은 건드리지 않는다. 옆에 새 파일을 만든다."""
    before, (after, rep) = _cleaned(payload)
    source = Path(before.source)
    suffix = source.suffix.lower()
    if suffix not in sheet.XLSX_SUFFIXES:
        suffix = ".csv"
    out = files.unique_path(source.with_name(f"{source.stem} (정리){suffix}"))
    sheet.save(after, out)
    args = ["sheet", "clean", *_source_args(payload)]
    if form.flag(payload, "dedupe"):
        args.append("--dedupe")
    return {"saved": str(out), "report": _report_rows(before, after, rep),
            "count": len(after.rows),
            "command": form.command(*args, "-o", out)}


BODY = """
<section class="card">
  <h2>어떤 파일인가요</h2>
  <div class="row">
    <div style="flex:3 1 22rem">
      <label for="path">파일 경로 (xlsx, csv, tsv)</label>
      <input type="text" id="path" placeholder="예: ~/문서/명단.xlsx" data-browse=".xlsx,.xlsm,.csv,.tsv" spellcheck="false">
    </div>
    <div>
      <label for="sheet">시트</label>
      <select id="sheet"><option value="">첫 시트</option></select>
    </div>
    <div style="flex:0 1 7rem">
      <label for="header_row">머리글 행</label>
      <input type="text" id="header_row" value="1" spellcheck="false">
    </div>
  </div>
  <div class="actions">
    <button class="primary" id="btn-open">열어 보기</button>
    <button id="btn-sheets">시트 목록</button>
    <span class="spacer"></span>
    <span class="note">원본은 이 화면에서 절대 덮어쓰지 않습니다.</span>
  </div>
  <div id="msg"></div>
</section>

<nav class="tabs" id="tabs">
  <button data-tab="훑어보기" aria-selected="true">훑어보기</button>
  <button data-tab="고치기" aria-selected="false">고치기</button>
  <button data-tab="골라내기" aria-selected="false">골라내기</button>
  <button data-tab="여러 파일" aria-selected="false">여러 파일</button>
  <button data-tab="내보내기 전에" aria-selected="false">내보내기 전에</button>
  <button data-tab="캘린더·연락처" aria-selected="false">캘린더·연락처</button>
  <button data-tab="인쇄" aria-selected="false">인쇄</button>
</nav>

<section class="card" data-panel="훑어보기">
  <h2>열마다 무엇이 들어 있나</h2>
  <div id="cols"><div class="empty">파일을 열면 여기에 나옵니다.</div></div>
</section>

<section class="card" data-panel="훑어보기">
  <h2>내용 미리보기</h2>
  <div id="rows"><div class="empty">아직 없습니다.</div></div>
</section>

<section class="card" data-panel="훑어보기">
  <h2>한 번에 훑기</h2>
  <p class="note">남이 보낸 표를 열었을 때 <b>무엇부터 봐야 하는지</b> 모아 줍니다 -
     빈 칸이 많은 열, 한 열에 섞인 타입, 똑같은 행, 숫자 열의 드문 값,
     개인정보로 보이는 열, 표기 흔들림. <b>고치지는 않습니다.</b>
     여기 없는 문제가 없다는 뜻도 아닙니다.</p>
  <div class="actions"><button class="primary" id="btn-audit">훑어보기</button></div>
  <div id="auditmsg"></div>
  <div id="auditout"></div>
</section>

<section class="card" data-panel="훑어보기" hidden>
  <h2>드문 값 찾기</h2>
  <p class="note">숫자 열에서 «0 하나, 1억 하나» 같은 입력 실수를 찾습니다.
     기본은 사분위 범위입니다 - 평균과 표준편차는 이상치 하나에 끌려가서
     정작 그 값을 보통 범위 안에 넣어 버립니다. <b>지우지 않습니다.</b>
     드문 값이 곧 틀린 값은 아니니 원본에서 확인하세요.</p>
  <div class="row">
    <div><label for="ocol">숫자 열</label><select id="ocol"></select></div>
    <div style="flex:0 1 12rem"><label for="omethod">어떻게</label>
      <select id="omethod"><option value="iqr">사분위 범위 (기본)</option><option value="sigma">평균 ± 표준편차</option></select></div>
    <div style="flex:0 1 7rem"><label for="ofactor">배수</label>
      <input type="text" id="ofactor" value="1.5" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-outliers">찾기</button></div>
  </div>
  <div id="outmsg"></div>
  <div id="outout"></div>
</section>

<section class="card" data-panel="인쇄" hidden>
  <h2>주소 라벨 만들기</h2>
  <p class="note">명단을 라벨지에 인쇄할 HTML 로 만듭니다. 만든 파일을 브라우저로
     열어 인쇄하되 <b>배율 100%%(«실제 크기»), 여백 «없음»</b> 이어야 자리가 맞습니다.
     <b>라벨지 규격은 제품마다 다릅니다</b> - 처음에는 «칸 선 그리기» 를 켜고 빈 종이에
     시험 인쇄해 보고, 왼쪽·위 여백으로 맞추세요. 쓰다 남은 라벨지는 시작 칸을
     정하면 그만큼 비워 둡니다.</p>
  <div class="row">
    <div style="flex:2 1 16rem"><label for="lblines">라벨에 넣을 줄 (한 줄에 하나, 비우면 모든 열)</label>
      <textarea id="lblines" rows="3" spellcheck="false" placeholder="{이름} 님&#10;{주소}&#10;[{우편번호}]"></textarea></div>
    <div style="flex:0 1 6rem"><label for="lbcols">가로 칸</label>
      <input type="text" id="lbcols" value="3" spellcheck="false"></div>
    <div style="flex:0 1 6rem"><label for="lbrows">세로 칸</label>
      <input type="text" id="lbrows" value="7" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="lbwidth">칸 가로(mm)</label>
      <input type="text" id="lbwidth" value="63.5" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="lbheight">칸 세로(mm)</label>
      <input type="text" id="lbheight" value="38.1" spellcheck="false"></div>
  </div>
  <div class="row">
    <div style="flex:0 1 7rem"><label for="lbleft">왼쪽 여백(mm)</label>
      <input type="text" id="lbleft" value="7.2" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="lbtop">위 여백(mm)</label>
      <input type="text" id="lbtop" value="15.1" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="lbfont">글자 크기(pt)</label>
      <input type="text" id="lbfont" value="10" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="lbstart">시작 칸</label>
      <input type="text" id="lbstart" value="1" spellcheck="false"></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="lbguide"> 칸 선 그리기 (자리 맞출 때만)</label>
  </div>
  <div class="actions">
    <button class="primary" id="btn-labels">무엇이 찍히나</button>
    <button id="btn-labels-save" disabled>HTML 만들기</button>
  </div>
  <div id="lbmsg"></div>
  <div id="lbout"></div>
</section>

<section class="card" data-panel="훑어보기">
  <h2>빠진 것 찾기</h2>
  <p class="note">전표 번호가 하나 비었는지, 어느 날 자료가 안 들어왔는지
     찾습니다. 있는 자료만 봐서는 보이지 않는 것입니다. 빠진 것은 낱개가 아니라
     <b>이어진 구간으로</b> 묶어 보여 줍니다. 번호도 날짜도 아닌 칸은
     <b>조용히 버리지 않고</b> 몇 개였는지 알려 줍니다.</p>
  <div class="row">
    <div><label for="gcol">번호·날짜 열</label><select id="gcol"></select></div>
    <div style="flex:0 1 10rem"><label for="gevery">날짜일 때 간격</label>
      <select id="gevery"><option value="day">날마다</option><option value="weekday">평일마다</option><option value="month">달마다</option></select></div>
    <div style="flex:0 1 7rem"><label for="gstep">번호 폭</label>
      <input type="text" id="gstep" value="1" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-gaps">찾기</button></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="gholidays"> 공휴일은 빠진 것으로 세지 않기</label>
  </div>
  <div id="gapmsg"></div>
  <div id="gapout"></div>
</section>

<section class="card" data-panel="훑어보기">
  <h2>점검</h2>
  <p class="note">중복된 열쇠, 빈 칸, 섞인 자료형처럼 나중에 문제가 되는 것을 찾습니다.</p>
  <div class="row">
    <div><label for="key">열쇠 열 (중복 검사)</label>
      <select id="key"><option value="">고르지 않음</option></select></div>
    <div><label for="required">비면 안 되는 열 (쉼표로 여러 개)</label>
      <input type="text" id="required" placeholder="예: 이름, 전화번호" spellcheck="false"></div>
  </div>
  <div class="actions"><button id="btn-check">점검하기</button></div>
  <div id="checkmsg"></div>
  <div id="issues"></div>
</section>

<section class="card" data-panel="여러 파일" hidden>
  <h2>다른 파일과 견주기</h2>
  <p class="note">지난달 명단과 이번달 명단처럼 두 파일을 비교하거나 합칩니다.
     <b>원본은 둘 다 그대로 둡니다.</b></p>
  <div class="row">
    <div style="flex:3 1 20rem"><label for="other">상대 파일</label>
      <input type="text" id="other" placeholder="예: ~/문서/지난달.xlsx" data-browse=".xlsx,.xlsm,.csv,.tsv" spellcheck="false"></div>
    <div><label for="other_sheet">상대 시트</label>
      <input type="text" id="other_sheet" placeholder="첫 시트" spellcheck="false"></div>
    <div><label for="dkey">열쇠 열 (비교할 때)</label>
      <select id="dkey"><option value="">고르지 않음</option></select></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="add_source" checked> 합칠 때 어느 파일에서 왔는지 열 붙이기</label>
  </div>
  <div class="actions">
    <button class="primary" id="btn-compare">무엇이 달라졌나</button>
    <button id="btn-merge">붙여 보기</button>
    <button id="btn-merge-save">붙여서 새 파일로</button>
  </div>
  <div id="pairmsg"></div>
  <div id="pair"></div>
</section>

<section class="card" data-panel="여러 파일" hidden>
  <h2>여러 파일에서 찾기</h2>
  <p class="note">«이 사번이 어느 파일에 있나»를 폴더째 훑어 찾습니다.
     xlsx 는 시트를 모두 봅니다. <b>읽기만 합니다.</b></p>
  <div class="row">
    <div><label for="needle">찾을 값</label>
      <input type="text" id="needle" placeholder="E1024" spellcheck="false" data-forget></div>
    <div style="flex:2 1 18rem"><label for="folder">폴더 (비우면 위의 파일만)</label>
      <input type="text" id="folder" placeholder="~/문서/2026" spellcheck="false" data-browse="dir"></div>
    <div><label for="scolumn">이 열만 (선택)</label>
      <input type="text" id="scolumn" spellcheck="false"></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="exact"> 정확히 같은 값만</label>
    <label><input type="checkbox" id="case"> 대소문자 가리기</label>
  </div>
  <div class="actions"><button class="primary" id="btn-search">찾기</button></div>
  <div id="searchmsg"></div>
  <div id="searchout"></div>
</section>

<section class="card" data-panel="골라내기" hidden>
  <h2>그림으로</h2>
  <p class="note">표를 그림 파일(SVG) 하나로 만듭니다. 보고서·슬라이드에 그림으로
     붙일 수 있습니다. 막대는 큰 것부터 그리고, 잘라 낸 칸이 있으면 몇 칸 중
     몇 칸인지 알려 줍니다.</p>
  <div class="row">
    <div><label for="clabel">이름 열</label><select id="clabel"></select></div>
    <div><label for="cvalue">값 열 (비우면 건수)</label><select id="cvalue"></select></div>
    <div style="flex:0 1 8rem"><label for="cagg">무엇을</label>
      <select id="cagg"><option value="sum">합계</option><option value="count">건수</option><option value="avg">평균</option><option value="min">최소</option><option value="max">최대</option></select></div>
    <div style="flex:0 1 8rem"><label for="ckind">모양</label>
      <select id="ckind"><option value="bar">가로 막대</option><option value="line">꺾은선</option></select></div>
  </div>
  <div class="row" style="margin-top:.6rem">
    <div style="flex:0 1 7rem"><label for="ctop">몇 칸까지</label>
      <input type="text" id="ctop" value="15" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="cunit">단위</label>
      <input type="text" id="cunit" placeholder="원" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-chart">그려 보기</button></div>
    <div style="flex:0 0 auto"><button id="btn-chart-save">.svg 로 저장</button></div>
  </div>
  <div id="chartmsg"></div>
  <div id="chartout"></div>
</section>

<section class="card" data-panel="골라내기" hidden>
  <h2>집계</h2>
  <p class="note">부서별 인원, 월별 매출처럼 묶어서 셉니다. 엑셀의 피벗과
     같은 일입니다.</p>
  <div class="row">
    <div><label for="grows">묶을 열 (쉼표로 여러 개)</label>
      <input type="text" id="grows" placeholder="부서" spellcheck="false"></div>
    <div style="flex:0 1 9rem"><label for="agg">어떻게</label>
      <select id="agg"><option value="sum">합계</option><option value="count">건수</option><option value="avg">평균</option><option value="min">최소</option><option value="max">최대</option></select></div>
    <div><label for="gvalues">집계할 값 열</label>
      <select id="gvalues"><option value="">건수만 셈</option></select></div>
    <div><label for="gcols">교차표 열 (선택)</label>
      <select id="gcols"><option value="">쓰지 않음</option></select></div>
  </div>
  <div class="actions">
    <button class="primary" id="btn-sum">집계</button>
    <button id="btn-sum-save" disabled>새 파일로 저장</button>
  </div>
  <div id="summsg"></div>
  <div id="sumout"></div>
</section>

<section class="card" data-panel="골라내기" hidden>
  <h2>골라내기</h2>
  <p class="note">조건에 맞는 행만 남기고, 정렬하고, 필요한 열만 고릅니다.
     <b>원본은 그대로 두고</b> 저장하면 옆에 «(골라낸)» 파일을 만듭니다.</p>
  <div class="row">
    <div><label for="wcol">조건 열</label>
      <select id="wcol"><option value="">고르지 않음</option></select></div>
    <div style="flex:0 1 10rem"><label for="wop">어떻게</label>
      <select id="wop"><option value="eq">같다</option><option value="ne">다르다</option><option value="gt">크다</option><option value="gte">크거나 같다</option><option value="lt">작다</option><option value="lte">작거나 같다</option><option value="has">포함한다</option><option value="empty">비어 있다</option><option value="filled">값이 있다</option></select></div>
    <div><label for="wval">값</label>
      <input type="text" id="wval" spellcheck="false"></div>
  </div>
  <div class="row" style="margin-top:.6rem">
    <div><label for="scol">정렬 기준 열</label>
      <select id="scol"><option value="">정렬 안 함</option></select></div>
    <div><label for="keep">남길 열 (쉼표로, 비우면 전부)</label>
      <input type="text" id="keep" placeholder="이름, 부서" spellcheck="false"></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="desc"> 내림차순</label>
  </div>
  <div class="actions">
    <button class="primary" id="btn-pick">골라 보기</button>
    <button id="btn-pick-save" disabled>새 파일로 저장</button>
  </div>
  <div id="pickmsg"></div>
  <div id="pickout"></div>
</section>

<section class="card" data-panel="고치기" hidden>
  <h2>값 찾아 바꾸기</h2>
  <p class="note">엑셀의 «모두 바꾸기» 를 파일째 합니다. <b>숫자·날짜 칸은
     건드리지 않습니다</b> - 글자로 바뀌면 그 열의 합계와 정렬이 어긋납니다.
     저장하면 옆에 «(바꾼)» 파일이 새로 생깁니다.</p>
  <div class="row">
    <div><label for="rfind">찾을 값</label>
      <input type="text" id="rfind" spellcheck="false"></div>
    <div><label for="rto">바꿀 값</label>
      <input type="text" id="rto" spellcheck="false"></div>
    <div><label for="rcols">이 열만 (쉼표로, 비우면 전부)</label>
      <input type="text" id="rcols" spellcheck="false"></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="rexact"> 칸 전체가 같을 때만</label>
    <label><input type="checkbox" id="rcase"> 대소문자 무시</label>
  </div>
  <div class="actions">
    <button class="primary" id="btn-replace">바꿔 보기</button>
    <button id="btn-replace-save" disabled>새 파일로 저장</button>
  </div>
  <div id="repmsg"></div>
  <div id="repout"></div>
</section>

<section class="card" data-panel="고치기" hidden>
  <h2>마감일까지 며칠</h2>
  <p class="note">마감일 열에서 «남은 일수» 와 «지남/오늘/남음» 을 만듭니다.
     기준일을 함께 적습니다 - 어제 만든 표와 오늘 만든 표의 숫자가 다른 것은
     당연하지만, 왜 다른지는 보여야 합니다.</p>
  <div class="row">
    <div><label for="ycol">마감일 열</label><select id="ycol"></select></div>
    <div><label for="yon">기준일 (비우면 오늘)</label>
      <input type="text" id="yon" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-dday">세어 보기</button></div>
    <div style="flex:0 0 auto"><button id="btn-dday-save">새 파일로 저장</button></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="ysort" checked> 가까운 순으로</label>
  </div>
  <div id="ddaymsg"></div>
  <div id="ddayout"></div>
</section>

<section class="card" data-panel="고치기" hidden>
  <h2>날짜에서 열 만들기</h2>
  <p class="note">피벗을 돌리기 전에 늘 손으로 만드는 열입니다. 요일·연월·분기
     같은 열을 날짜 열에서 만들어 붙입니다. <b>날짜로 못 읽은 칸은 비워 두고</b>
     몇 행이었는지 알려 줍니다 - 아무 날짜나 채우면 그 행이 엉뚱한 달에 잡힙니다.</p>
  <div class="row">
    <div><label for="dcol">날짜 열</label><select id="dcol"></select></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-dates">만들어 보기</button></div>
    <div style="flex:0 0 auto"><button id="btn-dates-save" disabled>새 파일로 저장</button></div>
  </div>
  <div class="checks" id="dparts">%(dateparts)s</div>
  <div id="datesmsg"></div>
  <div id="datesout"></div>
</section>

<section class="card" data-panel="고치기" hidden>
  <h2>근무 시간 세기</h2>
  <p class="note">출근·퇴근 열에서 하루 체류·휴게·실근무와 주별 합계를 만듭니다.
     휴게는 <b>근로기준법 제54조의 최소 시간</b>(4시간 30분, 8시간 1시간)을 뺍니다 -
     회사가 다르면 분을 직접 적으세요. 퇴근이 출근보다 이르면 <b>자정을 넘긴 것</b>으로
     봅니다. 시각을 못 읽은 행은 0 으로 채우지 않고 비워 둡니다.
     <b>야간·휴일 가산은 셈하지 않습니다.</b></p>
  <div class="row">
    <div><label for="wstart">출근 열</label><select id="wstart"></select></div>
    <div><label for="wend">퇴근 열</label><select id="wend"></select></div>
    <div><label for="wdate">날짜 열 (주별 합계)</label>
      <select id="wdate"></select></div>
    <div style="flex:0 1 8rem"><label for="wrest">휴게(분)</label>
      <input type="text" id="wrest" placeholder="법정" spellcheck="false"></div>
  </div>
  <div class="actions">
    <button class="primary" id="btn-worktime">세어 보기</button>
    <button id="btn-worktime-save" disabled>새 파일로 저장</button>
  </div>
  <div id="wtmsg"></div>
  <div id="wtout"></div>
</section>

<section class="card" data-panel="고치기" hidden>
  <h2>생년월일에서 나이·연령대</h2>
  <p class="note">명단의 생년월일 열에서 <b>만 나이</b>와 연령대를 만듭니다.
     칸이 주민등록번호면 성별까지 읽습니다. <b>읽지 못한 칸은 비워 둡니다</b> -
     아무 값이나 채우면 그 사람이 조용히 다른 연령대에 잡힙니다.</p>
  <div class="row">
    <div><label for="acol">생년월일 열</label><select id="acol"></select></div>
    <div><label for="aon">기준일 (비우면 오늘)</label>
      <input type="text" id="aon" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-age">만들어 보기</button></div>
    <div style="flex:0 0 auto"><button id="btn-age-save" disabled>새 파일로 저장</button></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="agroup" checked> 연령대 열도 (30대…)</label>
    <label><input type="checkbox" id="asex"> 성별 열도 (주민등록번호일 때만)</label>
  </div>
  <div id="agemsg"></div>
  <div id="ageout"></div>
</section>

<section class="card" data-panel="고치기" hidden>
  <h2>빈 칸 채우기 · 합계 줄</h2>
  <p class="note">병합된 셀을 풀면 첫 칸만 남고 아래가 빕니다. 그대로 두면
     정렬·피벗·필터가 어긋납니다. 빈 칸을 <b>바로 위 값</b>으로 채우고,
     맨 아래에 합계 줄을 붙입니다. 저장하면 옆에 «(정돈)» 파일이 생깁니다.</p>
  <div class="row">
    <div><label for="fcols">빈 칸을 채울 열 (쉼표로)</label>
      <input type="text" id="fcols" placeholder="부서, 지역" spellcheck="false"></div>
    <div><label for="tcols">셈할 열 (쉼표로, 비우면 숫자 열 전부)</label>
      <input type="text" id="tcols" placeholder="금액, 수량" spellcheck="false"></div>
  </div>
  <div class="row" style="margin-top:.6rem">
    <div style="flex:0 1 10rem"><label for="tkind">무엇을</label>
      <select id="tkind"><option value="sum">합계</option><option value="avg">평균</option><option value="count">개수</option></select></div>
    <div><label for="tlabel">첫 칸에 넣을 이름</label>
      <input type="text" id="tlabel" placeholder="합계" spellcheck="false"></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="wanttotal" checked> 맨 아래에 합계 줄 붙이기</label>
  </div>
  <div class="actions">
    <button class="primary" id="btn-tidy">이렇게 해 보기</button>
    <button id="btn-tidy-save" disabled>새 파일로 저장</button>
  </div>
  <div id="tidymsg"></div>
  <div id="tidyout"></div>
</section>

<section class="card" data-panel="고치기" hidden>
  <h2>표기 통일</h2>
  <p class="note">전화번호·사업자번호처럼 사람마다 다르게 적은 열을 한 꼴로
     맞춥니다. <b>규칙을 모르는 값은 손대지 않고</b> 몇 행인지 알려 줍니다.</p>
  <div class="row">
    <div><label for="fcol">열</label><select id="fcol"></select></div>
    <div><label for="fkind">형식</label><select id="fkind"><option value="전화">전화 · 010-1234-5678 꼴로</option><option value="사업자번호">사업자번호 · 123-45-67890 꼴로</option><option value="우편번호">우편번호 · 다섯 자리 숫자로</option><option value="날짜">날짜 · 2026-01-02 꼴로</option><option value="숫자">숫자 · 쉼표·«원»을 떼고 숫자로</option></select></div>
    <div style="flex:0 0 auto"><button id="btn-add">목록에 더하기</button></div>
  </div>
  <div id="specs" class="note" style="margin-top:.6rem"></div>
  <div class="actions">
    <button class="primary" id="btn-format">맞추면 어떻게 되나</button>
    <button id="btn-format-save" disabled>새 파일로 저장</button>
  </div>
  <div id="formatmsg"></div>
  <div id="formatreport"></div>
</section>

<section class="card" data-panel="내보내기 전에" hidden>
  <h2>같은 곳으로 보이는 값</h2>
  <p class="note">«(주)가나» 와 «주식회사 가나» 처럼 같은 곳이 따로 들어간 자리를
     찾습니다. <b>합치지는 않습니다</b> - 표기가 같아 보여도 정말 다른 곳일 수
     있어서 사람이 보고 정할 일입니다. 다듬은 이름의 앞 두 글자가 같은 것끼리만
     견주므로 첫 글자가 다른 오타는 찾지 못합니다.</p>
  <div class="row">
    <div><label for="simcol">열</label><select id="simcol"></select></div>
    <div style="flex:0 1 9rem"><label for="threshold">닮은 정도</label>
      <input type="text" id="threshold" value="0.85" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-similar">찾기</button></div>
  </div>
  <div id="simmsg"></div>
  <div id="simout"></div>
</section>

<section class="card" data-panel="내보내기 전에" hidden>
  <h2>개인정보 가리기</h2>
  <p class="note">밖으로 보낼 명단을 만듭니다. 이름 <b>홍*동</b>, 전화
     <b>010-****-5678</b>, 주민번호는 성별 자리까지, 계좌는 뒤 네 자리만 남깁니다.
     <b>꼴을 모르는 값은 통째로 가리고</b> 몇 행이었는지 알려 줍니다 -
     못 가리고 새는 것보다 낫기 때문입니다.</p>
  <div class="row">
    <div><label for="mcol">열</label><select id="mcol"></select></div>
    <div><label for="mkind">어떻게</label><select id="mkind"><option value="이름">이름 · 홍*동</option><option value="전화">전화 · 010-****-5678</option><option value="이메일">이메일 · ho**@example.com</option><option value="주민번호">주민번호 · 900101-1******</option><option value="계좌">계좌·카드 · 뒤 네 자리만</option><option value="주소">주소 · 시·군·구까지만</option></select></div>
    <div style="flex:0 0 auto"><button id="btn-madd">목록에 더하기</button></div>
  </div>
  <div id="mspecs" class="note" style="margin-top:.6rem"></div>
  <div class="actions">
    <button class="primary" id="btn-mask">가리면 어떻게 되나</button>
    <button id="btn-mask-save" disabled>새 파일로 저장</button>
  </div>
  <div id="maskmsg"></div>
  <div id="maskout"></div>
</section>

<section class="card" data-panel="캘린더·연락처" hidden>
  <h2>일정표 → 캘린더(ics)</h2>
  <p class="note">엑셀로 만든 일정표를 캘린더가 읽는 파일로 냅니다. 시작 칸에 시각이
     같이 있으면(<b>2026-03-04 14:30</b>) 시각까지 읽고, 날짜만 있으면 종일 일정이
     됩니다. 시각이 있는 일정은 한국 시간으로 넣고, <b>날짜를 못 읽은 행은 채우지
     않고</b> 몇 행인지 알려 줍니다. 파일은 원본 옆에 만듭니다.</p>
  <div class="row">
    <div><label for="ictitle">일정 이름 열</label><select id="ictitle"></select></div>
    <div><label for="icstart">시작 열</label><select id="icstart"></select></div>
    <div><label for="icend">끝 열</label><select id="icend"></select></div>
    <div><label for="icplace">장소 열</label><select id="icplace"></select></div>
    <div style="flex:0 1 7rem"><label for="icalarm">알림(분 전)</label>
      <input type="text" id="icalarm" value="0" spellcheck="false"></div>
  </div>
  <div class="actions">
    <button class="primary" id="btn-ics">어떻게 들어가나</button>
    <button id="btn-ics-save" disabled>ics 만들기</button>
  </div>
  <div id="icsmsg"></div>
  <div id="icsout"></div>
</section>

<section class="card" data-panel="캘린더·연락처" hidden>
  <h2>명단 → 연락처(vcf)</h2>
  <p class="note">거래처 명단을 폰 주소록이 읽는 파일로 냅니다. <b>이름을 성과 이름으로
     쪼개지 않습니다</b> - 남궁·제갈 같은 두 자 성을 잘못 자르지 않으려는 것입니다.
     이름이 빈 행은 건너뜁니다. 파일은 원본 옆에 만듭니다.</p>
  <div class="row">
    <div><label for="vcname">이름 열</label><select id="vcname"></select></div>
    <div><label for="vccompany">회사 열</label><select id="vccompany"></select></div>
    <div><label for="vctitle">직함 열</label><select id="vctitle"></select></div>
    <div><label for="vcmobile">휴대전화 열</label><select id="vcmobile"></select></div>
    <div><label for="vcphone">전화 열</label><select id="vcphone"></select></div>
    <div><label for="vcemail">메일 열</label><select id="vcemail"></select></div>
  </div>
  <div class="actions">
    <button class="primary" id="btn-vcard">어떻게 들어가나</button>
    <button id="btn-vcard-save" disabled>vcf 만들기</button>
  </div>
  <div id="vcmsg"></div>
  <div id="vcout"></div>
</section>

<section class="card" data-panel="여러 파일" hidden>
  <h2>사람마다 메일 초안 만들기</h2>
  <p class="note">명단과 본문 틀로 <b>사람마다 .eml 초안 파일</b>을 만듭니다.
     본문·제목에 <code>{이름}</code> 처럼 열 이름을 적으면 그 자리에 값이 들어갑니다.
     <b>보내지 않습니다</b> - 파일을 메일 앱에서 열면 초안으로 뜨고, 보내는 것은
     사람이 한 번 더 보고 누릅니다. 메일 주소로 보이지 않는 행과 첨부를 찾지 못한
     행은 만들지 않고 몇 행이 왜 빠졌는지 알려 줍니다.</p>
  <div class="row">
    <div style="flex:2 1 16rem"><label for="mltemplate">본문 틀 파일</label>
      <input type="text" id="mltemplate" spellcheck="false"
             data-browse=".md,.txt"></div>
    <div style="flex:2 1 14rem"><label for="mlsubject">제목 틀</label>
      <input type="text" id="mlsubject" spellcheck="false"
             placeholder="{이름}님 3월 정산 안내"></div>
  </div>
  <div class="row" style="margin-top:.6rem">
    <div><label for="mlto">받는 사람 열</label><select id="mlto"></select></div>
    <div><label for="mlattach">첨부 경로 열</label>
      <select id="mlattach"></select></div>
  </div>
  <div class="actions">
    <button class="primary" id="btn-mail">누구에게 무엇이 가나</button>
    <button id="btn-mail-save" disabled>초안 만들기</button>
  </div>
  <div id="mailmsg"></div>
  <div id="mailout"></div>
</section>

<section class="card" data-panel="여러 파일" hidden>
  <h2>받은 파일들의 서식 견주기</h2>
  <p class="note">합치기 전에 <b>누가 열을 고쳤는지</b> 봅니다. 열이 하나 늘거나 순서가
     바뀐 채로 합치면 값이 엉뚱한 열로 들어가는데, 표는 그대로 만들어집니다.
     기준은 <b>가장 흔한 열 구성</b>입니다 - 전부 똑같이 틀렸으면 아무 말도 못 하므로
     기준도 함께 보여 줍니다. 파일은 건드리지 않습니다.</p>
  <div class="row">
    <div style="flex:3 1 18rem"><label for="ffolder">받은 파일이 있는 폴더</label>
      <input type="text" id="ffolder" data-browse="dir" spellcheck="false"></div>
    <div style="flex:0 1 9rem"><label for="fglob">고를 무늬</label>
      <input type="text" id="fglob" spellcheck="false" placeholder="*.xlsx"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-forms">견줘 보기</button></div>
  </div>
  <div id="formsmsg"></div>
  <div id="formsout"></div>
</section>

<section class="card" data-panel="여러 파일" hidden>
  <h2>양식 취합</h2>
  <p class="note">부서마다 같은 서식에 채워 보낸 파일들에서 <b>같은 칸</b>만 뽑아
     한 표로 만듭니다. 칸은 엑셀에서 보이는 주소(B3, C7)로 적습니다. 칸이 비어도
     그 파일을 빼지 않고 표에 남깁니다 - 무엇이 안 왔는지 알아야 하기 때문입니다.</p>
  <div class="row">
    <div><label for="cfolder">받은 파일이 있는 폴더</label>
      <input type="text" id="cfolder" spellcheck="false" placeholder="/home/나/부서제출">
      <button class="browse" data-for="cfolder">찾아보기</button></div>
    <div style="flex:0 1 9rem"><label for="cglob">고를 무늬</label>
      <input type="text" id="cglob" spellcheck="false" placeholder="*.xlsx"></div>
  </div>
  <div class="row" style="margin-top:.6rem">
    <div><label for="cells">뽑을 칸 (쉼표로)</label>
      <input type="text" id="cells" spellcheck="false" placeholder="B3=담당자, C7=금액"></div>
    <div style="flex:0 1 10rem"><label for="csheet">시트 이름</label>
      <input type="text" id="csheet" spellcheck="false" placeholder="첫 시트"></div>
  </div>
  <div class="actions">
    <button class="primary" id="btn-collect">모아 보기</button>
    <button id="btn-collect-save" disabled>표로 저장</button>
  </div>
  <div id="collectmsg"></div>
  <div id="collectout"></div>
</section>

<section class="card" data-panel="고치기" hidden>
  <h2>정리</h2>
  <p class="note">앞뒤 공백·전각 문자를 다듬고, 숫자와 날짜를 제대로 읽고,
     빈 행을 지웁니다. 저장하면 <b>원본 옆에 «(정리)» 파일</b>이 새로 생깁니다.</p>
  <div class="checks">
    <label><input type="checkbox" id="dedupe"> 똑같은 행 지우기</label>
    <label><input type="checkbox" id="drop_empty" checked> 통째로 빈 열 지우기</label>
  </div>
  <div class="actions">
    <button id="btn-clean">정리하면 어떻게 되나</button>
    <button class="primary" id="btn-save" disabled>새 파일로 저장</button>
  </div>
  <div id="cleanmsg"></div>
  <div id="cleanreport"></div>
</section>

<script>
(function () {
  const $ = (id) => document.getElementById(id);
  let opened = false;

  document.querySelectorAll("#tabs button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll("#tabs button").forEach(function (b) {
        b.setAttribute("aria-selected", String(b === btn));
      });
      document.querySelectorAll("[data-panel]").forEach(function (panel) {
        panel.hidden = panel.dataset.panel !== btn.dataset.tab;
      });
    });
  });

  function values() {
    return {
      path: $("path").value,
      sheet: $("sheet").value,
      header_row: $("header_row").value,
      key: $("key").value,
      required: $("required").value,
      dedupe: $("dedupe").checked,
      drop_empty: $("drop_empty").checked,
    };
  }

  function options(sel, names, first) {
    const keep = sel.value;
    sel.innerHTML = '<option value="">' + first + "</option>" +
      names.map(n => '<option value="' + AT.esc(n) + '">' + AT.esc(n) +
                     "</option>").join("");
    if (names.indexOf(keep) >= 0) sel.value = keep;
  }

  let specs = [];

  function drawSpecs() {
    $("specs").innerHTML = specs.length
      ? specs.map(function (s, i) {
          return '<button data-i="' + i + '" class="spec">' + AT.esc(s[0]) +
                 " \u2192 " + AT.esc(s[1]) + " \u00d7</button>";
        }).join(" ")
      : "아직 고른 것이 없습니다.";
    $("specs").querySelectorAll("button.spec").forEach(function (b) {
      b.addEventListener("click", function () {
        specs.splice(Number(b.dataset.i), 1);
        drawSpecs();
        $("btn-format-save").disabled = true;
      });
    });
  }
  drawSpecs();

  $("btn-add").addEventListener("click", function () {
    const column = $("fcol").value;
    if (!column) { AT.message($("formatmsg"), "먼저 파일을 열어 주세요.", "bad"); return; }
    if (!specs.some(s => s[0] === column && s[1] === $("fkind").value)) {
      specs.push([column, $("fkind").value]);
      drawSpecs();
      $("btn-format-save").disabled = true;
    }
  });

  function formatBody() {
    const b = values();
    b.specs = specs;
    return b;
  }

  function drawFormat(d) {
    $("formatreport").innerHTML =
      AT.table(["열", "형식", "바꾼 값", "이미 맞음", "빈칸", "못 알아봄", "검증 실패"],
               d.report, [null, null, "num", "num", "num", "num", "num"]) +
      (d.left.length
        ? "<h2>손대지 않은 값</h2>" +
          AT.table(["열", "행", "값", "왜"], d.left, [null, "num", null, null])
        : "") +
      (d.headers ? AT.table(d.headers, d.rows) : "");
  }

  $("btn-format").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/format_preview", formatBody());
      drawFormat(d);
      AT.message($("formatmsg"), "이대로 저장할 수 있습니다.", "ok");
      $("btn-format-save").disabled = false;
    } catch (e) {
      AT.message($("formatmsg"), AT.esc(e.message), "bad");
      $("btn-format-save").disabled = true;
    }
  });

  $("btn-format-save").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/format_save", formatBody());
      drawFormat(d);
      AT.message($("formatmsg"), "저장했습니다: <b>" + AT.esc(d.saved) + "</b>", "ok");
      $("formatreport").innerHTML += AT.command(d.command);
      $("btn-format-save").disabled = true;
    } catch (e) { AT.message($("formatmsg"), AT.esc(e.message), "bad"); }
  });

  function pairValues(extra) {
    const b = values();
    b.other = $("other").value;
    b.other_sheet = $("other_sheet").value;
    b.key = $("dkey").value;
    b.add_source = $("add_source").checked;
    return Object.assign(b, extra || {});
  }

  $("btn-compare").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/compare", pairValues());
      const columns = []
        .concat(d.columns_added.map(c => "새 열: " + c))
        .concat(d.columns_removed.map(c => "사라진 열: " + c));
      $("pair").innerHTML = (d.same
          ? '<div class="empty">다른 곳이 없습니다.</div>'
          : AT.table(["무엇", "열쇠", "열", "먼저", "나중"], d.rows)) +
        (columns.length ? '<p class="note">' + columns.map(AT.esc).join(" · ") +
          "</p>" : "") + '<p class="note">' + AT.esc(d.note) + "</p>";
      AT.message($("pairmsg"), d.same ? "다른 곳이 없습니다."
        : "빠짐 <b>" + d.removed + "</b> · 새로 생김 <b>" + d.added +
          "</b> · 값 바뀜 <b>" + d.changed + "</b>", d.same ? "ok" : "bad");
    } catch (e) { AT.message($("pairmsg"), AT.esc(e.message), "bad"); }
  });

  async function doMerge(save) {
    try {
      const d = await AT.call("/api/sheet/merge", pairValues({ save: save }));
      $("pair").innerHTML =
        (d.warnings.length ? '<p class="note">' +
          d.warnings.map(AT.esc).join("<br>") + "</p>" : "") +
        AT.table(d.headers, d.rows) +
        (d.count > d.shown ? '<p class="note">' + d.count + "행 가운데 " +
          d.shown + "행만 보입니다.</p>" : "");
      AT.message($("pairmsg"), d.saved
        ? "저장했습니다: <b>" + AT.esc(d.saved) + "</b> (" + d.count + "행)"
        : "붙이면 <b>" + d.count + "행</b>이 됩니다. 아직 저장하지 않았습니다.",
        "ok");
    } catch (e) { AT.message($("pairmsg"), AT.esc(e.message), "bad"); }
  }

  $("btn-merge").addEventListener("click", function () { doMerge(false); });
  $("btn-merge-save").addEventListener("click", function () { doMerge(true); });

  $("btn-sheets").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/sheets", values());
      options($("sheet"), d.names, "첫 시트");
      $("cols").innerHTML = AT.table(["시트", "행", "열", "머리글"], d.rows,
                                     [null, "num", "num", null]);
      AT.message($("msg"), "시트 <b>" + d.count + "개</b>. 위에서 골라 열어 보세요.",
                 "ok");
    } catch (e) { AT.message($("msg"), AT.esc(e.message), "bad"); }
  });

  function pickValues() {
    const b = values();
    b.wcol = $("wcol").value; b.wop = $("wop").value; b.wval = $("wval").value;
    b.scol = $("scol").value; b.desc = $("desc").checked;
    b.keep = $("keep").value;
    return b;
  }

  function drawPick(d) {
    $("pickout").innerHTML =
      (d.steps.length ? '<p class="note">' + d.steps.map(AT.esc).join(" → ") +
        "</p>" : "") +
      (d.headers ? AT.table(d.headers, d.rows) : "") +
      (d.count > (d.shown || 0) ? '<p class="note">' + d.count + "행 가운데 " +
        d.shown + "행만 보입니다.</p>" : "") +
      AT.command(d.command);
  }

  $("btn-pick").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/pick_preview", pickValues());
      drawPick(d);
      AT.message($("pickmsg"), "<b>" + d.count + "행</b>이 남습니다.", "ok");
      $("btn-pick-save").disabled = d.count === 0;
    } catch (e) {
      AT.message($("pickmsg"), AT.esc(e.message), "bad");
      $("btn-pick-save").disabled = true;
    }
  });

  $("btn-pick-save").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/pick_save", pickValues());
      drawPick(d);
      AT.message($("pickmsg"), "저장했습니다: <b>" + AT.esc(d.saved) + "</b> (" +
                 d.count + "행)", "ok");
      $("btn-pick-save").disabled = true;
    } catch (e) { AT.message($("pickmsg"), AT.esc(e.message), "bad"); }
  });

  function sumValues() {
    const b = values();
    b.grows = $("grows").value; b.agg = $("agg").value;
    b.gvalues = $("gvalues").value; b.gcols = $("gcols").value;
    return b;
  }

  function drawSum(d) {
    $("sumout").innerHTML = AT.table(d.headers, d.rows) +
      (d.count > (d.shown || 0) ? '<p class="note">' + d.count + "행 가운데 " +
        d.shown + "행만 보입니다.</p>" : "") + AT.command(d.command);
  }

  $("btn-sum").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/sum_preview", sumValues());
      drawSum(d);
      AT.message($("summsg"), "<b>" + d.count + "줄</b>로 묶었습니다.", "ok");
      $("btn-sum-save").disabled = d.count === 0;
    } catch (e) {
      AT.message($("summsg"), AT.esc(e.message), "bad");
      $("btn-sum-save").disabled = true;
    }
  });

  $("btn-sum-save").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/sum_save", sumValues());
      drawSum(d);
      AT.message($("summsg"), "저장했습니다: <b>" + AT.esc(d.saved) + "</b>", "ok");
      $("btn-sum-save").disabled = true;
    } catch (e) { AT.message($("summsg"), AT.esc(e.message), "bad"); }
  });

  function tidyValues() {
    const b = values();
    b.fcols = $("fcols").value; b.tcols = $("tcols").value;
    b.tkind = $("tkind").value; b.tlabel = $("tlabel").value;
    b.wanttotal = $("wanttotal").checked;
    return b;
  }

  function drawTidy(d) {
    $("tidyout").innerHTML =
      (d.steps.length ? '<p class="note">' + d.steps.map(AT.esc).join(" → ") +
        "</p>" : "") +
      AT.table(d.headers, d.rows) +
      (d.count > (d.shown || 0) ? '<p class="note">' + d.count + "행 가운데 " +
        d.shown + "행만 보입니다.</p>" : "") + AT.command(d.command);
  }

  $("btn-tidy").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/tidy_preview", tidyValues());
      drawTidy(d);
      AT.message($("tidymsg"), "이대로 저장할 수 있습니다.", "ok");
      $("btn-tidy-save").disabled = false;
    } catch (e) {
      AT.message($("tidymsg"), AT.esc(e.message), "bad");
      $("btn-tidy-save").disabled = true;
    }
  });

  $("btn-tidy-save").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/tidy_save", tidyValues());
      drawTidy(d);
      AT.message($("tidymsg"), "저장했습니다: <b>" + AT.esc(d.saved) + "</b> (" +
                 d.count + "행)", "ok");
      $("btn-tidy-save").disabled = true;
    } catch (e) { AT.message($("tidymsg"), AT.esc(e.message), "bad"); }
  });

  $("btn-similar").addEventListener("click", async function () {
    try {
      const b = values();
      b.simcol = $("simcol").value; b.threshold = $("threshold").value;
      const d = await AT.call("/api/sheet/similar", b);
      $("simout").innerHTML = (d.count
          ? AT.table(["왜", "닮음", "어디", "값", "어디", "값"], d.rows,
                     [null, "num", null, null, null, null])
          : '<div class="empty">같은 곳으로 보이는 짝이 없습니다.</div>') +
        (d.count > d.shown ? '<p class="note">' + d.count + "개 가운데 " +
          d.shown + "개만 보입니다.</p>" : "") +
        (d.cut ? '<p class="note">너무 많아 도중에 멈췄습니다.</p>' : "") +
        AT.command(d.command);
      AT.message($("simmsg"), d.count
        ? "<b>" + d.count + "짝</b>이 같은 곳으로 보입니다. 합치지 않았습니다."
        : "같은 곳으로 보이는 짝이 없습니다.", d.count ? "ok" : "");
    } catch (e) { AT.message($("simmsg"), AT.esc(e.message), "bad"); }
  });

  $("btn-audit").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/audit", values());
      $("auditout").innerHTML = (d.count
          ? AT.table(["무엇", "열", "내용"], d.rows)
          : '<div class="empty">볼 만한 곳이 없습니다.</div>') +
        '<p class="note">본 것: ' + d.looked.map(AT.esc).join(" · ") +
        (d.skipped.length ? "<br>못 본 것: " + d.skipped.map(AT.esc).join("<br>") : "") +
        "<br>고치지는 않았습니다. 여기 없는 문제가 없다는 뜻은 아닙니다.</p>" +
        AT.command(d.command);
      AT.message($("auditmsg"), d.size + " · 볼 만한 곳 <b>" + d.count + "가지</b>",
                 d.count ? "bad" : "ok");
    } catch (e) { AT.message($("auditmsg"), AT.esc(e.message), "bad"); }
  });

  $("btn-outliers").addEventListener("click", async function () {
    try {
      const b = values();
      b.ocol = $("ocol").value; b.omethod = $("omethod").value;
      b.ofactor = $("ofactor").value;
      const d = await AT.call("/api/sheet/outliers", b);
      $("outout").innerHTML = (d.note
          ? '<div class="empty">' + AT.esc(d.note) + "</div>"
          : '<p class="note">' + AT.esc(d.how) + " · 가운데 " +
            AT.esc(d.middle) + " · 보통 범위 " + AT.esc(d.range) + "</p>" +
            (d.count
              ? AT.table(["행", "값", "어느 쪽"], d.rows, ["num", "num", null])
              : '<div class="empty">범위를 벗어난 값이 없습니다.</div>')) +
        AT.command(d.command);
      AT.message($("outmsg"), d.note ? AT.esc(d.note)
        : (d.count ? "숫자 " + d.counted + "개 가운데 <b>" + d.count +
                     "개</b>가 드뭅니다. 원본에서 확인하세요."
                   : "숫자 " + d.counted + "개, 드문 값 없음"),
        d.count ? "bad" : "ok");
    } catch (e) { AT.message($("outmsg"), AT.esc(e.message), "bad"); }
  });

  function labelValues() {
    const b = values();
    ["lblines", "lbcols", "lbrows", "lbwidth", "lbheight", "lbleft", "lbtop",
     "lbfont", "lbstart"].forEach(function (id) { b[id] = $(id).value; });
    b.lbguide = $("lbguide").checked;
    return b;
  }

  async function runLabels(save) {
    try {
      const d = await AT.call(save ? "/api/sheet/labels_save"
                                   : "/api/sheet/labels_preview", labelValues());
      $("lbout").innerHTML =
        (d.missing.length
          ? '<p class="note">표에 없는 자리표시자: ' +
            d.missing.map(AT.esc).join(", ") + " · 있는 열: " +
            d.headers.map(AT.esc).join(", ") + "</p>"
          : "") +
        AT.table(["라벨에 찍히는 것"], d.rows) + AT.command(d.command);
      AT.message($("lbmsg"), "<b>" + d.count + "장</b> · " + d.pages +
        "쪽 (한 쪽 " + d.per_page + "칸)" +
        (d.saved ? " · 만들었습니다: <b>" + AT.esc(d.saved) + "</b>"
                 : " · 아직 만들지 않았습니다."), "ok");
      $("btn-labels-save").disabled = !!save || d.count === 0;
    } catch (e) {
      AT.message($("lbmsg"), AT.esc(e.message), "bad");
      $("btn-labels-save").disabled = true;
    }
  }

  $("btn-labels").addEventListener("click", function () { runLabels(false); });
  $("btn-labels-save").addEventListener("click", function () { runLabels(true); });

  $("btn-gaps").addEventListener("click", async function () {
    try {
      const b = values();
      b.gcol = $("gcol").value; b.gevery = $("gevery").value;
      b.gstep = $("gstep").value; b.gholidays = $("gholidays").checked;
      const d = await AT.call("/api/sheet/gaps", b);
      $("gapout").innerHTML =
        '<p class="note">' + AT.esc(d.kind) + " " + AT.esc(d.first) + " ~ " +
        AT.esc(d.last) + " · 있어야 할 것 " + d.expected + "개 중 " +
        d.present + "개 있음" +
        (d.ignored ? " · 읽지 못한 칸 " + d.ignored + "개 (예: " +
                     d.samples.map(AT.esc).join(", ") + ")" : "") + "</p>" +
        (d.notes.length
          ? '<p class="note">' + d.notes.map(AT.esc).join("<br>") + "</p>" : "") +
        (d.count
          ? AT.table(["빠진 곳", "개수"], d.rows, [null, "num"])
          : '<div class="empty">빠진 것이 없습니다.</div>') +
        AT.command(d.command);
      AT.message($("gapmsg"), d.missing
        ? "<b>" + d.missing + "개</b>가 비었습니다 (" + d.count + "곳)"
        : "빠진 것이 없습니다.", d.missing ? "bad" : "ok");
    } catch (e) { AT.message($("gapmsg"), AT.esc(e.message), "bad"); }
  });

  function replaceValues() {
    const b = values();
    b.rfind = $("rfind").value; b.rto = $("rto").value;
    b.rcols = $("rcols").value; b.rexact = $("rexact").checked;
    b.rcase = $("rcase").checked;
    return b;
  }

  function drawReplace(d) {
    $("repout").innerHTML =
      '<p class="note">' + d.changed + "칸(" + d.changed_rows + "행) 바뀜" +
      (d.columns.length ? " · 바뀐 열: " + d.columns.map(AT.esc).join(", ") : "") +
      (d.skipped ? " · 숫자·날짜 칸 " + d.skipped +
        "개는 건드리지 않았습니다" : "") + "</p>" +
      AT.table(d.headers, d.rows) + AT.command(d.command);
  }

  $("btn-replace").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/replace_preview", replaceValues());
      drawReplace(d);
      AT.message($("repmsg"), d.changed
        ? "이대로 저장할 수 있습니다." : "찾지 못했습니다.", d.changed ? "ok" : "");
      $("btn-replace-save").disabled = d.changed === 0;
    } catch (e) {
      AT.message($("repmsg"), AT.esc(e.message), "bad");
      $("btn-replace-save").disabled = true;
    }
  });

  $("btn-replace-save").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/replace_save", replaceValues());
      drawReplace(d);
      AT.message($("repmsg"), "저장했습니다: <b>" + AT.esc(d.saved) + "</b>", "ok");
      $("btn-replace-save").disabled = true;
    } catch (e) { AT.message($("repmsg"), AT.esc(e.message), "bad"); }
  });

  async function runChart(save) {
    try {
      const b = values();
      b.clabel = $("clabel").value; b.cvalue = $("cvalue").value;
      b.cagg = $("cagg").value; b.ckind = $("ckind").value;
      b.ctop = $("ctop").value; b.cunit = $("cunit").value; b.csave = save;
      const d = await AT.call("/api/sheet/chart", b);
      $("chartout").innerHTML = d.svg +
        (d.whole > d.count ? '<p class="note">' + d.whole + "칸 가운데 " +
          d.count + "칸만 그렸습니다.</p>" : "") +
        AT.table(["이름", "값"], d.rows, [null, "num"]) + AT.command(d.command);
      AT.message($("chartmsg"), d.saved
        ? "저장했습니다: <b>" + AT.esc(d.saved) + "</b>"
        : "그렸습니다. 저장하려면 «.svg 로 저장»을 누르세요.", "ok");
    } catch (e) { AT.message($("chartmsg"), AT.esc(e.message), "bad"); }
  }

  $("btn-chart").addEventListener("click", function () { runChart(false); });
  $("btn-chart-save").addEventListener("click", function () { runChart(true); });

  async function runDday(save) {
    try {
      const b = values();
      b.ycol = $("ycol").value; b.yon = $("yon").value;
      b.ysort = $("ysort").checked; b.ysave = save;
      const d = await AT.call("/api/sheet/dday", b);
      $("ddayout").innerHTML =
        AT.table(["상태", "개수"], d.counts, [null, "num"]) +
        (d.failed.length ? "<h2>날짜로 못 읽은 칸</h2>" +
          AT.table(["행", "값"], d.failed, ["num", null]) : "") +
        AT.table(d.headers, d.rows) + AT.command(d.command);
      AT.message($("ddaymsg"), "기준일 " + AT.esc(d.today) +
        (d.saved ? " · 저장했습니다: <b>" + AT.esc(d.saved) + "</b>" : ""), "ok");
    } catch (e) { AT.message($("ddaymsg"), AT.esc(e.message), "bad"); }
  }

  $("btn-dday").addEventListener("click", function () { runDday(false); });
  $("btn-dday-save").addEventListener("click", function () { runDday(true); });

  function worktimeValues() {
    const b = values();
    b.wstart = $("wstart").value; b.wend = $("wend").value;
    b.wdate = $("wdate").value; b.wrest = $("wrest").value;
    return b;
  }

  function drawWorktime(d) {
    $("wtout").innerHTML =
      (d.unread.length
        ? "<h2>시각을 읽지 못한 행</h2>" +
          AT.table(["행", "까닭"], d.unread, ["num", null])
        : "") +
      (d.weeks.length
        ? "<h2>주별 실근무</h2>" +
          AT.table(["주 시작(월)", "시간"], d.weeks, [null, "num"])
        : "") +
      AT.table(d.headers, d.rows) +
      (d.count > (d.shown || 0) ? '<p class="note">' + d.count + "행 가운데 " +
        d.shown + "행만 보입니다.</p>" : "") + AT.command(d.command);
  }

  async function runWorktime(save) {
    try {
      const d = await AT.call(save ? "/api/sheet/worktime_save"
                                   : "/api/sheet/worktime_preview",
                              worktimeValues());
      drawWorktime(d);
      AT.message($("wtmsg"), "일한 날 <b>" + d.days + "일</b> · 실근무 " +
        d.worked + "시간 · 하루 평균 " + d.average + "시간" +
        (d.night ? " · 자정을 넘긴 날 " + d.night + "일" : "") +
        (d.saved ? " · 저장했습니다: <b>" + AT.esc(d.saved) + "</b>" : ""),
        "ok");
      $("btn-worktime-save").disabled = !!save;
    } catch (e) {
      AT.message($("wtmsg"), AT.esc(e.message), "bad");
      $("btn-worktime-save").disabled = true;
    }
  }

  $("btn-worktime").addEventListener("click", function () {
    runWorktime(false);
  });
  $("btn-worktime-save").addEventListener("click", function () {
    runWorktime(true);
  });

  function ageValues() {
    const b = values();
    b.acol = $("acol").value;
    b.aon = $("aon").value;
    b.agroup = $("agroup").checked;
    b.asex = $("asex").checked;
    return b;
  }

  function drawAge(d) {
    $("ageout").innerHTML =
      (d.failed.length
        ? "<h2>생년월일로 못 읽은 칸</h2>" +
          AT.table(["행", "값"], d.failed, ["num", null])
        : "") +
      AT.table(d.headers, d.rows) +
      (d.count > (d.shown || 0) ? '<p class="note">' + d.count + "행 가운데 " +
        d.shown + "행만 보입니다.</p>" : "") + AT.command(d.command);
  }

  async function runAge(save) {
    try {
      const d = await AT.call(save ? "/api/sheet/age_save"
                                   : "/api/sheet/age_preview", ageValues());
      drawAge(d);
      AT.message($("agemsg"), "나이를 읽은 칸 " + d.read + "개" +
        ($("asex").checked ? " · 성별 " + d.sexed + "개" : "") +
        (d.saved ? " · 저장했습니다: <b>" + AT.esc(d.saved) + "</b>"
                 : " · 이대로 저장할 수 있습니다."), "ok");
      $("btn-age-save").disabled = !!save;
    } catch (e) {
      AT.message($("agemsg"), AT.esc(e.message), "bad");
      $("btn-age-save").disabled = true;
    }
  }

  $("btn-age").addEventListener("click", function () { runAge(false); });
  $("btn-age-save").addEventListener("click", function () { runAge(true); });

  $("btn-forms").addEventListener("click", async function () {
    try {
      const b = values();
      b.ffolder = $("ffolder").value; b.fglob = $("fglob").value;
      const d = await AT.call("/api/sheet/forms", b);
      $("formsout").innerHTML =
        '<p class="note">기준으로 삼은 열 구성 (' + d.common + "개 파일이 같음): <b>" +
        d.standard.map(AT.esc).join(" | ") + "</b></p>" +
        AT.table(["파일", "시트", "행", "상태", "다른 점"], d.rows,
                 [null, null, "num", null, null]) + AT.command(d.command);
      AT.message($("formsmsg"), "파일 <b>" + d.count + "개</b> · 서식이 다른 것 " +
        d.odd + "개", d.odd ? "bad" : "ok");
    } catch (e) { AT.message($("formsmsg"), AT.esc(e.message), "bad"); }
  });

  function mailValues() {
    const b = values();
    b.mltemplate = $("mltemplate").value; b.mlsubject = $("mlsubject").value;
    b.mlto = $("mlto").value; b.mlattach = $("mlattach").value;
    return b;
  }

  function drawMail(d) {
    $("mailout").innerHTML =
      AT.table(["받는 사람", "제목", "첨부"], d.rows, [null, null, "num"]) +
      (d.problems.length
        ? "<h2>만들지 않은 행</h2>" +
          AT.table(["행", "까닭"], d.problems, ["num", null])
        : "") +
      (d.first ? "<h2>첫 건 본문</h2><pre>" + AT.esc(d.first) + "</pre>" : "") +
      AT.command(d.command);
  }

  async function runMail(save) {
    try {
      const d = await AT.call(save ? "/api/sheet/mail_make"
                                   : "/api/sheet/mail_preview", mailValues());
      drawMail(d);
      AT.message($("mailmsg"), "초안 <b>" + d.count + "건</b>" +
        (d.saved ? " · 만들었습니다: <b>" + AT.esc(d.saved) + "</b>"
                 : " · 아직 아무것도 만들지 않았습니다."), "ok");
      $("btn-mail-save").disabled = !!save || d.count === 0;
    } catch (e) {
      AT.message($("mailmsg"), AT.esc(e.message), "bad");
      $("btn-mail-save").disabled = true;
    }
  }

  $("btn-mail").addEventListener("click", function () { runMail(false); });
  $("btn-mail-save").addEventListener("click", function () { runMail(true); });

  function icsValues() {
    const b = values();
    b.ictitle = $("ictitle").value; b.icstart = $("icstart").value;
    b.icend = $("icend").value; b.icplace = $("icplace").value;
    b.icalarm = $("icalarm").value;
    return b;
  }

  function drawIcs(d) {
    $("icsout").innerHTML =
      AT.table(["일정", "시작", "끝", "장소"], d.rows) +
      (d.skipped.length
        ? "<h2>건너뛴 행</h2>" + AT.table(["행", "까닭"], d.skipped, ["num", null])
        : "") + AT.command(d.command);
  }

  async function runIcs(save) {
    try {
      const d = await AT.call(save ? "/api/sheet/ics_save"
                                   : "/api/sheet/ics_preview", icsValues());
      drawIcs(d);
      AT.message($("icsmsg"), "일정 <b>" + d.count + "개</b>" +
        (d.saved ? " · 만들었습니다: <b>" + AT.esc(d.saved) + "</b>"
                 : " · 아직 파일을 만들지 않았습니다."), "ok");
      $("btn-ics-save").disabled = !!save || d.count === 0;
    } catch (e) {
      AT.message($("icsmsg"), AT.esc(e.message), "bad");
      $("btn-ics-save").disabled = true;
    }
  }

  $("btn-ics").addEventListener("click", function () { runIcs(false); });
  $("btn-ics-save").addEventListener("click", function () { runIcs(true); });

  function vcardValues() {
    const b = values();
    b.vcname = $("vcname").value; b.vccompany = $("vccompany").value;
    b.vctitle = $("vctitle").value; b.vcmobile = $("vcmobile").value;
    b.vcphone = $("vcphone").value; b.vcemail = $("vcemail").value;
    return b;
  }

  function drawVcard(d) {
    $("vcout").innerHTML =
      AT.table(["이름", "회사", "직함", "번호", "메일"], d.rows) +
      (d.skipped.length
        ? "<h2>건너뛴 행</h2>" + AT.table(["행", "까닭"], d.skipped, ["num", null])
        : "") + AT.command(d.command);
  }

  async function runVcard(save) {
    try {
      const d = await AT.call(save ? "/api/sheet/vcard_save"
                                   : "/api/sheet/vcard_preview",
                              vcardValues());
      drawVcard(d);
      AT.message($("vcmsg"), "연락처 <b>" + d.count + "개</b>" +
        (d.saved ? " · 만들었습니다: <b>" + AT.esc(d.saved) + "</b>"
                 : " · 아직 파일을 만들지 않았습니다."), "ok");
      $("btn-vcard-save").disabled = !!save || d.count === 0;
    } catch (e) {
      AT.message($("vcmsg"), AT.esc(e.message), "bad");
      $("btn-vcard-save").disabled = true;
    }
  }

  $("btn-vcard").addEventListener("click", function () { runVcard(false); });
  $("btn-vcard-save").addEventListener("click", function () { runVcard(true); });

  function datesValues() {
    const b = values();
    b.dcol = $("dcol").value;
    b.dparts = [...document.querySelectorAll("#dparts input:checked")]
      .map(el => el.value);
    return b;
  }

  function drawDates(d) {
    $("datesout").innerHTML =
      (d.failed.length
        ? "<h2>날짜로 못 읽은 칸</h2>" +
          AT.table(["행", "값"], d.failed, ["num", null])
        : "") +
      AT.table(d.headers, d.rows) +
      (d.count > (d.shown || 0) ? '<p class="note">' + d.count + "행 가운데 " +
        d.shown + "행만 보입니다.</p>" : "") + AT.command(d.command);
  }

  $("btn-dates").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/dates_preview", datesValues());
      drawDates(d);
      AT.message($("datesmsg"), "이대로 저장할 수 있습니다.", "ok");
      $("btn-dates-save").disabled = false;
    } catch (e) {
      AT.message($("datesmsg"), AT.esc(e.message), "bad");
      $("btn-dates-save").disabled = true;
    }
  });

  $("btn-dates-save").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/dates_save", datesValues());
      drawDates(d);
      AT.message($("datesmsg"), "저장했습니다: <b>" + AT.esc(d.saved) + "</b>", "ok");
      $("btn-dates-save").disabled = true;
    } catch (e) { AT.message($("datesmsg"), AT.esc(e.message), "bad"); }
  });

  let mspecs = [];

  function drawMspecs() {
    $("mspecs").innerHTML = mspecs.length
      ? mspecs.map(function (s, i) {
          return '<button data-i="' + i + '" class="spec">' + AT.esc(s[0]) +
                 " \u2192 " + AT.esc(s[1]) + " \u00d7</button>";
        }).join(" ")
      : "아직 고른 것이 없습니다.";
    $("mspecs").querySelectorAll("button.spec").forEach(function (b) {
      b.addEventListener("click", function () {
        mspecs.splice(Number(b.dataset.i), 1);
        drawMspecs();
        $("btn-mask-save").disabled = true;
      });
    });
  }
  drawMspecs();

  $("btn-madd").addEventListener("click", function () {
    const column = $("mcol").value;
    if (!column) { AT.message($("maskmsg"), "먼저 파일을 열어 주세요.", "bad"); return; }
    if (!mspecs.some(s => s[0] === column && s[1] === $("mkind").value)) {
      mspecs.push([column, $("mkind").value]);
      drawMspecs();
      $("btn-mask-save").disabled = true;
    }
  });

  function maskValues() {
    const b = values();
    b.mspecs = mspecs;
    return b;
  }

  function drawMask(d) {
    $("maskout").innerHTML =
      AT.table(["열", "가림", "가린 값", "빈칸", "꼴을 몰라 통째로"], d.report,
               [null, null, "num", "num", "num"]) +
      (d.unclear.length
        ? "<h2>꼴을 몰라 통째로 가린 값</h2>" +
          AT.table(["열", "행", "원래 값"], d.unclear, [null, "num", null])
        : "") +
      AT.table(d.headers, d.rows) + AT.command(d.command);
  }

  $("btn-mask").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/mask_preview", maskValues());
      drawMask(d);
      AT.message($("maskmsg"), "이대로 저장할 수 있습니다.", "ok");
      $("btn-mask-save").disabled = false;
    } catch (e) {
      AT.message($("maskmsg"), AT.esc(e.message), "bad");
      $("btn-mask-save").disabled = true;
    }
  });

  $("btn-mask-save").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/mask_save", maskValues());
      drawMask(d);
      AT.message($("maskmsg"), "저장했습니다: <b>" + AT.esc(d.saved) + "</b>", "ok");
      $("btn-mask-save").disabled = true;
    } catch (e) { AT.message($("maskmsg"), AT.esc(e.message), "bad"); }
  });

  function collectValues() {
    return {
      cfolder: $("cfolder").value, cglob: $("cglob").value,
      cells: $("cells").value, csheet: $("csheet").value,
    };
  }

  function drawCollect(d) {
    $("collectout").innerHTML = AT.table(d.headers, d.rows) +
      (d.count > (d.shown || 0) ? '<p class="note">' + d.count + "개 가운데 " +
        d.shown + "개만 보입니다.</p>" : "") +
      (d.empty.length
        ? '<p class="note">뽑은 칸이 모두 빈 파일: ' +
          d.empty.map(AT.esc).join(", ") + " (양식이나 시트가 다릅니다)</p>"
        : "") +
      (d.skipped.length
        ? "<h2>못 읽은 것</h2>" + AT.table(["파일", "까닭"], d.skipped) : "") +
      AT.command(d.command);
  }

  $("btn-collect").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/collect_preview", collectValues());
      drawCollect(d);
      AT.remember("sheet", "cfolder", $("cfolder").value);
      AT.message($("collectmsg"), "파일 <b>" + d.count + "개</b>에서 칸 " +
                 d.cells + "개를 뽑았습니다.", "ok");
      $("btn-collect-save").disabled = d.count === 0;
    } catch (e) {
      AT.message($("collectmsg"), AT.esc(e.message), "bad");
      $("btn-collect-save").disabled = true;
    }
  });

  $("btn-collect-save").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/sheet/collect_save", collectValues());
      drawCollect(d);
      AT.message($("collectmsg"), "저장했습니다: <b>" + AT.esc(d.saved) + "</b>", "ok");
      $("btn-collect-save").disabled = true;
    } catch (e) { AT.message($("collectmsg"), AT.esc(e.message), "bad"); }
  });

  $("btn-search").addEventListener("click", async function () {
    try {
      const b = values();
      b.needle = $("needle").value; b.folder = $("folder").value;
      b.scolumn = $("scolumn").value; b.exact = $("exact").checked;
      b.case = $("case").checked;
      const d = await AT.call("/api/sheet/search", b);
      $("searchout").innerHTML = (d.count
          ? AT.table(["파일", "시트", "행", "열", "값", "그 행의 첫 열"], d.rows,
                     [null, null, "num", null, null, null])
          : '<div class="empty">찾지 못했습니다.</div>') +
        (d.count > d.shown ? '<p class="note">' + d.count + "건 가운데 " +
          d.shown + "건만 보입니다.</p>" : "") +
        (d.skipped.length
          ? "<h2>못 읽은 것</h2>" + AT.table(["파일", "까닭"], d.skipped) : "") +
        '<p class="note">' + AT.esc(d.note) + "</p>" + AT.command(d.command);
      AT.message($("searchmsg"), d.count
        ? "파일 " + d.files + "개에서 <b>" + d.count + "건</b>"
        : "파일 " + d.files + "개를 봤지만 찾지 못했습니다.", d.count ? "ok" : "");
    } catch (e) { AT.message($("searchmsg"), AT.esc(e.message), "bad"); }
  });

  $("btn-open").addEventListener("click", async function () {
    try {
      const data = await AT.call("/api/sheet/peek", values());
      opened = true;
      options($("sheet"), data.sheets, "첫 시트");
      options($("key"), data.headers, "고르지 않음");
      options($("fcol"), data.headers, "");
      options($("mcol"), data.headers, "");
      options($("simcol"), data.headers, "");
      options($("dcol"), data.headers, "");
      options($("acol"), data.headers, "");
      options($("wstart"), data.headers, "");
      options($("wend"), data.headers, "");
      options($("wdate"), data.headers, "쓰지 않음");
      options($("mlto"), data.headers, "");
      options($("mlattach"), data.headers, "쓰지 않음");
      options($("ictitle"), data.headers, "");
      options($("icstart"), data.headers, "");
      options($("icend"), data.headers, "쓰지 않음");
      options($("icplace"), data.headers, "쓰지 않음");
      options($("vcname"), data.headers, "");
      options($("vccompany"), data.headers, "쓰지 않음");
      options($("vctitle"), data.headers, "쓰지 않음");
      options($("vcmobile"), data.headers, "쓰지 않음");
      options($("vcphone"), data.headers, "쓰지 않음");
      options($("vcemail"), data.headers, "쓰지 않음");
      options($("ocol"), data.headers, "");
      options($("gcol"), data.headers, "");
      options($("clabel"), data.headers, "");
      options($("cvalue"), data.headers, "건수만 셈");
      options($("ycol"), data.headers, "");
      options($("dkey"), data.headers, "고르지 않음");
      options($("wcol"), data.headers, "고르지 않음");
      options($("scol"), data.headers, "정렬 안 함");
      options($("gvalues"), data.headers, "건수만 셈");
      options($("gcols"), data.headers, "쓰지 않음");
      $("cols").innerHTML = AT.table(
        ["열", "주로 들어 있는 것", "빈칸", "다른 값", "예시"],
        data.columns, [null, null, "num", "num", null]);
      $("rows").innerHTML = AT.table(data.headers, data.rows);
      AT.message($("msg"), "<b>" + data.count + "행</b>, " +
        data.headers.length + "열" + (data.sheet ? " · 시트 " +
        AT.esc(data.sheet) : "") + ". 아래에는 " + data.shown + "행만 보입니다.",
        "ok");
    } catch (e) { AT.message($("msg"), AT.esc(e.message), "bad"); }
  });

  $("btn-check").addEventListener("click", async function () {
    if (!opened) { AT.message($("checkmsg"), "먼저 파일을 열어 주세요.", "bad"); return; }
    try {
      const data = await AT.call("/api/sheet/check", values());
      $("issues").innerHTML = data.clean ? "" :
        AT.table(["종류", "열", "내용", "행 번호"], data.rows);
      AT.message($("checkmsg"), data.clean
        ? "걸리는 것이 없습니다."
        : "<b>" + data.rows.length + "가지</b>가 걸립니다.",
        data.clean ? "ok" : "bad");
    } catch (e) { AT.message($("checkmsg"), AT.esc(e.message), "bad"); }
  });

  $("btn-clean").addEventListener("click", async function () {
    try {
      const data = await AT.call("/api/sheet/clean_preview", values());
      $("cleanreport").innerHTML =
        AT.table(["한 일", "개수"], data.report, [null, "num"]) +
        "<p class=\\"note\\">정리한 뒤 " + data.count + "행. 아래는 " +
        data.shown + "행만.</p>" + AT.table(data.headers, data.rows);
      AT.message($("cleanmsg"), "이대로 저장할 수 있습니다.", "ok");
      $("btn-save").disabled = false;
    } catch (e) {
      AT.message($("cleanmsg"), AT.esc(e.message), "bad");
      $("btn-save").disabled = true;
    }
  });

  $("btn-save").addEventListener("click", async function () {
    try {
      const data = await AT.call("/api/sheet/clean_save", values());
      AT.message($("cleanmsg"), "저장했습니다: <b>" + AT.esc(data.saved) +
                 "</b> (" + data.count + "행)", "ok");
      $("btn-save").disabled = true;
    } catch (e) { AT.message($("cleanmsg"), AT.esc(e.message), "bad"); }
  });

  ["path", "sheet", "header_row"].forEach(function (id) {
    $(id).addEventListener("input", function () { $("btn-save").disabled = true; });
  });
})();
</script>
""" % {"dateparts": "".join(
    f'<label><input type="checkbox" value="{k}"'
    f'{" checked" if k in ("요일", "연월") else ""}> {k} ({v})</label>'
    for k, v in sheet.DATE_PARTS.items())}


def make() -> App:
    return App(
        key="sheet",
        name="엑셀 정리",
        summary="엑셀·CSV 를 열어 보고 점검하고 정리해 새 파일로 낸다",
        subtitle="열어 보기 → 점검 → 정리",
        body=lambda: BODY,
        actions={"peek": peek, "sheets": sheets, "check": check,
                 "search": search,
                 "compare": compare, "pick_preview": pick_preview,
                 "pick_save": pick_save, "sum_preview": sum_preview,
                 "sum_save": sum_save,
                 "tidy_preview": tidy_preview, "tidy_save": tidy_save,
                 "mask_preview": mask_preview, "mask_save": mask_save,
                 "collect_preview": collect_preview,
                 "collect_save": collect_save,
                 "dates_preview": dates_preview,
                 "dates_save": dates_save,
                 "age_preview": age_preview, "age_save": age_save,
                 "worktime_preview": worktime_preview,
                 "worktime_save": worktime_save,
                 "mail_preview": mail_preview, "mail_make": mail_make,
                 "forms": forms,
                 "ics_preview": ics_preview, "ics_save": ics_save,
                 "vcard_preview": vcard_preview, "vcard_save": vcard_save,
                 "similar": similar, "outliers": outliers,
                 "gaps": gaps,
                 "labels_preview": labels_preview,
                 "labels_save": labels_save,
                 "audit": audit, "chart": chart, "dday": dday,
                 "replace_preview": replace_preview,
                 "replace_save": replace_save,
                 "merge": merge,
                 "clean_preview": clean_preview, "clean_save": clean_save,
                 "format_preview": format_preview, "format_save": format_save},
        aliases=("엑셀", "표", "csv"),
        section="파일과 표",
    )
