"""at sheet - 엑셀·csv 실무."""

from __future__ import annotations

import sys
from pathlib import Path

from .. import files, hangul, sheet, text
from ..code import devkit, jsonkit
from ..docs import mdkit, report
from ..write import names
from .common import _pad, _p, _cut, _grid, _width


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
        try:
            names = sheet.xlsx.sheet_names(path)
        except sheet.xlsx.XlsxError as e:
            _p(f"읽지 못했습니다: {e}")
            return 1
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


def cmd_sheet_row(a) -> int:
    """한 행을 세로로 본다. 열이 서른 개면 가로로는 못 읽는다."""
    t = _load(a)
    if t is None:
        return 1

    conditions = []
    try:
        for op in ("eq", "has"):
            for spec in getattr(a, op) or []:
                conditions.append(sheet.Condition.parse(op, spec))
        found = sheet.find_rows(t, conditions, number=a.at)
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    if a.at is None and not conditions:
        _p("몇 행인지(--at) 또는 찾을 조건(--eq, --has)을 주세요.")
        _p("  예: at sheet row 명단.xlsx --eq 사번=E2")
        return 1

    if not found:
        if a.at == 1:
            _p("1행은 머리글입니다. 자료는 2행부터입니다.")
        else:
            _p("맞는 행이 없습니다.")
        return 1

    _p(f"{Path(a.file).name}  자료 {len(t.rows):,}행 "
       f"(줄 번호는 엑셀에서 보이는 번호입니다)")
    width = max(_width(h) for h in t.headers)
    for line, row in found[:a.rows]:
        _p(f"\n{line}행")
        for name, value in zip(t.headers, row):
            shown = sheet.to_text(value)
            _p(f"  {_pad(name, width)}  {shown if shown.strip() else '(빈 칸)'}")
    if len(found) > a.rows:
        _p(f"\n... {len(found) - a.rows:,}행 더 걸렸습니다. -n 으로 늘리세요.")
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


def cmd_sheet_find(a) -> int:
    """여러 파일에서 값 찾기. 어느 파일 어느 시트 몇 행인지 알려 준다."""
    targets: list[Path] = []
    for name in a.files:
        path = Path(name)
        if path.is_dir():
            targets += [q for q in sorted(path.rglob("*"))
                        if q.is_file()
                        and q.suffix.lower() in (sheet.XLSX_SUFFIXES | sheet.CSV_SUFFIXES)
                        and not q.name.startswith("~$")]   # 엑셀이 만드는 임시 파일
        elif path.is_file():
            targets.append(path)
        else:
            _p(f"경로가 없습니다: {path}")
            return 1
    if not targets:
        _p("찾아볼 파일이 없습니다. (csv, tsv, xlsx)")
        return 1

    found, skipped = sheet.find_in_files(
        targets, a.needle, column=a.column, exact=a.exact,
        ignore_case=not a.case, header_row=a.header_row - 1)

    if found:
        _grid(["파일", "시트", "행", "열", "값", "그 행의 첫 열"],
              [[Path(h.path).name, h.sheet or "-", str(h.row), h.column,
                _cut(h.value, 30), _cut(h.context, 20)]
               for h in found[:a.limit]], limit=30)
        if len(found) > a.limit:
            _p(f"... {len(found) - a.limit}건 더 (--limit 로 조절)")
        _p(f"\n파일 {len({h.path for h in found})}개에서 {len(found)}건.")
    else:
        _p(f"'{a.needle}' 을(를) 찾지 못했습니다. (파일 {len(targets)}개를 봤습니다)")

    if skipped:
        _p(f"\n못 읽은 것 {len(skipped)}개")
        for name, why in skipped[:5]:
            _p(f"  {Path(name).name}: {_cut(why, 60)}")
        if len(skipped) > 5:
            _p(f"  ... {len(skipped) - 5}개 더")
    return 0 if found else 1


def cmd_sheet_book(a) -> int:
    """여러 파일을 한 엑셀의 여러 시트로 묶는다."""
    tables: dict = {}
    for name in a.files:
        table = _load(a, name)
        if table is None:
            return 1
        tables[Path(name).stem] = table

    if not a.out:
        _grid(["파일", "시트 이름", "행", "열"],
              [[Path(n).name, s_, f"{len(t.rows):,}", str(t.width)]
               for n, s_, t in zip(a.files, sheet.unique_sheet_names(tables),
                                   tables.values())], limit=40)
        _p("\n저장하려면 -o 로 xlsx 파일을 지정하세요.")
        return 0

    try:
        out = sheet.save_sheets(tables, Path(a.out))
    except sheet.SheetError as e:
        _p(str(e))
        return 1
    _p(f"저장: {out}  (시트 {len(tables)}개)")
    _p("파일마다 열지 않고 엑셀에서 탭으로 넘겨 봅니다. "
       "시트 이름이 겹치면 번호를 붙였습니다.")
    return 0


def cmd_sheet_sheets(a) -> int:
    """엑셀 한 파일 안의 시트를 한눈에."""
    try:
        found = sheet.describe_sheets(Path(a.file), header_row=a.header_row - 1)
    except (sheet.SheetError, OSError) as e:
        _p(f"읽지 못했습니다: {e}")
        return 1
    if not found:
        _p("시트가 없습니다.")
        return 1

    _p(f"{Path(a.file).name}  시트 {len(found)}개")
    _grid(["시트", "행", "열", "머리글"],
          [[i.name, f"{i.rows:,}", str(i.columns),
            _cut(", ".join(i.headers), 50) if i.headers else (i.error or "비어 있음")]
           for i in found], limit=50)
    return 0


def cmd_sheet_format(a) -> int:
    """열마다 표기를 통일한다. 못 알아본 값은 손대지 않고 알려 준다."""
    t = _load(a)
    if t is None:
        return 1

    wanted: list[tuple[str, str]] = []
    for kind, names_ in (("전화", a.phone), ("사업자번호", a.bizno),
                         ("우편번호", a.post), ("날짜", a.date),
                         ("숫자", a.number)):
        for name in names_ or []:
            wanted.append((name, kind))
    if not wanted:
        _p("어느 열을 어떤 형식으로 맞출지 골라 주세요.")
        _p("  예: at sheet format 명단.xlsx --phone 연락처 --bizno 사업자등록번호")
        _p(f"  쓸 수 있는 형식: {', '.join(sheet.COLUMN_FORMATS)}")
        return 1

    reports = []
    for name, kind in wanted:
        try:
            t, rep = sheet.format_column(t, name, kind)
        except sheet.SheetError as e:
            _p(str(e))
            return 1
        reports.append(rep)

    _p(f"{Path(a.file).name}  {len(t.rows):,}행")
    _grid(["열", "형식", "바꾼 값", "이미 맞음", "빈칸", "못 알아봄"],
          [[r.column, r.kind, f"{r.changed:,}", f"{r.already:,}",
            f"{r.blank:,}", f"{len(r.failed):,}"] for r in reports], limit=40)

    bad = False
    for rep in reports:
        if rep.failed:
            bad = True
            _p(f"\n{rep.column}: 규칙을 몰라 그대로 둔 값 {len(rep.failed):,}개")
            for line, value in rep.failed[:a.limit]:
                _p(f"  {line}행  {_cut(value, 40)}")
            if len(rep.failed) > a.limit:
                _p(f"  ... {len(rep.failed) - a.limit:,}개 더")
        if rep.invalid:
            bad = True
            _p(f"\n{rep.column}: 꼴은 맞췄지만 검증에 걸린 값 {len(rep.invalid):,}개")
            for line, value in rep.invalid[:a.limit]:
                _p(f"  {line}행  {value}")

    if a.out:
        _p(f"\n저장: {sheet.save(t, Path(a.out))}")
    else:
        _p("\n저장하려면 -o 로 출력 파일을 지정하세요. (원본은 건드리지 않습니다)")
    return 1 if bad and a.strict else 0


def cmd_sheet_mask(a) -> int:
    """개인정보를 가린 사본을 만든다. 밖으로 내보낼 파일을 만드는 명령이다."""
    t = _load(a)
    if t is None:
        return 1

    wanted: list[tuple[str, str]] = []
    for kind, names_ in (("이름", a.name), ("전화", a.phone), ("이메일", a.email),
                         ("주민번호", a.rrn), ("계좌", a.account),
                         ("주소", a.address)):
        for column in names_ or []:
            wanted.append((column, kind))
    if not wanted:
        _p("어느 열을 어떻게 가릴지 골라 주세요.")
        _p("  예: at sheet mask 명단.xlsx --name 이름 --phone 연락처 -o 공유본.xlsx")
        _p(f"  쓸 수 있는 가림: {', '.join(sheet.MASK_KINDS)}")
        return 1

    reports = []
    for column, kind in wanted:
        try:
            t, rep = sheet.mask_column(t, column, kind)
        except sheet.SheetError as e:
            _p(str(e))
            return 1
        reports.append(rep)

    _p(f"{Path(a.file).name}  {len(t.rows):,}행")
    _grid(["열", "가림", "가린 값", "빈칸", "꼴을 몰라 통째로"],
          [[r.column, f"{r.kind} ({sheet.MASK_KINDS[r.kind][1]})",
            f"{r.masked:,}", f"{r.blank:,}", f"{len(r.unclear):,}"]
           for r in reports], limit=40)

    unclear = False
    for rep in reports:
        if rep.unclear:
            unclear = True
            _p(f"\n{rep.column}: 꼴을 몰라 통째로 가린 값 {len(rep.unclear):,}개")
            _p("  (새는 것보다 낫다고 보고 가렸습니다. 원본에서 확인하세요)")
            for line, value in rep.unclear[:a.limit]:
                _p(f"  {line}행  {_cut(value, 40)}")
            if len(rep.unclear) > a.limit:
                _p(f"  ... {len(rep.unclear) - a.limit:,}개 더")

    if a.out:
        _p(f"\n저장: {sheet.save(t, Path(a.out))}")
    else:
        _p("\n저장하려면 -o 로 출력 파일을 지정하세요. (원본은 건드리지 않습니다)")
    return 1 if unclear and a.strict else 0


def cmd_sheet_audit(a) -> int:
    """받은 표를 한 번에 훑는다. 무엇부터 봐야 하는지 알려 준다."""
    t = _load(a)
    if t is None:
        return 1
    rep = sheet.audit(t)

    name = Path(a.file).name + (f"[{t.sheet}]" if t.sheet else "")
    _p(f"{name}  {rep.rows:,}행 x {rep.columns}열")

    if not rep.notes:
        _p("\n볼 만한 곳이 없습니다.")
    else:
        _p(f"\n볼 만한 곳 {len(rep.notes)}가지")
        _grid(["무엇", "열", "내용"],
              [[n.kind, n.column or "-", _cut(n.detail, 52)] for n in rep.notes],
              limit=56)

    _p("\n본 것: " + " · ".join(rep.looked))
    for line in rep.skipped:
        _p(f"  못 본 것 - {line}")
    _p("  고치지는 않았습니다. 여기 없는 문제가 없다는 뜻은 아닙니다.")
    return 1 if rep.notes and a.strict else 0


def cmd_sheet_outliers(a) -> int:
    """숫자 열에서 드문 값을 찾는다. 지우지 않고 어디인지만 알려 준다."""
    t = _load(a)
    if t is None:
        return 1
    try:
        rep = sheet.find_outliers(t, a.column, method=a.method, factor=a.factor)
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    _p(f"{rep.column}  숫자로 읽은 칸 {rep.counted:,}개  "
       f"({sheet.OUTLIER_METHODS[rep.method]})")
    if rep.note:
        _p(f"  {rep.note}")
        return 0

    middle = "중앙값" if rep.method == "iqr" else "평균"
    _p(f"  {middle} {sheet.to_text(round(rep.middle, 2))}  ·  "
       f"보통 범위 {sheet.to_text(round(rep.low, 2))} ~ "
       f"{sheet.to_text(round(rep.high, 2))}  (배수 {a.factor:g})")

    if not rep.found:
        _p("\n범위를 벗어난 값이 없습니다.")
        return 0

    _p(f"\n드문 값 {len(rep.found):,}개")
    # 정수인 값은 소수점을 붙이지 않는다. 100000.0 은 읽기 나쁘다
    def _shown(value: float) -> str:
        return f"{int(value):,}" if float(value).is_integer() else f"{value:,.2f}"

    _grid(["행", "값", "어느 쪽"],
          [[str(o.row), _shown(o.value), o.side]
           for o in rep.found[:a.limit]], limit=24)
    if len(rep.found) > a.limit:
        _p(f"  ... {len(rep.found) - a.limit:,}개 더")
    _p("\n드문 값이 곧 틀린 값은 아닙니다. 원본에서 확인하세요.")
    return 1 if a.strict else 0


def cmd_sheet_replace(a) -> int:
    """표 안의 값을 찾아 바꾼다. 원본은 그대로 두고 새 파일로 낸다."""
    t = _load(a)
    if t is None:
        return 1
    try:
        result, rep = sheet.replace_values(
            t, a.find, a.to, columns=a.column or None, exact=a.exact,
            ignore_case=a.ignore_case)
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    where = ", ".join(a.column) if a.column else "모든 열"
    if not rep.changed:
        _p(f"'{a.find}' 를 찾지 못했습니다. ({where})")
        if rep.skipped_typed:
            _p(f"  숫자·날짜 칸 {rep.skipped_typed:,}개에는 있었지만 "
               "건드리지 않았습니다.")
        return 1

    _p(f"{where}  {rep.changed:,}칸 ({rep.rows:,}행)에서 "
       f"'{a.find}' -> '{a.to}'")
    _p(f"  바뀐 열: {', '.join(rep.columns)}")
    if rep.skipped_typed:
        _p(f"  숫자·날짜 칸 {rep.skipped_typed:,}개는 건드리지 않았습니다 "
           "(글자로 바뀌면 합계가 어긋납니다)")
    return _sheet_result(a, result, "바꾼 뒤")


def cmd_sheet_dates(a) -> int:
    """날짜 열에서 요일·월·분기 열을 만든다. 피벗 돌리기 전에 하는 일."""
    t = _load(a)
    if t is None:
        return 1
    try:
        result, failed = sheet.add_date_parts(t, a.column, a.add or [])
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    if failed:
        _p(f"날짜로 못 읽은 칸 {len(failed):,}개 - 비워 두었습니다")
        for line, value in failed[:a.limit]:
            _p(f"  {line}행  {_cut(value, 40)}")
        if len(failed) > a.limit:
            _p(f"  ... {len(failed) - a.limit:,}개 더")
        _p("")
    return _sheet_result(a, result, f"{a.column} -> " + ", ".join(a.add))


def cmd_sheet_to_sql(a) -> int:
    """표를 INSERT 문으로. 엑셀로 받은 자료를 개발 DB 에 넣을 때."""
    t = _load(a)
    if t is None:
        return 1
    try:
        body = sheet.to_sql(t, a.table, dialect=a.dialect, batch=a.batch,
                            create=a.create)
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    if a.out:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")
        _p(f"저장: {out}  ({len(t.rows):,}행, {a.dialect})")
    else:
        _p(body)

    _p(f"빈 칸은 NULL 로 넣었습니다. ({a.dialect} 따옴표 규칙)")
    if a.create:
        _p("CREATE TABLE 의 타입은 값에서 짐작한 것입니다. 스키마를 확인하세요.")
    return 0


def cmd_sheet_from_docx(a) -> int:
    """워드 문서 안의 표를 엑셀·csv 로. 손으로 다시 치지 않게."""
    path = Path(a.file)
    if not path.is_file():
        _p(f"파일이 없습니다: {path}")
        return 1
    try:
        tables = sheet.tables_from_docx(path)
    except sheet.SheetError as e:
        _p(f"읽지 못했습니다: {e}")
        return 1

    if not tables:
        _p("표가 없습니다. (글만 있는 문서라면 at doc from-docx 로 옮기세요)")
        return 1

    _p(f"{path.name}  표 {len(tables)}개")
    _grid(["번호", "행", "열", "머리글"],
          [[str(i), f"{len(t.rows):,}", str(t.width),
            _cut(", ".join(t.headers), 40)]
           for i, t in enumerate(tables, 1)], limit=40)

    if a.number is not None:
        if not 1 <= a.number <= len(tables):
            _p(f"\n{a.number}번 표가 없습니다. 1 부터 {len(tables)} 까지입니다.")
            return 1
        picked = [tables[a.number - 1]]
    else:
        picked = tables

    if not a.out:
        first = picked[0]
        _p(f"\n{first.sheet}")
        _grid(first.headers,
              [[sheet.to_text(v) for v in r] for r in first.rows[:a.rows]],
              limit=a.width)
        if len(first.rows) > a.rows:
            _p(f"  ... {len(first.rows) - a.rows:,}행 더")
        _p("\n저장하려면 -o 로 출력 파일을 지정하세요. "
           "(표를 하나만 내려면 --table 번호)")
        return 0

    out = Path(a.out)
    if len(picked) == 1:
        _p(f"\n저장: {sheet.save(picked[0], out)}")
    elif out.suffix.lower() in sheet.XLSX_SUFFIXES:
        saved = sheet.save_sheets({t.sheet: t for t in picked}, out)
        _p(f"\n저장: {saved}  (시트 {len(picked)}개)")
    else:
        _p("\n표가 여럿입니다. xlsx 로 저장하면 시트로 나눠 담습니다. "
           "csv 로 내려면 --table 로 하나를 고르세요.")
        return 1
    return 0


def cmd_sheet_from_md(a) -> int:
    """마크다운 문서 안의 표를 엑셀·csv 로. 문서에 붙은 표로 계산할 때."""
    path = Path(a.file)
    if not path.is_file():
        _p(f"파일이 없습니다: {path}")
        return 1
    try:
        body = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        _p(f"읽지 못했습니다: {e}")
        return 1

    blocks = mdkit.find_tables(body)
    if not blocks:
        _p("표가 없습니다. (머리글 + --- 구분줄이 있어야 표로 봅니다)")
        return 1

    tables = []
    for order, block in enumerate(blocks, 1):
        grid = [list(block.header)] + [list(r) for r in block.rows]
        try:
            table = sheet.table_from_grid(
                [[sheet.parse_value(c) for c in row] for row in grid],
                header_row=0, source=str(path), sheet_name=f"표{order}",
                label=str(path))
        except sheet.SheetError as e:
            _p(f"{order}번 표를 읽지 못했습니다: {e}")
            return 1
        tables.append((block, table))

    _p(f"{path.name}  표 {len(tables)}개")
    _grid(["번호", "줄", "행", "열", "머리글"],
          [[str(i), f"{b.start}-{b.end}", f"{len(t.rows):,}", str(t.width),
            _cut(", ".join(t.headers), 34)]
           for i, (b, t) in enumerate(tables, 1)], limit=40)

    if a.number is not None:
        if not 1 <= a.number <= len(tables):
            _p(f"\n{a.number}번 표가 없습니다. 1 부터 {len(tables)} 까지입니다.")
            return 1
        picked = [tables[a.number - 1][1]]
    else:
        picked = [t for _b, t in tables]

    if not a.out:
        first = picked[0]
        _p(f"\n{first.sheet}")
        _grid(first.headers,
              [[sheet.to_text(v) for v in r] for r in first.rows[:a.rows]],
              limit=a.width)
        if len(first.rows) > a.rows:
            _p(f"  ... {len(first.rows) - a.rows:,}행 더")
        _p("\n저장하려면 -o 로 출력 파일을 지정하세요. "
           "(표를 하나만 내려면 --table 번호)")
        return 0

    out = Path(a.out)
    if len(picked) == 1:
        _p(f"\n저장: {sheet.save(picked[0], out)}")
    elif out.suffix.lower() in sheet.XLSX_SUFFIXES:
        saved = sheet.save_sheets({t.sheet: t for t in picked}, out)
        _p(f"\n저장: {saved}  (시트 {len(picked)}개)")
    else:
        _p("\n표가 여럿입니다. xlsx 로 저장하면 시트로 나눠 담습니다. "
           "csv 로 내려면 --table 로 하나를 고르세요.")
        return 1
    return 0


def cmd_sheet_collect(a) -> int:
    """같은 양식으로 받은 파일들에서 같은 칸만 뽑아 한 표로 (취합)."""
    targets: list[Path] = []
    for name in a.paths:
        path = Path(name)
        if path.is_dir():
            targets += [q for q in sorted(path.rglob(a.glob or "*"))
                        if q.is_file() and q.suffix.lower() in
                        (sheet.XLSX_SUFFIXES | sheet.CSV_SUFFIXES)]
        else:
            targets.append(path)
    if not targets:
        _p("셀 파일을 찾지 못했습니다. 폴더 안에 xlsx·csv 가 있는지 보세요.")
        return 1

    try:
        specs = [sheet.parse_cell(spec) for spec in a.cell]
        table, skipped = sheet.collect_cells(targets, specs, sheet=a.sheet)
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    _p(f"파일 {len(table.rows):,}개에서 칸 {len(specs)}개를 뽑았습니다.")
    _grid(table.headers,
          [[sheet.to_text(v) if sheet.to_text(v).strip() else "(빈 칸)" for v in r]
           for r in table.rows[:a.rows]], limit=a.width)
    if len(table.rows) > a.rows:
        _p(f"  ... {len(table.rows) - a.rows:,}개 더")

    empty = [r[0] for r in table.rows if all(v is None or v == "" for v in r[1:])]
    if empty:
        _p(f"\n뽑은 칸이 모두 빈 파일 {len(empty):,}개 - 양식이 다르거나 시트가 다릅니다")
        for name in empty[:a.limit]:
            _p(f"  {_cut(name, 50)}")
        _p("  --sheet 로 시트 이름을 맞춰 보세요.")

    if skipped:
        _p(f"\n못 읽은 것 {len(skipped):,}개")
        for name, why in skipped[:a.limit]:
            _p(f"  {_cut(Path(name).name, 30)}  {why}")

    if a.out:
        _p(f"\n저장: {sheet.save(table, Path(a.out))}")
    else:
        _p("\n저장하려면 -o 로 출력 파일을 지정하세요.")
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
    # 한 파일 안의 두 시트를 견주는 일이 잦다 (8월 탭 vs 9월 탭)
    second = a.after or a.before
    if a.after is None and not a.other_sheet:
        _p("견줄 파일을 하나 더 주거나, 같은 파일의 다른 시트를 "
           "--other-sheet 로 골라 주세요.")
        return 1

    before = _load(a, a.before)
    if before is None:
        return 1
    try:
        after = sheet.load(Path(second),
                           sheet=a.other_sheet or getattr(a, "sheet", None),
                           header_row=a.header_row - 1)
    except (sheet.SheetError, OSError) as e:
        _p(f"읽지 못했습니다: {e}")
        return 1

    left = f"{Path(a.before).name}" + (f"[{before.sheet}]" if before.sheet else "")
    right = f"{Path(second).name}" + (f"[{after.sheet}]" if after.sheet else "")
    _p(f"{left}  ->  {right}")

    if a.columns:
        cd = sheet.column_diff(before, after)
        if cd.empty:
            _p("열 구조가 같습니다.")
            return 0
        if cd.added:
            _p(f"새로 생긴 열 {len(cd.added)}개: {', '.join(cd.added)}")
        if cd.removed:
            _p(f"사라진 열 {len(cd.removed)}개: {', '.join(cd.removed)}")
        for name, old_at, new_at in cd.moved:
            _p(f"자리 바뀜  {name}: {old_at}번째 -> {new_at}번째")
        for name, old_kind, new_kind in cd.retyped:
            _p(f"타입 바뀜  {name}: {old_kind} -> {new_kind}")
        _p("\n열 이름이 같으면 같은 열로 봅니다. 이름만 바꾼 열은 "
           "'사라짐 + 새로 생김' 으로 나옵니다.")
        return 1

    if not a.key:
        _p("--key 로 행을 짝지을 열을 주세요. 열 구조만 보려면 --columns 를 쓰세요.")
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

    if a.out:
        rows: list[list] = []
        for row in d.added:
            rows.append(["추가", sheet.to_text(row[key_i]), "", "", ""])
        bkey = before.index_of(a.key)
        for row in d.removed:
            rows.append(["삭제", sheet.to_text(row[bkey]), "", "", ""])
        for k, col, b, x in d.changed:
            rows.append(["바뀜", k, col, b, x])
        table = sheet.Table(["무엇", a.key, "열", "이전", "이후"], rows)
        _p(f"\n저장: {sheet.save(table, Path(a.out))}  ({len(rows):,}건)")
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


def cmd_sheet_rename(a) -> int:
    import json as _json

    t = _load(a)
    if t is None:
        return 1

    mapping: dict[str, str] = {}
    if a.map_file:
        path = Path(a.map_file)
        if not path.is_file():
            _p(f"매핑 파일이 없습니다: {path}")
            return 1
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
        except _json.JSONDecodeError as e:
            _p(f"매핑 파일을 읽지 못했습니다: {e}")
            return 1
        if not isinstance(data, dict):
            _p("매핑 파일은 {\"옛이름\": \"새이름\"} 꼴이어야 합니다.")
            return 1
        mapping.update({str(k): str(v) for k, v in data.items()})

    for spec in a.map or []:
        old, sep, new = spec.partition("=")
        if not sep:
            _p(f"'옛이름=새이름' 꼴로 적어 주세요: {spec}")
            return 1
        mapping[old.strip()] = new.strip()

    if not mapping and not a.strip:
        _p("바꿀 이름을 주세요. 예: --map '수량=개수' --map '금액=총액'")
        _p("또는 --strip 만 주면 열 이름의 앞뒤 공백을 정리합니다.")
        return 1

    result, missing = sheet.rename_columns(t, mapping, strip=a.strip)
    changed = [(a1, b1) for a1, b1 in zip(t.headers, result.headers) if a1 != b1]

    if changed:
        _grid(["전", "후"], [[a1, b1] for a1, b1 in changed])
    else:
        _p("바뀐 열 이름이 없습니다.")
    if missing:
        _p(f"\n표에 없는 이름 {len(missing)}개: {', '.join(missing)}")
        _p("매핑이 낡았거나 파일이 다릅니다. 조용히 넘기지 않습니다.")

    if a.out:
        _p(f"\n저장: {sheet.save(result, Path(a.out))}")
    elif changed:
        _p("\n저장하려면 -o 로 출력 파일을 지정하세요.")
    return 1 if missing else 0


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
        for op in ("eq", "ne", "gt", "gte", "lt", "lte", "has",
                   "empty", "filled"):
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
             "has": "포함", "empty": "빈 칸", "filled": "값 있음"}
    joined = (" 또는 " if a.any else " 그리고 ").join(
        f"{c.column} {words[c.op]} {c.value}".rstrip() for c in conditions)
    return _sheet_result(a, result, f"{len(t.rows):,}행 중  {joined}  ->")


def cmd_sheet_sort(a) -> int:
    t = _load(a)
    if t is None:
        return 1
    columns: list[str] = []
    flags: list[bool] = []
    for spec in a.by:
        name = spec.strip()
        down = a.desc
        if name.startswith("-"):             # --by=-연봉 은 그 열만 내림차순
            name, down = name[1:].strip(), True
        elif name.startswith("+"):
            name, down = name[1:].strip(), False
        elif ":" in name:                    # --by 연봉:내림 (앞의 - 는 argparse 가 먹는다)
            head, _, mark = name.rpartition(":")
            if mark.strip() in ("desc", "내림", "역순"):
                name, down = head.strip(), True
            elif mark.strip() in ("asc", "오름"):
                name, down = head.strip(), False
        columns.append(name)
        flags.append(down)

    try:
        result = sheet.sort_rows(t, columns, descending=a.desc, order=flags)
    except sheet.SheetError as e:
        _p(str(e))
        return 1
    shown = ", ".join(f"{name}{' 내림' if down else ' 오름'}"
                      for name, down in zip(columns, flags))
    return _sheet_result(a, result, f"{shown} 정렬")


def cmd_sheet_filldown(a) -> int:
    t = _load(a)
    if t is None:
        return 1
    try:
        result, filled = sheet.fill_down(t, a.col or None)
    except sheet.SheetError as e:
        _p(str(e))
        return 1
    where = ", ".join(a.col) if a.col else "모든 열"
    if not filled:
        _p("채울 빈 칸이 없습니다. 이미 값이 다 들어 있습니다.")
    return _sheet_result(a, result, f"{where}  빈 칸 {filled:,}개 채움")


def cmd_sheet_total(a) -> int:
    t = _load(a)
    if t is None:
        return 1
    try:
        result, counted = sheet.with_total(t, a.col or None, kind=a.kind,
                                           label=a.label or "")
    except sheet.SheetError as e:
        _p(str(e))
        return 1
    if not counted:
        _p("셈할 숫자 열이 없습니다. -c 로 열을 지정하거나 at sheet clean 으로 "
           "숫자를 먼저 정리하세요.")
        return 1
    return _sheet_result(a, result,
                         f"{sheet.TOTAL_KINDS[a.kind]} 줄 추가 ({', '.join(counted)})")


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

    if a.sheets:
        target = Path(a.sheets)
        _p(f"{len(t.rows):,}행 -> 시트 {len(pieces)}개  ({target})")
        for name, part in pieces.items():
            _p(f"  {name.replace(source.stem + '-', '')}  {len(part.rows):,}행")
        if not a.apply:
            _p("\n실제로 저장하려면 --apply 를 붙이세요.")
            return 0
        try:
            saved = sheet.save_sheets(
                {name.replace(f"{source.stem}-", "") or "전체": part
                 for name, part in pieces.items()}, target)
        except sheet.SheetError as e:
            _p(str(e))
            return 1
        _p(f"\n저장: {saved}")
        _p("시트 이름은 엑셀 규칙에 맞춰 다듬습니다(31자, : \\ / ? * [ ] 금지).")
        return 0

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


def cmd_sheet_unbook(a) -> int:
    """엑셀 한 파일의 시트들을 파일로 나눈다 (at sheet book 의 반대)."""
    source = Path(a.file)
    if not source.is_file():
        _p(f"파일이 없습니다: {source}")
        return 1
    if source.suffix.lower() not in sheet.XLSX_SUFFIXES:
        _p(f"엑셀 파일이 아닙니다: {source.suffix or '확장자 없음'}")
        return 1

    try:
        infos = sheet.describe_sheets(source, header_row=a.header_row - 1)
    except sheet.SheetError as e:
        _p(f"읽지 못했습니다: {e}")
        return 1

    out_dir = Path(a.out) if a.out else source.parent
    suffix = a.format if a.format.startswith(".") else "." + a.format
    _p(f"{source.name}  시트 {len(infos)}개 -> {out_dir}")

    made = 0
    for info in infos:
        safe = hangul.sanitize_filename(f"{source.stem}-{info.name}{suffix}")
        target = out_dir / safe
        if info.error:
            _p(f"  건너뜀  {info.name}  ({info.error})")
            continue
        if info.rows == 0 and not info.headers:
            _p(f"  건너뜀  {info.name}  (비어 있음)")
            continue
        if not a.apply:
            _p(f"  [미리보기] {target.name}  {info.rows:,}행 x {info.columns}열")
            made += 1
            continue
        table = sheet.load(source, sheet=info.name, header_row=a.header_row - 1)
        sheet.save(table, target, sheet_name=info.name)
        _p(f"  {target}  {info.rows:,}행")
        made += 1

    if not made:
        _p("\n낼 것이 없습니다.")
        return 1
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


def cmd_sheet_similar(a) -> int:
    """같은 곳으로 보이는 값을 찾는다. 합치지는 않는다 - 사람이 정할 일이다."""
    t = _load(a)
    if t is None:
        return 1
    try:
        pairs, cut = sheet.find_similar(t, a.column, threshold=a.threshold,
                                        limit=a.limit)
    except sheet.SheetError as e:
        _p(str(e))
        return 1

    _p(f"{Path(a.file).name}  {a.column}  {len(t.rows):,}행")
    if not pairs:
        _p("같은 곳으로 보이는 짝이 없습니다.")
        _p("  다듬은 이름의 앞 두 글자가 같은 것끼리만 견줍니다. "
           "--threshold 를 낮춰 보세요.")
        return 0

    _p(f"같은 곳으로 보이는 짝 {len(pairs):,}개  (합치지 않았습니다)\n")
    _grid(["왜", "닮음", "행", "값", "행", "값"],
          [[p.reason, f"{p.score:.2f}", str(p.left_row), _cut(p.left, a.width),
            str(p.right_row), _cut(p.right, a.width)] for p in pairs[:a.rows]],
          limit=a.width)
    if len(pairs) > a.rows:
        _p(f"  ... {len(pairs) - a.rows:,}개 더")
    if cut:
        _p(f"\n{a.limit:,}개까지만 찾았습니다. --limit 로 늘리세요.")

    _p("\n«표기만 다름» 은 법인 표기와 공백·기호를 뗀 뒤 완전히 같은 것입니다.")
    if a.out:
        table = sheet.Table(["왜", "닮음", "왼쪽 행", "왼쪽 값", "오른쪽 행", "오른쪽 값"],
                            [[p.reason, p.score, p.left_row, p.left,
                              p.right_row, p.right] for p in pairs])
        _p(f"저장: {sheet.save(table, Path(a.out))}")
    else:
        _p("표로 받으려면 -o 로 출력 파일을 지정하세요.")
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
            if a.formula:
                t, report = sheet.add_formula_column(t, name.strip(),
                                                     expression.strip())
            else:
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

    if a.formula:
        _p("\n수식으로 넣었습니다. 위 표에 보이는 것은 넣은 수식이고, "
           "파일에는 지금 계산한 값도 함께 들어가 엑셀에서 바로 보입니다. "
           "값을 고치면 엑셀이 다시 계산합니다.")
        if a.out and Path(a.out).suffix.lower() not in sheet.XLSX_SUFFIXES:
            _p("  csv 로 내면 수식이 «=...» 글자로 들어갑니다. "
               "엑셀에서 열면 수식으로 읽히지만, 다른 프로그램에서는 글자입니다.")

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

    rw = common(sh.add_parser("row", help="한 행을 세로로 보기 (열이 많은 표)"))
    rw.add_argument("file")
    rw.add_argument("--at", type=int, metavar="행",
                    help="엑셀에서 보이는 줄 번호 (머리글이 1행)")
    rw.add_argument("--eq", action="append", metavar="열=값", help="값이 같은 행")
    rw.add_argument("--has", action="append", metavar="열=값", help="값을 포함하는 행")
    rw.add_argument("-n", "--rows", type=int, default=5, metavar="개",
                    help="여러 행이 걸리면 몇 개까지 보일지 (기본 5)")
    rw.set_defaults(func=cmd_sheet_row)

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

    fd = common(sh.add_parser("find", help="여러 파일에서 값 찾기 (어느 파일 몇 행)"))
    fd.add_argument("needle", metavar="찾을값")
    fd.add_argument("files", nargs="+", metavar="파일|폴더")
    fd.add_argument("-c", "--column", metavar="열", help="이 열만 본다")
    fd.add_argument("--exact", action="store_true", help="정확히 같은 값만")
    fd.add_argument("--case", action="store_true", help="대소문자를 가린다")
    fd.add_argument("--limit", type=int, default=30, metavar="개")
    fd.set_defaults(func=cmd_sheet_find)

    bk = common(sh.add_parser("book", help="여러 파일을 한 엑셀의 여러 시트로"))
    bk.add_argument("files", nargs="+")
    bk.add_argument("-o", "--out", help="저장 경로 (.xlsx)")
    bk.set_defaults(func=cmd_sheet_book)

    sh_ = common(sh.add_parser("sheets", help="엑셀 안의 시트 목록과 머리글"))
    sh_.add_argument("file")
    sh_.set_defaults(func=cmd_sheet_sheets)

    fm = common(sh.add_parser("format", help="열 표기 통일 (전화·사업자번호·날짜)"))
    fm.add_argument("file")
    fm.add_argument("-o", "--out", help="저장 경로 (.csv 또는 .xlsx)")
    fm.add_argument("--phone", action="append", metavar="열", help="전화번호 열")
    fm.add_argument("--bizno", action="append", metavar="열", help="사업자등록번호 열")
    fm.add_argument("--post", action="append", metavar="열", help="우편번호 열")
    fm.add_argument("--date", action="append", metavar="열", help="날짜 열")
    fm.add_argument("--number", action="append", metavar="열", help="숫자 열")
    fm.add_argument("--limit", type=int, default=10, metavar="개",
                    help="못 알아본 값을 몇 개까지 보일지")
    fm.add_argument("--strict", action="store_true",
                    help="못 알아본 값이 있으면 1로 끝낸다")
    fm.set_defaults(func=cmd_sheet_format)

    mk = common(sh.add_parser("mask", help="개인정보 가린 사본 만들기 (밖으로 보낼 때)"))
    mk.add_argument("file")
    for flag, kind in (("name", "이름"), ("phone", "전화"), ("email", "이메일"),
                       ("rrn", "주민번호"), ("account", "계좌"),
                       ("address", "주소")):
        mk.add_argument(f"--{flag}", action="append", metavar="열",
                        help=f"{kind} 로 가릴 열 ({sheet.MASK_KINDS[kind][1]})")
    mk.add_argument("-o", "--out", metavar="파일")
    mk.add_argument("--limit", type=int, default=20, help="통째로 가린 값을 몇 개까지 보일지")
    mk.add_argument("--strict", action="store_true",
                    help="꼴을 모르는 값이 하나라도 있으면 1 로 끝낸다")
    mk.set_defaults(func=cmd_sheet_mask)

    fmd = sh.add_parser("from-md", help="마크다운 문서 안의 표를 엑셀·csv 로")
    fmd.add_argument("file", metavar="파일")
    fmd.add_argument("--table", type=int, dest="number", metavar="번호",
                     help="그 표 하나만 (없으면 전부)")
    fmd.add_argument("-o", "--out", metavar="파일",
                     help="xlsx 면 표마다 시트로 나눠 담는다")
    fmd.add_argument("--rows", type=int, default=10, metavar="개")
    fmd.add_argument("--width", type=int, default=20, metavar="칸")
    fmd.set_defaults(func=cmd_sheet_from_md)

    ts = common(sh.add_parser("to-sql", help="표를 INSERT 문으로 (개발 DB 에 넣기)"))
    ts.add_argument("file")
    ts.add_argument("-t", "--table", required=True, metavar="표이름")
    ts.add_argument("--dialect", default="sqlite", choices=sorted(sheet.SQL_DIALECTS),
                    help="따옴표·참거짓 표기가 달라진다 (기본 sqlite)")
    ts.add_argument("--batch", type=int, default=100, metavar="행",
                    help="INSERT 하나에 넣을 행 수 (기본 100)")
    ts.add_argument("--create", action="store_true",
                    help="CREATE TABLE 초안도 함께 (타입은 값에서 짐작)")
    ts.add_argument("-o", "--out", metavar="파일")
    ts.set_defaults(func=cmd_sheet_to_sql)

    fdx = sh.add_parser("from-docx", help="워드 문서 안의 표를 엑셀·csv 로")
    fdx.add_argument("file", metavar="파일")
    fdx.add_argument("--table", type=int, dest="number", metavar="번호",
                     help="그 표 하나만 (없으면 전부)")
    fdx.add_argument("-o", "--out", metavar="파일",
                     help="xlsx 면 표마다 시트로 나눠 담는다")
    fdx.add_argument("--rows", type=int, default=10, metavar="개")
    fdx.add_argument("--width", type=int, default=20, metavar="칸")
    fdx.set_defaults(func=cmd_sheet_from_docx)

    cl2 = sh.add_parser("collect", help="같은 양식 파일들에서 같은 칸만 뽑기 (취합)")
    cl2.add_argument("paths", nargs="+", metavar="경로", help="폴더 또는 파일들")
    cl2.add_argument("--cell", action="append", required=True, metavar="칸=이름",
                     help="예: --cell B3=담당자 --cell C7=금액")
    cl2.add_argument("--sheet", metavar="이름", help="xlsx 시트 이름 (모든 파일에 같게)")
    cl2.add_argument("--glob", metavar="무늬", help="폴더 안에서 고를 무늬. 예: '*.xlsx'")
    cl2.add_argument("-o", "--out", metavar="파일")
    cl2.add_argument("--rows", type=int, default=15, metavar="개")
    cl2.add_argument("--width", type=int, default=20, metavar="칸")
    cl2.add_argument("--limit", type=int, default=10, metavar="개")
    cl2.set_defaults(func=cmd_sheet_collect)

    mg = common(sh.add_parser("merge", help="여러 파일을 세로로 합치기"))
    mg.add_argument("files", nargs="+")
    mg.add_argument("-o", "--out")
    mg.add_argument("--no-source", action="store_true", help="출처 열을 넣지 않는다")
    mg.add_argument("--strict", action="store_true", help="열 구성이 다르면 중단")
    mg.set_defaults(func=cmd_sheet_merge)

    df = common(sh.add_parser("diff", help="두 파일을 키 기준으로 비교"))
    df.add_argument("before")
    df.add_argument("after", nargs="?",
                    help="없으면 같은 파일의 --other-sheet 와 견준다")
    df.add_argument("--other-sheet", metavar="시트",
                    help="견줄 쪽의 시트 이름 (한 파일 안의 두 시트 비교)")
    df.add_argument("--key", metavar="열", help="행을 짝지을 열")
    df.add_argument("--columns", action="store_true",
                    help="행 대신 열 구조만 비교 (키가 없어도 된다)")
    df.add_argument("--limit", type=int, default=20)
    df.add_argument("-o", "--out", metavar="파일",
                    help="변경 내역을 표로 저장 (추가·삭제·바뀜)")
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

    rn2 = common(sh.add_parser("rename", help="열 이름 바꾸기 (합치기 전에 맞추기)"))
    rn2.add_argument("file")
    rn2.add_argument("--map", action="append", metavar="옛이름=새이름")
    rn2.add_argument("--map-file", metavar="파일", help='{"옛이름": "새이름"} JSON')
    rn2.add_argument("--strip", action="store_true", help="열 이름의 앞뒤 공백 정리")
    rn2.add_argument("-o", "--out")
    rn2.set_defaults(func=cmd_sheet_rename)

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
    wh.add_argument("--empty", action="append", metavar="열", help="그 칸이 비어 있음")
    wh.add_argument("--filled", action="append", metavar="열", help="그 칸에 값이 있음")
    wh.set_defaults(func=cmd_sheet_where)

    so = sheet_out(common(sh.add_parser("sort", help="정렬")))
    so.add_argument("file")
    so.add_argument("--by", action="append", required=True, metavar="열",
                    help="여러 번 쓸 수 있다. '연봉:내림' 또는 --by=-연봉 이면 그 열만 내림차순")
    so.add_argument("--desc", action="store_true", help="전부 내림차순")
    so.set_defaults(func=cmd_sheet_sort)

    sp2 = sheet_out(common(sh.add_parser("sample", help="표본 뽑기")))
    sp2.add_argument("file")
    sp2.add_argument("-n", "--number", type=int, default=20, metavar="행")
    sp2.add_argument("--head", action="store_true", help="무작위 대신 앞에서")
    sp2.add_argument("--seed", type=int, help="같은 표본을 다시 뽑을 때")
    sp2.set_defaults(func=cmd_sheet_sample)

    ad = common(sh.add_parser("audit", help="받은 표 한 번에 훑기 (빈 칸·타입·중복·드문 값·개인정보)"))
    ad.add_argument("file")
    ad.add_argument("--strict", action="store_true",
                    help="볼 만한 곳이 있으면 1 로 끝낸다")
    ad.set_defaults(func=cmd_sheet_audit)

    ol2 = common(sh.add_parser("outliers", help="숫자 열에서 드문 값 찾기 (입력 실수 검수)"))
    ol2.add_argument("file")
    ol2.add_argument("-c", "--column", required=True, metavar="열")
    ol2.add_argument("--method", default="iqr", choices=sorted(sheet.OUTLIER_METHODS),
                     help="iqr 사분위 범위 (기본) · sigma 평균 ± 표준편차")
    ol2.add_argument("--factor", type=float, default=1.5, metavar="배수",
                     help="이 배수를 넘으면 드문 값 (기본 1.5, sigma 면 3 쯤)")
    ol2.add_argument("--limit", type=int, default=20, metavar="개")
    ol2.add_argument("--strict", action="store_true",
                     help="드문 값이 있으면 1 로 끝낸다")
    ol2.set_defaults(func=cmd_sheet_outliers)

    rp3 = sheet_out(common(sh.add_parser(
        "replace", help="표 안의 값 찾아 바꾸기 (엑셀의 모두 바꾸기)")))
    rp3.add_argument("file")
    rp3.add_argument("find", metavar="찾을값")
    rp3.add_argument("to", metavar="바꿀값")
    rp3.add_argument("-c", "--column", action="append", metavar="열",
                     help="이 열만 (없으면 모든 열)")
    rp3.add_argument("--exact", action="store_true",
                     help="칸 전체가 같을 때만 바꾼다")
    rp3.add_argument("-i", "--ignore-case", action="store_true")
    rp3.set_defaults(func=cmd_sheet_replace)

    dt = sheet_out(common(sh.add_parser(
        "dates", help="날짜 열에서 요일·월·분기·주차 열 만들기 (피벗 준비)")))
    dt.add_argument("file")
    dt.add_argument("-c", "--column", required=True, metavar="열")
    dt.add_argument("--add", action="append", required=True,
                    choices=list(sheet.DATE_PARTS),
                    help="여러 번 쓸 수 있다: " + ", ".join(
                        f"{k}({v})" for k, v in sheet.DATE_PARTS.items()))
    dt.add_argument("--limit", type=int, default=10, metavar="개")
    dt.set_defaults(func=cmd_sheet_dates)

    fdn = sheet_out(common(sh.add_parser("filldown", help="빈 칸을 바로 위 값으로 채우기 (병합 셀 푼 표)")))
    fdn.add_argument("file")
    fdn.add_argument("-c", "--col", action="append", metavar="열",
                     help="이 열만 채운다 (없으면 모든 열)")
    fdn.set_defaults(func=cmd_sheet_filldown)

    tt = sheet_out(common(sh.add_parser("total", help="맨 아래에 합계 줄 붙이기")))
    tt.add_argument("file")
    tt.add_argument("-c", "--col", action="append", metavar="열",
                    help="이 열만 센다 (없으면 숫자 열 전부)")
    tt.add_argument("--kind", choices=sorted(sheet.TOTAL_KINDS), default="sum",
                    help="sum 합계 · avg 평균 · count 개수 (기본 sum)")
    tt.add_argument("--label", metavar="글자", help="첫 칸에 넣을 이름 (기본 합계)")
    tt.set_defaults(func=cmd_sheet_total)

    sl = common(sh.add_parser("split", help="여러 파일로 나누기"))
    sl.add_argument("file")
    sl.add_argument("--rows", type=int, dest="rows_per", metavar="행",
                    help="이만큼씩 잘라서")
    sl.add_argument("--by", metavar="열", help="이 열의 값마다 (부서별·월별)")
    sl.add_argument("-o", "--out", metavar="디렉터리")
    sl.add_argument("--format", metavar="확장자", help="csv 또는 xlsx")
    sl.add_argument("--sheets", metavar="파일",
                    help="파일 여러 개 대신 한 xlsx 의 시트로 나눈다")
    sl.add_argument("--apply", action="store_true")
    sl.set_defaults(func=cmd_sheet_split)

    ub = sh.add_parser("unbook", help="엑셀의 시트들을 파일로 나누기 (book 의 반대)")
    ub.add_argument("file")
    ub.add_argument("-o", "--out", metavar="폴더", help="기본은 원본 옆")
    ub.add_argument("--format", default=".xlsx", metavar="확장자",
                    help="csv 로 내려면 --format csv (기본 xlsx)")
    ub.add_argument("--header-row", type=int, default=1, metavar="행")
    ub.add_argument("--apply", action="store_true", help="실제로 파일을 만든다")
    ub.set_defaults(func=cmd_sheet_unbook)

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
    fx.add_argument("--formula", action="store_true",
                    help="값 대신 엑셀 수식을 넣는다 (받는 쪽에서 다시 계산되게)")
    fx.add_argument("--round", type=int, default=None, metavar="자리",
                    help="숫자 결과를 이 자리에서 반올림")
    fx.add_argument("-o", "--out", metavar="파일")
    fx.add_argument("--rows", type=int, default=10, metavar="개")
    fx.add_argument("--width", type=int, default=16, metavar="칸")
    fx.set_defaults(func=cmd_sheet_fx)

    sm = common(sh.add_parser("similar", help="같은 곳으로 보이는 값 찾기 (거래처 표기 흔들림)"))
    sm.add_argument("file")
    sm.add_argument("-c", "--column", required=True, metavar="열")
    sm.add_argument("--threshold", type=float, default=0.85, metavar="0~1",
                    help="이만큼 닮으면 후보로 (기본 0.85)")
    sm.add_argument("--limit", type=int, default=500, metavar="개",
                    help="찾을 짝의 최대 개수")
    sm.add_argument("--rows", type=int, default=20, metavar="개", help="보여줄 개수")
    sm.add_argument("--width", type=int, default=22, metavar="칸")
    sm.add_argument("-o", "--out", metavar="파일")
    sm.set_defaults(func=cmd_sheet_similar)

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
