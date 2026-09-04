"""파일 정리 화면. 어질러진 폴더를 종류별·날짜별로 묶고, 되돌린다."""

from __future__ import annotations

from pathlib import Path

from ... import files
from .. import App, UiError, form

MODES = {
    "ext": "종류별 (문서·사진·압축…)",
    "date": "날짜별 (2026-09)",
    "ext-date": "종류별 → 날짜별",
    "date-ext": "날짜별 → 종류별",
    "fixname": "옮기지 않고 이름만 다듬기",
}


def _plan(payload: dict) -> tuple[Path, list[files.Move]]:
    root = form.folder(payload)
    mode = form.choice(payload, "mode", MODES, "ext")
    recursive = form.flag(payload, "recursive")
    hidden = form.flag(payload, "hidden")
    if mode == "fixname":
        moves = files.plan_fixname(root, recursive=recursive,
                                   include_hidden=hidden,
                                   space="underscore" if form.flag(payload, "underscore") else "keep")
    else:
        moves = files.plan_organize(
            root, by=mode, recursive=recursive, include_hidden=hidden,
            min_age_days=form.number(payload, "min_age", 0.0, low=0.0, high=36500.0),
            fixname=form.flag(payload, "fixname"))
    return root, moves


def _rows(root: Path, moves: list[files.Move]) -> list[list[str]]:
    rows = []
    for mv in moves:
        src, dst = Path(mv.src), Path(mv.dst)
        try:
            here = str(src.relative_to(root))
            there = str(dst.relative_to(root))
        except ValueError:  # 뿌리 밖으로 나가는 계획은 그대로 보여준다
            here, there = str(src), str(dst)
        rows.append([here, there])
    return rows


def preview(payload: dict) -> dict:
    root, moves = _plan(payload)
    return {"root": str(root), "count": len(moves),
            "rows": _rows(root, moves)}


def apply(payload: dict) -> dict:
    """계획을 여기서 다시 세운다. 화면이 보낸 경로를 그대로 옮기지 않는다."""
    root, moves = _plan(payload)
    if not moves:
        raise UiError("옮길 것이 없습니다. 먼저 미리보기로 확인해 주세요.")
    journal = files.apply_moves(moves)
    return {"applied": len(moves), "root": str(root),
            "journal": journal.name if journal else "",
            "rows": _rows(root, moves)}


def journals(payload: dict) -> dict:
    base = files.journal_dir()
    if not base.exists():
        return {"rows": []}
    rows = []
    for path in sorted(base.glob("*.jsonl"), reverse=True)[:20]:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        rows.append([path.name, str(len(lines))])
    return {"rows": rows}


def undo(payload: dict) -> dict:
    name = form.text(payload, "journal")
    if not name or "/" in name or name.startswith("."):
        raise UiError("되돌릴 기록을 골라 주세요.")
    path = files.journal_dir() / name
    if not path.exists():
        raise UiError(f"그런 기록이 없습니다: {name}")
    restored, errors = files.undo(path)
    if not errors:
        path.unlink()
    return {"restored": restored, "errors": errors}


BODY = """
<section class="card">
  <h2>무엇을 정리할까요</h2>
  <div class="row">
    <div style="flex:2 1 22rem">
      <label for="path">폴더 경로</label>
      <input type="text" id="path" placeholder="예: ~/다운로드" spellcheck="false">
    </div>
    <div>
      <label for="mode">정리 방식</label>
      <select id="mode">%(modes)s</select>
    </div>
    <div style="flex:0 1 8rem">
      <label for="min_age">며칠 지난 것만</label>
      <input type="text" id="min_age" placeholder="0" spellcheck="false">
    </div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="recursive"> 하위 폴더까지</label>
    <label><input type="checkbox" id="hidden"> 숨김 파일도</label>
    <label><input type="checkbox" id="fixname"> 옮기면서 이름도 다듬기</label>
  </div>
  <div class="actions">
    <button class="primary" id="btn-preview">미리보기</button>
    <button id="btn-apply" disabled>이대로 옮기기</button>
    <span class="spacer"></span>
    <span class="note">미리보기 없이는 아무것도 바뀌지 않습니다.</span>
  </div>
  <div id="msg"></div>
</section>

<section class="card">
  <h2>계획</h2>
  <div id="plan"><div class="empty">폴더를 넣고 미리보기를 눌러 주세요.</div></div>
</section>

<section class="card">
  <h2>되돌리기</h2>
  <p class="note">옮긴 기록은 <code>~/.attools/journal/</code> 에 남습니다.
     고른 기록을 되돌리면 파일이 원래 자리로 갑니다.</p>
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
  const plan = $("plan"), msg = $("msg");
  let ready = false;

  function values() {
    return {
      path: $("path").value,
      mode: $("mode").value,
      min_age: $("min_age").value,
      recursive: $("recursive").checked,
      hidden: $("hidden").checked,
      fixname: $("fixname").checked,
    };
  }

  function draw(data) {
    plan.innerHTML = AT.table(["지금 이름", "옮길 곳"], data.rows);
  }

  function lock(state) {
    $("btn-apply").disabled = !state;
    ready = state;
  }

  ["path", "mode", "min_age"].forEach(function (id) {
    $(id).addEventListener("input", function () { lock(false); });
  });
  ["recursive", "hidden", "fixname"].forEach(function (id) {
    $(id).addEventListener("change", function () { lock(false); });
  });

  $("btn-preview").addEventListener("click", async function () {
    try {
      const data = await AT.call("/api/files/preview", values());
      draw(data);
      if (data.count) {
        AT.message(msg, "<b>" + data.count + "개</b>를 옮길 수 있습니다. " +
                   AT.esc(data.root), "ok");
        lock(true);
      } else {
        AT.message(msg, "옮길 것이 없습니다.", "");
        lock(false);
      }
    } catch (e) { AT.message(msg, AT.esc(e.message), "bad"); lock(false); }
  });

  $("btn-apply").addEventListener("click", async function () {
    if (!ready) return;
    if (!confirm("파일을 실제로 옮깁니다. 계속할까요?")) return;
    try {
      const data = await AT.call("/api/files/apply", values());
      draw(data);
      AT.message(msg, "<b>" + data.applied + "개</b>를 옮겼습니다. 기록: " +
                 AT.esc(data.journal), "ok");
      lock(false);
      await loadJournals();
    } catch (e) { AT.message(msg, AT.esc(e.message), "bad"); }
  });

  async function loadJournals() {
    try {
      const data = await AT.call("/api/files/journals", {});
      const sel = $("journal");
      sel.innerHTML = data.rows.length
        ? data.rows.map(r => '<option value="' + AT.esc(r[0]) + '">' +
            AT.esc(r[0]) + " (" + AT.esc(r[1]) + "개)</option>").join("")
        : '<option value="">되돌릴 기록이 없습니다</option>';
    } catch (e) { /* 기록이 없어도 화면은 돈다 */ }
  }

  $("btn-undo").addEventListener("click", async function () {
    const name = $("journal").value;
    if (!name) return;
    if (!confirm(name + " 기록을 되돌립니다. 계속할까요?")) return;
    try {
      const data = await AT.call("/api/files/undo", { journal: name });
      const tail = data.errors.length
        ? " 못 되돌린 것 " + data.errors.length + "개: " +
          AT.esc(data.errors.join(", "))
        : "";
      AT.message($("undomsg"), "<b>" + data.restored + "개</b>를 되돌렸습니다." +
                 tail, data.errors.length ? "bad" : "ok");
      await loadJournals();
    } catch (e) { AT.message($("undomsg"), AT.esc(e.message), "bad"); }
  });

  loadJournals();
})();
</script>
""" % {"modes": "".join(
    f'<option value="{k}">{v}</option>' for k, v in MODES.items())}


def make() -> App:
    return App(
        key="files",
        name="파일 정리",
        summary="어질러진 폴더를 종류별·날짜별로 묶고, 되돌린다",
        subtitle="미리보기 → 옮기기 → 되돌리기",
        body=lambda: BODY,
        actions={"preview": preview, "apply": apply,
                 "journals": journals, "undo": undo},
        aliases=("파일", "정리"),
    )
