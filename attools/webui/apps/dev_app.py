"""개발 잡일 화면. JWT·시각·cron·마스킹·인코딩·키 생성·.env 대조."""

from __future__ import annotations

import json
from datetime import datetime

from ... import life
from ...code import dbkit, devkit, logkit
from ...code.schedule import Cron, CronError
from .. import App, UiError, form

SECRET_KINDS = {"token", "password", "hex", "uuid", "pin"}
MAX_LOG_BYTES = 20 << 20      # 20MB. 화면에서 여는 것이므로 선을 둔다
TOP = 15


def jwt(payload: dict) -> dict:
    token = form.text(payload, "token")
    if not token:
        raise UiError("토큰을 붙여 넣어 주세요.")
    try:
        info = devkit.decode_jwt(token)
    except Exception as exc:   # base64·json 오류가 여러 종류로 온다
        raise UiError(f"토큰을 읽지 못했습니다: {exc}") from None

    times = [[claim, when.strftime("%Y-%m-%d %H:%M:%S %Z")]
             for claim, when in info["times"].items()]
    if info["expired"] is None:
        state = "만료 정보(exp)가 없습니다."
    elif info["expired"]:
        state = "이미 만료된 토큰입니다."
    else:
        state = "아직 유효한 토큰입니다."
    return {
        "header": json.dumps(info["header"], ensure_ascii=False, indent=2),
        "payload": json.dumps(info["payload"], ensure_ascii=False, indent=2),
        "times": times,
        "state": state,
        "signed": info["signed"],
    }


def when(payload: dict) -> dict:
    raw = form.text(payload, "value")
    try:
        moment = devkit.parse_when(raw)
    except ValueError as exc:
        raise UiError(f"시각을 읽지 못했습니다: {exc}") from None
    report = devkit.when_report(moment)
    return {"rows": [[key, value] for key, value in report.items()],
            "headline": report["KST"]}


def cron(payload: dict) -> dict:
    expression = form.text(payload, "expression")
    if not expression:
        raise UiError("cron 식을 적어 주세요. 예: 0 9 * * 1-5")
    try:
        parsed = Cron(expression)
        runs = parsed.next_runs(datetime.now(), 8)
    except CronError as exc:
        raise UiError(str(exc)) from None
    return {"describe": parsed.describe(),
            "rows": [[f"{run:%Y-%m-%d %H:%M}", life.weekday_ko(run)]
                     for run in runs]}


def mask(payload: dict) -> dict:
    body = form.raw_text(payload, "text")
    if not body.strip():
        raise UiError("가릴 내용을 붙여 넣어 주세요.")
    masked, counts = devkit.mask_text(body)
    return {"text": masked,
            "rows": [[name, str(n)] for name, n in counts.items()],
            "found": sum(counts.values())}


def encode(payload: dict) -> dict:
    value = form.raw_text(payload, "value")
    if not value:
        raise UiError("바꿀 값을 적어 주세요.")
    return {"rows": [[key, text] for key, text in devkit.encodings(value).items()]}


def secret(payload: dict) -> dict:
    kind = form.choice(payload, "kind", SECRET_KINDS, "token")
    length = int(form.number(payload, "length", 32, low=4, high=256))
    count = int(form.number(payload, "count", 5, low=1, high=50))
    try:
        values = devkit.gen_secret(kind, length, count=count,
                                   readable=form.flag(payload, "readable"))
    except ValueError as exc:
        raise UiError(str(exc)) from None
    return {"values": values}


def log(payload: dict) -> dict:
    """로그 파일을 훑는다. 레벨 집계, 되풀이되는 에러, 경로별 응답 시간."""
    path = form.existing_file(payload, max_bytes=MAX_LOG_BYTES)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    entries = logkit.parse(lines)
    if not entries:
        raise UiError("로그로 읽을 줄이 없습니다.")

    levels = [[level, str(n)] for level, n in logkit.level_counts(entries).items()]
    groups = [[g.level or "-", str(g.count), g.sample[:70],
               ", ".join(str(n) for n in g.lines[:3])]
              for g in logkit.group_messages(entries, top=TOP)]

    timed = logkit.timings(entries)
    routes = [[stat.route, str(stat.count), f"{stat.p(50):,.0f}",
               f"{stat.p(95):,.0f}", f"{stat.avg:,.0f}"]
              for stat in logkit.by_route(timed, top=TOP)]

    first, last = logkit.span(entries)
    return {
        "lines": len(lines), "entries": len(entries),
        "levels": levels, "groups": groups, "routes": routes,
        "span": (f"{first:%Y-%m-%d %H:%M} ~ {last:%Y-%m-%d %H:%M}"
                 if first and last else "시각을 읽지 못했습니다"),
        "note": "되풀이되는 에러는 숫자·아이디를 지운 뒤 묶습니다. "
                "응답 시간은 줄에 적힌 ms 값을 읽은 것이라 로그 형식에 따라 "
                "못 찾을 수 있습니다.",
    }


def db(payload: dict) -> dict:
    """sqlite 파일을 읽기 전용으로 훑는다."""
    path = form.existing_file(payload)
    try:
        conn = dbkit.connect(path)
    except dbkit.DbError as exc:
        raise UiError(str(exc)) from None

    try:
        table = form.text(payload, "table")
        sql = form.raw_text(payload, "sql")
        if sql.strip():
            if dbkit.looks_like_write(sql):
                raise UiError("읽기 전용으로 열었습니다. SELECT 만 됩니다.")
            headers, rows, more = dbkit.query(conn, sql, limit=200)
        elif table:
            headers, rows, more = dbkit.sample(conn, table, limit=20)
        else:
            found = dbkit.tables(conn)
            return {"tables": [[t.name, t.kind, str(t.rows), str(t.columns)]
                               for t in found],
                    "names": [t.name for t in found],
                    "headers": [], "rows": [], "more": False,
                    "note": "읽기 전용(mode=ro)으로 엽니다. 고칠 수 없습니다."}
    except dbkit.DbError as exc:
        raise UiError(str(exc)) from None
    finally:
        conn.close()

    return {"tables": [], "names": [],
            "headers": headers,
            "rows": [["" if v is None else str(v) for v in row] for row in rows],
            "more": more,
            "note": "읽기 전용(mode=ro)으로 엽니다. 고칠 수 없습니다."}


def env(payload: dict) -> dict:
    example = form.existing_file(payload, "example")
    actual = form.existing_file(payload, "actual")
    diff = devkit.env_diff(example, actual)
    rows = []
    for label, names in (("예시엔 있는데 없음", diff.missing),
                         ("값이 비어 있음", diff.empty),
                         ("예시 값 그대로", diff.placeholder),
                         ("여기에만 있음", diff.extra)):
        for name in names:
            rows.append([label, name])
    return {"rows": rows, "ok": diff.ok,
            "note": "«여기에만 있음»은 문제가 아닐 수 있습니다. "
                    "예시 파일에 적는 것을 잊었을 뿐일 수도 있습니다."}


BODY = """
<nav class="tabs" id="tabs">
  <button data-tab="jwt" aria-selected="true">JWT</button>
  <button data-tab="when" aria-selected="false">시각</button>
  <button data-tab="cron" aria-selected="false">cron</button>
  <button data-tab="mask" aria-selected="false">가리기</button>
  <button data-tab="encode" aria-selected="false">인코딩</button>
  <button data-tab="secret" aria-selected="false">키 생성</button>
  <button data-tab="log" aria-selected="false">로그</button>
  <button data-tab="db" aria-selected="false">sqlite</button>
  <button data-tab="env" aria-selected="false">.env 대조</button>
</nav>

<section class="card" data-panel="jwt">
  <h2>JWT 안을 본다</h2>
  <p class="note">서명은 검증하지 않습니다. 안에 무엇이 들었는지 볼 뿐이니
     이 결과로 «믿을 수 있다»를 판단하면 안 됩니다.</p>
  <textarea id="j-token" spellcheck="false" placeholder="eyJhbGciOi..."></textarea>
  <div class="actions"><button class="primary" id="btn-jwt">뜯어보기</button></div>
  <div id="jwt-out"></div>
</section>

<section class="card" data-panel="when" hidden>
  <h2>시각 바꾸기</h2>
  <div class="row">
    <div><label for="w-value">epoch 초·밀리초, ISO 문자열, 또는 비우면 지금</label>
      <input type="text" id="w-value" placeholder="1735689600, 2026-01-01T09:00:00" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-when">바꾸기</button></div>
  </div>
  <div id="when-out"></div>
</section>

<section class="card" data-panel="cron" hidden>
  <h2>cron 식을 사람 말로</h2>
  <div class="row">
    <div><label for="c-expression">cron 식 (분 시 일 월 요일)</label>
      <input type="text" id="c-expression" placeholder="0 9 * * 1-5" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-cron">해석</button></div>
  </div>
  <div id="cron-out"></div>
</section>

<section class="card" data-panel="mask" hidden>
  <h2>로그를 넘기기 전에 가린다</h2>
  <p class="note">주민번호·카드번호·전화·이메일·계좌·토큰을 찾아 가립니다.
     찾지 못하는 것도 있으니 눈으로 한 번 더 보세요.</p>
  <textarea id="m-text" spellcheck="false"></textarea>
  <div class="actions"><button class="primary" id="btn-mask">가리기</button></div>
  <div id="mask-out"></div>
</section>

<section class="card" data-panel="encode" hidden>
  <h2>인코딩</h2>
  <div class="row">
    <div><label for="e-value">값</label>
      <input type="text" id="e-value" spellcheck="false" data-forget></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-encode">바꾸기</button></div>
  </div>
  <div id="encode-out"></div>
</section>

<section class="card" data-panel="secret" hidden>
  <h2>키·비밀번호 만들기</h2>
  <div class="row">
    <div><label for="s-kind">종류</label>
      <select id="s-kind">
        <option value="token">token</option>
        <option value="password">password</option>
        <option value="hex">hex</option>
        <option value="uuid">uuid</option>
        <option value="pin">pin</option>
      </select></div>
    <div style="flex:0 1 7rem"><label for="s-length">길이</label>
      <input type="text" id="s-length" value="32" spellcheck="false"></div>
    <div style="flex:0 1 7rem"><label for="s-count">개수</label>
      <input type="text" id="s-count" value="5" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-secret">만들기</button></div>
  </div>
  <div class="checks">
    <label><input type="checkbox" id="s-readable"> 헷갈리는 글자 빼기 (0O1lI)</label>
  </div>
  <div id="secret-out"></div>
</section>

<section class="card" data-panel="log" hidden>
  <h2>로그 훑기</h2>
  <div class="row">
    <div><label for="l-path">로그 파일</label>
      <input type="text" id="l-path" placeholder="예: /var/log/app.log" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-log">훑기</button></div>
  </div>
  <div id="log-out"></div>
</section>

<section class="card" data-panel="db" hidden>
  <h2>sqlite 훑기</h2>
  <p class="note">읽기 전용으로 엽니다. 이 화면에서는 고칠 수 없습니다.</p>
  <div class="row">
    <div><label for="d-path">db 파일</label>
      <input type="text" id="d-path" placeholder="예: ~/app.sqlite3" spellcheck="false"></div>
    <div><label for="d-table">표 (비우면 목록)</label>
      <select id="d-table"><option value="">표 목록</option></select></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-db">보기</button></div>
  </div>
  <div style="margin-top:.8rem">
    <label for="d-sql">직접 SELECT (적으면 표 대신 이걸 씁니다)</label>
    <textarea id="d-sql" spellcheck="false" style="min-height:4rem"
              placeholder="SELECT * FROM 주문 WHERE 상태 = '대기' LIMIT 20"></textarea>
  </div>
  <div id="db-out"></div>
</section>

<section class="card" data-panel="env" hidden>
  <h2>.env 대조</h2>
  <div class="row">
    <div><label for="v-example">예시 파일</label>
      <input type="text" id="v-example" placeholder=".env.example" spellcheck="false"></div>
    <div><label for="v-actual">실제 파일</label>
      <input type="text" id="v-actual" placeholder=".env" spellcheck="false"></div>
    <div style="flex:0 0 auto"><button class="primary" id="btn-env">대조</button></div>
  </div>
  <div id="env-out"></div>
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

  function big(text) { return '<p class="big">' + text + "</p>"; }
  function code(text) { return '<pre class="diff">' + AT.esc(text) + "</pre>"; }

  async function run(where, path, body, draw) {
    try { draw(await AT.call(path, body)); }
    catch (e) { AT.message($(where), AT.esc(e.message), "bad"); }
  }

  $("btn-jwt").addEventListener("click", function () {
    run("jwt-out", "/api/dev/jwt", { token: $("j-token").value }, function (d) {
      $("jwt-out").innerHTML = big(AT.esc(d.state)) +
        '<p class="note">' + (d.signed ? "서명 부분이 있습니다"
          : "서명 부분이 없습니다") + " (검증하지는 않았습니다).</p>" +
        '<p class="file">헤더</p>' + code(d.header) +
        '<p class="file">페이로드</p>' + code(d.payload) +
        (d.times.length ? AT.table(["시각 클레임", "언제"], d.times) : "");
    });
  });

  $("btn-when").addEventListener("click", function () {
    run("when-out", "/api/dev/when", { value: $("w-value").value }, function (d) {
      $("when-out").innerHTML = big(AT.esc(d.headline)) +
        AT.table(["표현", "값"], d.rows);
    });
  });

  $("btn-cron").addEventListener("click", function () {
    run("cron-out", "/api/dev/cron", { expression: $("c-expression").value },
        function (d) {
      $("cron-out").innerHTML = big(AT.esc(d.describe)) +
        AT.table(["다음 실행", "요일"], d.rows);
    });
  });

  $("btn-mask").addEventListener("click", function () {
    run("mask-out", "/api/dev/mask", { text: $("m-text").value }, function (d) {
      $("mask-out").innerHTML = big(d.found ? d.found + "곳을 가렸습니다"
                                            : "가릴 것을 찾지 못했습니다") +
        (d.rows.length ? AT.table(["종류", "개수"], d.rows, [null, "num"]) : "") +
        code(d.text);
    });
  });

  $("btn-encode").addEventListener("click", function () {
    run("encode-out", "/api/dev/encode", { value: $("e-value").value },
        function (d) {
      $("encode-out").innerHTML = AT.table(["표현", "값"], d.rows);
    });
  });

  $("btn-secret").addEventListener("click", function () {
    run("secret-out", "/api/dev/secret", {
      kind: $("s-kind").value, length: $("s-length").value,
      count: $("s-count").value, readable: $("s-readable").checked,
    }, function (d) {
      $("secret-out").innerHTML = code(d.values.join("\\n"));
    });
  });

  $("btn-log").addEventListener("click", function () {
    run("log-out", "/api/dev/log", { path: $("l-path").value }, function (d) {
      $("log-out").innerHTML = big(d.entries + "줄을 읽었습니다") +
        '<p class="note">' + AT.esc(d.span) + " · 모두 " + d.lines + "줄</p>" +
        "<h2>레벨</h2>" + AT.table(["레벨", "줄 수"], d.levels, [null, "num"]) +
        "<h2>되풀이되는 메시지</h2>" +
        AT.table(["레벨", "횟수", "본보기", "줄 번호"], d.groups,
                 [null, "num", null, null]) +
        (d.routes.length
          ? "<h2>경로별 응답 시간(ms)</h2>" +
            AT.table(["경로", "건수", "p50", "p95", "평균"], d.routes,
                     [null, "num", "num", "num", "num"])
          : "") +
        '<p class="note">' + AT.esc(d.note) + "</p>";
    });
  });

  function dbBody() {
    return { path: $("d-path").value, table: $("d-table").value,
             sql: $("d-sql").value };
  }

  $("btn-db").addEventListener("click", function () {
    run("db-out", "/api/dev/db", dbBody(), function (d) {
      if (d.tables.length) {
        const keep = $("d-table").value;
        $("d-table").innerHTML = '<option value="">표 목록</option>' +
          d.names.map(n => '<option value="' + AT.esc(n) + '">' + AT.esc(n) +
                           "</option>").join("");
        if (d.names.indexOf(keep) >= 0) $("d-table").value = keep;
      }
      $("db-out").innerHTML = (d.tables.length
          ? AT.table(["이름", "종류", "행", "열"], d.tables,
                     [null, null, "num", "num"])
          : AT.table(d.headers, d.rows)) +
        (d.more ? '<p class="note">더 있습니다. LIMIT 을 붙여 보세요.</p>' : "") +
        '<p class="note">' + AT.esc(d.note) + "</p>";
    });
  });

  $("btn-env").addEventListener("click", function () {
    run("env-out", "/api/dev/env",
        { example: $("v-example").value, actual: $("v-actual").value },
        function (d) {
      $("env-out").innerHTML = big(d.ok ? "빠진 값이 없습니다"
                                        : "확인할 것이 있습니다") +
        (d.rows.length ? AT.table(["무엇", "이름"], d.rows) : "") +
        '<p class="note">' + AT.esc(d.note) + "</p>";
    });
  });
})();
</script>
"""


def make() -> App:
    return App(
        key="dev",
        name="개발 잡일",
        summary="JWT·시각·cron·가리기·인코딩·키 생성·.env·로그·sqlite",
        subtitle="읽고 계산할 뿐, 고치지 않습니다",
        body=lambda: BODY,
        actions={"jwt": jwt, "when": when, "cron": cron, "mask": mask,
                 "encode": encode, "secret": secret, "env": env,
                 "log": log, "db": db},
        aliases=("개발", "dev잡일"),
        section="개발",
    )
