"""텍스트 일괄 처리 화면. 여러 파일을 한꺼번에 고치고, 통째로 되돌린다."""

from __future__ import annotations

from pathlib import Path

from ... import text as textkit
from .. import App, UiError, form

MODES = {
    "replace": "찾아 바꾸기",
    "encoding": "인코딩을 utf-8 로",
    "eol": "줄바꿈을 LF 로",
    "crlf": "줄바꿈을 CRLF 로",
    "trim": "줄 끝 공백 지우기",
}
MAX_SHOWN = 30


def _files(payload: dict) -> list[Path]:
    root = form.existing_path(payload)
    globs = [g.strip() for g in form.text(payload, "glob").split(",") if g.strip()]
    return list(textkit.iter_files([root], glob=globs or None,
                                   hidden=form.flag(payload, "hidden")))


def _plan(payload: dict) -> list:
    mode = form.choice(payload, "mode", MODES, "replace")
    files = _files(payload)
    if not files:
        raise UiError("읽을 파일이 없습니다. 경로와 파일 이름 조건을 확인해 주세요.")

    if mode == "replace":
        # 앞뒤 공백을 다듬지 않는다. 공백까지 포함해 찾는 일이 실제로 있다.
        needle = form.raw_text(payload, "needle")
        if not needle:
            raise UiError("찾을 말을 적어 주세요.")
        try:
            pattern = textkit.build_pattern(
                needle,
                regex=form.flag(payload, "regex"),
                ignore_case=form.flag(payload, "ignore_case"),
                whole_word=form.flag(payload, "whole_word"))
        except textkit.TextError as exc:
            raise UiError(str(exc)) from None
        return textkit.plan_replace(files, pattern,
                                    form.raw_text(payload, "replacement"),
                                    regex=form.flag(payload, "regex"))
    if mode == "encoding":
        return textkit.plan_encoding(files)
    if mode == "eol":
        return textkit.plan_eol(files, "lf")
    if mode == "crlf":
        return textkit.plan_eol(files, "crlf")
    return textkit.plan_trim(files)


def _rows(changes: list) -> list[dict]:
    out = []
    for change in changes[:MAX_SHOWN]:
        out.append({
            "path": str(change.path),
            "hits": change.hits,
            "note": change.note,
            "diff": change.diff(),
        })
    return out


def preview(payload: dict) -> dict:
    changes = _plan(payload)
    return {"count": len(changes),
            "hits": sum(c.hits for c in changes),
            "shown": min(len(changes), MAX_SHOWN),
            "files": _rows(changes)}


def apply(payload: dict) -> dict:
    """적용할 때 계획을 다시 세운다. 화면이 보낸 본문을 그대로 쓰지 않는다."""
    changes = _plan(payload)
    if not changes:
        raise UiError("바뀔 것이 없습니다. 먼저 미리보기로 확인해 주세요.")
    target = "utf-8" if form.choice(payload, "mode", MODES, "replace") == "encoding" else None
    journal = textkit.apply_changes(changes, target_encoding=target)
    return {"applied": len(changes),
            "journal": journal.parent.name if journal else "",
            "files": _rows(changes)}


def journals(payload: dict) -> dict:
    base = textkit.backup_dir()
    if not base.is_dir():
        return {"rows": []}
    rows = []
    for journal in sorted(base.glob("*/journal.jsonl"), reverse=True)[:20]:
        lines = [ln for ln in journal.read_text(encoding="utf-8").splitlines()
                 if ln.strip()]
        rows.append([journal.parent.name, str(len(lines))])
    return {"rows": rows}


def undo(payload: dict) -> dict:
    name = form.text(payload, "journal")
    if not name or "/" in name or name.startswith("."):
        raise UiError("되돌릴 기록을 골라 주세요.")
    journal = textkit.backup_dir() / name / "journal.jsonl"
    if not journal.is_file():
        raise UiError(f"그런 기록이 없습니다: {name}")
    restored, errors = textkit.undo(journal)
    return {"restored": restored, "errors": errors}


BODY = """
<section class="card">
  <h2>어떤 파일을</h2>
  <div class="row">
    <div style="flex:3 1 22rem">
      <label for="path">폴더 또는 파일</label>
      <input type="text" id="path" placeholder="예: ~/문서/원고" spellcheck="false">
    </div>
    <div>
      <label for="glob">파일 이름 조건 (쉼표로 여러 개)</label>
      <input type="text" id="glob" placeholder="*.md, *.txt" spellcheck="false">
    </div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="hidden"> 숨김 파일도</label>
  </div>
</section>

<section class="card">
  <h2>무엇을 할까요</h2>
  <div class="row">
    <div style="flex:0 1 14rem">
      <label for="mode">하는 일</label>
      <select id="mode">%(modes)s</select>
    </div>
    <div id="wrap-needle">
      <label for="needle">찾을 말</label>
      <input type="text" id="needle" spellcheck="false">
    </div>
    <div id="wrap-replacement">
      <label for="replacement">바꿀 말 (비우면 지웁니다)</label>
      <input type="text" id="replacement" spellcheck="false">
    </div>
  </div>
  <div class="checks" id="wrap-options">
    <label><input type="checkbox" id="regex"> 정규식</label>
    <label><input type="checkbox" id="ignore_case"> 대소문자 무시</label>
    <label><input type="checkbox" id="whole_word"> 낱말 단위</label>
  </div>
  <div class="actions">
    <button class="primary" id="btn-preview">미리보기</button>
    <button id="btn-apply" disabled>이대로 고치기</button>
    <span class="spacer"></span>
    <span class="note">고친 파일은 통째로 백업해 둡니다.</span>
  </div>
  <div id="msg"></div>
</section>

<section class="card">
  <h2>바뀌는 곳</h2>
  <div id="plan"><div class="empty">미리보기를 눌러 주세요.</div></div>
</section>

<section class="card">
  <h2>되돌리기</h2>
  <p class="note">고치기 전 원본은 <code>~/.attools/text/&lt;시각&gt;/</code> 에
     남습니다. 터미널에서는 <code>at text undo</code> 로도 됩니다.</p>
  <div class="row">
    <div><label for="journal">기록</label><select id="journal"></select></div>
    <div style="flex:0 0 auto">
      <button id="btn-undo" class="danger">되돌리기</button>
    </div>
  </div>
  <div id="undomsg"></div>
</section>

<script>
(function () {
  const $ = (id) => document.getElementById(id);
  let ready = false;

  function values() {
    return {
      path: $("path").value, glob: $("glob").value, hidden: $("hidden").checked,
      mode: $("mode").value, needle: $("needle").value,
      replacement: $("replacement").value, regex: $("regex").checked,
      ignore_case: $("ignore_case").checked, whole_word: $("whole_word").checked,
    };
  }

  function lock(state) { ready = state; $("btn-apply").disabled = !state; }

  function syncMode() {
    const replacing = $("mode").value === "replace";
    ["wrap-needle", "wrap-replacement", "wrap-options"].forEach(function (id) {
      $(id).hidden = !replacing;
    });
    lock(false);
  }
  $("mode").addEventListener("change", syncMode);
  syncMode();

  ["path", "glob", "needle", "replacement"].forEach(function (id) {
    $(id).addEventListener("input", function () { lock(false); });
  });
  ["hidden", "regex", "ignore_case", "whole_word"].forEach(function (id) {
    $(id).addEventListener("change", function () { lock(false); });
  });

  function colour(line) {
    const cls = line.startsWith("+") ? "add"
              : line.startsWith("-") ? "del"
              : line.startsWith("@") ? "at" : "";
    return cls ? '<span class="' + cls + '">' + AT.esc(line) + "</span>"
               : AT.esc(line);
  }

  function draw(data) {
    if (!data.files.length) {
      $("plan").innerHTML = '<div class="empty">바뀔 것이 없습니다.</div>';
      return;
    }
    $("plan").innerHTML = data.files.map(function (f) {
      const head = '<p class="file">' + AT.esc(f.path) +
        (f.hits ? " · " + f.hits + "곳" : "") +
        (f.note ? " · " + AT.esc(f.note) : "") + "</p>";
      return head + (f.diff.length
        ? '<pre class="diff">' + f.diff.map(colour).join("\\n") + "</pre>"
        : "");
    }).join("") + (data.count > data.shown
      ? '<p class="note">' + (data.count - data.shown) +
        "개 파일은 줄였습니다.</p>" : "");
  }

  $("btn-preview").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/text/preview", values());
      draw(d);
      if (d.count) {
        AT.message($("msg"), "파일 <b>" + d.count + "개</b>" +
          (d.hits ? ", 모두 " + d.hits + "곳" : "") + "이 바뀝니다.", "ok");
        lock(true);
      } else {
        AT.message($("msg"), "바뀔 것이 없습니다.", "");
        lock(false);
      }
    } catch (e) { AT.message($("msg"), AT.esc(e.message), "bad"); lock(false); }
  });

  $("btn-apply").addEventListener("click", async function () {
    if (!ready) return;
    if (!confirm("파일을 실제로 고칩니다. 계속할까요?")) return;
    try {
      const d = await AT.call("/api/text/apply", values());
      draw(d);
      AT.message($("msg"), "파일 <b>" + d.applied + "개</b>를 고쳤습니다. 기록: " +
                 AT.esc(d.journal), "ok");
      lock(false);
      await loadJournals();
    } catch (e) { AT.message($("msg"), AT.esc(e.message), "bad"); }
  });

  async function loadJournals() {
    try {
      const d = await AT.call("/api/text/journals", {});
      $("journal").innerHTML = d.rows.length
        ? d.rows.map(r => '<option value="' + AT.esc(r[0]) + '">' +
            AT.esc(r[0]) + " (" + AT.esc(r[1]) + "개)</option>").join("")
        : '<option value="">되돌릴 기록이 없습니다</option>';
    } catch (e) { /* 기록이 없어도 화면은 돈다 */ }
  }

  $("btn-undo").addEventListener("click", async function () {
    const name = $("journal").value;
    if (!name) return;
    if (!confirm(name + " 기록을 되돌립니다. 계속할까요?")) return;
    try {
      const d = await AT.call("/api/text/undo", { journal: name });
      const tail = d.errors.length
        ? " 못 되돌린 것 " + d.errors.length + "개: " + AT.esc(d.errors.join(", "))
        : "";
      AT.message($("undomsg"), "<b>" + d.restored + "개</b>를 되돌렸습니다." + tail,
                 d.errors.length ? "bad" : "ok");
    } catch (e) { AT.message($("undomsg"), AT.esc(e.message), "bad"); }
  });

  loadJournals();
})();
</script>
""" % {"modes": "".join(f'<option value="{k}">{v}</option>' for k, v in MODES.items())}


def make() -> App:
    return App(
        key="text",
        name="일괄 바꾸기",
        summary="여러 파일의 글자·인코딩·줄바꿈을 한꺼번에 고치고 되돌린다",
        subtitle="미리보기 → 고치기 → 되돌리기",
        body=lambda: BODY,
        actions={"preview": preview, "apply": apply,
                 "journals": journals, "undo": undo},
        aliases=("텍스트", "바꾸기", "치환"),
        section="파일과 표",
    )
