"""글자 손질 화면. 파일이 아니라 붙여넣은 글을 그 자리에서 손본다."""

from __future__ import annotations

from ... import hangul, sheet
from ... import text as textkit
from .. import App, UiError, form

MAX_ROWS = 60


def _body(payload: dict) -> str:
    body = form.raw_text(payload, "text")
    if not body.strip():
        raise UiError("글을 붙여 넣어 주세요.")
    return body


def kbd(payload: dict) -> dict:
    body = _body(payload)
    way = form.choice(payload, "to", {"auto", "ko", "en"}, "auto")
    if way == "auto":
        way = hangul.mistyped_direction(body)

    if way == "ko":
        return {"text": hangul.to_hangul(body), "both": None,
                "note": "영문 자판으로 친 글을 한글로 읽었습니다."}
    if way == "en":
        return {"text": hangul.to_qwerty(body), "both": None,
                "note": "한글로 친 글을 영문 자판 글자로 읽었습니다."}
    return {
        "text": "",
        "both": {"ko": hangul.to_hangul(body), "en": hangul.to_qwerty(body)},
        "note": "한글과 영문이 섞여 있어 어느 쪽인지 알 수 없습니다. "
                "둘 다 냈으니 맞는 쪽을 고르세요.",
    }


def typo(payload: dict) -> dict:
    body = _body(payload)
    found = hangul.find_typos(body)
    fixed, count = hangul.fix_typos(body)
    rows = [[str(t.line), t.wrong, t.right, t.note] for t in found[:MAX_ROWS]]
    return {"rows": rows, "total": len(found), "fixed": fixed, "count": count,
            "note": "맞춤법 검사기가 아닙니다. 확인한 규칙에 걸리는 자리만 "
                    "봅니다. 문맥에 따라 갈리는 것은 아예 넣지 않았습니다."}


def wrap(payload: dict) -> dict:
    body = _body(payload)
    width = int(form.number(payload, "width", 80, low=20, high=400))
    return {"text": textkit.wrap_text(body, width=width),
            "note": "한글은 두 칸으로 셉니다. 코드 블록과 표는 건드리지 않습니다."}


def pick(payload: dict) -> dict:
    """붙여넣은 글에서 이메일·전화·금액 같은 것을 뽑는다."""
    body = _body(payload)
    kinds = [k.strip() for k in form.text(payload, "kinds").split(",") if k.strip()]
    try:
        found = textkit.pick(body, kinds or None)
    except textkit.TextError as exc:
        raise UiError(str(exc)) from None
    if form.flag(payload, "unique"):
        found = textkit.unique_picked(found)

    counts: dict[str, int] = {}
    for item in found:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    return {"rows": [[p.kind, p.value, str(p.line)] for p in found[:MAX_ROWS]],
            "count": len(found),
            "summary": [[kind, str(n)] for kind, n in counts.items()],
            "kinds": list(textkit.PICK_RULES),
            "note": "좁게 잡습니다. 사업자번호는 하이픈이 있는 꼴만 봅니다 - "
                    "숫자 열 자리는 계좌·주문번호일 수도 있습니다."}


def table(payload: dict) -> dict:
    """엑셀에서 복사한 표(탭 구분)를 마크다운 표로."""
    import csv
    import io

    body = _body(payload)
    lines = [line for line in body.splitlines() if line.strip()]
    delimiter = "\t" if any("\t" in line for line in lines) else ","
    grid = [row for row in csv.reader(io.StringIO("\n".join(lines)),
                                      delimiter=delimiter) if row]
    if len(grid) < 2:
        raise UiError("머리글과 값이 적어도 한 줄씩은 있어야 합니다. "
                      "엑셀에서 표를 통째로 복사해 붙여 넣어 주세요.")

    try:
        made = sheet.table_from_grid(grid, label="붙여넣은 글")
    except sheet.SheetError as exc:
        raise UiError(str(exc)) from None
    return {"text": sheet.to_markdown(made),
            "columns": made.width, "count": len(made.rows),
            "note": "탭으로 나뉘어 있으면 탭, 아니면 쉼표로 나눕니다. "
                    "칸 너비는 at doc table 로 맞출 수 있습니다."}


def normalize(payload: dict) -> dict:
    body = _body(payload)
    fixed = hangul.to_nfc(body)
    return {"text": fixed,
            "decomposed": hangul.is_decomposed(body),
            "changed": fixed != body,
            "note": "맥에서 만든 파일 이름·글은 자모가 분리(NFD)돼 있어 "
                    "찾기와 정렬이 어긋납니다. NFC 로 되돌립니다."}


BODY = """
<section class="card">
  <h2>손볼 글</h2>
  <textarea id="text" spellcheck="false"
            placeholder="여기에 붙여 넣으세요. dkssudgktpdy 처럼 자판을 잘못 누른 글도 됩니다."></textarea>
  <div class="row" style="margin-top:.8rem">
    <div style="flex:0 1 12rem"><label for="to">자판 방향</label>
      <select id="to">
        <option value="auto">알아서</option>
        <option value="ko">한글로</option>
        <option value="en">영문으로</option>
      </select></div>
    <div style="flex:0 1 8rem"><label for="width">접을 폭</label>
      <input type="text" id="width" value="80" spellcheck="false"></div>
    <div><label for="kinds">뽑을 종류 (쉼표, 비우면 전부)</label>
      <input type="text" id="kinds" placeholder="이메일, 휴대폰" spellcheck="false"></div>
  </div>
  <div class="actions">
    <button class="primary" id="btn-kbd">자판 되살리기</button>
    <button id="btn-typo">흔한 표기 오류</button>
    <button id="btn-wrap">줄 접기</button>
    <button id="btn-normalize">자모 합치기 (NFC)</button>
    <button id="btn-table">붙여넣은 표를 마크다운으로</button>
    <button id="btn-pick">연락처·금액 뽑기</button>
  </div>
  <div id="msg"></div>
</section>

<section class="card">
  <h2>결과</h2>
  <div id="out"><div class="empty">글을 넣고 눌러 주세요.</div></div>
</section>

<script>
(function () {
  const $ = (id) => document.getElementById(id);
  const out = $("out");

  function code(text) { return '<pre class="diff">' + AT.esc(text) + "</pre>"; }
  function note(text) { return '<p class="note">' + AT.esc(text) + "</p>"; }

  function values() {
    return { text: $("text").value, to: $("to").value, width: $("width").value,
             kinds: $("kinds").value, unique: true };
  }

  async function run(path, draw) {
    try { draw(await AT.call(path, values())); }
    catch (e) { AT.message($("msg"), AT.esc(e.message), "bad"); }
  }

  $("btn-kbd").addEventListener("click", function () {
    run("/api/letters/kbd", function (d) {
      out.innerHTML = d.both
        ? '<p class="file">한글로</p>' + code(d.both.ko) +
          '<p class="file">영문으로</p>' + code(d.both.en) + note(d.note)
        : code(d.text) + note(d.note);
      AT.message($("msg"), "되살렸습니다.", "ok");
    });
  });

  $("btn-typo").addEventListener("click", function () {
    run("/api/letters/typo", function (d) {
      out.innerHTML = (d.total
          ? AT.table(["줄", "쓴 것", "바른 표기", "왜"], d.rows,
                     ["num", null, null, null]) +
            '<p class="file">고친 글 (' + d.count + "곳)</p>" + code(d.fixed)
          : '<div class="empty">걸리는 것이 없습니다.</div>') + note(d.note);
      AT.message($("msg"), d.total ? d.total + "곳이 걸립니다." : "걸리는 것이 없습니다.",
                 d.total ? "bad" : "ok");
    });
  });

  $("btn-wrap").addEventListener("click", function () {
    run("/api/letters/wrap", function (d) {
      out.innerHTML = code(d.text) + note(d.note);
      AT.message($("msg"), "접었습니다.", "ok");
    });
  });

  $("btn-pick").addEventListener("click", function () {
    run("/api/letters/pick", function (d) {
      out.innerHTML = (d.count
          ? AT.table(["종류", "값", "줄"], d.rows, [null, null, "num"]) +
            AT.table(["종류", "개수"], d.summary, [null, "num"])
          : '<div class="empty">뽑을 것이 없습니다. 찾는 종류: ' +
            AT.esc(d.kinds.join(", ")) + "</div>") + note(d.note);
      AT.message($("msg"), d.count ? "<b>" + d.count + "건</b>을 뽑았습니다."
                                   : "뽑을 것이 없습니다.", d.count ? "ok" : "");
    });
  });

  $("btn-table").addEventListener("click", function () {
    run("/api/letters/table", function (d) {
      out.innerHTML = code(d.text) + note(d.note);
      AT.message($("msg"), d.count + "행 " + d.columns + "열 표로 읽었습니다.", "ok");
    });
  });

  $("btn-normalize").addEventListener("click", function () {
    run("/api/letters/normalize", function (d) {
      out.innerHTML = code(d.text) + note(d.note);
      AT.message($("msg"), d.changed
        ? "자모가 분리돼 있어 합쳤습니다."
        : "이미 합쳐져 있습니다. 바꿀 것이 없습니다.", d.changed ? "ok" : "");
    });
  });
})();
</script>
"""


def make() -> App:
    return App(
        key="letters",
        name="글자 손질",
        summary="자판 실수·표기 오류·줄 접기·표를 마크다운으로·연락처 뽑기",
        subtitle="파일이 아니라 붙여넣은 글을 그 자리에서",
        body=lambda: BODY,
        actions={"kbd": kbd, "typo": typo, "wrap": wrap,
                 "normalize": normalize, "table": table, "pick": pick},
        aliases=("글자", "자판"),
        section="글",
    )
