"""단축키 화면. 한글·워드·엑셀·PPT·구글 문서 단축키를 나란히 놓고 찾는다."""

from __future__ import annotations

from ... import keys
from .. import App, UiError, form


def _groups():
    try:
        return keys.load_groups()[0]
    except keys.KeysError as exc:
        raise UiError(str(exc)) from None


def groups(payload: dict) -> dict:
    rows = []
    for group in _groups():
        unknown = sum(len(item.unknown_apps(group.app_ids)) for item in group.items)
        rows.append({"id": group.id, "name": group.name, "desc": group.desc,
                     "items": len(group.items), "unknown": unknown})
    return {"groups": rows}


def table(payload: dict) -> dict:
    found = _groups()
    wanted = form.text(payload, "group") or found[0].id
    try:
        group = keys.find_group(found, wanted)
    except keys.KeysError as exc:
        raise UiError(str(exc)) from None

    query = form.text(payload, "query")
    items = keys.search(group, query)
    items.sort(key=lambda i: (i.cat, -i.freq, i.name))

    apps = group.app_ids
    rows = [[item.name, item.cat] + [item.shortcut(app) for app in apps]
            for item in items]
    unknown = sum(len(item.unknown_apps(apps)) for item in items)
    return {
        "headers": ["기능", "갈래"] + [group.app_name(app) for app in apps],
        "rows": rows,
        "count": len(items),
        "total": len(group.items),
        "unknown": unknown,
        "name": group.name,
        "desc": group.desc,
    }


BODY = """
<section class="card">
  <h2>어느 프로그램의 단축키</h2>
  <nav class="tabs" id="tabs"></nav>
  <div class="row">
    <div>
      <label for="query">찾기 (기능 이름이나 키 조합)</label>
      <input type="text" id="query" placeholder="예: 찾기, ctrl f, 서식"
             spellcheck="false" autocomplete="off">
    </div>
  </div>
  <div id="msg"></div>
</section>

<section class="card">
  <h2 id="title">단축키</h2>
  <div id="table"><div class="empty">불러오는 중…</div></div>
  <p class="note"><b>—</b> 는 기본 단축키가 없다고 확인한 것,
     <b>?</b> 는 아직 확인하지 못한 것입니다. 지어내지 않고 둘을 구분해 둡니다.
     내 단축키는 <code>~/.attools/shortcuts.json</code> 에 더할 수 있습니다.</p>
</section>

<script>
(function () {
  const $ = (id) => document.getElementById(id);
  let current = "";
  let timer = null;

  async function draw() {
    try {
      const d = await AT.call("/api/keys/table",
                              { group: current, query: $("query").value });
      $("title").textContent = d.name + " — " + d.desc;
      $("table").innerHTML = AT.table(d.headers, d.rows);
      AT.message($("msg"), "<b>" + d.count + "개</b>" +
        (d.count === d.total ? "" : " / 모두 " + d.total + "개") +
        (d.unknown ? " · 확인하지 못한 칸 " + d.unknown + "개" : ""), "ok");
    } catch (e) { AT.message($("msg"), AT.esc(e.message), "bad"); }
  }

  $("query").addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(draw, 120);
  });

  (async function start() {
    try {
      const d = await AT.call("/api/keys/groups", {});
      current = d.groups.length ? d.groups[0].id : "";
      $("tabs").innerHTML = d.groups.map(function (g, i) {
        return '<button data-group="' + AT.esc(g.id) + '" aria-selected="' +
               (i === 0) + '">' + AT.esc(g.name) + "</button>";
      }).join("");
      $("tabs").querySelectorAll("button").forEach(function (btn) {
        btn.addEventListener("click", function () {
          current = btn.dataset.group;
          $("tabs").querySelectorAll("button").forEach(function (b) {
            b.setAttribute("aria-selected", String(b === btn));
          });
          draw();
        });
      });
      await draw();
    } catch (e) { AT.message($("msg"), AT.esc(e.message), "bad"); }
  })();
})();
</script>
"""


def make() -> App:
    return App(
        key="keys",
        name="단축키",
        summary="한글·워드·엑셀·PPT·구글 문서 단축키를 나란히 놓고 찾는다",
        subtitle="읽기만 합니다",
        body=lambda: BODY,
        actions={"groups": groups, "table": table},
        aliases=("단축키", "키"),
        section="그 밖",
    )
