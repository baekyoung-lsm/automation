"""웹 화면의 공용 껍데기. 색·글꼴·표·버튼을 한 벌만 둔다."""

from __future__ import annotations

CSS = """
:root {
  --ink:#1b1a18; --dim:#6f6b64; --paper:#faf9f7; --card:#fff; --line:#e4e0d9;
  --mark:#f2efe9; --blue:#2a78d6; --blue-ink:#fff; --red:#c0392b; --green:#2e7d4f;
  --radius:10px;
}
@media (prefers-color-scheme: dark) {
  :root { --ink:#e9e6e0; --dim:#9a948b; --paper:#141312; --card:#1c1b19;
    --line:#332f2a; --mark:#232120; --blue:#4c94ea; --blue-ink:#0d1117;
    --red:#e57373; --green:#69b98a; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--paper); color:var(--ink); word-break:keep-all;
  font:15px/1.65 "Pretendard","Apple SD Gothic Neo","Malgun Gothic",
  "Noto Sans KR",system-ui,sans-serif; }
a { color:var(--blue); }
header { border-bottom:1px solid var(--line); background:var(--card); }
header .inner { max-width:60rem; margin:0 auto; padding:.9rem 1.2rem;
  display:flex; align-items:baseline; gap:.8rem; }
header h1 { font-size:1.05rem; margin:0; letter-spacing:-0.01em; }
header .sub { color:var(--dim); font-size:.85rem; }
header .home { margin-left:auto; font-size:.85rem; text-decoration:none; }
main { max-width:60rem; margin:0 auto; padding:1.6rem 1.2rem 5rem; }
section.card { background:var(--card); border:1px solid var(--line);
  border-radius:var(--radius); padding:1.1rem 1.2rem; margin-bottom:1.1rem; }
h2 { font-size:.95rem; margin:0 0 .9rem; color:var(--dim); font-weight:600;
  letter-spacing:.02em; }
label { display:block; font-size:.85rem; color:var(--dim); margin-bottom:.35rem; }
input[type=text], select { width:100%; padding:.55rem .7rem; font:inherit;
  color:inherit; background:var(--paper); border:1px solid var(--line);
  border-radius:8px; }
input[type=text]:focus, select:focus { outline:2px solid var(--blue);
  outline-offset:1px; }
.row { display:flex; gap:.8rem; flex-wrap:wrap; align-items:flex-end; }
.row > div { flex:1 1 12rem; }
.checks { display:flex; gap:1rem; flex-wrap:wrap; margin-top:.8rem;
  font-size:.9rem; }
.checks label { display:flex; align-items:center; gap:.35rem; margin:0;
  color:var(--ink); }
button { font:inherit; padding:.55rem 1.1rem; border-radius:8px; cursor:pointer;
  border:1px solid var(--line); background:var(--paper); color:var(--ink); }
button:hover { border-color:var(--dim); }
button.primary { background:var(--blue); border-color:var(--blue);
  color:var(--blue-ink); font-weight:600; }
button.primary:disabled { opacity:.45; cursor:not-allowed; }
button.danger { color:var(--red); }
.actions { display:flex; gap:.6rem; margin-top:1rem; align-items:center;
  flex-wrap:wrap; }
.actions .spacer { flex:1; }
.note { color:var(--dim); font-size:.85rem; }
textarea { width:100%; min-height:7rem; padding:.55rem .7rem; font:inherit;
  color:inherit; background:var(--paper); border:1px solid var(--line);
  border-radius:8px; resize:vertical; }
textarea:focus { outline:2px solid var(--blue); outline-offset:1px; }
nav.tabs { display:flex; gap:.4rem; flex-wrap:wrap; margin:0 0 1.1rem; }
nav.tabs button { padding:.4rem .9rem; font-size:.9rem; }
nav.tabs button[aria-selected="true"] { background:var(--blue);
  border-color:var(--blue); color:var(--blue-ink); font-weight:600; }
.big { font-size:1.4rem; font-weight:600; letter-spacing:-0.01em; }
.tablewrap { overflow-x:auto; border:1px solid var(--line); border-radius:8px; }
table { border-collapse:collapse; width:100%; font-size:.9rem; }
th, td { padding:.45rem .7rem; text-align:left; white-space:nowrap;
  border-bottom:1px solid var(--line); }
th { background:var(--mark); position:sticky; top:0; font-weight:600; }
tr:last-child td { border-bottom:0; }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
pre.diff { margin:.4rem 0 1rem; padding:.6rem .8rem; overflow-x:auto;
  background:var(--mark); border:1px solid var(--line); border-radius:8px;
  font:12.5px/1.55 "D2Coding","Menlo","Consolas",monospace; }
pre.diff.cmd { color:var(--blue); user-select:all; }
pre.diff .add { color:var(--green); }
pre.diff .del { color:var(--red); }
pre.diff .at { color:var(--dim); }
button.spec { padding:.25rem .6rem; font-size:.85rem; margin:.15rem 0; }
.browse { border:1px solid var(--line); border-radius:8px; margin-top:.4rem;
  max-height:15rem; overflow:auto; background:var(--card); }
.browse .head { padding:.4rem .7rem; border-bottom:1px solid var(--line);
  color:var(--dim); font-size:.8rem; position:sticky; top:0;
  background:var(--card); word-break:break-all; }
.browse button.row { display:block; width:100%; text-align:left; border:0;
  border-radius:0; padding:.35rem .7rem; font-size:.9rem; background:none; }
.browse button.row:hover { background:var(--mark); }
.browse button.row.pick { color:var(--blue); }
.browse .empty { padding:.6rem .7rem; }
.file { font-weight:600; font-size:.9rem; margin:.9rem 0 .2rem; }
.msg { padding:.7rem .9rem; border-radius:8px; margin-top:1rem; font-size:.9rem;
  border:1px solid var(--line); background:var(--mark); }
.msg.ok { border-color:var(--green); }
.msg.bad { border-color:var(--red); }
.msg b { font-weight:600; }
.empty { color:var(--dim); padding:1.2rem; text-align:center; }
ul.apps { list-style:none; padding:0; margin:0; display:grid; gap:.8rem;
  grid-template-columns:repeat(auto-fill,minmax(15rem,1fr)); }
ul.apps a { display:block; padding:1rem 1.1rem; border:1px solid var(--line);
  border-radius:var(--radius); background:var(--card); text-decoration:none;
  color:inherit; }
ul.apps a:hover { border-color:var(--blue); }
ul.apps strong { display:block; margin-bottom:.25rem; }
ul.apps span { color:var(--dim); font-size:.85rem; }
footer { max-width:60rem; margin:0 auto; padding:0 1.2rem 3rem;
  color:var(--dim); font-size:.8rem; }
"""

JS = """
window.AT = (function () {
  const token = new URLSearchParams(location.search).get("t") || "";

  async function call(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-At-Token": token },
      body: JSON.stringify(body || {}),
    });
    let data;
    try { data = await res.json(); }
    catch (e) { throw new Error("응답을 읽지 못했습니다 (" + res.status + ")"); }
    if (!res.ok || data.error) throw new Error(data.error || "요청이 실패했습니다");
    return data;
  }

  function table(headers, rows, aligns) {
    if (!rows.length) return '<div class="empty">보여줄 것이 없습니다.</div>';
    const head = headers.map(h => "<th>" + esc(h) + "</th>").join("");
    const body = rows.map(function (row) {
      return "<tr>" + row.map(function (cell, i) {
        const cls = aligns && aligns[i] === "num" ? ' class="num"' : "";
        return "<td" + cls + ">" + esc(cell) + "</td>";
      }).join("") + "</tr>";
    }).join("");
    return '<div class="tablewrap"><table><thead><tr>' + head +
           "</tr></thead><tbody>" + body + "</tbody></table></div>";
  }

  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function message(where, text, kind) {
    where.innerHTML = '<div class="msg ' + (kind || "") + '">' + text + "</div>";
  }

  // 화면마다 최근에 넣은 경로를 기억한다. 브라우저가 아니라 서버에 둔다 -
  // 실행할 때마다 포트가 달라져 localStorage 는 매번 비어 있기 때문이다.
  function remember(scope) {
    if (!scope) return;
    const boxes = [].slice.call(
      document.querySelectorAll("input[type=text][id]"))
      .filter(el => el.dataset.forget === undefined);
    if (!boxes.length) return;

    function fill(el, values) {
      if (!values || !values.length) return;
      let list = document.getElementById("recent-" + el.id);
      if (!list) {
        list = document.createElement("datalist");
        list.id = "recent-" + el.id;
        document.body.appendChild(list);
      }
      // 이 JS 는 파이썬 문자열 안에 있다. 역슬래시 이스케이프는 살아남지
      // 못하므로 따옴표를 섞어 쓴다.
      list.innerHTML = values.map(function (v) {
        return '<option value="' + esc(v).replace(/"/g, "&quot;") + '">';
      }).join("");
      el.setAttribute("list", list.id);
    }

    call("/api/-/recent", { app: scope }).then(function (data) {
      boxes.forEach(function (el) {
        const values = data.fields[el.id];
        fill(el, values);
        if (!el.value && values && values.length) el.value = values[0];
      });
    }).catch(function () { /* 기억이 없어도 화면은 돈다 */ });

    boxes.forEach(function (el) {
      el.addEventListener("change", function () {
        if (!el.value.trim()) return;
        call("/api/-/remember",
             { app: scope, field: el.id, value: el.value })
          .then(function (data) { fill(el, data.values); })
          .catch(function () {});
      });
    });
  }

  // 긴 경로를 손으로 치지 않게, 칸 옆에서 폴더를 훑어 고른다.
  function browse() {
    document.querySelectorAll("input[data-browse]").forEach(function (el) {
      const wants = el.dataset.browse;            // dir 또는 파일 확장자 목록
      const holder = document.createElement("div");
      const open = document.createElement("button");
      open.type = "button";
      open.textContent = "찾아보기";
      open.style.marginTop = ".35rem";
      const panel = document.createElement("div");
      panel.className = "browse";
      panel.hidden = true;
      holder.appendChild(open);
      holder.appendChild(panel);
      el.parentNode.appendChild(holder);

      function row(label, value, pick) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = pick ? "row pick" : "row";
        b.textContent = label;
        b.addEventListener("click", function () {
          if (pick) {
            el.value = value;
            el.dispatchEvent(new Event("change"));
            panel.hidden = true;
            return;
          }
          show(value);
        });
        return b;
      }

      function wanted(name) {
        if (wants === "dir") return false;
        if (wants === "any") return true;
        return wants.split(",").some(function (ext) {
          return name.toLowerCase().endsWith(ext.trim());
        });
      }

      async function show(path) {
        try {
          const d = await call("/api/-/browse", { path: path });
          panel.innerHTML = "";
          const head = document.createElement("div");
          head.className = "head";
          head.textContent = d.here;
          panel.appendChild(head);
          panel.appendChild(row("이 폴더를 고른다", d.here, true));
          if (d.parent) panel.appendChild(row(".. 위로", d.parent, false));
          d.dirs.forEach(function (name) {
            panel.appendChild(row(name + "/", d.here + "/" + name, false));
          });
          d.files.filter(wanted).forEach(function (name) {
            panel.appendChild(row(name, d.here + "/" + name, true));
          });
          panel.hidden = false;
        } catch (e) {
          panel.innerHTML = '<div class="empty">' + esc(e.message) + "</div>";
          panel.hidden = false;
        }
      }

      open.addEventListener("click", function () {
        if (!panel.hidden) { panel.hidden = true; return; }
        show(el.value);
      });
    });
  }

  // 화면에서 한 일을 터미널 명령으로 보여 준다. 다음부터는 직접 칠 수 있다.
  function command(text) {
    if (!text) return "";
    return '<p class="note">터미널에서는 이렇게 합니다</p>' +
           '<pre class="diff cmd">' + esc(text) + "</pre>";
  }

  return { call: call, table: table, esc: esc, message: message,
           token: token, remember: remember, browse: browse,
           command: command };
})();
"""


def page(title: str, subtitle: str, body: str, *, home: bool = True,
         scope: str = "") -> str:
    """화면 한 장. 머리글과 껍데기는 어느 화면이나 같다."""
    from html import escape

    back = '<a class="home" href="/">다른 기능</a>' if home else ""
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · attools</title>
<style>{CSS}</style>
<!-- AT 는 화면 본문의 스크립트보다 먼저 있어야 한다. 본문 스크립트가
     불러오자마자 AT.call 을 쓰는 화면이 있다. -->
<script>{JS}</script>
</head>
<body>
<header><div class="inner">
  <h1>{escape(title)}</h1>
  <span class="sub">{escape(subtitle)}</span>
  {back}
</div></header>
<main>
{body}
</main>
<footer>내 컴퓨터에서만 도는 화면입니다. 창을 닫고 터미널에서 Ctrl+C 를 누르면 끝납니다.</footer>
<script>AT.remember({escape(scope)!r}); AT.browse();</script>
</body>
</html>
"""
