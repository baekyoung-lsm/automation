"""단축키 모음을 브라우저에서 열어 보는 단일 HTML 파일로 뽑는다."""

from __future__ import annotations

import json
from pathlib import Path

from .keys import Group

TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>단축키 모음</title>
<style>
:root {
  --bg:#fbfbfa; --card:#fff; --ink:#1d1c1a; --dim:#6b6862; --line:#e4e1dc;
  --accent:#9a5b34; --accent-soft:#f3e9e2; --pin:#c98a2e;
}
@media (prefers-color-scheme: dark) {
  :root { --bg:#191817; --card:#232120; --ink:#eceae6; --dim:#9c968d; --line:#37342f;
          --accent:#d9a179; --accent-soft:#33291f; --pin:#e0b25e; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 -apple-system,
  BlinkMacSystemFont,"Segoe UI","Pretendard","Malgun Gothic","맑은 고딕",sans-serif; }
.wrap { max-width:1080px; margin:0 auto; padding:24px 20px 64px; }
h1 { font-size:19px; margin:0 0 2px; letter-spacing:-0.01em; }
.sub { color:var(--dim); font-size:13px; margin-bottom:18px; }
.tabs { display:flex; gap:4px; flex-wrap:wrap; border-bottom:1px solid var(--line);
  margin-bottom:14px; }
.tab { padding:8px 14px; border:0; background:none; color:var(--dim); cursor:pointer;
  font:inherit; font-weight:600; border-bottom:2px solid transparent; margin-bottom:-1px; }
.tab[aria-selected="true"] { color:var(--accent); border-bottom-color:var(--accent); }
.tab:hover { color:var(--ink); }
.bar { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:14px; }
input[type=search], select { font:inherit; padding:7px 10px; border:1px solid var(--line);
  border-radius:7px; background:var(--card); color:var(--ink); }
input[type=search] { flex:1; min-width:200px; }
.count { color:var(--dim); font-size:13px; }
table { width:100%; border-collapse:collapse; background:var(--card);
  border:1px solid var(--line); border-radius:10px; overflow:hidden; }
th, td { text-align:left; padding:9px 12px; border-bottom:1px solid var(--line);
  vertical-align:middle; }
th { font-size:12px; color:var(--dim); font-weight:600; letter-spacing:0.02em;
  background:var(--bg); position:sticky; top:0; }
tr:last-child td { border-bottom:0; }
tr.row:hover td { background:var(--accent-soft); }
td.name { font-weight:600; white-space:nowrap; }
td.cat { color:var(--dim); font-size:12px; white-space:nowrap; }
kbd { display:inline-block; font:13px/1.3 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  background:var(--bg); border:1px solid var(--line); border-bottom-width:2px;
  border-radius:5px; padding:2px 6px; white-space:nowrap; }
.none { color:var(--dim); }
.unknown { color:var(--dim); font-style:italic; cursor:help; }
.legend { color:var(--dim); font-size:12px; margin-left:auto; }
.tools { white-space:nowrap; text-align:right; }
.tools button { border:0; background:none; cursor:pointer; color:var(--dim);
  font:inherit; padding:2px 4px; border-radius:4px; opacity:0; transition:opacity .12s; }
tr:hover .tools button, tr.pinned .tools button, .tools button:focus { opacity:1; }
@media (hover:none) { .tools button { opacity:1; } }
.tools button:hover { background:var(--accent-soft); color:var(--ink); }
#reset { border:1px solid var(--line); border-radius:7px; background:var(--card);
  color:var(--dim); padding:7px 12px; font-weight:400; }
#reset:hover { color:var(--ink); border-color:var(--dim); }
.pinned td.name::before { content:"★ "; color:var(--pin); }
.hits { color:var(--dim); font-size:12px; }
footer { margin-top:22px; color:var(--dim); font-size:12px; line-height:1.7; }
footer a { color:var(--accent); }
@media print {
  .bar, .tools, footer { display:none; }
  .tab[aria-selected="false"] { display:none; }
  body { background:#fff; }
}
</style>
</head>
<body>
<div class="wrap">
  <h1>단축키 모음</h1>
  <div class="sub">탭으로 프로그램 묶음을 넘기고, 행을 누르면 자주 찾는 순에 반영됩니다.
    기록은 이 브라우저에만 저장됩니다.</div>

  <div class="tabs" id="tabs" role="tablist"></div>
  <div class="bar">
    <input type="search" id="q" placeholder="기능 이름이나 키로 검색 (예: 붙여넣기, ctrl+shift+v)">
    <select id="sort">
      <option value="freq">자주 찾는 순</option>
      <option value="abc">가나다 순</option>
      <option value="custom">사용자 순</option>
      <option value="cat">분류 순</option>
    </select>
    <span class="count" id="count"></span>
    <span class="legend">— 기본 단축키 없음 · ? 확인 못 함</span>
    <button id="reset" title="이 묶음의 기록과 순서를 지웁니다">기록 지우기</button>
  </div>

  <table><thead id="thead"></thead><tbody id="tbody"></tbody></table>

  <footer id="foot"></footer>
</div>

<script>
const DATA = __DATA__;
const KEY = "attools.keys.v1";
const NONE = "없음";   // 확인했고 기본 단축키가 없는 기능
let store = { hits:{}, order:{}, pins:[] };
try { store = Object.assign(store, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch (e) {}
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(store)); } catch (e) {} };

let gi = 0, sortMode = "freq", query = "";
const norm = s => (s || "").toLowerCase().replace(/[\\s\\-_+·,]/g, "");
const uid = (g, it) => g.id + ":" + it.name;

function visible() {
  const g = DATA.groups[gi];
  const needle = norm(query);
  let items = g.items.filter(it => !needle || norm(
    [it.name, it.cat].concat(g.apps.map(a => {
      const v = it.keys[a.id];
      return !v || v === NONE ? "" : v;
    })).join(" ")).includes(needle));

  const hits = it => store.hits[uid(g, it)] || 0;
  if (sortMode === "freq") {
    items.sort((a, b) => hits(b) - hits(a) || b.freq - a.freq || a.name.localeCompare(b.name, "ko"));
  } else if (sortMode === "abc") {
    items.sort((a, b) => a.name.localeCompare(b.name, "ko"));
  } else if (sortMode === "cat") {
    items.sort((a, b) => a.cat.localeCompare(b.cat, "ko") || b.freq - a.freq
      || a.name.localeCompare(b.name, "ko"));
  } else {
    const order = store.order[g.id] || [];
    const rank = n => { const i = order.indexOf(n); return i < 0 ? order.length : i; };
    items.sort((a, b) => rank(a.name) - rank(b.name) || hits(b) - hits(a)
      || a.name.localeCompare(b.name, "ko"));
  }
  const pinned = items.filter(it => store.pins.includes(uid(g, it)));
  return pinned.length ? pinned.concat(items.filter(it => !pinned.includes(it))) : items;
}

function moveItem(name, delta) {
  const g = DATA.groups[gi];
  let order = store.order[g.id] || visible().map(it => it.name);
  if (!order.includes(name)) order.push(name);
  const i = order.indexOf(name);
  const j = Math.max(0, Math.min(order.length - 1, i + delta));
  order.splice(j, 0, order.splice(i, 1)[0]);
  store.order[g.id] = order;
  sortMode = "custom";
  document.getElementById("sort").value = "custom";
  save(); render();
}

function render() {
  const g = DATA.groups[gi];
  document.getElementById("tabs").innerHTML = DATA.groups.map((x, n) =>
    `<button class="tab" role="tab" aria-selected="${n === gi}" data-i="${n}">${x.name}</button>`
  ).join("");
  document.querySelectorAll("#tabs .tab").forEach(b => b.onclick = () => {
    gi = +b.dataset.i; render();
  });

  document.getElementById("thead").innerHTML =
    "<tr><th>기능</th><th>분류</th>" + g.apps.map(a => `<th>${a.name}</th>`).join("")
    + '<th class="tools">횟수</th></tr>';

  const items = visible();
  document.getElementById("count").textContent =
    `${g.desc} · ${items.length}개` + (query ? ` (전체 ${g.items.length})` : "");

  document.getElementById("tbody").innerHTML = items.map(it => {
    const id = uid(g, it);
    const hits = store.hits[id] || 0;
    const cells = g.apps.map(a => {
      const v = it.keys[a.id];
      if (v === NONE) return '<td class="none" title="기본 단축키가 없는 기능">—</td>';
      if (!v) return '<td class="unknown" title="아직 확인하지 못한 칸">?</td>';
      return `<td><kbd>${v}</kbd></td>`;
    }).join("");
    return `<tr class="row ${store.pins.includes(id) ? "pinned" : ""}" data-name="${it.name}">
      <td class="name">${it.name}</td><td class="cat">${it.cat}</td>${cells}
      <td class="tools"><span class="hits">${hits || ""}</span>
        <button data-act="pin" title="맨 위에 고정">★</button>
        <button data-act="up" title="사용자 순서에서 위로">↑</button>
        <button data-act="down" title="사용자 순서에서 아래로">↓</button></td></tr>`;
  }).join("");

  document.querySelectorAll("#tbody tr").forEach(tr => {
    const name = tr.dataset.name;
    const id = g.id + ":" + name;
    tr.onclick = e => {
      const act = e.target.dataset ? e.target.dataset.act : null;
      if (act === "pin") {
        const i = store.pins.indexOf(id);
        i < 0 ? store.pins.push(id) : store.pins.splice(i, 1);
      } else if (act === "up") { moveItem(name, -1); return; }
      else if (act === "down") { moveItem(name, 1); return; }
      else { store.hits[id] = (store.hits[id] || 0) + 1; }
      save(); render();
    };
  });

  document.getElementById("foot").innerHTML =
    "출처: " + Object.entries(DATA.sources).map(([k, v]) =>
      `<a href="${v}" target="_blank" rel="noopener">${k}</a>`).join(" · ")
    + "<br>—는 기본 단축키가 없는 기능, ?는 아직 확인하지 못한 칸입니다. "
    + "프로그램 버전과 설정에 따라 다를 수 있습니다.";
}

document.getElementById("q").addEventListener("input", e => { query = e.target.value; render(); });
document.getElementById("sort").addEventListener("change", e => {
  sortMode = e.target.value; render();
});
document.getElementById("reset").addEventListener("click", () => {
  const g = DATA.groups[gi];
  if (!confirm(`'${g.name}' 묶음의 조회 기록과 사용자 순서를 지웁니다.`)) return;
  g.items.forEach(it => delete store.hits[uid(g, it)]);
  delete store.order[g.id];
  store.pins = store.pins.filter(p => !p.startsWith(g.id + ":"));
  save(); render();
});
document.addEventListener("keydown", e => {
  const typing = ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName);
  if (e.key === "/" && !typing) { e.preventDefault(); document.getElementById("q").focus(); }
  else if (e.key === "Escape") { document.getElementById("q").value = ""; query = ""; render(); }
  else if (!typing && e.key >= "1" && e.key <= String(DATA.groups.length)) {
    gi = +e.key - 1; render();
  } else if (!typing && (e.key === "ArrowRight" || e.key === "ArrowLeft")) {
    gi = (gi + (e.key === "ArrowRight" ? 1 : DATA.groups.length - 1)) % DATA.groups.length;
    render();
  }
});
render();
</script>
</body>
</html>
"""


def build(groups: list[Group], sources: dict) -> str:
    data = {
        "sources": sources,
        "groups": [
            {
                "id": g.id, "name": g.name, "desc": g.desc,
                "apps": g.apps,
                "items": [{"name": i.name, "cat": i.cat, "freq": i.freq, "keys": i.keys}
                          for i in g.items],
            }
            for g in groups
        ],
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", payload)


def write(path: Path, groups: list[Group], sources: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(groups, sources), encoding="utf-8")
    return path
