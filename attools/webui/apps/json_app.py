"""JSON 화면. 응답 구조를 훑고, 두 응답을 비교하고, 표나 타입으로 옮긴다."""

from __future__ import annotations

import json
from pathlib import Path

from ... import files, sheet
from ...code import jsonkit
from .. import App, UiError, form

LANGS = {"python": "파이썬 dataclass", "typescript": "TypeScript interface"}
SAVE_FORMATS = {".csv": "csv", ".xlsx": "xlsx"}
MAX_ROWS = 200


def _data(payload: dict, key: str = "body", label: str = "입력"):
    """붙여넣은 글이 먼저, 없으면 파일 경로를 본다."""
    raw = form.raw_text(payload, key)
    if raw.strip():
        try:
            return jsonkit.loads(raw, name=label), label
        except jsonkit.JsonError as exc:
            raise UiError(str(exc)) from None

    where = form.text(payload, key + "_path")
    if not where:
        raise UiError(f"{label}: JSON 을 붙여 넣거나 파일 경로를 적어 주세요.")
    path = form.existing_file({"path": where})
    try:
        return jsonkit.load(path), str(path)
    except jsonkit.JsonError as exc:
        raise UiError(str(exc)) from None


def schema(payload: dict) -> dict:
    data, name = _data(payload)
    rows = []
    for field in jsonkit.schema(data):
        rows.append([
            field.path or "(뿌리)",
            "|".join(sorted(field.types)),
            "예" if field.optional else "",
            f"{field.seen}/{field.total}",
            jsonkit.preview(field.samples[0]) if field.samples else "",
        ])
    return {"rows": rows, "name": name, "count": len(rows),
            "note": "«있다 없다»에 표시된 키는 어떤 항목에는 없습니다. "
                    "받는 쪽에서 없을 수 있다고 다뤄야 합니다."}


def compare(payload: dict) -> dict:
    before, _ = _data(payload, "before", "먼저 것")
    after, _ = _data(payload, "after", "나중 것")
    key = form.text(payload, "key") or None
    result = jsonkit.diff(before, after, key=key)

    rows = []
    for path, value in result.removed:
        rows.append(["사라짐", path, jsonkit.preview(value), ""])
    for path, was, now in result.type_changed:
        rows.append(["타입 바뀜", path, was, now])
    for path, value in result.added:
        rows.append(["새로 생김", path, "", jsonkit.preview(value)])
    for path, was, now in result.value_changed:
        rows.append(["값 바뀜", path, jsonkit.preview(was), jsonkit.preview(now)])

    return {"rows": rows[:MAX_ROWS], "total": len(rows),
            "breaking": len(result.breaking), "same": result.empty,
            "note": "사라진 키와 타입이 바뀐 키는 받는 쪽을 깨뜨립니다. "
                    "새로 생긴 키는 보통 괜찮습니다."}


def _table(payload: dict) -> tuple[sheet.Table, object]:
    data, _ = _data(payload)
    try:
        records = sheet.find_records(data, form.text(payload, "at"))
    except (sheet.SheetError, jsonkit.JsonError) as exc:
        raise UiError(str(exc)) from None
    if not records:
        raise UiError("표로 만들 객체 배열을 찾지 못했습니다. "
                      "자리를 직접 적어 보세요. 예: data.items")
    table, report = sheet.from_records(
        records, depth=int(form.number(payload, "depth", 2, low=1, high=6)))
    return table, report


def flatten(payload: dict) -> dict:
    table, report = _table(payload)
    return {"headers": table.headers,
            "rows": [[sheet.to_text(c) for c in row] for row in table.rows[:MAX_ROWS]],
            "count": report.rows, "columns": report.columns,
            "skipped": report.skipped,
            "shown": min(report.rows, MAX_ROWS)}


def save(payload: dict) -> dict:
    table, report = _table(payload)
    suffix = form.choice(payload, "format", SAVE_FORMATS, ".csv")
    where = form.text(payload, "body_path")
    stem = Path(where).stem if where else "표"
    folder = Path(where).parent if where else Path.home()
    out = files.unique_path(folder / f"{stem}{suffix}")
    sheet.save(table, out)
    return {"saved": str(out), "count": report.rows,
            "skipped": report.skipped}


def types(payload: dict) -> dict:
    data, _ = _data(payload)
    lang = form.choice(payload, "lang", LANGS, "python")
    root = jsonkit.infer_type(data, form.text(payload, "root") or "Root")
    code = jsonkit.to_python(root) if lang == "python" else jsonkit.to_typescript(root)
    return {"code": code,
            "note": "받은 예시 하나로 만든 것입니다. 있다 없다 하는 키는 "
                    "예시에 없으면 나오지 않습니다."}


BODY = """
<section class="card">
  <h2>JSON 을 넣어 주세요</h2>
  <div class="row">
    <div><label for="body_path">파일 경로 (또는 아래에 붙여넣기)</label>
      <input type="text" id="body_path" placeholder="예: ~/내려받기/응답.json" spellcheck="false"></div>
  </div>
  <textarea id="body" spellcheck="false" placeholder='{"items": [{"id": 1}]}'
            style="margin-top:.8rem"></textarea>
  <nav class="tabs" id="tabs" style="margin-top:1.1rem">
    <button data-tab="schema" aria-selected="true">구조</button>
    <button data-tab="table" aria-selected="false">표로</button>
    <button data-tab="types" aria-selected="false">타입 코드</button>
    <button data-tab="compare" aria-selected="false">두 응답 비교</button>
  </nav>
  <div id="msg"></div>
</section>

<section class="card" data-panel="schema">
  <h2>구조</h2>
  <div class="actions"><button class="primary" id="btn-schema">훑어보기</button></div>
  <div id="schema-out"></div>
</section>

<section class="card" data-panel="table" hidden>
  <h2>표로 옮기기</h2>
  <div class="row">
    <div><label for="at">배열이 있는 자리 (비우면 가장 큰 배열)</label>
      <input type="text" id="at" placeholder="data.items" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="depth">펼칠 깊이</label>
      <input type="text" id="depth" value="2" spellcheck="false"></div>
    <div><label for="format">저장 형식</label>
      <select id="format"><option value=".csv">csv</option>
        <option value=".xlsx">xlsx</option></select></div>
  </div>
  <div class="actions">
    <button class="primary" id="btn-flatten">표로 보기</button>
    <button id="btn-save" disabled>파일로 저장</button>
    <span class="spacer"></span>
    <span class="note">저장은 원본 파일 옆에 새로 만듭니다.</span>
  </div>
  <div id="table-out"></div>
</section>

<section class="card" data-panel="types" hidden>
  <h2>타입 코드로</h2>
  <div class="row">
    <div><label for="lang">언어</label>
      <select id="lang"><option value="python">파이썬 dataclass</option>
        <option value="typescript">TypeScript interface</option></select></div>
    <div><label for="root">뿌리 이름</label>
      <input type="text" id="root" placeholder="Root" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-types">만들기</button></div>
  </div>
  <div id="types-out"></div>
</section>

<section class="card" data-panel="compare" hidden>
  <h2>두 응답 비교</h2>
  <p class="note">위에 넣은 것이 «먼저 것»입니다. 아래에 «나중 것»을 넣어 주세요.</p>
  <div class="row">
    <div><label for="after_path">나중 것 파일 경로</label>
      <input type="text" id="after_path" spellcheck="false"></div>
    <div><label for="key">객체 배열을 짝지을 열쇠 (예: id)</label>
      <input type="text" id="key" spellcheck="false"></div>
  </div>
  <textarea id="after" spellcheck="false" style="margin-top:.8rem"></textarea>
  <div class="actions"><button class="primary" id="btn-compare">비교</button></div>
  <div id="compare-out"></div>
</section>

<script>
(function () {
  const $ = (id) => document.getElementById(id);

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

  function source() {
    return { body: $("body").value, body_path: $("body_path").value };
  }
  function big(t) { return '<p class="big">' + t + "</p>"; }
  function code(t) { return '<pre class="diff">' + AT.esc(t) + "</pre>"; }

  async function run(path, body, draw) {
    try { draw(await AT.call(path, body)); }
    catch (e) { AT.message($("msg"), AT.esc(e.message), "bad"); }
  }

  $("btn-schema").addEventListener("click", function () {
    run("/api/json/schema", source(), function (d) {
      $("schema-out").innerHTML =
        AT.table(["경로", "타입", "있다 없다", "나온 횟수", "예시"], d.rows) +
        '<p class="note">' + AT.esc(d.note) + "</p>";
      AT.message($("msg"), "경로 <b>" + d.count + "개</b> · " + AT.esc(d.name), "ok");
    });
  });

  function tableBody() {
    const b = source();
    b.at = $("at").value; b.depth = $("depth").value; b.format = $("format").value;
    return b;
  }

  $("btn-flatten").addEventListener("click", function () {
    run("/api/json/flatten", tableBody(), function (d) {
      $("table-out").innerHTML = AT.table(d.headers, d.rows) +
        '<p class="note">' + d.count + "행 " + d.columns + "열" +
        (d.skipped ? " · 객체가 아니라 건너뛴 것 " + d.skipped + "개" : "") +
        (d.count > d.shown ? " · " + d.shown + "행만 보입니다" : "") + "</p>";
      $("btn-save").disabled = false;
      AT.message($("msg"), "표로 옮겼습니다.", "ok");
    });
  });

  $("btn-save").addEventListener("click", function () {
    run("/api/json/save", tableBody(), function (d) {
      AT.message($("msg"), "저장했습니다: <b>" + AT.esc(d.saved) + "</b> (" +
                 d.count + "행)", "ok");
    });
  });

  $("btn-types").addEventListener("click", function () {
    const b = source();
    b.lang = $("lang").value; b.root = $("root").value;
    run("/api/json/types", b, function (d) {
      $("types-out").innerHTML = code(d.code) +
        '<p class="note">' + AT.esc(d.note) + "</p>";
      AT.message($("msg"), "만들었습니다.", "ok");
    });
  });

  $("btn-compare").addEventListener("click", function () {
    run("/api/json/compare", {
      before: $("body").value, before_path: $("body_path").value,
      after: $("after").value, after_path: $("after_path").value,
      key: $("key").value,
    }, function (d) {
      $("compare-out").innerHTML = big(d.same ? "다른 곳이 없습니다"
        : d.total + "곳이 다릅니다" +
          (d.breaking ? " · 깨뜨릴 수 있는 것 " + d.breaking + "곳" : "")) +
        (d.same ? "" : AT.table(["무엇", "경로", "먼저", "나중"], d.rows)) +
        '<p class="note">' + AT.esc(d.note) + "</p>";
      AT.message($("msg"), "비교했습니다.", d.breaking ? "bad" : "ok");
    });
  });

  ["body", "body_path", "at", "depth"].forEach(function (id) {
    $(id).addEventListener("input", function () { $("btn-save").disabled = true; });
  });
})();
</script>
"""


def make() -> App:
    return App(
        key="json",
        name="JSON 훑기",
        summary="응답 구조를 훑고, 두 응답을 비교하고, 표나 타입으로 옮긴다",
        subtitle="구조 · 표 · 타입 · 비교",
        body=lambda: BODY,
        actions={"schema": schema, "compare": compare, "flatten": flatten,
                 "save": save, "types": types},
        aliases=("json", "응답"),
    )
