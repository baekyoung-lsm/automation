"""원고 화면. 얼마나 썼는지 보고, 되풀이되는 말과 인물 등장을 점검한다."""

from __future__ import annotations

from pathlib import Path

from ...write import manuscript, names
from .. import App, UiError, form

TOP = 12


def _chapters(payload: dict) -> list[tuple[str, str]]:
    root = form.existing_path(payload)
    paths = manuscript.collect([root])
    if not paths:
        raise UiError(f"읽을 원고가 없습니다: {root} (txt, md 를 찾습니다)")
    out = []
    for path in paths:
        label = str(path.relative_to(root)) if root.is_dir() else path.name
        out.append((label, manuscript.read_text(path)))
    return out


def count(payload: dict) -> dict:
    chapters = _chapters(payload)
    stats = [manuscript.analyze(Path(label), text) for label, text in chapters]
    rows = [[
        s.path,
        f"{s.chars_no_space:,}",
        f"{s.wongoji:.1f}",
        f"{s.paragraphs:,}",
        f"{s.dialogue_ratio * 100:.0f}%",
        f"{s.read_minutes:.0f}분",
    ] for s in stats]

    whole = manuscript.total(stats)
    return {
        "rows": rows,
        "total": [whole.path, f"{whole.chars_no_space:,}", f"{whole.wongoji:.1f}",
                  f"{whole.paragraphs:,}",
                  f"{whole.dialogue_ratio * 100:.0f}%",
                  f"{whole.read_minutes:.0f}분"],
        "book": f"{whole.book_ratio:.2f}",
        "files": len(stats),
    }


def inspect(payload: dict) -> dict:
    chapters = _chapters(payload)
    body = "\n\n".join(text for _, text in chapters)
    limit = int(form.number(payload, "long_limit", 100, low=20, high=1000))
    found = manuscript.inspect(body, top=TOP, long_limit=limit)

    quotes = []
    for label, text in chapters:
        for issue in manuscript.check_quotes(text):
            quotes.append([label, str(issue.line), issue.kind, issue.excerpt[:40]])

    return {
        "cliches": [[word, str(n)] for word, n in found.cliches],
        "adverbs": [[word, str(n)] for word, n in found.adverbs],
        "phrases": [[word, str(n)] for word, n in found.phrases],
        "runs": [[f"…{ending}", str(length), str(start)]
                 for ending, length, start in found.ending_runs],
        "long": [[str(number), str(length), preview]
                 for number, length, preview in found.long_sentences[:TOP]],
        "quotes": quotes[:TOP * 2],
        "long_total": len(found.long_sentences),
        "quote_total": len(quotes),
    }


def cast(payload: dict) -> dict:
    chapters = _chapters(payload)
    body = "\n\n".join(text for _, text in chapters)
    people = [n.text for n in names.extract(
        body, min_count=int(form.number(payload, "min_count", 3, low=1, high=999)))]
    if not people:
        return {"rows": [], "labels": [c[0] for c in chapters], "josa": [],
                "note": "고유명사로 볼 만한 말이 없습니다. 등장 횟수 기준을 낮춰 보세요."}

    rows = []
    for row in names.cast_by_chapter(chapters, people)[:20]:
        gone = row.gone_for()
        rows.append([row.name, str(row.total), str(row.first), str(row.last),
                     f"{gone}화째 안 나옴" if gone else "최근까지"])

    josa = [[e.name, e.wrong, e.right, str(e.line)]
            for e in names.check_josa(body, people)[:TOP]]
    return {"rows": rows, "labels": [c[0] for c in chapters], "josa": josa,
            "note": ""}


BODY = """
<section class="card">
  <h2>어느 원고인가요</h2>
  <div class="row">
    <div style="flex:3 1 22rem">
      <label for="path">원고 폴더 또는 파일 (txt, md)</label>
      <input type="text" id="path" placeholder="예: ~/글/장편" spellcheck="false">
    </div>
    <div style="flex:0 1 9rem">
      <label for="long_limit">긴 문장 기준(자)</label>
      <input type="text" id="long_limit" value="100" spellcheck="false">
    </div>
    <div style="flex:0 1 9rem">
      <label for="min_count">인물 최소 등장</label>
      <input type="text" id="min_count" value="3" spellcheck="false">
    </div>
  </div>
  <div class="actions">
    <button class="primary" id="btn-count">분량 보기</button>
    <button id="btn-inspect">되풀이 점검</button>
    <button id="btn-cast">인물 흐름</button>
    <span class="spacer"></span>
    <span class="note">읽기만 합니다. 원고는 바뀌지 않습니다.</span>
  </div>
  <div id="msg"></div>
</section>

<section class="card" id="card-count">
  <h2>분량</h2>
  <div id="count"><div class="empty">원고 경로를 넣고 눌러 주세요.</div></div>
</section>

<section class="card" id="card-inspect" hidden>
  <h2>되풀이되는 말</h2>
  <div id="inspect"></div>
</section>

<section class="card" id="card-cast" hidden>
  <h2>인물</h2>
  <div id="cast"></div>
</section>

<script>
(function () {
  const $ = (id) => document.getElementById(id);

  function values() {
    return {
      path: $("path").value,
      long_limit: $("long_limit").value,
      min_count: $("min_count").value,
    };
  }

  function block(title, headers, rows, aligns, empty) {
    if (!rows.length) return "<h2>" + title + "</h2><p class=\\"note\\">" +
                             empty + "</p>";
    return "<h2>" + title + "</h2>" + AT.table(headers, rows, aligns);
  }

  $("btn-count").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/novel/count", values());
      const rows = d.rows.concat([d.total]);
      $("count").innerHTML = AT.table(
        ["파일", "글자(공백 제외)", "원고지", "문단", "대사", "읽는 시간"],
        rows, [null, "num", "num", "num", "num", "num"]);
      AT.message($("msg"), "파일 <b>" + d.files + "개</b>. 단행본 기준 " +
                 AT.esc(d.book) + "권 분량입니다 (10만 자 = 1권, 어림값).", "ok");
    } catch (e) { AT.message($("msg"), AT.esc(e.message), "bad"); }
  });

  $("btn-inspect").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/novel/inspect", values());
      $("card-inspect").hidden = false;
      $("inspect").innerHTML =
        block("상투 표현", ["표현", "횟수"], d.cliches, [null, "num"],
              "걸리는 것이 없습니다.") +
        block("군더더기 부사", ["부사", "횟수"], d.adverbs, [null, "num"],
              "걸리는 것이 없습니다.") +
        block("되풀이되는 두 어절", ["어구", "횟수"], d.phrases, [null, "num"],
              "3번 이상 되풀이되는 어구가 없습니다.") +
        block("같은 어미가 이어지는 곳", ["어미", "연속", "시작 문장"], d.runs,
              [null, "num", "num"], "이어지는 곳이 없습니다.") +
        block("긴 문장 (모두 " + d.long_total + "개)",
              ["문장 번호", "길이", "앞부분"], d.long, ["num", "num", null],
              "기준을 넘는 문장이 없습니다.") +
        block("따옴표 (모두 " + d.quote_total + "개)",
              ["파일", "줄", "무엇", "앞부분"], d.quotes, [null, "num", null, null],
              "짝이 맞지 않는 따옴표가 없습니다.");
      AT.message($("msg"), "점검했습니다.", "ok");
    } catch (e) { AT.message($("msg"), AT.esc(e.message), "bad"); }
  });

  $("btn-cast").addEventListener("click", async function () {
    try {
      const d = await AT.call("/api/novel/cast", values());
      $("card-cast").hidden = false;
      $("cast").innerHTML = d.note
        ? '<p class="note">' + AT.esc(d.note) + "</p>"
        : block("등장 흐름 (" + d.labels.length + "개 파일 기준)",
                ["이름", "전체", "처음", "마지막", "그 뒤"], d.rows,
                [null, "num", "num", "num", null], "") +
          block("조사가 어색한 곳", ["이름", "쓴 것", "맞는 것", "줄"], d.josa,
                [null, null, null, "num"], "걸리는 것이 없습니다.");
      AT.message($("msg"), "인물을 세었습니다. 이름은 글에서 뽑은 것이라 " +
                 "사람이 아닌 말이 섞일 수 있습니다.", "ok");
    } catch (e) { AT.message($("msg"), AT.esc(e.message), "bad"); }
  });
})();
</script>
"""


def make() -> App:
    return App(
        key="novel",
        name="원고 점검",
        summary="얼마나 썼는지 보고, 되풀이되는 말과 인물 등장을 점검한다",
        subtitle="분량 · 되풀이 · 인물",
        body=lambda: BODY,
        actions={"count": count, "inspect": inspect, "cast": cast},
        aliases=("원고", "소설", "집필"),
    )
