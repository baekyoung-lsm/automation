"""at dev - 백엔드 개발 잡일."""

from __future__ import annotations

import sys
from pathlib import Path

from .. import files, hangul, life, sheet, text
from ..code import (dbkit, deps, devkit, fakedata, jsonkit, logkit, openapi,
                    pyscan)
from ..code.schedule import Cron, CronError
from ..write import manuscript
from .common import (InputError, _pad, _p, _confirm, _read_input, _cut,
                     _grid)


def _read_log_lines(sources: list[str]) -> list[str] | None:
    lines: list[str] = []
    for source in sources:
        if source == "-":
            lines += sys.stdin.read().splitlines()
            continue
        path = Path(source)
        if not path.is_file():
            _p(f"파일이 없습니다: {path}")
            return None
        lines += manuscript.read_text(path).splitlines()
    return lines


def cmd_dev_env(a) -> int:
    example, actual = Path(a.example), Path(a.actual)

    if a.sync:
        if not actual.is_file():
            _p(f"파일이 없습니다: {actual}")
            return 1
        text, added = devkit.build_example(
            actual, existing=example if example.is_file() else None,
            keep_values=a.keep_values)

        if not a.apply:
            _p(f"{actual} -> {example} (미리보기)\n")
            _p(text)
            if added:
                _p(f"새로 들어갈 키 {len(added)}개: {', '.join(added)}")
            _p("\n실제로 쓰려면 --apply 를 붙이세요.")
            return 0

        example.write_text(text, encoding="utf-8")
        _p(f"{example} 를 갱신했습니다." + (f"  새 키 {len(added)}개" if added else ""))
        _p("비밀값은 <이름> 자리표시자로 바꿨습니다. 커밋 전에 한 번 확인하세요.")
        return 0

    for p in (example, actual):
        if not p.is_file():
            _p(f"파일이 없습니다: {p}")
            return 1

    d = devkit.env_diff(example, actual)
    if d.missing:
        _p(f"빠진 키 ({len(d.missing)}개) - {actual.name} 에 추가해야 합니다")
        for k in d.missing:
            _p(f"  - {k}")
    if d.empty:
        _p(f"\n값이 비어 있음 ({len(d.empty)}개)")
        for k in d.empty:
            _p(f"  - {k}")
    if d.placeholder:
        _p(f"\n예시 값 그대로 ({len(d.placeholder)}개) - 실제 값으로 바꾸세요")
        for k in d.placeholder:
            _p(f"  - {k}")
    if d.extra and a.show_extra:
        _p(f"\n{example.name} 에 없는 키 ({len(d.extra)}개) - 예시 파일에 추가할지 확인")
        for k in d.extra:
            _p(f"  - {k}")

    if a.show_values:
        _p(f"\n{actual.name} 현재 값 (마스킹)")
        for k, v in devkit.parse_env(actual).items():
            shown = devkit.mask_value(v) if devkit.SECRET_HINT.search(k) else (v or "(비어 있음)")
            _p(f"  {k} = {shown}")

    if d.ok:
        _p("문제 없습니다.")
    return 0 if d.ok else 1


def cmd_dev_port(a) -> int:
    try:
        listeners = devkit.who_listens(a.port)
    except RuntimeError as e:
        _p(str(e))
        return 1

    if not listeners:
        _p(f"{a.port} 포트는 비어 있습니다.")
        return 0

    for l in listeners:
        _p(f"pid {l.pid}  {l.name}")

    if not a.kill:
        _p(f"\n종료하려면: at dev port {a.port} --kill")
        return 0
    if not a.yes and not _confirm(f"위 {len(listeners)}개 프로세스를 종료할까요?"):
        _p("취소했습니다.")
        return 1

    killed = devkit.kill_listeners(a.port, force=a.force)
    _p(f"{len(killed)}개 프로세스에 {'SIGKILL' if a.force else 'SIGTERM'} 을 보냈습니다.")
    return 0


def cmd_dev_jwt(a) -> int:
    token = sys.stdin.read().strip() if a.token == "-" else a.token
    try:
        info = devkit.decode_jwt(token)
    except Exception as e:
        _p(f"디코드 실패: {e}")
        return 1

    import json as _json
    _p("헤더")
    _p(_json.dumps(info["header"], ensure_ascii=False, indent=2))
    _p("\n페이로드")
    _p(_json.dumps(info["payload"], ensure_ascii=False, indent=2))
    if info["times"]:
        _p("\n시각 (KST)")
        for k, dt in info["times"].items():
            rel = devkit.humanize_delta(devkit.datetime.now(devkit.KST) - dt)
            _p(f"  {_pad(k, 10)}{dt:%Y-%m-%d %H:%M:%S}  ({rel})")
    if info["expired"] is not None:
        _p(f"\n만료 여부: {'만료됨' if info['expired'] else '유효'}")
    _p("서명은 검증하지 않았습니다. 내용 확인용으로만 쓰세요.")
    return 0


def cmd_dev_time(a) -> int:
    try:
        dt = devkit.parse_when(a.when)
    except ValueError as e:
        _p(f"해석 실패: {e}")
        return 1
    for k, v in devkit.when_report(dt).items():
        _p(f"{_pad(k, 10)}{v}")
    return 0


def cmd_dev_slow(a) -> int:
    import re as _re

    lines = _read_log_lines(a.files)
    if lines is None:
        return 1
    if not lines:
        _p("읽을 내용이 없습니다.")
        return 1

    pattern = None
    if a.pattern:
        try:
            pattern = _re.compile(a.pattern)
        except _re.error as e:
            _p(f"정규식이 잘못됐습니다: {e}")
            return 1

    entries = logkit.parse(lines)
    timed = logkit.timings(entries, pattern=pattern)
    if not timed:
        _p(f"{len(entries):,}줄에서 응답 시간을 찾지 못했습니다.")
        _p("34ms, 1.2s 처럼 단위가 붙은 값을 찾습니다. 형식이 다르면 "
           "--pattern '지연=(\\d+)' 처럼 정규식으로 알려 주세요.")
        return 1

    values = [t.ms for t in timed]
    rate = len(timed) / len(entries)
    _p(f"{len(entries):,}줄 중 {len(timed):,}줄에서 시간을 읽었습니다 ({rate:.0%})")
    _p(f"  p50 {logkit.percentile(values, 50):,.0f}ms · "
       f"p95 {logkit.percentile(values, 95):,.0f}ms · "
       f"p99 {logkit.percentile(values, 99):,.0f}ms · "
       f"최대 {max(values):,.0f}ms")
    if a.over:
        slow = [v for v in values if v >= a.over]
        _p(f"  {a.over:,}ms 이상 {len(slow):,}건 ({len(slow) / len(values):.1%})")

    stats = logkit.by_route(timed, top=a.top, sort=a.sort)
    _p("")
    _grid(["경로", "건수", "p50", "p95", "최대", "합계"],
          [[s.route, f"{s.count:,}", f"{s.p(50):,.0f}", f"{s.p(95):,.0f}",
            f"{max(s.values):,.0f}", f"{s.total / 1000:,.1f}s"] for s in stats],
          limit=40)

    worst = sorted(timed, key=lambda t: -t.ms)[:a.limit]
    if worst:
        _p("\n가장 느린 줄")
        for t in worst:
            _p(f"  {t.ms:>9,.0f}ms  {t.entry.line}행  {_cut(t.entry.raw.strip(), 70)}")

    if rate < 0.5 and not pattern:
        _p(f"\n시간을 읽은 줄이 절반이 안 됩니다({rate:.0%}). 형식이 다르면 "
           "--pattern 으로 알려 주세요. 못 읽은 줄은 통계에 들어가지 않았습니다.")
    _p("\n백분위는 보간 없이 실제 값 중에서 고릅니다. 표본이 적으면 그대로 참고만 하세요.")
    return 0


def cmd_dev_retry(a) -> int:
    commands = a.command or []
    if not commands:
        _p("돌릴 명령을 주세요. 예: at dev retry -n 5 -- curl -sf http://localhost:8080/health")
        return 1

    _p(f"{' '.join(commands)}  (최대 {a.tries}번, 처음 {a.delay:g}초 뒤부터 "
       f"{a.backoff:g}배씩)")

    def show(attempt) -> None:
        wait = f"{attempt.waited:g}초 기다림 -> " if attempt.waited else ""
        state = "성공" if attempt.code == 0 else f"실패(코드 {attempt.code})"
        _p(f"  {wait}{attempt.number}번째  {state}  {attempt.seconds:.2f}초")

    attempts = devkit.retry(commands, tries=a.tries, delay=a.delay,
                            backoff=a.backoff, max_delay=a.max_delay,
                            on_attempt=show)
    last = attempts[-1]
    spent = sum(x.seconds + x.waited for x in attempts)
    if last.code == 0:
        _p(f"\n{len(attempts)}번 만에 성공했습니다. 모두 {spent:.1f}초.")
        return 0
    code = hangul.josa(str(last.code), "을/를")
    _p(f"\n{len(attempts)}번 다 실패했습니다. 모두 {spent:.1f}초. "
       f"마지막 종료 코드 {code} 그대로 돌려줍니다.")
    return last.code


def cmd_dev_db(a) -> int:
    path = Path(a.file)
    try:
        conn = dbkit.connect(path)
    except dbkit.DbError as e:
        _p(str(e))
        return 1

    try:
        if a.query:
            if dbkit.looks_like_write(a.query):
                _p("읽기 전용으로 열기 때문에 값을 바꾸는 문장은 돌아가지 않습니다.")
                return 1
            headers, rows, more = dbkit.query(conn, a.query, limit=a.limit)
        elif a.table:
            cols = dbkit.columns(conn, a.table)
            _p(f"{a.table}  열 {len(cols)}개")
            _grid(["열", "타입", "빈칸", "기본값", "키"],
                  [[c.name, c.type or "-", "안 됨" if c.notnull else "됨",
                    c.default or "-", "PK" if c.pk else ""] for c in cols])
            headers, rows, more = dbkit.sample(conn, a.table, limit=a.limit)
            _p(f"\n앞에서 {len(rows)}행")
        else:
            items = dbkit.tables(conn)
            if not items:
                _p("표가 없습니다.")
                return 0
            _grid(["이름", "종류", "행", "열"],
                  [[t.name, t.kind, "?" if t.rows < 0 else f"{t.rows:,}",
                    str(t.columns)] for t in items])
            total = sum(t.rows for t in items if t.rows > 0)
            _p(f"\n표 {len([t for t in items if t.kind == 'table'])}개, "
               f"뷰 {len([t for t in items if t.kind == 'view'])}개, "
               f"행 {total:,}개")
            _p("--table 이름 으로 열 구성과 앞 몇 행을, -q 로 직접 조회합니다.")
            return 0
    except dbkit.DbError as e:
        _p(str(e))
        return 1
    finally:
        conn.close()

    if not headers:
        _p("결과가 없습니다.")
        return 0

    _grid(headers, [[sheet.to_text(v) for v in row] for row in rows])
    if more:
        _p(f"  ... {a.limit}행까지만 보여줍니다 (--limit 로 늘리세요)")

    if a.out:
        table = sheet.Table(headers, rows, source=str(path))
        _p(f"저장: {sheet.save(table, Path(a.out))}")
    return 0


def cmd_dev_api(a) -> int:
    source = Path(a.file)
    if source.suffix.lower() in (".yaml", ".yml"):
        _p("yaml 은 읽지 못합니다. 표준 라이브러리에 yaml 파서가 없습니다.")
        _p("json 으로 바꿔서 주세요 (대부분의 도구가 openapi.json 을 함께 내놓습니다).")
        return 1
    try:
        data = jsonkit.load(a.file)
        spec = openapi.load(data)
    except (jsonkit.JsonError, openapi.SpecError) as e:
        _p(str(e))
        return 1

    head = f"{spec.title or '이름 없음'}"
    if spec.version:
        head += f"  {spec.version}"
    if spec.openapi:
        head += f"  (OpenAPI {spec.openapi})"
    _p(head)
    for url in spec.servers:
        _p(f"  서버  {url}")

    items = spec.endpoints
    if a.find:
        items = openapi.find(spec, a.find)
    if a.method:
        items = [e for e in items if e.method.lower() == a.method.lower()]
    if a.holes:
        items = [e for e in items if e in openapi.undocumented(spec)]
    if not items:
        _p("\n해당하는 엔드포인트가 없습니다.")
        return 1

    _p(f"\n엔드포인트 {len(items)}개 / 전체 {len(spec.endpoints)}개")
    if a.detail:
        for e in items[:a.limit]:
            _p(f"\n{e.method} {e.path}" + ("  [폐기 예정]" if e.deprecated else ""))
            if e.summary:
                _p(f"  {e.summary}")
            for p in e.params:
                mark = "필수" if p.required else "선택"
                _p(f"  - {p.place:6} {p.name}  ({p.type or '?'}, {mark})")
            if e.body_fields:
                _p(f"  - 본문   {', '.join(e.body_fields[:12])}"
                   + ("  (필수)" if e.body_required else ""))
            _p(f"  응답  {', '.join(e.responses) or '적혀 있지 않음'}")
    else:
        _grid(["메서드", "경로", "요약", "인자", "응답"],
              [[e.method, e.path, e.summary or "-",
                f"{len(e.required_params)}/{len(e.params)}",
                ",".join(e.responses) or "-"] for e in items[:a.limit]], limit=44)
        if len(items) > a.limit:
            _p(f"  ... {len(items) - a.limit}개 더")

    tags = spec.tags
    if tags and not a.find:
        _p("\n태그  " + "  ".join(f"{name} {count}" for name, count in
                                   list(tags.items())[:8]))
    holes = openapi.undocumented(spec)
    old = [e for e in spec.endpoints if e.deprecated]
    if holes:
        _p(f"요약이나 오류 응답이 빠진 엔드포인트 {len(holes)}개 (--holes 로 봅니다)")
    if old:
        _p(f"폐기 예정 {len(old)}개")
    _p("인자는 필수/전체 개수입니다. 참조($ref)는 문서 안의 것만 따라갑니다.")
    return 0


def cmd_dev_fake(a) -> int:
    try:
        fields = [fakedata.parse_field(spec) for spec in a.col]
        headers, rows = fakedata.make_rows(fields, a.rows, seed=a.seed)
    except fakedata.FakeError as e:
        _p(str(e))
        _p("예: -c 이름 -c 연락처=전화 -c 금액=금액:10000:50000 -c 가입일=날짜:365")
        return 1

    table = sheet.Table(headers, rows, source="가짜 자료")
    _grid(headers, [[sheet.to_text(v) for v in r] for r in rows[:a.limit]])
    if len(rows) > a.limit:
        _p(f"  ... {len(rows) - a.limit}행 더")
    _p(f"\n{len(rows):,}행 x {len(headers)}열" +
       (f"  (씨앗 {a.seed}: 같은 값이 다시 나옵니다)" if a.seed is not None else ""))
    if any(f.kind == "사업자번호" for f in fields):
        _p("사업자번호는 검증번호까지 맞지만 실제로 등록된 번호가 아닙니다.")
    _p("전부 무작위입니다. 실제 사람·회사와 관계없습니다.")
    if a.out:
        _p(f"저장: {sheet.save(table, Path(a.out))}")
    return 0


def cmd_dev_lock(a) -> int:
    before_path, after_path = Path(a.before), Path(a.after)
    for path in (before_path, after_path):
        if not path.is_file():
            _p(f"파일이 없습니다: {path}")
            return 1

    before = deps.read_lock(before_path)
    after = deps.read_lock(after_path)
    if not before and not after:
        _p("두 파일 모두에서 버전을 읽지 못했습니다.")
        _p("package-lock.json, pipfile.lock, poetry.lock, yarn.lock, "
           "requirements.txt, go.mod 를 읽습니다.")
        return 1

    changes = deps.lock_diff(before, after)
    if not changes:
        _p(f"패키지 {len(after):,}개, 바뀐 것이 없습니다.")
        return 0

    if a.major:
        changes = [c for c in changes if c.major]
        if not changes:
            _p("맨 앞 숫자가 바뀐 패키지는 없습니다.")
            return 0

    _grid(["패키지", "전", "후", "무엇"],
          [[c.name, c.before or "-", c.after or "-",
            c.kind + ("  (맨 앞 숫자)" if c.major else "")]
           for c in changes[:a.limit]], limit=40)
    if len(changes) > a.limit:
        _p(f"  ... {len(changes) - a.limit}개 더")

    counts: dict[str, int] = {}
    for c in changes:
        counts[c.kind] = counts.get(c.kind, 0) + 1
    _p("\n" + " · ".join(f"{k} {n}" for k, n in counts.items())
       + f"  (전체 {len(before):,} -> {len(after):,}개)")
    majors = [c for c in changes if c.major]
    if majors:
        _p(f"맨 앞 숫자가 바뀐 것 {len(majors)}개: "
           + ", ".join(c.name for c in majors[:8]))
        _p("대개 여기서 호환이 깨집니다. 바뀐 것 전체를 훑기 전에 이것부터 보세요.")
    return 0


def cmd_dev_unused(a) -> int:
    roots = [Path(p) for p in a.dirs]
    for root in roots:
        if not root.is_dir():
            _p(f"디렉터리가 아닙니다: {root}")
            return 1

    found: list = []
    checked = 0
    for root in roots:
        for path in pyscan.iter_python(root):
            checked += 1
            found += pyscan.unused_imports(path, skip_init=not a.init)

    if found:
        _p(f"안 쓰는 import {len(found)}건 (파일 {checked}개 훑음)")
        for item in found[:a.limit]:
            _p(f"  {item.path}:{item.line}  {item.source}")
        if len(found) > a.limit:
            _p(f"  ... {len(found) - a.limit}건 더")
        _p("한 줄만 넘기려면 그 줄에 attools:ignore 를 적으면 됩니다.")
    else:
        _p(f"파일 {checked}개, 안 쓰는 import 가 없습니다.")

    if a.modules:
        orphans = [m for root in roots for m in pyscan.module_uses(root) if m.orphan]
        _p(f"\n아무도 import 하지 않는 모듈 {len(orphans)}개")
        for item in orphans[:a.limit]:
            _p(f"  {item.path}")
        _p("진입점(패키지 최상단, 스크립트)은 원래 아무도 부르지 않습니다. "
           "지우기 전에 확인하세요.")

    if found:
        _p("\n별표 import(from x import *)는 판단하지 않습니다. "
           "동적으로 부르는 이름도 못 봅니다.")
        return 1
    return 0


def cmd_dev_http(a) -> int:
    import json as _json

    headers: dict[str, str] = {}
    try:
        for item in a.header or []:
            name, value = devkit.parse_header(item)
            headers[name] = value
    except ValueError as e:
        _p(str(e))
        return 1

    body = None
    method = a.method
    if a.json:
        body = a.json.encode("utf-8")
        headers.setdefault("Content-Type", "application/json; charset=utf-8")
        method = method or "POST"
    elif a.data:
        body = a.data.encode("utf-8")
        method = method or "POST"
    method = method or "GET"

    url = a.url if "://" in a.url else f"http://{a.url}"
    try:
        result = devkit.fetch(url, method=method, headers=headers, body=body,
                              timeout=a.timeout)
    except OSError as e:
        _p(f"부르지 못했습니다: {e}")
        _p("주소와 포트를 확인하세요. 사내망이면 프록시 설정도 봅니다.")
        return 1

    mark = "" if result.ok else "  <- 실패"
    _p(f"{method} {url}")
    _p(f"  {result.status} {result.reason}{mark}  ·  {result.seconds * 1000:,.0f}ms"
       f"  ·  {files.human_size(len(result.body))}  ·  {result.kind or '형식 없음'}")
    if result.url != url:
        _p(f"  따라간 주소: {result.url}")

    if a.headers or a.head:
        _p("")
        for name, value in result.safe_headers():
            _p(f"  {name}: {_cut(value, 70)}")
        _p("  (Authorization 같은 값은 가려서 보여줍니다)")
    if a.head:
        return 0 if result.ok else 1

    text = result.text()
    if a.out:
        Path(a.out).write_bytes(result.body)
        _p(f"\n본문 저장: {a.out}")
        return 0 if result.ok else 1

    _p("")
    if "json" in result.kind.lower() or text.lstrip()[:1] in "[{":
        try:
            data = _json.loads(text)
            text = _json.dumps(data, ensure_ascii=False, indent=2)
        except _json.JSONDecodeError:
            pass                      # JSON 이 아니면 그대로 보여준다
    lines = text.splitlines()
    for line in lines[:a.limit]:
        _p(line)
    if len(lines) > a.limit:
        _p(f"... {len(lines) - a.limit}줄 더 (--limit 로 늘리거나 -o 로 저장하세요)")
    return 0 if result.ok else 1


def cmd_dev_outline(a) -> int:
    roots = [Path(p) for p in a.paths]
    for root in roots:
        if not root.exists():
            _p(f"경로가 없습니다: {root}")
            return 1

    rows = pyscan.outlines(roots)
    broken = [r for r in rows if r.error]
    rows = [r for r in rows if not r.error]
    if not rows:
        _p("파이썬 파일을 찾지 못했습니다.")
        return 1

    if a.file:
        wanted = [r for r in rows if str(r.path).endswith(a.file)]
        if not wanted:
            _p(f"그 파일을 찾지 못했습니다: {a.file}")
            return 1
        for result in wanted:
            _p(f"{result.path}  {result.lines:,}줄")
            body = [s for s in result.symbols if a.private or s.public]
            _grid(["이름", "종류", "줄", "길이", "설명"],
                  [[("  " + s.name) if s.parent else s.name, s.kind,
                    str(s.line), f"{s.lines}줄", "있음" if s.doc else "없음"]
                   for s in body], limit=40)
            _p("")
        return 0

    order = {"줄": lambda r: -r.lines,
             "길이": lambda r: -(r.longest.lines if r.longest else 0),
             "설명": lambda r: -len(r.undocumented),
             "이름": lambda r: str(r.path)}
    rows.sort(key=order[a.sort])

    _grid(["파일", "줄", "클래스", "함수", "가장 긴 것", "설명 없는 공개"],
          [[str(r.path), f"{r.lines:,}", str(len(r.classes)), str(len(r.functions)),
            (f"{r.longest.name} {r.longest.lines}줄" if r.longest else "-"),
            str(len(r.undocumented))] for r in rows[:a.limit]], limit=40)
    if len(rows) > a.limit:
        _p(f"  ... {len(rows) - a.limit}개 더")

    total_lines = sum(r.lines for r in rows)
    total_symbols = sum(len(r.symbols) for r in rows)
    _p(f"\n파일 {len(rows)}개 · {total_lines:,}줄 · 클래스와 함수 {total_symbols:,}개")
    long = [r for r in rows if r.longest and r.longest.lines >= a.long]
    if long:
        _p(f"{a.long}줄 넘는 함수가 있는 파일 {len(long)}개: "
           + ", ".join(f"{r.path.name}({r.longest.name})" for r in long[:5]))
    if broken:
        _p(f"읽지 못한 파일 {len(broken)}개: "
           + ", ".join(str(r.path) for r in broken[:3]))
    _p("--file 로 파일 하나의 클래스·함수 목록을 봅니다.")
    return 0


def cmd_dev_mask(a) -> int:
    try:
        text = _read_input(a.file)
    except InputError as e:
        _p(str(e))
        return 1
    masked, counts = devkit.mask_text(text)

    if a.in_place and a.file != "-":
        Path(a.file).write_text(masked, encoding="utf-8")
        _p(f"{a.file} 을(를) 덮어썼습니다.")
    else:
        sys.stdout.write(masked)

    if counts:
        summary = ", ".join(f"{k} {v}건" for k, v in counts.items())
        print(f"\n[마스킹] {summary}", file=sys.stderr)
    else:
        print("\n[마스킹] 걸린 항목 없음", file=sys.stderr)
    return 0


def cmd_dev_wait(a) -> int:
    def progress(attempt, elapsed, last):
        print(f"  {elapsed:5.1f}초 경과, {attempt}회 시도 ({last})", file=sys.stderr)

    _p(f"{a.target} 기다리는 중 (최대 {a.timeout:.0f}초)")
    try:
        ok, elapsed, last = devkit.wait_for(
            a.target, timeout=a.timeout, interval=a.interval,
            on_try=None if a.quiet else progress)
    except ValueError as e:
        _p(str(e))
        return 2

    if ok:
        _p(f"준비됨: {a.target} ({elapsed:.1f}초)")
        return 0
    _p(f"시간 초과: {a.target} ({elapsed:.1f}초) 마지막 오류 - {last}")
    return 1


def cmd_dev_cron(a) -> int:
    try:
        cron = Cron(a.expression)
    except CronError as e:
        _p(f"해석 실패: {e}")
        return 1

    now = devkit.datetime.now(devkit.KST)
    _p(f"{cron.expression}")
    _p(f"  뜻: {cron.describe()}")
    _p(f"\n다음 실행 (KST)")
    for dt in cron.next_runs(now.replace(tzinfo=None), a.count):
        rel = devkit.humanize_delta(now.replace(tzinfo=None) - dt)
        _p(f"  {dt:%Y-%m-%d}({life.weekday_ko(dt.date())}) {dt:%H:%M}  {rel}")
    return 0


def cmd_dev_gen(a) -> int:
    try:
        values = devkit.gen_secret(a.kind, a.length, count=a.count, readable=a.readable)
    except ValueError as e:
        _p(str(e))
        return 1
    for v in values:
        _p(v)
    return 0


def cmd_dev_enc(a) -> int:
    value = sys.stdin.read().strip() if a.value == "-" else a.value
    for k, v in devkit.encodings(value).items():
        _p(f"{_pad(k, 16)}{v}")
    return 0


def cmd_dev_log(a) -> int:
    lines: list[str] = []
    for source in a.files:
        if source == "-":
            lines += sys.stdin.read().splitlines()
            continue
        path = Path(source)
        if not path.is_file():
            _p(f"파일이 없습니다: {path}")
            return 1
        lines += manuscript.read_text(path).splitlines()

    if not lines:
        _p("읽을 내용이 없습니다.")
        return 1

    entries = logkit.parse(lines)
    levels = {l.upper() for l in a.level} if a.level else None
    if levels:
        unknown = levels - set(logkit.LEVELS) - {"WARN", "FATAL"}
        if unknown:
            _p(f"모르는 레벨입니다: {', '.join(unknown)}")
            return 1

    counts = logkit.level_counts(entries)
    first, last = logkit.span(entries)
    _p(f"{len(entries):,}줄" + (f"  ·  {first:%m-%d %H:%M} ~ {last:%m-%d %H:%M}"
                                if first and last else "  ·  시각 없음"))
    if counts:
        _p("  " + "  ".join(f"{k} {v:,}" for k, v in counts.items()))
    severe = sum(v for k, v in counts.items() if k in logkit.SEVERE)
    if severe and len(entries):
        _p(f"  심각 {severe:,}건 ({severe / len(entries):.1%})")
    _p("")

    series = logkit.histogram(entries, bucket=a.bucket, levels=levels)
    if series:
        peak = max(v for _, v in series)
        title = f"{a.bucket} 단위 분포" + (f" ({'/'.join(sorted(levels))})" if levels else "")
        _p(title)
        for when, count in series[-a.rows:]:
            bar = "█" * max(1, round(count / peak * 32))
            _p(f"  {when:%m-%d %H:%M}  {count:>6,}  {bar}")
        _p("")

        for when, count, ratio in logkit.spikes(series):
            _p(f"  급증: {when:%m-%d %H:%M} 에 {count:,}건 (평소의 {ratio:.1f}배)")
        _p("")

    groups = logkit.group_messages(entries, levels=levels or logkit.SEVERE, top=a.top)
    if not groups:
        _p("묶을 메시지가 없습니다.")
        return 0

    label = "/".join(sorted(levels)) if levels else "심각한 것"
    _p(f"반복되는 메시지 ({label}) 상위 {len(groups)}개")
    for g in groups:
        when = f"  {g.first:%m-%d %H:%M}~{g.last:%H:%M}" if g.first and g.last else ""
        _p(f"  {g.count:>5,}회  [{g.level or '-'}]{when}")
        _p(f"         {_cut(g.sample, a.width)}")
        if a.lines:
            _p(f"         줄 {', '.join(str(n) for n in g.lines)}")
    _p("\n숫자·UUID·IP·경로 같은 값은 <n>, <uuid> 처럼 바꿔서 같은 사고끼리 묶었습니다.")
    return 0


def cmd_dev_bench(a) -> int:
    commands: list[tuple[object, bool, str]] = []
    for text in a.cmd or []:
        commands.append((text, True, text))
    if a.command:
        commands.append((a.command, False, " ".join(a.command)))
    if not commands:
        _p("측정할 명령을 주세요.")
        _p('  at dev bench -n 10 -- python3 a.py')
        _p('  at dev bench --cmd "python3 a.py" --cmd "python3 b.py"')
        return 1

    results = []
    for command, shell, label in commands:
        _p(f"측정 중: {label}  ({a.warmup}회 예열 + {a.runs}회)")
        results.append(devkit.run_bench(command, label=label, runs=a.runs,
                                        warmup=a.warmup, shell=shell))
    _p("")

    fmt = devkit.format_seconds
    for n, r in enumerate(results, 1):
        _p(f"{n}) {r.label}")
        if not r.times:
            _p("   실행하지 못했습니다.")
            continue
        _p(f"   평균 {fmt(r.mean)}  중앙 {fmt(r.median)}  "
           f"최소 {fmt(r.fastest)}  최대 {fmt(r.slowest)}  편차 {fmt(r.stdev)}")
        if r.failures:
            _p(f"   실패 {r.failures}/{r.runs}회 - 시간을 믿기 어렵습니다.")

    usable = [r for r in results if r.times]
    if len(usable) > 1:
        best = min(usable, key=lambda r: r.median)
        _p(f"\n가장 빠름: {best.label}")
        for r in usable:
            if r is best:
                continue
            ratio = r.median / best.median if best.median else 0
            spread = max(r.stdev, best.stdev)
            note = "  (편차가 커서 차이가 뚜렷하지 않습니다)" if abs(
                r.median - best.median) < spread else ""
            _p(f"  {r.label}: {ratio:.2f}배 느림{note}")
    return 0


def cmd_dev_ports(a) -> int:
    try:
        ports = devkit.listening_ports()
    except RuntimeError as e:
        _p(str(e))
        return 1

    if a.filter:
        needle = a.filter.lower()
        ports = [p for p in ports
                 if needle in p.name.lower() or needle == str(p.port)]
    if not ports:
        _p("열려 있는 포트가 없습니다." if not a.filter else "맞는 포트가 없습니다.")
        return 0

    _grid(["포트", "프로세스", "PID", "주소"],
          [[str(p.port), p.name, str(p.pid) if p.pid else "-", p.address or "-"]
           for p in ports[:a.limit]], limit=24)
    if len(ports) > a.limit:
        _p(f"  ... {len(ports) - a.limit}개 더")
    _p(f"\n{len(ports)}개.  하나를 종료하려면: at dev port <번호> --kill")
    return 0


def cmd_dev_deps(a) -> int:
    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    paths = [Path(f) for f in a.file] if a.file else deps.find_files(root)
    if not paths:
        _p("의존성 파일을 찾지 못했습니다.")
        _p("  찾는 것: pyproject.toml, package.json, go.mod, requirements*.txt")
        return 1

    found: list[deps.DepFile] = []
    for path in paths:
        if not path.is_file():
            _p(f"파일이 없습니다: {path}")
            return 1
        try:
            found.append(deps.read_file(path))
        except ValueError as e:
            _p(str(e))
            return 1

    total = sum(len(f.deps) for f in found)
    loose = [d for f in found for d in f.deps if not d.pinned]
    _p(f"의존성 {total:,}개  ·  파일 {len(found)}개  ·  "
       f"버전 고정 {total - len(loose):,} / 열림 {len(loose):,}\n")

    for f in found:
        pinned = sum(1 for d in f.deps if d.pinned)
        _p(f"{f.path.name}  ({f.kind})  {len(f.deps):,}개"
           + (f"  고정 {pinned}/{len(f.deps)}" if f.deps else ""))
        for note in f.notes:
            _p(f"    {note}")
        if a.list and f.deps:
            _grid(["이름", "버전 조건", "묶음", "고정"],
                  [[d.name, d.spec or "-", d.group, "예" if d.pinned else "아니오"]
                   for d in f.deps[:a.limit]], limit=30)
            if len(f.deps) > a.limit:
                _p(f"    ... {len(f.deps) - a.limit}개 더")
        _p("")

    if a.loose:
        if not loose:
            _p("버전이 열린 의존성이 없습니다.")
            return 0
        _p(f"버전이 고정되지 않은 것 {len(loose)}개")
        _grid(["이름", "조건", "파일"],
              [[d.name, d.spec or "(조건 없음)", Path(d.source).name]
               for d in loose[:a.limit]], limit=28)
        if len(loose) > a.limit:
            _p(f"  ... {len(loose) - a.limit}개 더")
        _p("")

    clashes = deps.conflicts(found)
    if clashes:
        _p(f"파일마다 조건이 다른 것 {len(clashes)}개")
        for name, rows in clashes[:a.limit]:
            joined = ", ".join(f"{where} {spec or '(조건 없음)'}" for where, spec in rows)
            _p(f"  {_pad(name, 24)}{joined}")
        return 1
    _p("파일 사이에 조건이 어긋나는 의존성은 없습니다.")
    return 0


def add_commands(sub) -> None:
    """dev 하위 명령을 붙인다."""
    dp = sub.add_parser("dev", help="백엔드 개발 잡일").add_subparsers(dest="cmd", required=True)

    e = dp.add_parser("env", help=".env 와 .env.example 대조")
    e.add_argument("example", nargs="?", default=".env.example")
    e.add_argument("actual", nargs="?", default=".env")
    e.add_argument("--show-extra", action="store_true")
    e.add_argument("--show-values", action="store_true", help="값을 마스킹해 출력")
    e.add_argument("--sync", action="store_true",
                   help=".env 에서 .env.example 을 만든다 (비밀값은 자리표시자로)")
    e.add_argument("--keep-values", action="store_true",
                   help="--sync 에서 비밀이 아닌 값은 그대로 둔다")
    e.add_argument("--apply", action="store_true", help="--sync 결과를 실제로 쓴다")
    e.set_defaults(func=cmd_dev_env)

    pt = dp.add_parser("port", help="포트 점유 프로세스 확인/종료")
    pt.add_argument("port", type=int)
    pt.add_argument("--kill", action="store_true")
    pt.add_argument("--force", action="store_true", help="SIGKILL")
    pt.add_argument("-y", "--yes", action="store_true", help="확인 없이 종료")
    pt.set_defaults(func=cmd_dev_port)

    dpz = dp.add_parser("deps", help="의존성 파일 훑기 - 개수·고정 여부·충돌")
    dpz.add_argument("dir", nargs="?", default=".")
    dpz.add_argument("-f", "--file", action="append", metavar="파일",
                     help="직접 지정 (여러 번)")
    dpz.add_argument("-l", "--list", action="store_true", help="의존성 목록도")
    dpz.add_argument("--loose", action="store_true", help="버전이 열린 것만 모아 보기")
    dpz.add_argument("--limit", type=int, default=40)
    dpz.set_defaults(func=cmd_dev_deps)

    pl = dp.add_parser("ports", help="열려 있는 포트 전부 보기")
    pl.add_argument("filter", nargs="?", metavar="이름|번호",
                    help="프로세스 이름이나 포트 번호로 거르기")
    pl.add_argument("--limit", type=int, default=40)
    pl.set_defaults(func=cmd_dev_ports)

    j = dp.add_parser("jwt", help="JWT 내용 확인 (서명 검증 안 함)")
    j.add_argument("token", nargs="?", default="-")
    j.set_defaults(func=cmd_dev_jwt)

    t = dp.add_parser("time", help="epoch <-> KST/UTC 변환")
    t.add_argument("when", nargs="?", default="now", help="epoch, ISO 문자열, now")
    t.set_defaults(func=cmd_dev_time)

    wt = dp.add_parser("wait", help="포트/URL 이 열릴 때까지 대기")
    wt.add_argument("target", help="host:port 또는 http(s):// URL")
    wt.add_argument("-t", "--timeout", type=float, default=60.0, metavar="초")
    wt.add_argument("-i", "--interval", type=float, default=1.0, metavar="초")
    wt.add_argument("-q", "--quiet", action="store_true")
    wt.set_defaults(func=cmd_dev_wait)

    cr = dp.add_parser("cron", help="cron 표현식 해석과 다음 실행 시각")
    cr.add_argument("expression", help='예: "0 9 * * 1-5", @daily')
    cr.add_argument("-n", "--count", type=int, default=5)
    cr.set_defaults(func=cmd_dev_cron)

    g = dp.add_parser("gen", help="비밀번호·토큰·UUID 생성")
    g.add_argument("kind", nargs="?", default="password",
                   choices=["password", "token", "hex", "uuid", "pin"])
    g.add_argument("-l", "--length", type=int, default=20)
    g.add_argument("-n", "--count", type=int, default=1)
    g.add_argument("--readable", action="store_true", help="0/O/l/1 처럼 헷갈리는 문자 제외")
    g.set_defaults(func=cmd_dev_gen)

    en = dp.add_parser("enc", help="base64/hex/URL 인코딩·디코딩 한 번에")
    en.add_argument("value", nargs="?", default="-")
    en.set_defaults(func=cmd_dev_enc)

    bn = dp.add_parser("bench", help="명령 실행 시간 측정·비교")
    bn.add_argument("-n", "--runs", type=int, default=10, metavar="회")
    bn.add_argument("-w", "--warmup", type=int, default=1, metavar="회",
                    help="측정에 넣지 않고 먼저 돌릴 횟수")
    bn.add_argument("--cmd", action="append", metavar="명령",
                    help="셸로 실행. 여러 번 주면 서로 비교한다")
    bn.epilog = ('예: at dev bench -n 20 -- pytest -q\n'
                 '    at dev bench --cmd "sort a.txt" --cmd "sort -S1M a.txt"')
    bn.set_defaults(func=cmd_dev_bench, command=[])

    lg = dp.add_parser("log", help="로그 레벨 집계·시간대 분포·반복 에러 묶기")
    lg.add_argument("files", nargs="+", metavar="파일")
    lg.add_argument("-l", "--level", action="append", metavar="레벨",
                    help="예: -l ERROR -l WARN")
    lg.add_argument("-b", "--bucket", default="1h", choices=list(logkit.BUCKETS))
    lg.add_argument("--top", type=int, default=10)
    lg.add_argument("--rows", type=int, default=24, metavar="개",
                help="분포는 최근 이만큼만 보여준다")
    lg.add_argument("--width", type=int, default=90, metavar="칸")
    lg.add_argument("--lines", action="store_true", help="해당 줄 번호도 표시")
    lg.set_defaults(func=cmd_dev_log)

    sl = dp.add_parser("slow", help="로그의 응답 시간 - 경로별 p50/p95 와 느린 요청")
    sl.add_argument("files", nargs="+", metavar="파일")
    sl.add_argument("--pattern", metavar="정규식",
                    help="시간을 뽑을 정규식 (첫 그룹을 ms 로 본다)")
    sl.add_argument("--sort", default="p95",
                    choices=["p95", "p50", "avg", "count", "total"])
    sl.add_argument("--top", type=int, default=10, metavar="개", help="경로 상위 N개")
    sl.add_argument("--over", type=float, default=0, metavar="ms",
                    help="이 시간을 넘는 요청 비율도 센다")
    sl.add_argument("--limit", type=int, default=5, metavar="줄",
                    help="가장 느린 줄 N개")
    sl.set_defaults(func=cmd_dev_slow)

    rt = dp.add_parser("retry", help="성공할 때까지 명령 다시 돌리기 (배로 늘려 기다림)")
    rt.add_argument("-n", "--tries", type=int, default=5, metavar="번")
    rt.add_argument("--delay", type=float, default=1.0, metavar="초",
                    help="첫 실패 뒤 기다릴 시간 (기본 1)")
    rt.add_argument("--backoff", type=float, default=2.0, metavar="배",
                    help="실패할 때마다 곱할 배수 (기본 2)")
    rt.add_argument("--max-delay", type=float, default=60.0, metavar="초")
    rt.add_argument("command", nargs="*", metavar="명령",
                    help="-- 뒤에 그대로 적는다")
    rt.set_defaults(func=cmd_dev_retry, command=[])

    db = dp.add_parser("db", help="sqlite 파일 훑기 (읽기 전용)")
    db.add_argument("file", metavar="db파일")
    db.add_argument("--table", metavar="이름", help="그 표의 열 구성과 앞 몇 행")
    db.add_argument("-q", "--query", metavar="SQL", help="직접 조회 (SELECT 만)")
    db.add_argument("-o", "--out", metavar="파일", help="결과를 csv/xlsx 로 저장")
    db.add_argument("--limit", type=int, default=20, metavar="행")
    db.set_defaults(func=cmd_dev_db)

    ap_ = dp.add_parser("api", help="OpenAPI(json) 문서 훑기 - 엔드포인트·인자·응답")
    ap_.add_argument("file", metavar="openapi.json")
    ap_.add_argument("--find", metavar="말", help="경로나 요약에 이 말이 든 것만")
    ap_.add_argument("--method", metavar="GET", help="이 메서드만")
    ap_.add_argument("--detail", action="store_true", help="인자와 본문까지 자세히")
    ap_.add_argument("--holes", action="store_true",
                     help="요약이나 오류 응답이 빠진 것만")
    ap_.add_argument("--limit", type=int, default=30)
    ap_.set_defaults(func=cmd_dev_api)

    fk = dp.add_parser("fake", help="시험용 가짜 표 만들기 (한글 이름·전화·주소)")
    fk.add_argument("-c", "--col", action="append", required=True, metavar="열=종류",
                    help="예: 이름, 연락처=전화, 금액=금액:1000:9000, 가입일=날짜:365")
    fk.add_argument("-n", "--rows", type=int, default=10, metavar="행")
    fk.add_argument("--seed", type=int, metavar="씨앗", help="같은 값을 다시 만들 때")
    fk.add_argument("-o", "--out", metavar="파일", help="csv 또는 xlsx 로 저장")
    fk.add_argument("--limit", type=int, default=10)
    fk.set_defaults(func=cmd_dev_fake)

    lk = dp.add_parser("lock", help="잠금 파일 두 개를 비교 - 어떤 패키지가 얼마나 바뀌었나")
    lk.add_argument("before", metavar="이전")
    lk.add_argument("after", metavar="이후")
    lk.add_argument("--major", action="store_true", help="맨 앞 숫자가 바뀐 것만")
    lk.add_argument("--limit", type=int, default=40)
    lk.set_defaults(func=cmd_dev_lock)

    un = dp.add_parser("unused", help="안 쓰는 import 찾기 (파이썬)")
    un.add_argument("dirs", nargs="*", default=["."], metavar="경로")
    un.add_argument("--modules", action="store_true",
                    help="아무도 import 하지 않는 모듈도 찾는다")
    un.add_argument("--init", action="store_true",
                    help="__init__.py 도 본다 (다시 내보내기가 많아 오탐이 늘어난다)")
    un.add_argument("--limit", type=int, default=30)
    un.set_defaults(func=cmd_dev_unused)

    ht = dp.add_parser("http", help="HTTP 한 번 부르기 - 상태·시간·본문 (한글 안 깨짐)")
    ht.add_argument("url", metavar="주소")
    ht.add_argument("-X", "--method", metavar="메서드", help="기본 GET (본문 주면 POST)")
    ht.add_argument("-H", "--header", action="append", metavar="이름: 값")
    ht.add_argument("-d", "--data", metavar="본문")
    ht.add_argument("--json", metavar="JSON", help="본문을 JSON 으로 보낸다")
    ht.add_argument("--headers", action="store_true", help="응답 헤더도 보여준다")
    ht.add_argument("--head", action="store_true", help="헤더만 보고 본문은 안 본다")
    ht.add_argument("--timeout", type=float, default=10.0, metavar="초")
    ht.add_argument("-o", "--out", metavar="파일", help="본문을 파일로 저장")
    ht.add_argument("--limit", type=int, default=40, metavar="줄")
    ht.set_defaults(func=cmd_dev_http)

    ol = dp.add_parser("outline", help="파이썬 소스 구조 - 파일별 클래스·함수·긴 함수")
    ol.add_argument("paths", nargs="*", default=["."], metavar="경로")
    ol.add_argument("--file", metavar="파일", help="그 파일의 클래스·함수 목록")
    ol.add_argument("--private", action="store_true", help="_ 로 시작하는 것도")
    ol.add_argument("--sort", default="줄", choices=["줄", "길이", "설명", "이름"])
    ol.add_argument("--long", type=int, default=60, metavar="줄",
                    help="이보다 긴 함수가 있으면 따로 알린다 (기본 60)")
    ol.add_argument("--limit", type=int, default=25)
    ol.set_defaults(func=cmd_dev_outline)

    m = dp.add_parser("mask", help="로그의 개인정보·시크릿 가리기")
    m.add_argument("file", nargs="?", default="-")
    m.add_argument("--in-place", action="store_true")
    m.set_defaults(func=cmd_dev_mask)
