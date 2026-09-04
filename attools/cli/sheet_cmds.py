"""at sheet - 엑셀·csv 실무."""

from __future__ import annotations

import sys
from pathlib import Path

from .. import devkit, files, hangul, jsonkit, names, report, sheet, text
from .common import _pad, _p, _cut, _grid


def _load(a, path: str | None = None) -> sheet.Table | None:
    try:
        return sheet.load(Path(path or a.file), sheet=getattr(a, "sheet", None),
                          header_row=getattr(a, "header_row", 1) - 1)
    except (sheet.SheetError, OSError) as e:
        _p(f"읽지 못했습니다: {e}")
        return None


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


RULE_KINDS = ("required", "unique", "type", "match", "range", "oneof",
              "format")


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

    if a.stats:
        _p("\n요약")
        rows = []
        for c in sheet.column_stats(t):
            if c.kind == "숫자":
                rows.append([c.name, "숫자", f"{c.total:,.10g}", f"{c.mean:,.2f}",
                             f"{c.median:,.10g}", "-"])
            else:
                top = f"{c.top} {c.top_ratio:.0%}" if c.top else "-"
                rows.append([c.name, c.kind, "-", "-", "-", top])
        _grid(["열", "타입", "합계", "평균", "중앙값", "최빈값"], rows, limit=a.width)
        _p("평균과 중앙값을 함께 봅니다. 한쪽만 보면 치우친 자료를 잘못 읽습니다.")

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


def cmd_sheet_melt(a) -> int:
    t = _load(a)
    if t is None:
        return 1
    try:
        result = sheet.melt(t, keep=a.keep, value_cols=a.value_col,
                            name=a.name, value=a.value, skip_blank=not a.keep_blank)
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    _grid(result.headers, [[sheet.to_text(v) for v in r]
                           for r in result.rows[:a.limit]])
    _p(f"\n{len(t.rows):,}행 x {t.width}열 -> {len(result.rows):,}행 x "
       f"{result.width}열")
    if not a.keep_blank:
        _p("빈 칸은 행으로 만들지 않았습니다 (--keep-blank 로 남길 수 있습니다).")
    if a.out:
        _p(f"저장: {sheet.save(result, Path(a.out))}")
    else:
        _p("-o 로 저장하면 그대로 피벗테이블에 넣을 수 있습니다.")
    return 0


def cmd_sheet_transpose(a) -> int:
    t = _load(a)
    if t is None:
        return 1
    try:
        result = sheet.transpose(t, header=a.name)
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    _grid(result.headers, [[sheet.to_text(v) for v in r]
                           for r in result.rows[:a.limit]])
    _p(f"\n{len(t.rows):,}행 x {t.width}열 -> {len(result.rows):,}행 x "
       f"{result.width}열")
    _p(f"첫 열({t.headers[0]})의 값이 새 머리글이 됩니다.")
    if a.out:
        _p(f"저장: {sheet.save(result, Path(a.out))}")
    return 0


def cmd_sheet_expand(a) -> int:
    t = _load(a)
    if t is None:
        return 1
    try:
        result, report = sheet.expand_column(
            t, a.col, sep=a.sep, regex=a.regex,
            names=[n.strip() for n in a.names.split(",")] if a.names else None,
            keep=a.keep, limit=a.max)
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    _grid(result.headers, [[sheet.to_text(v) for v in r]
                           for r in result.rows[:a.limit]])
    if len(result.rows) > a.limit:
        _p(f"  ... {len(result.rows) - a.limit}행 더")

    _p(f"\n'{a.col}' 열을 {report.widest}개로 갈랐습니다.")
    if report.uneven:
        spread = ", ".join(f"{n}조각 {c:,}행" for n, c in
                           sorted(report.pieces.items(), reverse=True) if n)
        _p(f"행마다 조각 수가 다릅니다: {spread}")
        _p("모자란 자리는 빈칸으로 뒀습니다. 잘라내면 값이 조용히 사라집니다.")
    if report.blanks:
        _p(f"원래 값이 비어 있던 행 {report.blanks:,}개")
    if a.out:
        _p(f"저장: {sheet.save(result, Path(a.out))}")
    return 0


def cmd_sheet_combine(a) -> int:
    t = _load(a)
    if t is None:
        return 1
    cols = [c.strip() for spec in a.cols for c in spec.split(",") if c.strip()]
    try:
        result = sheet.combine_columns(t, cols, into=a.into, sep=a.sep,
                                       keep=a.keep, skip_blank=not a.keep_blank)
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    _grid(result.headers, [[sheet.to_text(v) for v in r]
                           for r in result.rows[:a.limit]])
    if len(result.rows) > a.limit:
        _p(f"  ... {len(result.rows) - a.limit}행 더")
    _p(f"\n{len(cols)}개 열을 '{a.into}' 하나로 합쳤습니다.")
    if not a.keep_blank:
        _p("빈 칸은 건너뛰어 구분자가 겹치지 않게 했습니다.")
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


def cmd_sheet_join(a) -> int:
    left = _load(a, a.left)
    right = _load(a, a.right)
    if left is None or right is None:
        return 1

    try:
        merged, info = sheet.join(left, right, on=a.on, right_on=a.right_on,
                                  how=a.how, suffix=a.suffix)
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    how_names = {"left": "왼쪽 기준", "inner": "양쪽에 다 있는 것만", "outer": "양쪽 전부"}
    _p(f"{Path(a.left).name} {len(left.rows):,}행  +  "
       f"{Path(a.right).name} {len(right.rows):,}행"
       f"  ->  {len(merged.rows):,}행 x {merged.width}열  ({how_names[a.how]})")
    _p(f"  짝 찾음 {info.matched:,}  ·  오른쪽에 없음 {info.left_only:,}"
       + (f"  ·  왼쪽에 없음 {info.right_only:,}" if a.how == "outer" else ""))

    if info.multiplied:
        _p(f"\n주의: 오른쪽 키가 겹쳐서 {info.multiplied:,}행이 늘어났습니다.")
        _p(f"  겹친 키 {len(info.duplicate_keys)}개: "
           + ", ".join(info.duplicate_keys[:5])
           + (" ..." if len(info.duplicate_keys) > 5 else ""))
        _p("  VLOOKUP 은 첫 짝만 가져오지만 여기서는 짝마다 행을 만듭니다.")
    if info.blank_keys:
        _p(f"  오른쪽에서 키가 빈 행 {info.blank_keys:,}개는 뺐습니다.")
    if info.renamed:
        _p(f"  이름이 겹쳐 바꾼 열: "
           + ", ".join(f"{old} -> {new}" for old, new in info.renamed[:5]))

    _p("")
    _grid(merged.headers,
          [[sheet.to_text(v) for v in row] for row in merged.rows[:a.rows]],
          limit=a.width)
    if len(merged.rows) > a.rows:
        _p(f"  ... {len(merged.rows) - a.rows:,}행 더")

    if a.out:
        _p(f"\n저장: {sheet.save(merged, Path(a.out))}")
    else:
        _p("\n저장하려면 -o 로 출력 파일을 지정하세요.")
    return 0


def cmd_sheet_dedupe(a) -> int:
    t = _load(a)
    if t is None:
        return 1
    try:
        result, info = sheet.dedupe(t, a.key, keep=a.keep, by=a.by)
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    # 받침에 맞는 조사를 붙인다. 우리가 만든 hangul.josa 를 쓴다.
    subject = hangul.josa(a.by, "이/가") if a.by else ""
    how = {"first": "먼저 나온 것", "last": "나중에 나온 것",
           "max": f"{subject} 가장 큰 것", "min": f"{subject} 가장 작은 것"}[a.keep]
    _p(f"{', '.join(a.key)} 기준으로 {how}만 남깁니다")
    _p(f"  {len(t.rows):,}행 -> {info.kept:,}행  ·  지운 행 {info.removed:,}")
    if info.blank_keys:
        _p(f"  키가 빈 행 {info.blank_keys:,}개는 한 묶음으로 봤습니다.")

    if info.duplicate_keys:
        _p(f"\n겹친 키 {len(info.duplicate_keys)}개")
        for key, count in info.duplicate_keys[:a.limit]:
            _p(f"  {_pad(_cut(key, 24), 26)}{count}행")
        if len(info.duplicate_keys) > a.limit:
            _p(f"  ... {len(info.duplicate_keys) - a.limit}개 더")

    if not info.removed:
        _p("\n중복이 없습니다.")
        return 0

    if a.out:
        _p(f"\n저장: {sheet.save(result, Path(a.out))}")
    else:
        _p("\n저장하려면 -o 로 출력 파일을 지정하세요.")
    return 0


def cmd_sheet_fx(a) -> int:
    t = _load(a)
    if t is None:
        return 1

    reports: list[sheet.FxReport] = []
    for spec in a.add:
        name, sep, expression = spec.partition("=")
        if not sep or not name.strip() or not expression.strip():
            _p(f"'새열=수식' 형태로 적으세요: {spec}")
            _p("  예: --add '월급=연봉/12'  --add '등급=\"A\" if 연봉>5000만 else \"B\"'")
            return 1
        try:
            t, report = sheet.add_column(t, name.strip(), expression.strip(),
                                         digits=a.round)
        except sheet.SheetError as e:
            _p(f"{name.strip()}: {e}")
            return 1
        reports.append(report)

    for report in reports:
        line = f"{report.name} = {report.expression}  ·  계산 {report.computed:,}행"
        if report.failed:
            line += f"  ·  비운 행 {report.failed:,}"
        _p(line)
        for reason, count in report.reasons.most_common():
            _p(f"    {reason} {count:,}행"
               + (f" (예: {report.samples[0][0]}행)" if report.samples else ""))
    _p("")

    _grid(t.headers, [[sheet.to_text(v) for v in row] for row in t.rows[:a.rows]],
          limit=a.width)
    if len(t.rows) > a.rows:
        _p(f"  ... {len(t.rows) - a.rows:,}행 더")

    if a.out:
        _p(f"\n저장: {sheet.save(t, Path(a.out))}")
    else:
        _p("\n저장하려면 -o 로 출력 파일을 지정하세요.")
    return 0


def cmd_sheet_validate(a) -> int:
    import json as _json

    t = _load(a)
    if t is None:
        return 1

    rules: list[sheet.Rule] = []
    try:
        for kind in RULE_KINDS:
            for spec in getattr(a, kind) or []:
                rules.append(sheet.parse_rule(kind, spec))
        if a.rules:
            path = Path(a.rules)
            if not path.is_file():
                _p(f"규칙 파일이 없습니다: {path}")
                return 1
            for item in _json.loads(path.read_text(encoding="utf-8")):
                rules.append(sheet.Rule(item["kind"], item["column"],
                                        item.get("argument", "")))
    except (sheet.SheetError, KeyError, _json.JSONDecodeError) as e:
        _p(f"규칙을 읽지 못했습니다: {e}")
        return 1

    if not rules:
        _p("규칙을 하나 이상 주세요.")
        _p("  예: --required 이름 --unique 사번 --match '사번=^E\\d{3}$'")
        _p("      --range '연봉=0:' --type 입사일=날짜 --oneof 부서=영업,개발")
        _p("      --format 사업자등록번호=사업자번호 --format 연락처=휴대폰")
        return 1

    try:
        violations = sheet.validate_rules(t, rules)
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    _p(f"{Path(a.file).name}  {len(t.rows):,}행  ·  규칙 {len(rules)}개")
    if not violations:
        _p("모든 규칙을 통과했습니다.")
        return 0

    total = sum(v.count for v in violations)
    _p(f"어긴 것 {total:,}건  ·  규칙 {len(violations)}개\n")
    for v in violations:
        _p(f"[{v.rule.describe()}]  {v.count:,}건")
        _p(f"  해당 행: {', '.join(str(n) for n in v.rows[:a.limit])}"
           + (" ..." if v.count > len(v.rows) else ""))
        if v.samples:
            _p(f"  값 예시: {', '.join(_cut(x, 24) for x in v.samples)}")
        _p("")
    _p("행 번호는 헤더를 1행으로 센 엑셀 기준입니다.")
    return 1


def cmd_sheet_from_json(a) -> int:
    try:
        data = jsonkit.load(a.file)
    except jsonkit.JsonError as e:
        _p(str(e))
        return 1

    try:
        records = sheet.find_records(data, a.path)
        table, info = sheet.from_records(records, depth=a.depth)
    except (sheet.SheetError, jsonkit.JsonError) as e:
        _p(str(e))
        return 1

    where = f"'{a.path}'" if a.path else "가장 큰 객체 배열"
    _p(f"{Path(a.file).name} 의 {where}  ->  {info.rows:,}행 x {info.columns}열")
    if info.skipped:
        _p(f"  객체가 아니라 건너뛴 원소 {info.skipped:,}개")
    if info.max_depth:
        _p(f"  중첩된 객체는 '부모.자식' 으로 폈습니다 (깊이 {info.max_depth})")
    _p("")

    _grid(table.headers,
          [[sheet.to_text(v) for v in row] for row in table.rows[:a.rows]],
          limit=a.width)
    if len(table.rows) > a.rows:
        _p(f"  ... {len(table.rows) - a.rows:,}행 더")

    if a.out:
        _p(f"\n저장: {sheet.save(table, Path(a.out), sheet_name=a.path or 'Sheet1')}")
    else:
        _p("\n저장하려면 -o 로 csv 나 xlsx 를 지정하세요.")
    return 0


def cmd_sheet_to_json(a) -> int:
    import json as _json

    t = _load(a)
    if t is None:
        return 1

    records = sheet.to_records(t, nest=a.nest, skip_blank=not a.keep_blank,
                               parse_json=a.parse_json)
    if a.lines:
        text_out = "\n".join(_json.dumps(r, ensure_ascii=False) for r in records) + "\n"
    else:
        text_out = _json.dumps(records, ensure_ascii=False,
                               indent=None if a.compact else 2) + "\n"

    if a.out:
        target = Path(a.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text_out, encoding="utf-8")
        _p(f"{len(records):,}개 객체를 저장: {target}")
        if a.nest:
            _p("  '부모.자식' 열은 중첩 객체로 되돌렸습니다.")
        if not a.keep_blank:
            _p("  빈 칸은 키 자체를 넣지 않았습니다. (--keep-blank 로 null 로 둡니다)")
        return 0

    sys.stdout.write(text_out)
    return 0


def add_commands(sub) -> None:
    """sheet 하위 명령을 붙인다."""
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
    pk.add_argument("--stats", action="store_true",
                    help="숫자 열의 합계·평균·중앙값, 나머지 열의 최빈값")
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

    ml = common(sh.add_parser("melt", help="넓은 표를 긴 표로 (pivot 의 반대)"))
    ml.add_argument("file")
    ml.add_argument("--keep", action="append", required=True, metavar="열",
                    help="그대로 둘 열 (여러 번 쓸 수 있음)")
    ml.add_argument("--value-col", action="append", metavar="열",
                    help="펼 열을 직접 지정 (기본은 --keep 이 아닌 모든 열)")
    ml.add_argument("--name", default="항목", metavar="열이름")
    ml.add_argument("--value", default="값", metavar="열이름")
    ml.add_argument("--keep-blank", action="store_true", help="빈 칸도 행으로 남긴다")
    ml.add_argument("--limit", type=int, default=20)
    ml.add_argument("-o", "--out")
    ml.set_defaults(func=cmd_sheet_melt)

    tp = common(sh.add_parser("transpose", help="행과 열 바꾸기"))
    tp.add_argument("file")
    tp.add_argument("--name", default="항목", metavar="열이름",
                    help="새 표의 첫 열 이름")
    tp.add_argument("--limit", type=int, default=20)
    tp.add_argument("-o", "--out")
    tp.set_defaults(func=cmd_sheet_transpose)

    xp = common(sh.add_parser("expand", help="한 열을 구분자로 갈라 여러 열로"))
    xp.add_argument("file")
    xp.add_argument("--col", required=True, metavar="열", help="가를 열")
    xp.add_argument("--sep", default=",", metavar="구분자", help="기본은 쉼표")
    xp.add_argument("-e", "--regex", action="store_true", help="--sep 을 정규식으로")
    xp.add_argument("--names", metavar="이름,이름", help="새 열 이름")
    xp.add_argument("--keep", action="store_true", help="원래 열도 남긴다")
    xp.add_argument("--max", type=int, default=0, metavar="개",
                    help="이 개수까지만 가른다 (나머지는 마지막 칸에)")
    xp.add_argument("--limit", type=int, default=20)
    xp.add_argument("-o", "--out")
    xp.set_defaults(func=cmd_sheet_expand)

    cb = common(sh.add_parser("combine", help="여러 열을 한 열로 합치기 (expand 의 반대)"))
    cb.add_argument("file")
    cb.add_argument("--cols", action="append", required=True, metavar="열,열",
                    help="합칠 열 (쉼표로 여러 개, 여러 번 써도 된다)")
    cb.add_argument("--into", default="합침", metavar="열이름")
    cb.add_argument("--sep", default=" ", metavar="구분자")
    cb.add_argument("--keep", action="store_true", help="원래 열도 남긴다")
    cb.add_argument("--keep-blank", action="store_true",
                    help="빈 칸도 자리를 차지하게 둔다")
    cb.add_argument("--limit", type=int, default=20)
    cb.add_argument("-o", "--out")
    cb.set_defaults(func=cmd_sheet_combine)

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

    fj = sh.add_parser("from-json", help="JSON 배열을 표로 (API 응답 -> 엑셀)")
    fj.add_argument("file", help="'-' 이면 표준 입력")
    fj.add_argument("--path", default="", metavar="경로",
                    help="배열이 있는 자리 (예: data.users). 생략하면 알아서 찾는다")
    fj.add_argument("--depth", type=int, default=2, metavar="단계",
                    help="중첩 객체를 이만큼까지 펴고 그보다 깊으면 JSON 글자로 둔다")
    fj.add_argument("-o", "--out", metavar="파일")
    fj.add_argument("--rows", type=int, default=10, metavar="개")
    fj.add_argument("--width", type=int, default=18, metavar="칸")
    fj.set_defaults(func=cmd_sheet_from_json)

    tj = common(sh.add_parser("to-json", help="표를 JSON 배열로 (엑셀 -> API)"))
    tj.add_argument("file")
    tj.add_argument("-o", "--out", metavar="파일", help="생략하면 화면으로")
    tj.add_argument("--lines", action="store_true", help="JSON Lines 로")
    tj.add_argument("--compact", action="store_true", help="들여쓰기 없이")
    tj.add_argument("--nest", action="store_true",
                    help="'meta.부서' 열을 중첩 객체로 되돌린다")
    tj.add_argument("--keep-blank", action="store_true",
                    help="빈 칸도 null 로 넣는다 (기본은 키를 빼고 넣는다)")
    tj.add_argument("--parse-json", action="store_true",
                    help="[..] {..} 처럼 생긴 칸을 JSON 으로 되돌린다")
    tj.set_defaults(func=cmd_sheet_to_json)

    vd = common(sh.add_parser("validate", help="규칙으로 검증 (납품·수령 데이터)"))
    vd.add_argument("file")
    vd.add_argument("--required", action="append", metavar="열", help="빈 칸이 없어야")
    vd.add_argument("--unique", action="append", metavar="열", help="값이 겹치지 않아야")
    vd.add_argument("--type", action="append", metavar="열=종류",
                    help="숫자 · 정수 · 날짜 · 참거짓 · 문자")
    vd.add_argument("--match", action="append", metavar="열=정규식")
    vd.add_argument("--range", action="append", metavar="열=최소:최대",
                    help="예: '연봉=0:' 또는 '나이=18:65'")
    vd.add_argument("--oneof", action="append", metavar="열=값,값")
    vd.add_argument("--format", action="append", metavar="열=형식",
                    dest="format", help="사업자번호 · 휴대폰 · 전화번호 · 우편번호 · 이메일")
    vd.add_argument("--rules", metavar="파일", help="규칙을 적어 둔 JSON")
    vd.add_argument("--limit", type=int, default=20)
    vd.set_defaults(func=cmd_sheet_validate)

    fx = common(sh.add_parser("fx", help="수식으로 계산한 열 붙이기"))
    fx.add_argument("file")
    fx.add_argument("--add", action="append", required=True, metavar="새열=수식",
                    help="예: '월급=연봉/12'. 여러 번 주면 순서대로 계산한다")
    fx.add_argument("--round", type=int, default=None, metavar="자리",
                    help="숫자 결과를 이 자리에서 반올림")
    fx.add_argument("-o", "--out", metavar="파일")
    fx.add_argument("--rows", type=int, default=10, metavar="개")
    fx.add_argument("--width", type=int, default=16, metavar="칸")
    fx.set_defaults(func=cmd_sheet_fx)

    dd = common(sh.add_parser("dedupe", help="키가 같은 행 중 하나만 남기기"))
    dd.add_argument("file")
    dd.add_argument("-k", "--key", action="append", required=True, metavar="열")
    dd.add_argument("--keep", default="first",
                    choices=["first", "last", "max", "min"])
    dd.add_argument("--by", default="", metavar="열",
                    help="--keep max/min 일 때 기준 열 (예: 수정일)")
    dd.add_argument("-o", "--out", metavar="파일")
    dd.add_argument("--limit", type=int, default=15)
    dd.set_defaults(func=cmd_sheet_dedupe)

    jn = common(sh.add_parser("join", help="두 표를 키로 합치기 (VLOOKUP 대신)"))
    jn.add_argument("left", metavar="왼쪽파일")
    jn.add_argument("right", metavar="오른쪽파일")
    jn.add_argument("--on", required=True, metavar="열", help="맞출 키 열")
    jn.add_argument("--right-on", default="", metavar="열",
                    help="오른쪽 키 열 이름이 다를 때")
    jn.add_argument("--how", default="left", choices=["left", "inner", "outer"])
    jn.add_argument("--suffix", default="_2", metavar="접미사",
                    help="열 이름이 겹칠 때 오른쪽에 붙인다")
    jn.add_argument("-o", "--out", metavar="파일")
    jn.add_argument("--rows", type=int, default=10, metavar="개", dest="rows")
    jn.add_argument("--width", type=int, default=16, metavar="칸")
    jn.set_defaults(func=cmd_sheet_join)

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
