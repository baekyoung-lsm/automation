"""문서 화면. 마크다운을 점검하고, 목차와 표를 다듬고, 다른 형식으로 낸다."""

from __future__ import annotations

from pathlib import Path

from ... import docx, files
from ... import text as textkit
from ...docs import mdkit
from .. import App, UiError, form

FIXES = {"toc": "목차 갱신 (<!-- toc --> 자리)", "tables": "표 칸 맞추기"}
EXPORTS = {"html": "HTML 한 장", "slides": "슬라이드 HTML", "docx": "워드 (docx)"}


def _markdown(payload: dict) -> tuple[Path, str]:
    path = form.existing_file(payload)
    if path.suffix.lower() not in (".md", ".markdown", ".txt"):
        raise UiError(f"마크다운 파일이 아닙니다: {path.suffix or '확장자 없음'}")
    return path, path.read_text(encoding="utf-8", errors="replace")


def check(payload: dict) -> dict:
    path, body = _markdown(payload)
    rows = [[issue.kind, issue.detail, str(issue.line)]
            for issue in mdkit.check_links(path) + mdkit.check_headings(body)]
    rows.sort(key=lambda row: int(row[2]))
    heads = [[str(h.level), h.title, str(h.line)] for h in mdkit.headings(body)]
    return {"rows": rows, "headings": heads, "clean": not rows,
            "note": "외부 URL 은 두드려 보지 않습니다. 상대 경로 파일과 "
                    "문서 안 앵커만 봅니다."}


def terms(payload: dict) -> dict:
    """같은 말을 다르게 적은 곳. 어느 쪽이 옳은지는 정하지 않는다."""
    path, body = _markdown(payload)
    found = mdkit.term_variants([(path.name, body)],
                                min_count=int(form.number(payload, "min_count", 2,
                                                          low=1, high=99)))
    rows = []
    for use in found:
        where = ", ".join(f"{form_}: {file}:{line}"
                          for form_, (file, line) in list(use.places.items())[:3])
        rows.append([use.kind, use.summary(), str(use.total), where])
    return {"rows": rows, "count": len(found),
            "note": "어느 쪽이 옳은지는 정하지 않습니다. 프로젝트마다 다르고, "
                    "틀렸다고 단정하면 결과를 안 보게 됩니다."}


def images(payload: dict) -> dict:
    """문서가 쓰는 그림이 실제로 있는지, 너무 크지 않은지."""
    path, body = _markdown(payload)
    rows, missing, no_alt = [], 0, 0
    for link in mdkit.links(body):
        if link.kind != "image":
            continue
        target = link.target.split("#", 1)[0]
        if "://" in target or target.startswith("data:"):
            continue
        if not link.text.strip():
            no_alt += 1
        spot = (path.parent / target).resolve()
        if not spot.is_file():
            missing += 1
            rows.append([str(link.line), target, "없음", "-"])
            continue
        size = spot.stat().st_size
        info = files.image_info(spot)
        rows.append([str(link.line), target,
                     f"{info.width}x{info.height}" if info else "?",
                     files.human_size(size)])
    return {"rows": rows, "missing": missing, "no_alt": no_alt,
            "count": len(rows),
            "note": "설명(alt)이 없는 그림은 화면 낭독기와 그림이 안 뜰 때 "
                    "아무것도 알려 주지 못합니다."}


def _fixed(payload: dict) -> tuple[Path, str, str, str]:
    path, before = _markdown(payload)
    kind = form.choice(payload, "fix", FIXES, "toc")

    if kind == "toc":
        toc = mdkit.build_toc(mdkit.headings(before),
                              depth=int(form.number(payload, "depth", 3, low=1, high=6)))
        if not toc:
            raise UiError("목차로 만들 제목이 없습니다.")
        after, changed = mdkit.update_toc(before, toc)
        if not changed and after == before:
            raise UiError("<!-- toc --> 와 <!-- /toc --> 표시가 없거나 "
                          "이미 최신입니다. 넣을 자리는 사람이 정합니다.")
        note = "목차"
    else:
        after, count = mdkit.format_tables(before)
        if not count:
            raise UiError("맞출 표가 없습니다.")
        note = f"표 {count}개"
    return path, before, after, note


def fix_preview(payload: dict) -> dict:
    path, before, after, note = _fixed(payload)
    change = textkit.Change(path, before, after, "utf-8", note=note)
    return {"path": str(path), "note": note, "changed": change.changed,
            "diff": change.diff(context=2, limit=40)}


def fix_apply(payload: dict) -> dict:
    """계획을 다시 세워 적용한다. 원본은 at text undo 로 되돌릴 수 있게 백업한다."""
    path, before, after, note = _fixed(payload)
    change = textkit.Change(path, before, after, "utf-8", note=note)
    if not change.changed:
        raise UiError("바뀔 것이 없습니다.")
    journal = textkit.apply_changes([change])
    return {"path": str(path), "note": note,
            "journal": journal.parent.name if journal else ""}


def export(payload: dict) -> dict:
    path, body = _markdown(payload)
    kind = form.choice(payload, "kind", EXPORTS, "html")
    title = form.text(payload, "title") or path.stem

    if kind == "docx":
        parts = mdkit.to_docx_parts(body)
        if not parts:
            raise UiError("옮길 내용이 없습니다.")
        out = files.unique_path(path.with_suffix(".docx"))
        docx.write_document(out, parts)
        return {"saved": str(out),
                "note": "문단 안의 굵게·기울임 표시는 글자만 남습니다."}

    if kind == "slides":
        html = mdkit.to_slides(body, title=title)
        out = files.unique_path(path.with_name(path.stem + " (슬라이드).html"))
        note = "브라우저에서 좌우 키로 넘기고, 인쇄하면 한 장에 한 쪽씩 나옵니다."
    else:
        html = mdkit.to_html(body, title=title, toc=form.flag(payload, "toc"))
        out = files.unique_path(path.with_suffix(".html"))
        note = "이미지와 링크는 상대 경로 그대로입니다. 같이 옮겨야 보입니다."

    out.write_text(html, encoding="utf-8")
    return {"saved": str(out), "note": note}


BODY = """
<section class="card">
  <h2>어느 문서인가요</h2>
  <div class="row">
    <div style="flex:3 1 22rem">
      <label for="path">마크다운 파일</label>
      <input type="text" id="path" placeholder="예: ~/문서/README.md" spellcheck="false">
    </div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-check">점검</button></div>
    <div style="flex:0 0 auto"><button id="btn-terms">용어 흔들림</button></div>
    <div style="flex:0 0 auto"><button id="btn-images">그림 점검</button></div>
  </div>
  <div id="msg"></div>
</section>

<section class="card">
  <h2>점검 결과</h2>
  <div id="check"><div class="empty">파일을 넣고 점검을 눌러 주세요.</div></div>
</section>

<section class="card">
  <h2>다듬기</h2>
  <div class="row">
    <div><label for="fix">무엇을</label><select id="fix">%(fixes)s</select></div>
    <div style="flex:0 1 8rem"><label for="depth">목차 깊이</label>
      <input type="text" id="depth" value="3" spellcheck="false"></div>
  </div>
  <div class="actions">
    <button class="primary" id="btn-fix">어떻게 바뀌나</button>
    <button id="btn-fix-apply" disabled>이대로 고치기</button>
    <span class="spacer"></span>
    <span class="note">고치기 전 원본은 백업합니다 (at text undo).</span>
  </div>
  <div id="fixmsg"></div>
  <div id="fix"></div>
</section>

<section class="card">
  <h2>다른 형식으로 내보내기</h2>
  <div class="row">
    <div><label for="kind">형식</label><select id="kind">%(exports)s</select></div>
    <div><label for="title">제목 (비우면 파일 이름)</label>
      <input type="text" id="title" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-export">내보내기</button></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="toc"> HTML 안에 목차 넣기</label>
  </div>
  <div id="exportmsg"></div>
</section>

<script>
(function () {
  const $ = (id) => document.getElementById(id);
  let ready = false;

  function values() {
    return {
      path: $("path").value, fix: $("fix").value, depth: $("depth").value,
      kind: $("kind").value, title: $("title").value, toc: $("toc").checked,
    };
  }

  function lock(state) { ready = state; $("btn-fix-apply").disabled = !state; }
  ["path", "depth"].forEach(function (id) {
    $(id).addEventListener("input", function () { lock(false); });
  });
  $("fix").addEventListener("change", function () { lock(false); });

  function colour(line) {
    const cls = line.startsWith("+") ? "add"
              : line.startsWith("-") ? "del"
              : line.startsWith("@") ? "at" : "";
    return cls ? '<span class="' + cls + '">' + AT.esc(line) + "</span>"
               : AT.esc(line);
  }

  $("btn-check").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/doc/check", values());
      $("check").innerHTML =
        (d.clean ? '<p class="note">깨진 링크·앵커와 제목 구조 문제가 없습니다.</p>'
                 : AT.table(["무엇", "어디", "줄"], d.rows, [null, null, "num"])) +
        "<h2>제목 구조</h2>" +
        AT.table(["단계", "제목", "줄"], d.headings, ["num", null, "num"]) +
        '<p class="note">' + AT.esc(d.note) + "</p>";
      AT.message($("msg"), d.clean ? "걸리는 것이 없습니다."
        : "<b>" + d.rows.length + "가지</b>가 걸립니다.", d.clean ? "ok" : "bad");
    } catch (e) { AT.message($("msg"), AT.esc(e.message), "bad"); }
  });

  $("btn-terms").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/doc/terms", values());
      $("check").innerHTML = (d.count
          ? AT.table(["무엇이 다른가", "표기", "모두", "처음 나온 곳"], d.rows,
                     [null, null, "num", null])
          : '<div class="empty">흔들리는 표기가 없습니다.</div>') +
        '<p class="note">' + AT.esc(d.note) + "</p>";
      AT.message($("msg"), d.count ? "<b>" + d.count + "가지</b>가 흔들립니다."
                                   : "흔들리는 표기가 없습니다.", "ok");
    } catch (e) { AT.message($("msg"), AT.esc(e.message), "bad"); }
  });

  $("btn-images").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/doc/images", values());
      $("check").innerHTML = (d.count
          ? AT.table(["줄", "경로", "크기", "용량"], d.rows,
                     ["num", null, null, "num"])
          : '<div class="empty">문서가 쓰는 그림이 없습니다.</div>') +
        '<p class="note">' + AT.esc(d.note) + "</p>";
      AT.message($("msg"), "그림 <b>" + d.count + "개</b>" +
        (d.missing ? " · 없는 파일 " + d.missing + "개" : "") +
        (d.no_alt ? " · 설명 없는 것 " + d.no_alt + "개" : ""),
        d.missing ? "bad" : "ok");
    } catch (e) { AT.message($("msg"), AT.esc(e.message), "bad"); }
  });

  $("btn-fix").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/doc/fix_preview", values());
      $("fix").innerHTML = '<pre class="diff">' +
        d.diff.map(colour).join("\\n") + "</pre>";
      AT.message($("fixmsg"), AT.esc(d.note) + "를 고칩니다.", "ok");
      lock(true);
    } catch (e) {
      $("fix").innerHTML = "";
      AT.message($("fixmsg"), AT.esc(e.message), "bad");
      lock(false);
    }
  });

  $("btn-fix-apply").addEventListener("click", async function () {
    if (!ready) return;
    if (!confirm("문서를 실제로 고칩니다. 계속할까요?")) return;
    try {
      const d = await AT.call("/api/doc/fix_apply", values());
      AT.message($("fixmsg"), AT.esc(d.note) + "를 고쳤습니다. 기록: " +
                 AT.esc(d.journal), "ok");
      lock(false);
    } catch (e) { AT.message($("fixmsg"), AT.esc(e.message), "bad"); }
  });

  $("btn-export").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/doc/export", values());
      AT.message($("exportmsg"), "저장했습니다: <b>" + AT.esc(d.saved) +
                 "</b><br>" + AT.esc(d.note), "ok");
    } catch (e) { AT.message($("exportmsg"), AT.esc(e.message), "bad"); }
  });
})();
</script>
""" % {"fixes": "".join(f'<option value="{k}">{v}</option>' for k, v in FIXES.items()),
       "exports": "".join(f'<option value="{k}">{v}</option>' for k, v in EXPORTS.items())}


def make() -> App:
    return App(
        key="doc",
        name="문서 손질",
        summary="마크다운을 점검하고 목차·표를 다듬고 HTML·워드로 낸다",
        subtitle="점검 → 다듬기 → 내보내기",
        body=lambda: BODY,
        actions={"check": check, "terms": terms, "images": images,
                 "fix_preview": fix_preview, "fix_apply": fix_apply,
                 "export": export},
        aliases=("문서", "마크다운", "md"),
        section="글",
    )
