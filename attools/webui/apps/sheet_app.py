"""엑셀·CSV 화면. 받은 파일을 열어 보고, 점검하고, 정리해 새 파일로 낸다."""

from __future__ import annotations

from pathlib import Path

from ... import files, sheet, xlsx
from .. import App, UiError, form

PEEK_ROWS = 30


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


def clean_save(payload: dict) -> dict:
    """원본은 건드리지 않는다. 옆에 새 파일을 만든다."""
    before, (after, rep) = _cleaned(payload)
    source = Path(before.source)
    suffix = source.suffix.lower()
    if suffix not in sheet.XLSX_SUFFIXES:
        suffix = ".csv"
    out = files.unique_path(source.with_name(f"{source.stem} (정리){suffix}"))
    sheet.save(after, out)
    return {"saved": str(out), "report": _report_rows(before, after, rep),
            "count": len(after.rows)}


BODY = """
<section class="card">
  <h2>어떤 파일인가요</h2>
  <div class="row">
    <div style="flex:3 1 22rem">
      <label for="path">파일 경로 (xlsx, csv, tsv)</label>
      <input type="text" id="path" placeholder="예: ~/문서/명단.xlsx" spellcheck="false">
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

  $("btn-open").addEventListener("click", async function () {
    try {
      const data = await AT.call("/api/sheet/peek", values());
      opened = true;
      options($("sheet"), data.sheets, "첫 시트");
      options($("key"), data.headers, "고르지 않음");
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
        actions={"peek": peek, "check": check,
                 "clean_preview": clean_preview, "clean_save": clean_save},
        aliases=("엑셀", "표", "csv"),
    )
