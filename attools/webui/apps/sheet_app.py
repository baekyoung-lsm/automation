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

<section class="card">
  <h2>열마다 무엇이 들어 있나</h2>
  <div id="cols"><div class="empty">파일을 열면 여기에 나옵니다.</div></div>
</section>

<section class="card">
  <h2>내용 미리보기</h2>
  <div id="rows"><div class="empty">아직 없습니다.</div></div>
</section>

<section class="card">
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

<section class="card">
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

<section class="card">
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

<section class="card">
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

<section class="card">
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

<section class="card">
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

<section class="card">
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

<section class="card">
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

<section class="card">
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

<section class="card">
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
"""


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
                 "merge": merge,
                 "clean_preview": clean_preview, "clean_save": clean_save,
                 "format_preview": format_preview, "format_save": format_save},
        aliases=("엑셀", "표", "csv"),
        section="파일과 표",
    )
