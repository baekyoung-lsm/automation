"""git 화면. 저장소를 훑어보기만 한다 - 브랜치를 지우거나 커밋하지 않는다."""

from __future__ import annotations

from ... import files
from ...code import gitkit, todo
from .. import App, UiError, form

MAX_ROWS = 60


def _root(payload: dict):
    where = form.folder(payload)
    try:
        return gitkit.repo_root(where)
    except RuntimeError as exc:
        raise UiError(f"git 저장소가 아닙니다: {where} ({exc})") from None
    except FileNotFoundError:
        raise UiError("git 을 찾지 못했습니다. 설치돼 있는지 확인해 주세요.") from None


def scan(payload: dict) -> dict:
    root = _root(payload)
    findings = gitkit.scan_paths(root, tracked=True)
    rows = [[f.kind, f.path, str(f.line), f.excerpt] for f in findings[:MAX_ROWS]]
    return {"rows": rows, "total": len(findings), "root": str(root),
            "note": "찾은 것이 모두 진짜 시크릿은 아니고, 못 찾는 것도 있습니다. "
                    "커밋 전에 눈으로 한 번 더 보세요."}


def branches(payload: dict) -> dict:
    root = _root(payload)
    try:
        sweep = gitkit.find_stale_branches(root)
    except RuntimeError as exc:
        raise UiError(str(exc)) from None
    rows = [["병합 끝남", name] for name in sweep.merged]
    rows += [["원격이 사라짐", name] for name in sweep.gone]
    return {"rows": rows, "base": sweep.base, "current": sweep.current,
            "note": "이 화면은 브랜치를 지우지 않습니다. "
                    "터미널에서 at git sweep --apply 로 지우세요."}


def ready(payload: dict) -> dict:
    """커밋 전 점검. 스테이징된 것만 본다."""
    root = _root(payload)
    names = [n for n in gitkit.run(["diff", "--cached", "--name-only"],
                                   root).splitlines() if n]
    if not names:
        raise UiError("스테이징된 파일이 없습니다. 먼저 git add 를 하세요.")

    rows = []
    for finding in gitkit.scan_paths(root, staged=True)[:MAX_ROWS]:
        rows.append(["시크릿", f"{finding.path}:{finding.line}",
                     finding.kind, finding.excerpt[:60]])
    for conflict in gitkit.scan_conflicts(root, names=names)[:MAX_ROWS]:
        rows.append(["충돌 표시", f"{conflict.path}:{conflict.line}", "", ""])
    for mark in gitkit.find_debug_marks(gitkit.staged_added_lines(root))[:MAX_ROWS]:
        rows.append(["디버그 흔적", mark.path, mark.kind, mark.line[:60]])
    for name, size in gitkit.staged_big_files(root)[:MAX_ROWS]:
        rows.append(["큰 파일", name, files.human_size(size), ""])

    return {"rows": rows, "staged": len(names), "count": len(rows),
            "note": "의도한 것이면 그대로 커밋하세요. 여기서 막지는 않습니다. "
                    "디버그 흔적은 이번에 더한 줄에서만 찾습니다."}


def conflicts(payload: dict) -> dict:
    root = _root(payload)
    found = gitkit.scan_conflicts(root)
    rows = [[c.path, str(c.line), str(c.ours), str(c.theirs),
             "한쪽이 비었음" if c.one_sided else ""] for c in found[:MAX_ROWS]]
    return {"rows": rows, "total": len(found),
            "note": "병합 중이 아니어도 남아 있는 충돌 표시를 찾습니다."}


def todos(payload: dict) -> dict:
    root = _root(payload)
    found = todo.collect(root)
    if form.flag(payload, "blame"):
        try:
            todo.add_blame(root, found)
        except RuntimeError:
            pass                       # blame 이 안 되는 저장소여도 목록은 낸다
    found = todo.sort_todos(found, "age" if form.flag(payload, "blame") else "severity")
    # 표 한 칸에 들어가야 하므로 줄바꿈을 공백으로 눕힌다
    rows = [[t.marker, t.path, str(t.line), " ".join(t.text.split())[:60],
             t.owner or t.author,
             "" if t.age_days is None else f"{t.age_days}일"]
            for t in found[:MAX_ROWS]]
    return {"rows": rows, "total": len(found),
            "summary": [[k, str(v)] for k, v in todo.summarize(found).items()],
            "note": "주석 안에 있는 것만 셉니다. 문자열 속 TODO 는 세지 않습니다."}


def stats(payload: dict) -> dict:
    root = _root(payload)
    since = form.text(payload, "since") or "3 months ago"
    try:
        commits = gitkit.read_log(root, since=since)
    except RuntimeError as exc:
        raise UiError(str(exc)) from None
    if not commits:
        return {"authors": [], "churn": [], "count": 0, "since": since}

    authors = [[name, str(n), f"{added:,}", f"{deleted:,}"]
               for name, n, added, deleted in gitkit.by_author(commits)]
    churn = [[f.path, str(f.commits), f"{f.churn:,}", str(len(f.authors))]
             for f in gitkit.churn_by_file(commits)[:20]]
    return {"authors": authors, "churn": churn, "count": len(commits),
            "since": since}


BODY = """
<section class="card">
  <h2>어느 저장소</h2>
  <div class="row">
    <div style="flex:3 1 22rem">
      <label for="path">폴더 (안쪽 어디든 됩니다)</label>
      <input type="text" id="path" placeholder="예: ~/코드/내프로젝트" data-browse="dir" spellcheck="false">
    </div>
  </div>
  <nav class="tabs" id="tabs" style="margin-top:1.1rem">
    <button data-tab="scan" aria-selected="true">시크릿 검사</button>
    <button data-tab="branches" aria-selected="false">묵은 브랜치</button>
    <button data-tab="ready" aria-selected="false">커밋 전 점검</button>
  <button data-tab="conflicts" aria-selected="false">충돌 표시</button>
    <button data-tab="todos" aria-selected="false">TODO</button>
    <button data-tab="stats" aria-selected="false">커밋 통계</button>
  </nav>
  <p class="note">이 화면은 읽기만 합니다. 지우거나 커밋하지 않습니다.</p>
  <div id="msg"></div>
</section>

<section class="card" data-panel="scan">
  <h2>커밋하면 안 될 값이 있나</h2>
  <div class="actions"><button class="primary" id="btn-scan">검사</button></div>
  <div id="scan-out"></div>
</section>

<section class="card" data-panel="branches" hidden>
  <h2>병합이 끝났거나 원격이 사라진 브랜치</h2>
  <div class="actions"><button class="primary" id="btn-branches">찾기</button></div>
  <div id="branches-out"></div>
</section>

<section class="card" data-panel="ready" hidden>
  <h2>커밋 전 점검</h2>
  <p class="note">스테이징한 것만 봅니다 — 시크릿, 남은 충돌 표시,
     이번에 더한 줄의 디버그 흔적, 큰 파일.</p>
  <div class="actions"><button class="primary" id="btn-ready">점검</button></div>
  <div id="ready-out"></div>
</section>

<section class="card" data-panel="conflicts" hidden>
  <h2>남아 있는 충돌 표시</h2>
  <div class="actions"><button class="primary" id="btn-conflicts">찾기</button></div>
  <div id="conflicts-out"></div>
</section>

<section class="card" data-panel="todos" hidden>
  <h2>TODO / FIXME</h2>
  <div class="checks">
    <label><input type="checkbox" id="blame"> 누가 언제 남겼는지도 (느립니다)</label>
  </div>
  <div class="actions"><button class="primary" id="btn-todos">모으기</button></div>
  <div id="todos-out"></div>
</section>

<section class="card" data-panel="stats" hidden>
  <h2>커밋 통계</h2>
  <div class="row">
    <div><label for="since">언제부터</label>
      <input type="text" id="since" placeholder="3 months ago, 2026-01-01" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-stats">세기</button></div>
  </div>
  <div id="stats-out"></div>
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

  function big(t) { return '<p class="big">' + t + "</p>"; }
  function note(t) { return '<p class="note">' + AT.esc(t) + "</p>"; }

  async function run(path, body, draw) {
    try { draw(await AT.call(path, body)); }
    catch (e) { AT.message($("msg"), AT.esc(e.message), "bad"); }
  }

  function where(extra) {
    return Object.assign({ path: $("path").value }, extra || {});
  }

  function tail(total, shown) {
    return total > shown ? note(total + "개 가운데 " + shown + "개만 보입니다.") : "";
  }

  $("btn-scan").addEventListener("click", function () {
    run("/api/git/scan", where(), function (d) {
      $("scan-out").innerHTML = big(d.total ? d.total + "곳이 걸립니다"
                                            : "걸리는 것이 없습니다") +
        (d.total ? AT.table(["무엇", "파일", "줄", "앞부분"], d.rows,
                            [null, null, "num", null]) : "") +
        tail(d.total, d.rows.length) + note(d.note);
      AT.message($("msg"), AT.esc(d.root), d.total ? "bad" : "ok");
    });
  });

  $("btn-branches").addEventListener("click", function () {
    run("/api/git/branches", where(), function (d) {
      $("branches-out").innerHTML = big(d.rows.length
          ? d.rows.length + "개를 정리할 수 있습니다" : "정리할 것이 없습니다") +
        (d.rows.length ? AT.table(["무엇", "브랜치"], d.rows) : "") +
        note("기준 " + d.base + " · 지금 " + d.current) + note(d.note);
      AT.message($("msg"), "봤습니다.", "ok");
    });
  });

  $("btn-ready").addEventListener("click", function () {
    run("/api/git/ready", where(), function (d) {
      $("ready-out").innerHTML = big(d.count
          ? d.count + "건이 걸립니다" : "걸리는 것이 없습니다. 커밋해도 됩니다") +
        (d.count ? AT.table(["무엇", "어디", "종류", "내용"], d.rows) : "") +
        note("스테이징된 파일 " + d.staged + "개") + note(d.note);
      AT.message($("msg"), "봤습니다.", d.count ? "bad" : "ok");
    });
  });

  $("btn-conflicts").addEventListener("click", function () {
    run("/api/git/conflicts", where(), function (d) {
      $("conflicts-out").innerHTML = big(d.total ? d.total + "곳이 남아 있습니다"
                                                 : "남은 충돌 표시가 없습니다") +
        (d.total ? AT.table(["파일", "줄", "우리 쪽", "저쪽", ""], d.rows,
                            [null, "num", "num", "num", null]) : "") +
        tail(d.total, d.rows.length) + note(d.note);
      AT.message($("msg"), "봤습니다.", d.total ? "bad" : "ok");
    });
  });

  $("btn-todos").addEventListener("click", function () {
    run("/api/git/todos", where({ blame: $("blame").checked }), function (d) {
      $("todos-out").innerHTML = big(d.total + "개") +
        (d.summary.length ? AT.table(["표시", "개수"], d.summary, [null, "num"]) : "") +
        (d.total ? AT.table(["표시", "파일", "줄", "내용", "누가", "묵은 정도"],
                            d.rows, [null, null, "num", null, null, "num"]) : "") +
        tail(d.total, d.rows.length) + note(d.note);
      AT.message($("msg"), "모았습니다.", "ok");
    });
  });

  $("btn-stats").addEventListener("click", function () {
    run("/api/git/stats", where({ since: $("since").value }), function (d) {
      $("stats-out").innerHTML = big(d.count + "개 커밋 (" + AT.esc(d.since) + " 이후)") +
        (d.count
          ? "<h2>누가</h2>" +
            AT.table(["이름", "커밋", "더한 줄", "지운 줄"], d.authors,
                     [null, "num", "num", "num"]) +
            "<h2>자주 바뀐 파일</h2>" +
            AT.table(["파일", "커밋", "바뀐 줄", "손댄 사람"], d.churn,
                     [null, "num", "num", "num"])
          : note("그 기간에 커밋이 없습니다."));
      AT.message($("msg"), "세었습니다.", "ok");
    });
  });
})();
</script>
"""


def make() -> App:
    return App(
        key="git",
        name="저장소 훑기",
        summary="커밋 전 점검·시크릿·묵은 브랜치·충돌·TODO·커밋 통계 (읽기만)",
        subtitle="읽기만 합니다 · 지우거나 커밋하지 않습니다",
        body=lambda: BODY,
        actions={"scan": scan, "branches": branches, "conflicts": conflicts,
                 "todos": todos, "stats": stats, "ready": ready},
        aliases=("git", "저장소"),
        section="개발",
    )
