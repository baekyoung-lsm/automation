"""at novel - 소설 집필."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from .. import manuscript, names, sheet, text
from .common import _pad, _p, _read_input, _cut, _grid


def _print_stats(s: manuscript.Stats, *, name: str | None = None) -> None:
    _p(f"{name or s.path}")
    _p(f"  글자수(공백 포함)  {s.chars:,}")
    _p(f"  글자수(공백 제외)  {s.chars_no_space:,}")
    _p(f"  원고지(200자)      {s.wongoji:,.1f}매")
    _p(f"  어절 / 문장 / 문단  {s.words:,} / {s.sentences:,} / {s.paragraphs:,}")
    _p(f"  평균 문장 길이     {s.avg_sentence:.1f}자")
    _p(f"  대사 비율          {s.dialogue_ratio:.1%}")
    _p(f"  읽는 시간          약 {s.read_minutes:.0f}분")
    _p(f"  단행본 환산        약 {s.book_ratio:.2f}권 (10만자 기준 어림값)")


def _parse_goal(text: str) -> int:
    """'300000' 또는 '1500매'(원고지 200자) 를 글자수로."""
    body = text.strip().replace(",", "")
    if body.endswith("매"):
        return int(float(body[:-1]) * 200)
    if body.endswith("자"):
        body = body[:-1]
    return int(float(body))


def cmd_novel_stats(a) -> int:
    targets = manuscript.collect([Path(p) for p in a.paths])
    if not targets:
        _p("텍스트 파일을 찾지 못했습니다.")
        return 1

    stats = [manuscript.analyze(p) for p in targets]
    if a.each or len(stats) == 1:
        for s in stats:
            _print_stats(s)
            _p("")
    if len(stats) > 1:
        _print_stats(manuscript.total(stats))
    return 0


def cmd_novel_check(a) -> int:
    text = _read_input(a.file)
    f = manuscript.inspect(text, top=a.top, long_limit=a.long,
                           run_threshold=a.run)
    empty = True

    def section(title: str, rows: list[str]) -> None:
        nonlocal empty
        if not rows:
            return
        empty = False
        _p(title)
        for r in rows:
            _p(f"  {r}")
        _p("")

    section("상투 표현", [f"{c} x{n}" for c, n in f.cliches])
    section("군더더기 부사", [f"{c} x{n}" for c, n in f.adverbs])
    section("반복 어구(2어절)", [f"{c} x{n}" for c, n in f.phrases])
    section(f"종결 어미 {a.run}회 이상 연속",
            [f"'{e}' {n}문장 연속 (문장 {i}~{i + n - 1})" for e, n, i in f.ending_runs])
    section("같은 말로 시작하는 문장 연속",
            [f"'{w}' {n}문장 연속 (문장 {i}~{i + n - 1})" for w, n, i in f.start_runs])
    section(f"{a.long}자 넘는 문장",
            [f"문장 {i} ({n}자) {prev}" for i, n, prev in f.long_sentences[:a.top]])

    if empty:
        _p("걸리는 항목이 없습니다.")
    return 0


def cmd_novel_snap(a) -> int:
    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    snaps = manuscript.list_snapshots(root)
    if a.list:
        if not snaps:
            _p("스냅샷이 없습니다.")
            return 0
        prev = None
        for s in snaps:
            delta = f"  ({s['total'] - prev:+,}자)" if prev is not None else ""
            note = f"  {s['note']}" if s.get("note") else ""
            _p(f"{s['id']}  {s['total']:,}자{delta}{note}")
            prev = s["total"]
        return 0

    before = snaps[-1]["total"] if snaps else None
    dest = manuscript.snapshot(root, note=a.note)
    after = manuscript.list_snapshots(root)[-1]["total"]
    _p(f"스냅샷 저장: {dest}")
    _p(f"현재 분량: {after:,}자" + (f" ({after - before:+,}자)" if before is not None else ""))
    return 0


def cmd_novel_pace(a) -> int:
    from datetime import date

    root = Path(a.dir)
    if not root.is_dir():
        _p(f"디렉터리가 아닙니다: {root}")
        return 1

    goal = 0
    if a.goal:
        try:
            goal = _parse_goal(a.goal)
        except ValueError:
            _p(f"목표를 읽지 못했습니다: {a.goal} (예: 300000 또는 1500매)")
            return 1
    due = None
    if a.due:
        try:
            due = date.fromisoformat(a.due)
        except ValueError:
            _p(f"마감일은 2026-12-31 형식으로 적어 주세요: {a.due}")
            return 1

    snaps = manuscript.list_snapshots(root)
    if not snaps:
        _p("스냅샷이 없습니다. at novel snap 으로 먼저 한 번 찍어 두세요.")
        return 1

    p = manuscript.pace(snaps, window=a.window, goal=goal, due=due)
    live = manuscript.total([manuscript.analyze(f)
                             for f in manuscript.collect([root])]).chars_no_space

    _p(f"{root}  스냅샷 {len(snaps)}개 "
       f"({p.days[0].day} ~ {p.days[-1].day})")
    _p(f"  마지막 기록      {p.current:,}자 (원고지 {p.current / 200:,.1f}매)")
    if live != p.current:
        _p(f"  지금 원고        {live:,}자 ({live - p.current:+,}자, 아직 스냅샷 안 함)")

    if len(p.days) < 2:
        _p("\n기록이 하루뿐이라 속도를 계산할 수 없습니다. "
           "며칠 더 at novel snap 을 찍어 주세요.")
        return 0

    _p(f"  기록 기간        {p.span}일, 그중 쓴 날 {p.written_days}일")
    _p(f"  하루 평균        {p.per_day:,.0f}자 (달력) / "
       f"{p.per_written_day:,.0f}자 (쓴 날만)")
    if best := p.best:
        _p(f"  가장 많이 쓴 날  {best.day}  {best.written:,}자")

    if a.days:
        _p("")
        rows = [[str(d.day), f"{d.total:,}",
                 "기준" if d.baseline else f"{d.written:+,}"]
                for d in p.days[-a.days:]]
        _grid(["날짜", "누적", "그날"], rows)

    if not goal:
        _p("\n--goal 300000 이나 --goal 1500매 를 주면 남은 분량과 마감을 계산합니다.")
        return 0

    _p(f"\n목표 {goal:,}자까지 {p.remaining:,}자 남았습니다 "
       f"({p.current / goal:.0%} 씀).")
    left = p.days_left()
    if left is not None:
        if left <= 0:
            _p(f"마감 {p.due} 이 지났거나 오늘입니다.")
        else:
            need = p.need_per_day() or 0
            _p(f"마감 {p.due} 까지 {left}일 -> 하루 {need:,.0f}자")
            if need > p.per_day > 0:
                _p(f"필요한 속도가 지금 속도({p.per_day:,.0f}자/일)의 "
                   f"{need / p.per_day:.1f}배입니다.")
    if finish := p.finish_day():
        _p(f"지금 속도면 {finish} 에 목표에 닿습니다. "
           "쉰 날까지 나눈 값이라 계획이 아니라 어림값입니다.")
    elif p.per_day <= 0:
        _p("기간 중 늘어난 분량이 없어 도착일을 계산하지 않았습니다.")
    return 0


def cmd_novel_outline(a) -> int:
    targets = manuscript.collect([Path(p) for p in a.paths])
    if not targets:
        _p("텍스트 파일을 찾지 못했습니다.")
        return 1

    scenes: list[manuscript.Scene] = []
    for path in targets:
        body = manuscript.strip_headings(manuscript.read_text(path)) \
            if a.no_headings else manuscript.read_text(path)
        found = manuscript.split_scenes(body, min_chars=a.min)
        for scene in found:
            scene.number = len(scenes) + 1
            scene.title = scene.title or (path.stem if len(targets) > 1 else "")
            scenes.append(scene)

    if not scenes:
        _p(f"{a.min}자 이상인 장면이 없습니다. --min 을 낮춰 보세요.")
        return 1

    whole = "\n".join(s.text for s in scenes)
    people = list(a.name or []) or [n.text for n in names.extract(whole, min_count=a.people)]
    manuscript.tag_people(scenes, people)

    lengths = [s.chars for s in scenes]
    total = sum(lengths)
    _p(f"장면 {len(scenes)}개  ·  {total:,}자  ·  평균 {total // len(scenes):,}자"
       f"  ·  원고지 {total / manuscript.WONGOJI_CHARS:,.0f}매")
    longest, shortest = max(scenes, key=lambda s: s.chars), min(scenes, key=lambda s: s.chars)
    _p(f"가장 긴 장면 {longest.number}번 {longest.chars:,}자  ·  "
       f"가장 짧은 장면 {shortest.number}번 {shortest.chars:,}자\n")

    header = ["번호", "제목", "행", "분량", "대사", "인물", "첫 문장"]
    body_rows = [[str(s.number), s.title or "-", str(s.line), f"{s.chars:,}",
                  f"{s.dialogue_ratio:.0%}", ", ".join(s.people[:3]) or "-", s.opening]
                 for s in scenes]
    _grid(header, body_rows[:a.limit], limit=a.width)
    if len(scenes) > a.limit:
        _p(f"  ... {len(scenes) - a.limit}개 더 (--limit 로 조절)")

    if a.out:
        table = sheet.Table(header, body_rows)
        _p(f"\n저장: {sheet.save(table, Path(a.out), sheet_name='장면')}")
    return 0


def cmd_novel_find(a) -> int:
    import re as _re

    targets = manuscript.collect([Path(p) for p in a.paths])
    if not targets:
        _p("텍스트 파일을 찾지 못했습니다.")
        return 1

    body = a.query if a.regex else _re.escape(a.query)
    try:
        pattern = _re.compile(body, _re.I if a.ignore_case else 0)
    except _re.error as e:
        _p(f"정규식이 잘못됐습니다: {e}")
        return 1

    found: list[manuscript.Mention] = []
    for path in targets:
        raw = manuscript.read_text(path)
        # 장면 경계는 원문에서 잡고(구분선이 살아 있어야 한다),
        # 찾기는 제목만 지운 본문에서 한다. 줄 수가 같아 행 번호가 맞는다.
        scenes = manuscript.split_scenes(raw, min_chars=a.min)
        found += manuscript.find_mentions(manuscript.strip_headings(raw), pattern,
                                          path=path.name, context=a.context,
                                          scenes=scenes)

    if not found:
        _p(f"'{a.query}' 를 찾지 못했습니다.")
        return 1

    _p(f"'{a.query}'  {len(found)}번  (파일 {len({m.path for m in found})}개)")
    first, last = found[0], found[-1]
    _p(f"처음 {first.path}:{first.line}행" + (f" 장면 {first.scene}" if first.scene else "")
       + f"  ·  마지막 {last.path}:{last.line}행"
       + (f" 장면 {last.scene}" if last.scene else "") + "\n")

    for m in found[:a.limit]:
        where = f"{m.path}:{m.line}행" + (f"  장면 {m.scene}" if m.scene else "")
        _p(f"  {where}")
        _p(f"    {_cut(m.context(), a.width)}")
    if len(found) > a.limit:
        _p(f"  ... {len(found) - a.limit}번 더 (--limit 로 조절)")
    return 0


def cmd_novel_timeline(a) -> int:
    targets = manuscript.collect([Path(p) for p in a.paths])
    if not targets:
        _p("텍스트 파일을 찾지 못했습니다.")
        return 1

    marks: list[manuscript.TimeMark] = []
    conflicts: list[tuple[str, manuscript.TimeConflict]] = []
    for path in targets:
        raw = manuscript.read_text(path)
        scenes = manuscript.split_scenes(raw, min_chars=a.min)
        found = manuscript.find_time_marks(manuscript.strip_headings(raw), scenes=scenes)
        for m in found:
            m.sentence = f"{path.name}|{m.sentence}"
        marks += found
        conflicts += [(path.name, c) for c in manuscript.time_conflicts(found)]

    if not marks:
        _p("시간을 가리키는 표현을 찾지 못했습니다.")
        return 0

    kinds = Counter(m.kind for m in marks)
    _p(f"시간 표현 {len(marks)}개  ·  "
       + "  ".join(f"{k} {v}" for k, v in kinds.most_common()) + "\n")

    shown = [m for m in marks if not a.kind or m.kind in a.kind]
    for m in shown[:a.limit]:
        name, _, sentence = m.sentence.partition("|")
        where = f"{name}:{m.line}행" + (f" 장면 {m.scene}" if m.scene else "")
        _p(f"  {_pad(m.text, 16)}[{m.kind}]  {where}")
        if a.context:
            _p(f"      {_cut(sentence, a.width)}")
    if len(shown) > a.limit:
        _p(f"  ... {len(shown) - a.limit}개 더")

    if not conflicts:
        _p("\n한 장면 안에서 시간대·계절이 어긋난 곳은 없습니다.")
        return 0

    _p(f"\n같은 장면에서 어긋난 곳 {len(conflicts)}건")
    for name, c in conflicts:
        _p(f"  {name} 장면 {c.scene}: {c.kind} 이 {', '.join(c.values)} 로 섞였습니다"
           f"  ({', '.join(str(n) for n in c.lines)}행)")
    _p("\n회상이나 시간 경과를 일부러 넣은 것일 수 있으니 눈으로 확인하세요.")
    return 1


def cmd_novel_style(a) -> int:
    targets = manuscript.collect([Path(p) for p in a.paths])
    if not targets:
        _p("텍스트 파일을 찾지 못했습니다.")
        return 1

    rows: list[manuscript.Style] = []
    if a.by == "scene":
        for path in targets:
            raw = manuscript.read_text(path)
            for scene in manuscript.split_scenes(raw, min_chars=a.min):
                label = f"{path.stem}#{scene.number}"
                rows.append(manuscript.style_metrics(scene.text, label,
                                                     long_limit=a.long))
    else:
        for path in targets:
            rows.append(manuscript.style_metrics(manuscript.read_text(path),
                                                 path.stem, long_limit=a.long))

    rows = [r for r in rows if r.sentences]
    if not rows:
        _p("잴 만한 내용이 없습니다.")
        return 1

    _grid(manuscript.STYLE_COLUMNS, [r.as_row() for r in rows[:a.limit]], limit=14)
    if len(rows) > a.limit:
        _p(f"  ... {len(rows) - a.limit}개 더")

    _p("\n평균/중앙 = 문장 길이(자)  ·  긴문장 = "
       f"{a.long}자 초과 비율  ·  어미쏠림 = 종결 어미 상위 3개 비중")
    _p("어휘 = 고유 어절 / 전체 어절. 낮을수록 같은 말이 반복된다는 뜻입니다.")

    outliers = manuscript.style_outliers(rows, sigma=a.sigma)
    if not outliers:
        _p("\n다른 것들과 크게 다른 곳은 없습니다."
           if len(rows) >= 3 else "\n비교하려면 대상이 셋 이상 있어야 합니다.")
        return 0

    _p(f"\n튀는 곳 {len(outliers)}개")
    for name, reasons in outliers.items():
        _p(f"  {_pad(name, 16)}{', '.join(reasons)}")
    _p("\n의도한 것일 수 있습니다. 어느 화가 다른지 짚어 줄 뿐입니다.")
    return 0


def cmd_novel_export(a) -> int:
    targets = manuscript.collect([Path(p) for p in a.paths])
    # 내보낸 파일이 원고 디렉터리 안에 있으면 다음 실행에서 원고로 다시 잡힌다.
    # 형식을 바꿔 가며 내보내면 투고본.txt 가 투고본.html 의 원고가 되는 식이다.
    if a.out:
        out_path = Path(a.out).resolve()
        before = len(targets)
        targets = [p for p in targets
                   if p.resolve() != out_path and p.stem != out_path.stem]
        dropped = before - len(targets)
        if dropped:
            _p(f"앞서 내보낸 '{out_path.stem}' 파일 {dropped}개는 원고에서 뺐습니다.")
    if not targets:
        _p("텍스트 파일을 찾지 못했습니다.")
        return 1

    chapters: list[tuple[str, str]] = []
    total = 0
    for path in targets:
        raw = manuscript.read_text(path)
        name = manuscript.chapter_title(path, raw)
        # HTML·EPUB 은 CSS 로 들여쓰므로 본문에 공백 문자를 넣지 않는다
        body = manuscript.normalize_body(raw,
                                         indent=a.indent
                                         and a.format not in ("html", "epub"),
                                         scene_mark=a.scene_mark,
                                         join_lines=a.join)
        total += len("".join(body.split()))   # 공백 제외 글자수
        chapters.append((name, body))

    note = a.note or (f"{total:,}자  ·  원고지 {total / manuscript.WONGOJI_CHARS:,.0f}매"
                      f"  ·  {len(chapters)}편")

    if not a.out:
        _p(note)
        for name, body in chapters:
            _p(f"  {_pad(name, 24)}{len(''.join(body.split())):,}자")
        _p("\n저장하려면 -o 로 출력 파일을 지정하세요.")
        return 0

    if a.format == "epub":
        dest = manuscript.export_epub(chapters, Path(a.out), title=a.title,
                                      author=a.author, note=note, indent=a.indent)
        _p(f"저장: {dest}  ({note})")
        _p("리더에 넣어 읽으면 화면이 달라져서 눈에 안 띄던 것이 보입니다.")
        return 0

    if a.format == "html":
        text = manuscript.export_html(chapters, title=a.title, author=a.author,
                                      note=note, indent=a.indent)
    else:
        text = manuscript.export_text(chapters, title=a.title, author=a.author,
                                      note=note, markdown=a.format == "md")

    target = Path(a.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    _p(f"저장: {target}  ({note})")
    if a.format == "html":
        _p("브라우저에서 열어 인쇄하면 화마다 쪽이 나뉩니다.")
    return 0


def cmd_novel_dialogue(a) -> int:
    targets = manuscript.collect([Path(p) for p in a.paths])
    if not targets:
        _p("텍스트 파일을 찾지 못했습니다.")
        return 1

    body = "\n".join(manuscript.strip_headings(manuscript.read_text(p))
                     for p in targets)
    # 대사 화자는 대부분 '이름이 말했다' 꼴이라 조사 종류가 하나뿐이다.
    # 이름 후보를 뽑을 때 조사 다양성 조건을 걸면 주요 인물이 통째로 빠진다.
    people = list(a.name or []) or [n.text for n in names.extract(body, min_count=a.min,
                                                                  min_variety=1)]
    if not people:
        _p(f"{a.min}회 이상 나오는 인물을 찾지 못했습니다. --min 을 낮추거나 "
           "--name 으로 지정하세요.")
        return 1

    speeches = names.extract_speech(body, people)
    if not speeches:
        _p("대사를 찾지 못했습니다. 따옴표로 묶인 부분을 대사로 봅니다.")
        return 1

    profiles, unknown = names.voice_profiles(speeches)
    total = len(speeches)
    _p(f"대사 {total:,}개  ·  인물 {len(profiles)}명"
       f"  ·  화자 못 찾음 {unknown:,}개 ({unknown / total:.0%})\n")

    _grid(["인물", "대사", "비중", "평균", "존댓말", "자주 쓰는 어미"],
          [[p.name, f"{p.count:,}", f"{p.count / total:.0%}",
            f"{p.avg_length:.0f}자", f"{p.polite_ratio:.0%}",
            " ".join(f"{e}{n}" for e, n in p.top_endings) or "-"]
           for p in profiles[:a.limit]], limit=22)

    if unknown / total > 0.3:
        _p(f"\n화자를 못 찾은 대사가 {unknown / total:.0%} 입니다. 같은 줄에 이름이 "
           "없으면 비워 둡니다 - 억지로 채우면 집계가 어긋나서입니다.")

    if a.samples:
        _p("")
        for profile in profiles[:a.limit]:
            lines = [s.text for s in speeches if s.speaker == profile.name][:a.samples]
            _p(f"{profile.name}")
            for line in lines:
                _p(f"  \"{_cut(line, a.width)}\"")
    return 0


def cmd_novel_wordlist(a) -> int:
    targets = manuscript.collect([Path(p) for p in a.paths])
    if not targets:
        _p("텍스트 파일을 찾지 못했습니다.")
        return 1

    documents = [(p.stem, manuscript.strip_markup(manuscript.read_text(p)))
                 for p in targets]
    words = names.build_wordlist(documents, min_count=a.min, max_len=a.max_len,
                                 skip_common=not a.all)
    if not words:
        _p(f"{a.min}회 이상 나오는 말이 없습니다.")
        return 1

    order = [name for name, _ in documents]
    _p(f"어휘 {len(words):,}개  ·  파일 {len(documents)}개  ·  "
       f"{a.min}회 이상만\n")

    if a.only:
        if a.only not in order:
            _p(f"'{a.only}' 파일이 없습니다. 있는 것: {', '.join(order)}")
            return 1
        picked = names.words_only_in(words, a.only)
        _p(f"'{a.only}' 에서만 쓰인 말 {len(picked):,}개")
        _grid(["말", "횟수"], [[w.text, f"{w.count:,}"] for w in picked[:a.limit]],
              limit=20)
        if len(picked) > a.limit:
            _p(f"  ... {len(picked) - a.limit:,}개 더")
        return 0

    if a.new:
        firsts = names.first_appearances(words, order)
        for name in order:
            rows = firsts[name]
            _p(f"{name}  처음 나온 말 {len(rows):,}개")
            _p("  " + _cut(", ".join(w.text for w in rows[:a.limit]), a.width * 3))
            _p("")
        return 0

    table_rows = [[w.text, f"{w.count:,}", w.first_source, f"{w.spread}개"]
                  for w in words]
    _grid(["말", "횟수", "처음 나온 곳", "쓰인 곳"], table_rows[:a.limit], limit=20)
    if len(words) > a.limit:
        _p(f"  ... {len(words) - a.limit:,}개 더 (--limit 로 조절)")

    once = [w for w in words if w.spread == 1]
    _p(f"\n한 곳에서만 쓰인 말 {len(once):,}개"
       f"  ·  --only <파일이름> 으로 어느 편의 고유 어휘인지 봅니다.")

    if a.out:
        out_table = sheet.Table(["말", "횟수", "처음 나온 곳", "쓰인 곳 수"],
                                [[w.text, w.count, w.first_source, w.spread]
                                 for w in words])
        _p(f"저장: {sheet.save(out_table, Path(a.out), sheet_name='어휘')}")
    return 0


def cmd_novel_names(a) -> int:
    targets = manuscript.collect([Path(p) for p in a.paths])
    if not targets:
        _p("텍스트 파일을 찾지 못했습니다.")
        return 1

    body = manuscript.strip_markup("\n".join(manuscript.read_text(p) for p in targets))
    found = names.extract(body, min_count=a.min, min_variety=a.variety)
    known = [n.text for n in found] + list(a.name or [])

    if not found and not a.name:
        _p(f"{a.min}회 이상 나오는 이름 후보가 없습니다. --min 을 낮춰 보세요.")
        return 0

    speakers = names.dialogue_speakers(body, known)
    _p(f"이름 후보 {len(found)}개  (파일 {len(targets)}개)")
    _grid(["이름", "등장", "붙은 조사", "대사 뒤"],
          [[n.text, f"{n.count}회",
            " ".join(f"{p}{c}" for p, c in n.particles.most_common(4)),
            f"{speakers[n.text]}회" if speakers.get(n.text) else "-"]
           for n in found[:a.limit]], limit=a.width)
    if len(found) > a.limit:
        _p(f"  ... {len(found) - a.limit}개 더")
    _p("")

    shaky = names.variants(found, names.all_stems(body), distance=a.distance)
    if shaky:
        _p(f"표기 흔들림 의심 {len(shaky)}건")
        for confirmed, rare, dist in shaky[:a.limit]:
            _p(f"  {confirmed.text}({confirmed.count}회)  vs  "
               f"{rare.text}({rare.count}회)")
        _p("  드물게 나오는 쪽이 오타일 가능성이 큽니다.\n")

    if a.no_josa:
        return 0

    errors = names.check_josa(body, known)
    if not errors:
        _p("이름 뒤 조사는 문제 없습니다.")
        return 0

    _p(f"이름 뒤 조사 오류 {len(errors)}건")
    for e in errors[:a.limit]:
        _p(f"  {e.line}행  {e.name}{e.wrong} -> {e.name}{e.right}")
        _p(f"        …{e.excerpt}…")
    if len(errors) > a.limit:
        _p(f"  ... {len(errors) - a.limit}건 더")
    _p("\n행 번호는 파일을 이어 붙인 기준입니다.")
    return 1


def add_commands(sub) -> None:
    """novel 하위 명령을 붙인다."""
    np_ = sub.add_parser("novel", help="소설 원고").add_subparsers(dest="cmd", required=True)

    s = np_.add_parser("stats", help="분량 집계 (원고지·단행본 환산)")
    s.add_argument("paths", nargs="+")
    s.add_argument("--each", action="store_true", help="파일별로도 출력")
    s.set_defaults(func=cmd_novel_stats)

    c = np_.add_parser("check", help="반복·상투구·긴 문장 점검")
    c.add_argument("file", nargs="?", default="-")
    c.add_argument("--top", type=int, default=10)
    c.add_argument("--long", type=int, default=100, metavar="자")
    c.add_argument("--run", type=int, default=4, metavar="회")
    c.set_defaults(func=cmd_novel_check)

    nm = np_.add_parser("names", help="인물·지명 표기 흔들림과 이름 뒤 조사 오류")
    nm.add_argument("paths", nargs="+")
    nm.add_argument("--min", type=int, default=3, metavar="회",
                    help="이름으로 볼 최소 등장 횟수")
    nm.add_argument("--variety", type=int, default=2, metavar="개",
                    help="붙은 조사 종류가 이만큼 이상일 때만 이름으로 본다")
    nm.add_argument("--name", action="append", metavar="이름",
                    help="검사할 이름을 직접 지정 (여러 번)")
    nm.add_argument("--distance", type=int, default=1, choices=[1, 2])
    nm.add_argument("--limit", type=int, default=20)
    nm.add_argument("--width", type=int, default=20, metavar="칸")
    nm.add_argument("--no-josa", action="store_true", help="조사 검사 생략")
    nm.set_defaults(func=cmd_novel_names)

    ol = np_.add_parser("outline", help="장면 목록 - 분량·대사 비율·등장인물·첫 문장")
    ol.add_argument("paths", nargs="+")
    ol.add_argument("--min", type=int, default=100, metavar="자",
                    help="이보다 짧은 덩어리는 장면으로 세지 않는다")
    ol.add_argument("--people", type=int, default=3, metavar="회",
                    help="인물로 볼 최소 등장 횟수")
    ol.add_argument("--name", action="append", metavar="이름", help="인물을 직접 지정")
    ol.add_argument("--no-headings", action="store_true",
                    help="마크다운 제목을 장면 제목으로 쓰지 않는다")
    ol.add_argument("--limit", type=int, default=50)
    ol.add_argument("--width", type=int, default=30, metavar="칸")
    ol.add_argument("-o", "--out", metavar="파일", help="csv 또는 xlsx 로 저장")
    ol.set_defaults(func=cmd_novel_outline)

    fd = np_.add_parser("find", help="원고에서 문맥과 함께 찾기 (복선·소재 추적)")
    fd.add_argument("query", metavar="찾을것")
    fd.add_argument("paths", nargs="+")
    fd.add_argument("-e", "--regex", action="store_true")
    fd.add_argument("-i", "--ignore-case", action="store_true")
    fd.add_argument("-c", "--context", type=int, default=1, metavar="문장",
                    help="앞뒤로 붙일 문장 수")
    fd.add_argument("--min", type=int, default=100, metavar="자", help="장면 최소 분량")
    fd.add_argument("--limit", type=int, default=30)
    fd.add_argument("--width", type=int, default=110, metavar="칸")
    fd.set_defaults(func=cmd_novel_find)

    tl = np_.add_parser("timeline", help="시간 표현 모아 보기와 장면 안 시간 충돌")
    tl.add_argument("paths", nargs="+")
    tl.add_argument("-k", "--kind", action="append", metavar="종류",
                    choices=["날짜", "시각", "요일", "상대", "기간", "시간대", "계절"])
    tl.add_argument("--context", action="store_true", help="문장도 함께")
    tl.add_argument("--min", type=int, default=100, metavar="자", help="장면 최소 분량")
    tl.add_argument("--limit", type=int, default=60)
    tl.add_argument("--width", type=int, default=100, metavar="칸")
    tl.set_defaults(func=cmd_novel_timeline)

    sy = np_.add_parser("style", help="화별 문체 지표 비교 - 튀는 화 찾기")
    sy.add_argument("paths", nargs="+")
    sy.add_argument("--by", default="file", choices=["file", "scene"])
    sy.add_argument("--long", type=int, default=80, metavar="자",
                    help="긴 문장으로 볼 기준")
    sy.add_argument("--sigma", type=float, default=1.5, metavar="배",
                    help="표준편차 이만큼 벗어나면 튀는 것으로 본다")
    sy.add_argument("--min", type=int, default=100, metavar="자", help="장면 최소 분량")
    sy.add_argument("--limit", type=int, default=40)
    sy.set_defaults(func=cmd_novel_style)

    ex = np_.add_parser("export", help="여러 화를 한 파일로 - 투고·인쇄용")
    ex.add_argument("paths", nargs="+")
    ex.add_argument("-o", "--out", metavar="파일")
    ex.add_argument("-f", "--format", default="html",
                    choices=["html", "txt", "md", "epub"])
    ex.add_argument("--title", default="", metavar="제목")
    ex.add_argument("--author", default="", metavar="필명")
    ex.add_argument("--note", default="", metavar="설명", help="기본: 분량 요약")
    ex.add_argument("--indent", action="store_true", help="문단 첫 줄을 한 칸 들여쓴다")
    ex.add_argument("--join", action="store_true",
                    help="여러 줄에 접힌 문단을 한 문단으로 합친다")
    ex.add_argument("--scene-mark", default="", metavar="표시",
                    help="장면 구분선을 이걸로 바꾼다 (예: ＊)")
    ex.set_defaults(func=cmd_novel_export)

    dg = np_.add_parser("dialogue", help="인물별 대사량과 말투 (존댓말·어미)")
    dg.add_argument("paths", nargs="+")
    dg.add_argument("--name", action="append", metavar="이름", help="인물 직접 지정")
    dg.add_argument("--min", type=int, default=3, metavar="회",
                    help="인물로 볼 최소 등장 횟수")
    dg.add_argument("--samples", type=int, default=0, metavar="개",
                    help="인물마다 대사 예시를 이만큼 보여준다")
    dg.add_argument("--limit", type=int, default=20)
    dg.add_argument("--width", type=int, default=70, metavar="칸")
    dg.set_defaults(func=cmd_novel_dialogue)

    wl = np_.add_parser("wordlist", help="어휘 목록 - 빈도·처음 나온 화·고유 어휘")
    wl.add_argument("paths", nargs="+")
    wl.add_argument("--min", type=int, default=2, metavar="회")
    wl.add_argument("--max-len", type=int, default=6, metavar="자",
                    help="이보다 긴 어절은 세지 않는다")
    wl.add_argument("--new", action="store_true", help="화마다 처음 나온 말")
    wl.add_argument("--all", action="store_true",
                    help="'마을·얼굴' 같은 흔한 말도 포함")
    wl.add_argument("--only", metavar="파일이름", help="그 파일에서만 쓰인 말")
    wl.add_argument("--limit", type=int, default=40)
    wl.add_argument("--width", type=int, default=24, metavar="칸")
    wl.add_argument("-o", "--out", metavar="파일", help="csv 또는 xlsx 로 저장")
    wl.set_defaults(func=cmd_novel_wordlist)

    sn = np_.add_parser("snap", help="원고 스냅샷 저장/목록")
    sn.add_argument("dir", nargs="?", default=".")
    sn.add_argument("--note", default="")
    sn.add_argument("-l", "--list", action="store_true")
    sn.set_defaults(func=cmd_novel_snap)

    pc = np_.add_parser("pace", help="스냅샷으로 집필 속도·마감 계산")
    pc.add_argument("dir", nargs="?", default=".")
    pc.add_argument("--goal", metavar="분량", help="목표 (예: 300000 또는 1500매)")
    pc.add_argument("--due", metavar="날짜", help="마감일 (2026-12-31)")
    pc.add_argument("--window", type=int, default=0, metavar="일",
                    help="최근 N일 기록만 본다 (기본 전부)")
    pc.add_argument("--days", type=int, default=0, metavar="줄",
                    help="날짜별 표를 N줄 보여준다")
    pc.set_defaults(func=cmd_novel_pace)
