"""개인정보 점검 화면. 읽기만 한다 - 파일을 고치거나 지우지 않는다.

밖으로 보내기 전에 폴더를 훑어 주민등록번호·카드번호가 들어 있는지 본다.
찾은 값은 가려서 보여 준다 - 점검 화면에 주민번호를 그대로 띄우면
그 화면이 새 유출이 된다.
"""

from __future__ import annotations

from ... import text as textkit
from .. import App, UiError, form

MAX_FILES = 60
MAX_EACH = 12


def _kinds(payload: dict) -> list[str] | None:
    """고른 종류만. 하나도 안 고르면 전부 본다."""
    골라 = [kind for spot, kind in enumerate(textkit.PRIVACY_KINDS)
           if form.flag(payload, f"kind_{spot}")]
    return 골라 or None


def _globs(payload: dict) -> list[str] | None:
    out = [one.strip() for one in form.text(payload, "glob").split(",")
           if one.strip()]
    return out or None


def _command(payload: dict, kinds: list[str] | None) -> str:
    args: list[object] = ["text", "privacy", form.text(payload, "path")]
    if kinds:
        args += ["--only", ",".join(kinds)]
    for pattern in _globs(payload) or []:
        args += ["-g", pattern]
    if form.flag(payload, "hidden"):
        args.append("--hidden")
    args.append("--detail")
    return form.command(*args)


def scan(payload: dict) -> dict:
    root = form.existing_path(payload)
    kinds = _kinds(payload)
    try:
        seen = textkit.privacy_scan([root], kinds=kinds, glob=_globs(payload),
                                    hidden=form.flag(payload, "hidden"))
    except textkit.TextError as exc:
        raise UiError(str(exc)) from None
    if not seen:
        raise UiError("읽을 파일이 없습니다. 경로와 파일 이름 조건을 확인해 주세요.")

    hits = sorted((one for one in seen if one.found),
                  key=lambda f: (-f.serious, -f.count))
    rows = [[one.path.name, str(one.count), ", ".join(one.kinds()),
             one.found[0].shown, one.found[0].sure] for one in hits[:MAX_FILES]]
    detail = []
    for one in hits[:MAX_FILES]:
        detail.append({
            "path": str(one.path),
            "read_as": one.read_as,
            "rows": [[f"{item.where} {item.line}줄".strip(), item.kind,
                      item.shown, item.sure, item.note]
                     for item in one.found[:MAX_EACH]],
            "more": max(0, one.count - MAX_EACH),
        })
    broken = [[one.path.name, one.error] for one in seen if one.error]
    return {
        "rows": rows, "detail": detail, "broken": broken,
        "files": len(seen), "hit_files": len(hits),
        "total": sum(one.count for one in hits),
        "shown": min(len(hits), MAX_FILES),
        "command": _command(payload, kinds),
    }


BODY = """
<section class="card">
  <h2>어디를 볼까요</h2>
  <div class="row">
    <div style="flex:3 1 22rem">
      <label for="path">폴더 또는 파일</label>
      <input type="text" id="path" placeholder="예: ~/문서/보낼자료" data-browse="any" spellcheck="false">
    </div>
    <div>
      <label for="glob">파일 이름 조건 (쉼표로 여러 개)</label>
      <input type="text" id="glob" placeholder="*.xlsx, *.docx" spellcheck="false">
    </div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="hidden"> 숨김 파일도</label>
  </div>
  <p class="note">워드·한글(hwpx)·PDF·슬라이드·엑셀·메일·글 파일을 열어 봅니다.
     <b>파일은 고치지 않습니다.</b> 스캔한 그림처럼 글자가 없는 파일은 찾지
     못하므로 «없음» 이 «안전» 이라는 뜻은 아닙니다.</p>
</section>

<section class="card">
  <h2>무엇을 찾을까요</h2>
  <div class="checks" id="kinds">%(kinds)s</div>
  <p class="note">하나도 고르지 않으면 전부 찾습니다.</p>
  <div class="actions">
    <button class="primary" id="btn-scan">훑어보기</button>
    <span class="spacer"></span>
    <span class="note">찾은 값은 가려서 보여 줍니다 (900101-1******).</span>
  </div>
  <div id="msg"></div>
  <div id="cmd"></div>
</section>

<section class="card">
  <h2>찾은 파일</h2>
  <div id="summary"><div class="empty">훑어보기를 눌러 주세요.</div></div>
</section>

<section class="card">
  <h2>어느 줄에</h2>
  <div id="detail"><div class="empty">아직 없습니다.</div></div>
</section>

<script>
(function () {
  const $ = (id) => document.getElementById(id);

  function values() {
    const out = { path: $("path").value, glob: $("glob").value,
                  hidden: $("hidden").checked };
    document.querySelectorAll("#kinds input").forEach(function (box) {
      out[box.id] = box.checked;
    });
    return out;
  }

  $("btn-scan").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/privacy/scan", values());
      $("summary").innerHTML = d.rows.length
        ? AT.table(["파일", "건수", "무엇이", "보기", "확신"], d.rows,
                   [null, "num", null, null, null]) +
          (d.hit_files > d.shown ? '<p class="note">파일 ' +
            (d.hit_files - d.shown) + "개는 줄였습니다.</p>" : "")
        : '<div class="empty">찾은 것이 없습니다.</div>';
      $("detail").innerHTML = d.detail.length
        ? d.detail.map(function (f) {
            return '<p class="file">' + AT.esc(f.path) +
              (f.read_as ? " · " + AT.esc(f.read_as) : "") + "</p>" +
              AT.table(["자리", "종류", "가린 값", "확신", "메모"], f.rows) +
              (f.more ? '<p class="note">' + f.more + "건 더 있습니다.</p>" : "");
          }).join("")
        : '<div class="empty">찾은 것이 없습니다.</div>';
      let tail = "";
      if (d.broken.length) {
        tail = " 못 읽은 파일 " + d.broken.length + "개는 보지 못했습니다.";
      }
      AT.message($("msg"), d.total
        ? "파일 <b>" + d.hit_files + "개</b>에서 " + d.total + "건을 찾았습니다." + tail
        : "찾은 것이 없습니다. (파일 " + d.files + "개를 봤습니다)" + tail,
        d.total ? "bad" : "ok");
      $("cmd").innerHTML = AT.command(d.command);
    } catch (e) { AT.message($("msg"), AT.esc(e.message), "bad"); }
  });
})();
</script>
""" % {"kinds": "".join(
    f'<label><input type="checkbox" id="kind_{i}"> {kind}</label>'
    for i, kind in enumerate(textkit.PRIVACY_KINDS))}


def make() -> App:
    return App(
        key="privacy",
        name="개인정보 점검",
        summary="보내기 전에 폴더를 훑어 주민번호·카드번호가 든 파일을 찾는다",
        subtitle="읽기만 합니다 · 찾은 값은 가려서 보여 줍니다",
        body=lambda: BODY,
        actions={"scan": scan},
        aliases=("주민번호", "개인정보", "보안", "점검"),
        section="파일과 표",
    )
