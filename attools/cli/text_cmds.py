"""at text - 여러 파일 텍스트 처리."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from .. import docx, files, hangul, hwpx, sheet, text
from ..docs import report
from .common import _p, _cut, _grid, _may_write


def _text_targets(a, *, documents: bool = False):
    paths = [Path(p) for p in (a.paths or ["."])]
    missing = [p for p in paths if not p.exists()]
    if missing:
        _p(f"경로가 없습니다: {', '.join(str(m) for m in missing)}")
        return None
    return list(text.iter_files(paths, glob=a.glob, hidden=a.hidden,
                                documents=documents))


def _text_report(a, changes, headline: str) -> int:
    if not changes:
        _p("바꿀 것이 없습니다.")
        return 0

    total = sum(c.hits for c in changes)
    _p(f"{headline}  파일 {len(changes)}개, {total}곳\n")

    for c in changes[:a.limit]:
        note = f"  ({c.note})" if c.note else f"  {c.hits}곳"
        _p(f"{c.path}{note}")
        if not a.quiet:
            for line in c.diff(limit=a.context):
                mark = line[:1]
                prefix = "  " if mark not in "+-" else ("  " + mark)
                _p(f"{prefix if mark in '+-' else '   '}{line[1:] if mark in '+-' else line}")
        _p("")
    if len(changes) > a.limit:
        _p(f"... 파일 {len(changes) - a.limit}개 더 (--limit 로 조절)\n")

    if not a.apply:
        _p("실제로 고치려면 --apply 를 붙이세요. (원본은 백업합니다)")
        return 0

    target = getattr(a, "to", None) if getattr(a, "recode", False) else None
    journal = text.apply_changes(changes, target_encoding=target)
    _p(f"파일 {len(changes)}개를 고쳤습니다.")
    _p(f"되돌리기: at text undo {journal}")
    return 0


def _docx_hint(a, targets, found=None) -> None:
    """워드·한글·PDF 를 봤는지 안 봤는지 분명히 말한다.

    안 보고 조용히 넘기면 «찾았는데 없다» 가 되고, 보고 말 안 하면
    at text replace 로 고칠 수 있는 줄 알게 된다. 둘 다 알려 준다.
    """
    if not a.docx:
        left = [p for p in (_text_targets(a, documents=True) or [])
                if p.suffix.lower() in text.DOCUMENT_SUFFIXES]
        if left:
            _p(f"\n워드·한글·PDF 문서 {len(left)}개는 보지 않았습니다. "
               "--docx 를 붙이면 글자를 꺼내 함께 찾습니다.")
        return
    words = [p for p in targets if p.suffix.lower() in text.DOCUMENT_SUFFIXES]
    if not words:
        return
    hit_words = [f for f in (found or [])
                 if f.path.suffix.lower() in text.DOCUMENT_SUFFIXES]
    if hit_words:
        _p("\n워드·한글·PDF 의 줄 번호는 문단 번호입니다. "
           "그 문서들은 at text replace 로 고치지 못합니다.")
        if any(f.path.suffix.lower() == ".pdf" for f in hit_words):
            _p("PDF 는 글꼴에 글자 정보가 없으면 그 부분이 빠집니다 "
               "(at file pdftext 로 무엇이 빠졌는지 봅니다).")


def cmd_text_find(a) -> int:
    """찾기만 한다. 고치지 않으므로 --apply 가 없다."""
    targets = _text_targets(a, documents=a.docx)
    if targets is None:
        return 1

    try:
        pattern = text.build_pattern(a.find, regex=a.regex,
                                     ignore_case=a.ignore_case, whole_word=a.word)
    except text.TextError as e:
        _p(str(e))
        return 1

    found = text.find_in_files(targets, pattern, context=a.context,
                               per_file=a.per_file, documents=a.docx)
    if not found:
        _p(f"'{a.find}' 를 찾지 못했습니다. (파일 {len(targets)}개를 봤습니다)")
        _docx_hint(a, targets)
        return 1

    total = sum(f.count for f in found)
    if a.count:
        _grid(["파일", "걸린 곳"],
              [[str(f.path), str(f.count)] for f in found[:a.limit]], limit=70)
        if len(found) > a.limit:
            _p(f"\n... 파일 {len(found) - a.limit}개 더 (--limit 로 조절)")
        _p(f"\n파일 {len(found)}개, {total}곳.")
        return 0

    if a.files:
        for f in found[:a.limit]:
            _p(str(f.path))
        if len(found) > a.limit:
            _p(f"... 파일 {len(found) - a.limit}개 더 (--limit 로 조절)")
        return 0

    for f in found[:a.limit]:
        _p(f"{f.path}  ({f.count}곳)")
        for hit in f.hits:
            for offset, line in enumerate(hit.before, hit.line - len(hit.before)):
                _p(f"  {offset:>5}  {_cut(line.rstrip(), a.width)}")
            _p(f"  {hit.line:>5}: {_cut(hit.text.rstrip(), a.width)}")
            for offset, line in enumerate(hit.after, hit.line + 1):
                _p(f"  {offset:>5}  {_cut(line.rstrip(), a.width)}")
            if a.context:
                _p("")
        _p("")

    if len(found) > a.limit:
        _p(f"... 파일 {len(found) - a.limit}개 더 (--limit 로 조절)")
    _p(f"파일 {len(found)}개, {total}곳.")
    _docx_hint(a, targets, found=found)
    return 0


def cmd_text_count(a) -> int:
    """글자 수를 센다. 자소서·과제·기고문에서 매번 세는 그 숫자다."""
    targets = _text_targets(a, documents=True)
    if targets is None:
        return 1
    if not targets:
        _p("파일이 없습니다.")
        return 1

    counts = [text.count_text(p) for p in targets]
    good = [c for c in counts if not c.error]
    counts.sort(key=lambda c: -c.chars)

    _grid(["파일", "글자(공백 포함)", "글자(공백 제외)", "낱말", "줄", "문단",
           "원고지", "못 읽은 까닭"],
          [[_cut(c.path.name, 24), f"{c.chars:,}", f"{c.chars_no_space:,}",
            f"{c.words:,}", f"{c.lines:,}", f"{c.paragraphs:,}",
            f"{c.sheets:g}", _cut(c.error, 24)]
           for c in counts[:a.limit]], limit=24)
    if len(counts) > a.limit:
        _p(f"  ... {len(counts) - a.limit:,}개 더")

    if len(good) > 1:
        chars = sum(c.chars for c in good)
        no_space = sum(c.chars_no_space for c in good)
        _p(f"\n파일 {len(good):,}개  ·  글자 {chars:,} (공백 제외 {no_space:,})"
           f"  ·  원고지 {round(chars / text.MANUSCRIPT_SHEET, 1):g}장")

    if a.limit_chars:
        over = [c for c in good
                if (c.chars_no_space if a.no_space else c.chars) > a.limit_chars]
        기준 = "공백 제외" if a.no_space else "공백 포함"
        if over:
            _p(f"\n{기준} {a.limit_chars:,}자를 넘는 파일 {len(over)}개:")
            for c in over[:a.limit]:
                셈 = c.chars_no_space if a.no_space else c.chars
                _p(f"  {c.path.name}  {셈:,}자  ({셈 - a.limit_chars:,}자 초과)")
            return 1
        _p(f"\n{기준} {a.limit_chars:,}자를 넘는 파일이 없습니다.")

    if any(c.kind in ("워드 문단", "한글 문단") for c in good):
        _p("워드·한글 문서는 문단 글자만 셉니다 (머리글·바닥글·표 밖 글상자는 "
           "빠집니다).")
    if any(str(c.kind).startswith("PDF") for c in good):
        _p("PDF 는 글꼴에 글자 정보(ToUnicode)가 있는 부분만 셉니다 "
           "(스캔한 그림 속 글자는 못 셉니다).")
    _p("원고지는 200자를 한 장으로 셈한 것입니다.")
    return 0


def cmd_text_pick(a) -> int:
    """글에서 이메일·전화·금액 같은 것을 뽑는다. 정규식을 몰라도 되게."""
    targets = _text_targets(a, documents=a.docx)
    if targets is None:
        return 1
    if not targets:
        _p("읽을 파일이 없습니다.")
        return 1

    kinds = [k.strip() for k in (a.only or "").split(",") if k.strip()] or None
    found: list = []
    for path in targets:
        try:
            if a.docx and path.suffix.lower() in text.DOCUMENT_SUFFIXES:
                body, _kind = text.read_words_or_text(path)
            else:
                body, _encoding = text.read_text_any(path)
        except (text.TextError, docx.DocxError, hwpx.HwpxError, OSError):
            continue
        try:
            found += text.pick(body, kinds, source=str(path))
        except text.TextError as e:
            _p(str(e))
            return 1

    if a.unique:
        found = text.unique_picked(found)
    if not found:
        _p(f"뽑을 것이 없습니다. (파일 {len(targets)}개를 봤습니다)")
        _p(f"찾는 종류: {', '.join(text.PICK_RULES)}")
        return 1

    if a.out:
        from .. import sheet

        table = sheet.Table(["종류", "값", "파일", "줄", "그 줄"],
                            [[p.kind, p.value, p.source, p.line, p.context]
                             for p in found])
        if not _may_write(a, Path(a.out)):
            return 1
        _p(f"저장: {sheet.save(table, Path(a.out))}  ({len(found):,}건)")
        return 0

    counts: dict[str, int] = {}
    for item in found:
        counts[item.kind] = counts.get(item.kind, 0) + 1

    _grid(["종류", "값", "파일", "줄"],
          [[p.kind, _cut(p.value, 40), Path(p.source).name, str(p.line)]
           for p in found[:a.limit]], limit=40)
    if len(found) > a.limit:
        _p(f"... {len(found) - a.limit:,}건 더 (--limit 로 조절)")
    _p("\n" + ", ".join(f"{kind} {n}건" for kind, n in counts.items()))
    _p("-o 결과.csv 로 저장할 수 있습니다. 겹치는 값을 하나로 보려면 --unique.")
    return 0


def cmd_text_kbd(a) -> int:
    """한/영 자판을 잘못 눌러 깨진 글을 되살린다."""
    body = " ".join(a.words) if a.words else sys.stdin.read().rstrip("\n")
    if not body.strip():
        _p("고칠 글을 주세요. 예: at text kbd dkssudgktpdy")
        return 1

    way = a.to
    if way == "auto":
        way = hangul.mistyped_direction(body)

    if way == "ko":
        _p(hangul.to_hangul(body))
    elif way == "en":
        _p(hangul.to_qwerty(body))
    else:
        # 한글과 영문이 섞여 있으면 어느 쪽인지 알 수 없다. 둘 다 보여준다.
        _p("한글과 영문이 섞여 있어 어느 쪽인지 알 수 없습니다. 둘 다 냅니다.")
        _p(f"  한글로: {hangul.to_hangul(body)}")
        _p(f"  영문으로: {hangul.to_qwerty(body)}")
    return 0


def cmd_text_lines(a) -> int:
    path = Path(a.file)
    if not path.is_file():
        _p(f"파일이 없습니다: {path}")
        return 1
    try:
        lines = text.read_lines(path, keep_blank=a.blank)
    except (text.TextError, OSError) as e:
        _p(f"읽지 못했습니다: {e}")
        return 1

    if a.compare:
        other = Path(a.compare)
        if not other.is_file():
            _p(f"파일이 없습니다: {other}")
            return 1
        result = text.compare_lines(lines, text.read_lines(other, keep_blank=a.blank),
                                    ignore_case=a.ignore_case)
        _p(f"{path.name} {len(lines):,}줄  vs  {other.name} "
           f"{len(text.read_lines(other, keep_blank=a.blank)):,}줄")
        for label, rows in result.items():
            _p(f"\n{label} {len(rows):,}줄")
            for row in rows[:a.limit]:
                _p(f"  {_cut(row, a.width)}")
            if len(rows) > a.limit:
                _p(f"  ... {len(rows) - a.limit:,}줄 더")
        if a.out:
            picked = result.get(a.pick, [])
            if not _may_write(a, Path(a.out)):
                return 1
            Path(a.out).write_text("\n".join(picked) + "\n", encoding="utf-8")
            _p(f"\n'{a.pick}' {len(picked):,}줄을 저장: {a.out}")
        return 0

    stats = text.line_stats(lines)
    _p(f"{path.name}  {stats.total:,}줄  ·  고유 {stats.unique:,}"
       f"  ·  중복된 값 {stats.duplicated:,}종류({stats.extra:,}줄 초과)"
       + (f"  ·  빈 줄 {stats.blank:,}" if stats.blank else ""))

    if a.count:
        counts = Counter(line for line in lines if line)
        _p(f"\n많이 나온 줄 상위 {min(a.count, len(counts))}개")
        for line, n in counts.most_common(a.count):
            _p(f"  {n:>6,}회  {_cut(line, a.width)}")
        return 0

    result = lines
    if a.unique:
        result = text.unique_lines(result, ignore_case=a.ignore_case)
    if a.sort or a.sort_num:
        result = text.sort_lines(result, descending=a.desc, numeric=a.sort_num)

    if result == lines and not a.out:
        _p("\n--unique, --sort, --count, --compare 중 하나를 주면 처리 결과를 냅니다.")
        return 0

    if a.out:
        if not _may_write(a, Path(a.out)):
            return 1
        Path(a.out).write_text("\n".join(result) + "\n", encoding="utf-8")
        _p(f"\n{len(result):,}줄을 저장: {a.out}")
        return 0

    _p("")
    for line in result[:a.limit]:
        _p(line)
    if len(result) > a.limit:
        _p(f"... {len(result) - a.limit:,}줄 더 (-o 로 저장하세요)")
    return 0


def cmd_text_extract(a) -> int:
    import re as _re

    sources = [Path(f) for f in a.files]
    lines: list[str] = []
    for source in sources:
        if str(source) == "-":
            lines += sys.stdin.read().splitlines()
            continue
        if not source.is_file():
            _p(f"파일이 없습니다: {source}")
            return 1
        try:
            content, _ = text.read_text_any(source)
        except text.TextError as e:
            _p(f"{source}: {e}")
            return 1
        lines += content.splitlines()

    try:
        pattern = _re.compile(a.pattern, _re.I if a.ignore_case else 0)
    except _re.error as e:
        _p(f"정규식이 잘못됐습니다: {e}")
        return 1

    result = text.extract(lines, pattern)
    if not result.rows:
        _p(f"맞는 줄이 없습니다. ({result.total_lines:,}줄 확인)")
        _p("이름 붙인 그룹을 쓰면 열 이름이 됩니다: (?P<시각>\\S+) (?P<레벨>\\w+)")
        return 1

    ratio = result.matched_lines / result.total_lines if result.total_lines else 0
    _p(f"{result.matched_lines:,}줄에서 뽑았습니다 "
       f"(전체 {result.total_lines:,}줄 중 {ratio:.0%})")
    if result.missed and not a.quiet:
        _p(f"  맞지 않은 줄 {result.missed:,}개" +
           (f", 예: {result.samples_missed[0][0]}행 "
            f"{_cut(result.samples_missed[0][1], 50)}" if result.samples_missed else ""))
    _p("")

    _grid(result.headers, result.rows[:a.rows], limit=a.width)
    if len(result.rows) > a.rows:
        _p(f"  ... {len(result.rows) - a.rows:,}행 더")

    if a.out:
        table = sheet.Table(result.headers,
                            [[sheet.parse_value(c) for c in row] for row in result.rows])
        if not _may_write(a, Path(a.out)):
            return 1
        _p(f"\n저장: {sheet.save(table, Path(a.out), sheet_name='추출')}")
    else:
        _p("\n표로 저장하려면 -o 로 csv 나 xlsx 를 지정하세요.")
    return 0


def cmd_text_replace(a) -> int:
    files = _text_targets(a)
    if files is None:
        return 1
    try:
        pattern = text.build_pattern(a.find, regex=a.regex, ignore_case=a.ignore_case,
                                     whole_word=a.word)
        changes = text.plan_replace(files, pattern, a.replace, regex=a.regex)
    except text.TextError as e:
        _p(str(e))
        return 1
    return _text_report(a, changes, f"'{a.find}' -> '{a.replace}'")


def cmd_text_encoding(a) -> int:
    files = _text_targets(a)
    if files is None:
        return 1
    a.recode = True
    changes = text.plan_encoding(files, a.to)
    return _text_report(a, changes, f"인코딩 -> {a.to}")


def cmd_text_eol(a) -> int:
    files = _text_targets(a)
    if files is None:
        return 1
    return _text_report(a, text.plan_eol(files, a.to), f"줄바꿈 -> {a.to.upper()}")


def cmd_text_trim(a) -> int:
    files = _text_targets(a)
    if files is None:
        return 1
    return _text_report(a, text.plan_trim(files, tabs=a.tabs), "공백 정리")


def cmd_text_diff(a) -> int:
    left, right = Path(a.old), Path(a.new)
    for path in (left, right):
        if not path.is_file():
            _p(f"파일이 없습니다: {path}")
            return 1
    try:
        old, old_kind = text.read_words_or_text(left)
        new, new_kind = text.read_words_or_text(right)
    except (text.TextError, docx.DocxError, hwpx.HwpxError) as e:
        _p(f"읽지 못했습니다: {e}")
        return 1

    unit = {"줄": "line", "문장": "sentence", "문단": "para"}[a.unit]
    report = text.diff_units(old, new, unit=unit, similar=a.similar)
    _p(f"{left} -> {right}  ({a.unit} 단위)")
    if {"워드 문단", "한글 문단"} & {old_kind, new_kind}:
        _p("  워드·한글 문서는 문단 글자만 견줍니다. "
           "서식·그림·머리글·각주의 차이는 안 보입니다.")
    if str(old_kind).startswith("PDF") or str(new_kind).startswith("PDF"):
        _p("  PDF 는 글꼴에 글자 정보가 있는 부분만 견줍니다. 줄 나눔은 글자를 "
           "찍은 자리로 어림한 것이라 실제 줄과 다를 수 있습니다.")

    shown = report.edits[:a.limit]
    for e in shown:
        where = f"{e.old_no or e.new_no}"
        if e.kind == "수정" and not a.full:
            _p(f"  {where:>5}  수정  {text.word_marks(e.old, e.new)}")
        elif e.kind == "수정":
            _p(f"  {where:>5}  - {e.old}")
            _p(f"  {'':>5}  + {e.new}")
        elif e.kind == "삭제":
            _p(f"  {where:>5}  - {e.old}")
        else:
            _p(f"  {where:>5}  + {e.new}")

    if len(report.edits) > len(shown):
        _p(f"  … {len(report.edits) - len(shown)}건 더 (--limit 로 늘리세요)")

    c = report.counts
    if not report.edits:
        _p(f"\n{a.unit} {report.new_total}개, 다른 곳이 없습니다.")
        return 0
    _p(f"\n같은 곳 {report.same} · 수정 {c['수정']} · 추가 {c['추가']} · "
       f"삭제 {c['삭제']} · 겹치는 정도 {report.ratio:.0%}")
    _p(f"{a.unit} {report.old_total}개 -> {report.new_total}개. "
       "자리를 옮긴 것은 추가와 삭제로 셉니다.")
    return 1


def cmd_text_typo(a) -> int:
    targets = [Path(p) for p in a.paths]
    files_list: list[Path] = []
    for path in targets:
        if path.is_dir():
            files_list += [q for q in text.iter_files([path], glob=a.glob)]
        elif path.is_file():
            files_list.append(path)
        else:
            _p(f"파일이 없습니다: {path}")
            return 1
    if not files_list:
        _p("검사할 파일이 없습니다.")
        return 1

    changes: list[text.Change] = []
    total = 0
    for path in files_list:
        try:
            body, encoding = text.read_text_any(path)
        except text.TextError:
            continue
        found = hangul.find_typos(body)
        if not found:
            continue
        total += len(found)
        _p(f"{path}  {len(found)}건")
        for t in found[:a.limit]:
            note = f"  ({t.note})" if t.note else ""
            _p(f"  {t.line}행 {t.column}칸  {t.wrong} -> {t.right}{note}")
            _p(f"      {_cut(t.context, 72)}")
        if len(found) > a.limit:
            _p(f"  ... {len(found) - a.limit}건 더")
        _p("")

        fixed, _count = hangul.fix_typos(body)
        if fixed != body:
            changes.append(text.Change(path, body, fixed, encoding, hits=len(found)))

    if not total:
        _p(f"파일 {len(files_list)}개, 걸리는 표기가 없습니다.")
        _p(f"확인한 규칙 {len(hangul.TYPO_RULES) + 1}개만 봅니다. 맞춤법 검사기가 아닙니다.")
        return 0

    _p(f"모두 {total}건")
    if not a.apply:
        _p("고치려면 --apply 를 붙이세요. 되돌리기는 at text undo 입니다.")
        return 1

    journal = text.apply_changes(changes)
    _p(f"파일 {len(changes)}개를 고쳤습니다. 되돌리려면 at text undo")
    _p(f"백업: {journal.parent if journal else '-'}")
    return 0


def cmd_text_wrap(a) -> int:
    targets: list[Path] = []
    for name in a.paths:
        path = Path(name)
        if path.is_dir():
            targets += list(text.iter_files([path], glob=a.glob))
        elif path.is_file():
            targets.append(path)
        else:
            _p(f"파일이 없습니다: {path}")
            return 1
    if not targets:
        _p("접을 파일이 없습니다.")
        return 1

    changes: list[text.Change] = []
    for path in targets:
        try:
            body, encoding = text.read_text_any(path)
        except text.TextError as e:
            _p(f"{path}: 건너뜀 ({e})")
            continue
        wrapped = text.wrap_text(body, width=a.width, skip_code=not a.all,
                                 skip_marked=not a.all)
        if wrapped != body:
            changes.append(text.Change(path, body, wrapped, encoding))

    if not changes:
        _p(f"파일 {len(targets)}개, {a.width}칸을 넘는 줄이 없습니다.")
        return 0

    for c in changes:
        _p(f"{c.path}")
        for line in c.diff(limit=a.limit):
            _p(f"  {line}")
        _p("")

    if not a.apply:
        _p(f"파일 {len(changes)}개를 고칩니다. 실제로 쓰려면 --apply 를 붙이세요.")
        if not a.all:
            _p("코드 블록·표·목록·인용은 건드리지 않습니다 (--all 로 포함).")
        return 0

    journal = text.apply_changes(changes)
    _p(f"파일 {len(changes)}개를 접었습니다. 되돌리려면 at text undo")
    _p(f"백업: {journal.parent if journal else '-'}")
    return 0


def cmd_text_repeat(a) -> int:
    targets: list[Path] = []
    for name in a.paths:
        path = Path(name)
        if path.is_dir():
            targets += list(text.iter_files([path], glob=a.glob))
        elif path.is_file():
            targets.append(path)
        else:
            _p(f"파일이 없습니다: {path}")
            return 1
    if not targets:
        _p("읽을 파일이 없습니다.")
        return 1

    sources: list[tuple[str, str]] = []
    for path in targets:
        try:
            body, _ = text.read_text_any(path)
        except text.TextError:
            continue
        sources.append((str(path), body))

    found = text.repeated_sentences(sources, min_chars=a.min_chars,
                                    min_count=a.min_count)
    if a.same_file:
        found = [r for r in found if r.same_file]
    if not found:
        _p(f"파일 {len(sources)}개, {a.min_chars}자 넘게 똑같이 반복되는 문장이 없습니다.")
        return 0

    _p(f"반복되는 문장 {len(found)}개")
    for r in found[:a.limit]:
        _p(f"\n  {r.count}번  {_cut(r.text, 70)}")
        for name, line in r.places[:6]:
            _p(f"    {name}:{line}")
        if len(r.places) > 6:
            _p(f"    ... {len(r.places) - 6}곳 더")
    if len(found) > a.limit:
        _p(f"\n... {len(found) - a.limit}개 더 (--limit 로 늘리세요)")
    _p("\n일부러 반복한 문장일 수 있습니다. 판단은 사람이 합니다.")
    return 1


def cmd_text_undo(a) -> int:
    journal = Path(a.journal) if a.journal else text.latest_journal()
    if journal is None or not journal.is_file():
        _p("되돌릴 저널이 없습니다.")
        return 1
    if not a.journal:
        _p(f"최근 저널을 사용합니다: {journal}")
    try:
        restored, errors = text.undo(journal)
    except (OSError, ValueError) as e:
        _p(f"저널을 읽지 못했습니다: {e}")
        _p(f"  기록은 {text.backup_dir()} 아래에 남습니다.")
        return 1
    _p(f"{restored}개 파일을 되돌렸습니다.")
    for e in errors:
        _p(f"  건너뜀: {e}")
    return 0 if not errors else 1


def add_commands(sub) -> None:
    """text 하위 명령을 붙인다."""
    tp = sub.add_parser("text", help="여러 파일 텍스트 일괄 처리").add_subparsers(
        dest="cmd", required=True)

    def text_paths(parser):
        parser.add_argument("paths", nargs="*", default=["."], metavar="경로")
        return parser

    def text_common(parser):
        parser.add_argument("-g", "--glob", action="append", metavar="패턴",
                            help="예: -g '*.py' -g '*.md' (기본 전체)")
        parser.add_argument("--hidden", action="store_true")
        parser.add_argument("--apply", action="store_true", help="실제로 고친다")
        parser.add_argument("--limit", type=int, default=20, metavar="개")
        parser.add_argument("--context", type=int, default=8, metavar="줄",
                            help="미리보기 줄 수")
        parser.add_argument("-q", "--quiet", action="store_true", help="차이 미리보기 생략")
        return parser

    ct = tp.add_parser("count", help="글자 수 세기 (공백 포함·제외, 원고지 매수)")
    ct.add_argument("paths", nargs="*", metavar="경로")
    ct.add_argument("-g", "--glob", action="append", metavar="패턴")
    ct.add_argument("--hidden", action="store_true")
    ct.add_argument("--limit-chars", type=int, metavar="자",
                    help="이 글자 수를 넘는 파일이 있으면 1 로 끝난다")
    ct.add_argument("--no-space", action="store_true",
                    help="--limit-chars 를 공백 제외로 센다")
    ct.add_argument("--limit", type=int, default=20, metavar="개")
    ct.set_defaults(func=cmd_text_count)

    pk = tp.add_parser("pick", help="이메일·전화·금액·날짜 뽑아내기 (정규식 없이)")
    text_paths(pk)
    pk.add_argument("-g", "--glob", action="append", metavar="패턴")
    pk.add_argument("--hidden", action="store_true")
    pk.add_argument("--only", metavar="종류",
                    help="쉼표로. 예: --only 이메일,전화 (기본 전부)")
    pk.add_argument("--docx", "--documents", action="store_true",
                    help="워드·한글(hwpx)·PDF 에서도 글자를 꺼내 뽑는다")
    pk.add_argument("--unique", action="store_true", help="같은 값은 한 번만")
    pk.add_argument("-o", "--out", metavar="파일", help="표로 저장 (.csv, .xlsx)")
    pk.add_argument("--overwrite", action="store_true",
                    help="이미 있는 파일을 덮어쓴다")
    pk.add_argument("--limit", type=int, default=40, metavar="개")
    pk.set_defaults(func=cmd_text_pick)

    kb = tp.add_parser("kbd", help="한/영 자판을 잘못 눌러 깨진 글 되살리기")
    kb.add_argument("words", nargs="*", metavar="글",
                    help="비우면 표준 입력에서 읽는다")
    kb.add_argument("--to", default="auto", choices=["auto", "ko", "en"],
                    help="ko=한글로, en=영문으로 (기본 auto)")
    kb.set_defaults(func=cmd_text_kbd)

    fp = tp.add_parser("find", help="여러 파일에서 찾기만 (고치지 않는다)")
    fp.add_argument("find", metavar="찾을것")
    text_paths(fp)
    fp.add_argument("-g", "--glob", action="append", metavar="패턴",
                    help="예: -g '*.py' -g '*.md' (기본 전체)")
    fp.add_argument("--hidden", action="store_true")
    fp.add_argument("-e", "--regex", action="store_true", help="정규식으로")
    fp.add_argument("-i", "--ignore-case", action="store_true")
    fp.add_argument("-w", "--word", action="store_true", help="단어 단위로만")
    fp.add_argument("--docx", "--documents", action="store_true",
                    help="워드·한글(hwpx)·PDF 에서도 글자를 꺼내 찾는다 "
                         "(줄 번호는 문단 번호)")
    fp.add_argument("-C", "--context", type=int, default=0, metavar="줄",
                    help="앞뒤 문맥 줄 수")
    fp.add_argument("--per-file", type=int, default=0, metavar="개",
                    help="파일마다 이 개수까지만 (0=전부)")
    fp.add_argument("--limit", type=int, default=20, metavar="개",
                    help="보여줄 파일 수")
    fp.add_argument("--width", type=int, default=100, metavar="칸",
                    help="줄을 자를 폭")
    fp.add_argument("--files", action="store_true", help="파일 이름만")
    fp.add_argument("--count", action="store_true", help="파일별 건수만")
    fp.set_defaults(func=cmd_text_find)

    rp = tp.add_parser("replace", help="여러 파일에서 찾아 바꾸기")
    rp.add_argument("find", metavar="찾을것")
    rp.add_argument("replace", metavar="바꿀것")
    text_common(text_paths(rp))
    rp.add_argument("-e", "--regex", action="store_true", help="정규식으로")
    rp.add_argument("-i", "--ignore-case", action="store_true")
    rp.add_argument("-w", "--word", action="store_true", help="단어 단위로만")
    rp.set_defaults(func=cmd_text_replace)

    ep = text_common(text_paths(tp.add_parser("encoding", help="cp949 등을 utf-8 로 통일")))
    ep.add_argument("--to", default="utf-8", metavar="인코딩")
    ep.set_defaults(func=cmd_text_encoding)

    lp2 = text_common(text_paths(tp.add_parser("eol", help="줄바꿈을 LF/CRLF 로 통일")))
    lp2.add_argument("--to", default="lf", choices=["lf", "crlf"])
    lp2.set_defaults(func=cmd_text_eol)

    tr = text_common(text_paths(tp.add_parser("trim", help="줄 끝 공백·파일 끝 개행 정리")))
    tr.add_argument("--tabs", type=int, default=0, metavar="칸",
                    help="탭을 이만큼의 공백으로 (기본: 그대로)")
    tr.set_defaults(func=cmd_text_trim)

    ln2 = tp.add_parser("lines", help="줄 단위 정리·대조 (명단 맞춰보기)")
    ln2.add_argument("file")
    ln2.add_argument("--unique", action="store_true", help="중복 줄 제거 (순서 유지)")
    ln2.add_argument("--sort", action="store_true", help="가나다 순 정렬")
    ln2.add_argument("--sort-num", action="store_true", help="줄 앞 숫자로 정렬")
    ln2.add_argument("--desc", action="store_true", help="내림차순")
    ln2.add_argument("--count", type=int, default=0, metavar="개",
                     help="많이 나온 줄 상위 N개")
    ln2.add_argument("--compare", metavar="파일", help="다른 파일과 줄 단위 대조")
    ln2.add_argument("--pick", default="왼쪽만",
                     choices=["공통", "왼쪽만", "오른쪽만"],
                     help="--compare 결과 중 -o 로 저장할 것")
    ln2.add_argument("-i", "--ignore-case", action="store_true")
    ln2.add_argument("--blank", action="store_true", help="빈 줄도 센다")
    ln2.add_argument("-o", "--out", metavar="파일")
    ln2.add_argument("--overwrite", action="store_true",
                     help="이미 있는 파일을 덮어쓴다")
    ln2.add_argument("--limit", type=int, default=30)
    ln2.add_argument("--width", type=int, default=80, metavar="칸")
    ln2.set_defaults(func=cmd_text_lines)

    td = tp.add_parser("diff", help="두 글을 줄·문장·문단 단위로 대조")
    td.add_argument("old", metavar="이전")
    td.add_argument("new", metavar="이후")
    td.add_argument("--unit", default="줄", choices=["줄", "문장", "문단"],
                    help="비교 단위 (기본 줄)")
    td.add_argument("--full", action="store_true",
                    help="고친 곳을 이전·이후 두 줄로 모두 보여준다")
    td.add_argument("--similar", type=float, default=0.5, metavar="비율",
                    help="이만큼 닮아야 '수정' 으로 묶는다 (기본 0.5)")
    td.add_argument("--limit", type=int, default=40)
    td.set_defaults(func=cmd_text_diff)

    ty = tp.add_parser("typo", help="흔한 한글 표기 오류 찾기 (며칠, 웬만, 됐…)")
    ty.add_argument("paths", nargs="+", metavar="경로")
    ty.add_argument("-g", "--glob", action="append", metavar="패턴")
    ty.add_argument("--limit", type=int, default=20)
    ty.add_argument("--apply", action="store_true")
    ty.set_defaults(func=cmd_text_typo)

    tw = tp.add_parser("wrap", help="긴 줄을 폭에 맞춰 접기 (한글 두 칸으로 셈)")
    tw.add_argument("paths", nargs="+", metavar="경로")
    tw.add_argument("-w", "--width", type=int, default=80, metavar="칸")
    tw.add_argument("-g", "--glob", action="append", metavar="패턴")
    tw.add_argument("--all", action="store_true",
                    help="코드 블록·표·목록도 접는다")
    tw.add_argument("--limit", type=int, default=12, metavar="줄")
    tw.add_argument("--apply", action="store_true")
    tw.set_defaults(func=cmd_text_wrap)

    tr = tp.add_parser("repeat", help="똑같이 반복되는 문장 찾기 (복붙 흔적·중복 설명)")
    tr.add_argument("paths", nargs="+", metavar="경로")
    tr.add_argument("-g", "--glob", action="append", metavar="패턴")
    tr.add_argument("--min-chars", type=int, default=12, metavar="자",
                    help="이보다 짧은 문장은 세지 않는다 (기본 12)")
    tr.add_argument("--min-count", type=int, default=2, metavar="번")
    tr.add_argument("--same-file", action="store_true",
                    help="한 파일 안에서 반복된 것만")
    tr.add_argument("--limit", type=int, default=20)
    tr.set_defaults(func=cmd_text_repeat)

    ex2 = tp.add_parser("extract", help="정규식으로 뽑아 표 만들기")
    ex2.add_argument("pattern", metavar="정규식",
                     help="이름 붙인 그룹이 열이 된다: '(?P<시각>\\S+) (?P<레벨>\\w+)'")
    ex2.add_argument("files", nargs="+", metavar="파일", help="'-' 이면 표준 입력")
    ex2.add_argument("-i", "--ignore-case", action="store_true")
    ex2.add_argument("-o", "--out", metavar="파일", help="csv 또는 xlsx")
    ex2.add_argument("--overwrite", action="store_true",
                     help="이미 있는 파일을 덮어쓴다")
    ex2.add_argument("--rows", type=int, default=15, metavar="개")
    ex2.add_argument("--width", type=int, default=22, metavar="칸")
    ex2.add_argument("-q", "--quiet", action="store_true", help="맞지 않은 줄 안내 생략")
    ex2.set_defaults(func=cmd_text_extract)

    tu = tp.add_parser("undo", help="text 명령 되돌리기")
    tu.add_argument("journal", nargs="?")
    tu.set_defaults(func=cmd_text_undo)
