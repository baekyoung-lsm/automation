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
    "photo-month": "사진을 찍은 달별 (EXIF)",
    "photo-year": "사진을 찍은 해별 (EXIF)",
    "fixname": "옮기지 않고 이름만 다듬기",
}


def _plan(payload: dict) -> tuple[Path, list[files.Move], list[str]]:
    """계획과 함께 «못 한 것»을 돌려준다. 조용히 빼놓지 않기 위해서다."""
    root = form.folder(payload)
    mode = form.choice(payload, "mode", MODES, "ext")
    recursive = form.flag(payload, "recursive")
    hidden = form.flag(payload, "hidden")
    notes: list[str] = []

    if mode == "fixname":
        moves = files.plan_fixname(
            root, recursive=recursive, include_hidden=hidden,
            space="underscore" if form.flag(payload, "underscore") else "keep")
    elif mode.startswith("photo-"):
        plan = files.plan_photos(
            root, by=mode.split("-", 1)[1], recursive=recursive,
            include_hidden=hidden, use_mtime=form.flag(payload, "mtime"))
        moves = plan.moves
        if plan.from_exif:
            notes.append(f"촬영 시각으로 {plan.from_exif}개")
        if plan.from_mtime:
            notes.append(f"수정 시각으로 {len(plan.from_mtime)}개 "
                         "(복사한 날일 수 있습니다)")
        if plan.left:
            notes.append(f"촬영 시각을 못 읽어 두고 온 사진 {len(plan.left)}개 "
                         "(JPEG 의 EXIF 만 읽습니다)")
    else:
        moves = files.plan_organize(
            root, by=mode, recursive=recursive, include_hidden=hidden,
            min_age_days=form.number(payload, "min_age", 0.0, low=0.0, high=36500.0),
            fixname=form.flag(payload, "fixname"))
    return root, moves, notes


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
    root, moves, notes = _plan(payload)
    return {"root": str(root), "count": len(moves),
            "rows": _rows(root, moves), "notes": notes}


def apply(payload: dict) -> dict:
    """계획을 여기서 다시 세운다. 화면이 보낸 경로를 그대로 옮기지 않는다."""
    root, moves, notes = _plan(payload)
    if not moves:
        raise UiError("옮길 것이 없습니다. 먼저 미리보기로 확인해 주세요.")
    journal = files.apply_moves(moves)
    return {"applied": len(moves), "root": str(root),
            "journal": journal.name if journal else "",
            "rows": _rows(root, moves), "notes": notes}


DUPE_DEST = "_중복"


def _dupe_groups(payload: dict):
    root = form.folder(payload)
    groups = files.find_duplicates(
        root, recursive=not form.flag(payload, "flat"),
        include_hidden=form.flag(payload, "hidden"),
        min_size=int(form.number(payload, "min_size", 1024, low=1,
                                 high=1 << 40)))
    keep = form.choice(payload, "keep", files.KEEP_MODES, "shortest")
    return root, groups, keep


def dupes(payload: dict) -> dict:
    root, groups, keep = _dupe_groups(payload)
    rows, wasted = [], 0
    for number, group in enumerate(groups[:40], 1):
        size = group[0].stat().st_size
        wasted += size * (len(group) - 1)
        keeper = files.pick_keeper(group, keep)
        for path in sorted(group):
            rows.append([str(number), "남김" if path == keeper else "중복",
                         str(path.relative_to(root)), files.human_size(size)])
    return {"rows": rows, "groups": len(groups),
            "wasted": files.human_size(wasted),
            "keep": files.KEEP_MODES[keep],
            "shown": min(len(groups), 40)}


def _collect_plan(payload: dict):
    root, groups, keep = _dupe_groups(payload)
    if not groups:
        raise UiError("중복 파일이 없습니다.")
    moves = files.plan_collect_dupes(root, groups, root / DUPE_DEST, keep=keep)
    if not moves:
        raise UiError("모을 것이 없습니다. 이미 다 모아 두었습니다.")
    return root, moves


def collect_preview(payload: dict) -> dict:
    root, moves = _collect_plan(payload)
    return {"count": len(moves), "dest": str(root / DUPE_DEST),
            "rows": _rows(root, moves)}


def collect_apply(payload: dict) -> dict:
    """지우지 않고 옮긴다. 저널에 남아 되돌리기에서 함께 보인다."""
    root, moves = _collect_plan(payload)
    journal = files.apply_moves(moves)
    return {"applied": len(moves), "dest": str(root / DUPE_DEST),
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
    <label><input type="checkbox" id="mtime"> 사진: 촬영 시각이 없으면 수정 시각으로</label>
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
  <h2>중복 찾기</h2>
  <p class="note">내용이 똑같은 파일을 찾습니다. <b>지우지 않고</b>
     무리마다 하나만 남긴 뒤 나머지를 <code>_중복/</code> 으로 옮깁니다.
     옮긴 것은 아래 되돌리기에서 통째로 되돌아옵니다.</p>
  <div class="row">
    <div><label for="keep">무리마다 남길 것</label>
      <select id="keep"><option value="shortest">경로가 가장 짧은 것 (대개 원본 자리)</option><option value="first">이름 순으로 첫 번째</option><option value="oldest">수정 시각이 가장 이른 것</option></select></div>
    <div style="flex:0 1 10rem"><label for="min_size">최소 크기(바이트)</label>
      <input type="text" id="min_size" value="1024" spellcheck="false"></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="flat"> 하위 폴더는 보지 않기</label>
  </div>
  <div class="actions">
    <button class="primary" id="btn-dupes">찾기</button>
    <button id="btn-collect">모으면 어떻게 되나</button>
    <button id="btn-collect-apply" disabled>_중복/ 으로 옮기기</button>
  </div>
  <div id="dupemsg"></div>
  <div id="dupes"></div>
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
      mtime: $("mtime").checked,
    };
  }

  function draw(data) {
    plan.innerHTML = AT.table(["지금 이름", "옮길 곳"], data.rows) +
      (data.notes && data.notes.length
        ? '<p class="note">' + data.notes.map(AT.esc).join(" · ") + "</p>"
        : "");
  }

  function lock(state) {
    $("btn-apply").disabled = !state;
    ready = state;
  }

  ["path", "mode", "min_age"].forEach(function (id) {
    $(id).addEventListener("input", function () { lock(false); });
  });
  ["recursive", "hidden", "fixname", "mtime"].forEach(function (id) {
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

  function dupeValues() {
    return {
      path: $("path").value, keep: $("keep").value,
      min_size: $("min_size").value, flat: $("flat").checked,
      hidden: $("hidden").checked,
    };
  }

  function lockCollect(state) { $("btn-collect-apply").disabled = !state; }
  ["keep", "min_size", "flat"].forEach(function (id) {
    $(id).addEventListener("change", function () { lockCollect(false); });
  });

  $("btn-dupes").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/files/dupes", dupeValues());
      $("dupes").innerHTML = d.groups
        ? AT.table(["무리", "", "파일", "크기"], d.rows,
                   ["num", null, null, "num"]) +
          (d.groups > d.shown ? '<p class="note">무리 ' + (d.groups - d.shown) +
            "개는 줄였습니다.</p>" : "")
        : '<div class="empty">중복 파일이 없습니다.</div>';
      AT.message($("dupemsg"), d.groups
        ? "<b>" + d.groups + "무리</b>, 되찾을 수 있는 용량 " + AT.esc(d.wasted) +
          " · 남길 기준: " + AT.esc(d.keep)
        : "중복 파일이 없습니다.", d.groups ? "ok" : "");
      lockCollect(false);
    } catch (e) { AT.message($("dupemsg"), AT.esc(e.message), "bad"); }
  });

  $("btn-collect").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/files/collect_preview", dupeValues());
      $("dupes").innerHTML = AT.table(["지금 이름", "옮길 곳"], d.rows);
      AT.message($("dupemsg"), "<b>" + d.count + "개</b>를 " +
                 AT.esc(d.dest) + " 로 옮깁니다. 지우지 않습니다.", "ok");
      lockCollect(true);
    } catch (e) {
      AT.message($("dupemsg"), AT.esc(e.message), "bad");
      lockCollect(false);
    }
  });

  $("btn-collect-apply").addEventListener("click", async function () {
    if (!confirm("중복 파일을 _중복/ 으로 옮깁니다. 계속할까요?")) return;
    try {
      const d = await AT.call("/api/files/collect_apply", dupeValues());
      $("dupes").innerHTML = AT.table(["지금 이름", "옮긴 곳"], d.rows);
      AT.message($("dupemsg"), "<b>" + d.applied + "개</b>를 옮겼습니다. 기록: " +
                 AT.esc(d.journal) + " · 눈으로 확인한 뒤 폴더째 지우세요.", "ok");
      lockCollect(false);
      await loadJournals();
    } catch (e) { AT.message($("dupemsg"), AT.esc(e.message), "bad"); }
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
        actions={"preview": preview, "apply": apply, "dupes": dupes,
                 "collect_preview": collect_preview,
                 "collect_apply": collect_apply,
                 "journals": journals, "undo": undo},
        aliases=("파일", "정리"),
        section="파일과 표",
    )
