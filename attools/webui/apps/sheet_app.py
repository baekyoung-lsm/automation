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
    return {"saved": str(out), "report": _format_rows(reports),
            "left": _left_alone(reports)}


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
      $("btn-format-save").disabled = true;
    } catch (e) { AT.message($("formatmsg"), AT.esc(e.message), "bad"); }
  });

  $("btn-open").addEventListener("click", async function () {
    try {
      const data = await AT.call("/api/sheet/peek", values());
      opened = true;
      options($("sheet"), data.sheets, "첫 시트");
      options($("key"), data.headers, "고르지 않음");
      options($("fcol"), data.headers, "");
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
                 "clean_preview": clean_preview, "clean_save": clean_save,
                 "format_preview": format_preview, "format_save": format_save},
        aliases=("엑셀", "표", "csv"),
        section="파일과 표",
    )
