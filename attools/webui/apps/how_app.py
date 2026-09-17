"""«이럴 땐 이렇게» 화면. 하고 싶은 일에서 명령을 찾는다.

터미널 명령을 보여 주는 화면이다. 화면으로 할 수 있는 일이면 그 화면으로
가는 길도 함께 적는다 - 여기서 명령을 베껴 치게만 두면 반쪽이다.
"""

from __future__ import annotations

from ... import recipes
from .. import App, form

# 명령의 갈래와 화면은 하나씩 짝이 있다. 없는 갈래(git 의 일부 등)는 비운다.
SCREENS = {"sheet": "엑셀 정리", "file": "파일 정리", "text": "글자 손질",
           "doc": "문서 손질", "novel": "원고 점검", "dev": "개발 잡일",
           "git": "저장소 훑기", "life": "일상 계산"}
MAX_SHOWN = 40


def _screen_of(one) -> list[str]:
    """이 레시피를 화면으로도 할 수 있나. (화면 key, 이름)"""
    for step in one.steps:
        parts = step.split()
        if len(parts) >= 2 and parts[1] in SCREENS:
            key = parts[1]
            return [{"sheet": "sheet", "file": "files", "text": "text",
                     "doc": "doc", "novel": "novel", "dev": "dev",
                     "git": "git", "life": "life"}[key], SCREENS[key]]
    return []


def _rows(items) -> list[dict]:
    return [{"topic": one.topic, "title": one.title, "steps": one.steps,
             "note": one.note, "screen": _screen_of(one)}
            for one in items[:MAX_SHOWN]]


def find(payload: dict) -> dict:
    """주제나 말로 찾는다. 둘 다 없으면 전부."""
    topic = form.text(payload, "topic")
    needle = form.text(payload, "needle")

    items = recipes.RECIPES
    if topic:
        items = recipes.by_topic(topic)
    if needle:
        found = recipes.search(needle)
        items = [one for one in items if one in found] if topic else found
    return {"rows": _rows(items), "total": len(items),
            "shown": min(len(items), MAX_SHOWN),
            "topics": recipes.topics(),
            "command": form.command("how", needle or topic or "--all")}


BODY = """
<section class="card">
  <h2>무엇을 하려고 하시나요</h2>
  <div class="row">
    <div style="flex:3 1 20rem">
      <label for="needle">하고 싶은 일 (비우면 전부)</label>
      <input type="text" id="needle" placeholder="예: 취합, 개인정보, 합계, 스캔" spellcheck="false">
    </div>
    <div style="flex:0 0 auto" class="actions" style="margin:0">
      <button class="primary" id="btn-find">찾기</button>
    </div>
  </div>
  <div class="checks" id="topics"></div>
  <div id="msg"></div>
</section>

<section class="card">
  <h2>이렇게 합니다</h2>
  <p class="note">명령 줄은 그대로 터미널에 붙여 넣으면 됩니다.
     같은 일을 할 수 있는 화면이 있으면 옆에 적어 두었습니다.</p>
  <div id="list"><div class="empty">찾기를 눌러 주세요.</div></div>
</section>

<script>
(function () {
  const $ = (id) => document.getElementById(id);
  let topic = "";

  function drawTopics(names) {
    if ($("topics").dataset.ready) return;
    $("topics").dataset.ready = "1";
    $("topics").innerHTML = ['<button class="spec" data-t="">전부</button>']
      .concat(names.map(n => '<button class="spec" data-t="' + AT.esc(n) + '">'
                             + AT.esc(n) + "</button>")).join(" ");
    $("topics").querySelectorAll("button.spec").forEach(function (b) {
      b.addEventListener("click", function () {
        topic = b.dataset.t;
        $("topics").querySelectorAll("button.spec").forEach(function (o) {
          o.style.fontWeight = o.dataset.t === topic ? "700" : "";
        });
        run();
      });
    });
  }

  function draw(d) {
    drawTopics(d.topics);
    $("list").innerHTML = d.rows.length ? d.rows.map(function (r) {
      const steps = r.steps.map(s => AT.esc(s)).join("\\n");
      const screen = r.screen.length
        ? '<p class="note">화면으로도 됩니다: <a href="/' +
          AT.esc(r.screen[0]) + "?t=" + encodeURIComponent(AT.token) + '">' +
          AT.esc(r.screen[1]) + "</a></p>"
        : "";
      return '<p class="file">[' + AT.esc(r.topic) + "] " + AT.esc(r.title) +
             '</p><pre class="diff cmd">' + steps + "</pre>" +
             (r.note ? '<p class="note">' + AT.esc(r.note) + "</p>" : "") + screen;
    }).join("") : '<div class="empty">찾지 못했습니다.</div>';
    AT.message($("msg"), d.total
      ? "<b>" + d.total + "가지</b>" + (d.total > d.shown
          ? " 가운데 " + d.shown + "가지만 보입니다." : "")
      : "찾지 못했습니다. 다른 말로 해 보세요.", d.total ? "ok" : "");
  }

  async function run() {
    try {
      draw(await AT.call("/api/how/find",
                         { needle: $("needle").value, topic: topic }));
    } catch (e) { AT.message($("msg"), AT.esc(e.message), "bad"); }
  }

  $("btn-find").addEventListener("click", run);
  $("needle").addEventListener("keydown", function (e) {
    if (e.key === "Enter") run();
  });
  run();
})();
</script>
"""


def make() -> App:
    return App(
        key="how",
        name="이럴 땐 이렇게",
        summary="하고 싶은 일에서 명령을 찾는다 (취합·점검·내보내기·정리…)",
        subtitle="자주 하는 일 %d가지" % len(recipes.RECIPES),
        body=lambda: BODY,
        actions={"find": find},
        aliases=("사용법", "도움말", "레시피", "how"),
        section="그 밖",
    )
