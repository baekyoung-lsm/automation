"""양식 문서의 «{이름}» 자리 채우기 - 워드와 한글이 함께 쓴다.

두 형식 모두 zip 안의 xml 이고, 문단은 «p», 글자는 «t» 태그다(이름공간
접두사만 다르다: w:, hp:). 그래서 채우는 규칙을 한 벌만 둔다.

xml 을 다시 만들지 않고 글자가 든 자리의 바이트만 고친다. 다시 만들면
이름공간 별칭과 호환성 표시(mc:Ignorable 같은 것)가 떨어져 나가 워드·한글이
«파일이 손상됐다» 고 한다.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

SLOT = re.compile(r"\{([^{}\n]{1,60})\}")
# XML 1.0 이 담지 못하는 제어 문자. 그대로 넣으면 문서가 열리지 않는다
ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
PRESERVE = ' xml:space="preserve"'


@dataclass
class FillReport:
    filled: int = 0                      # 바꾼 자리 수
    used: list = field(default_factory=list)      # 채운 이름
    missing: list = field(default_factory=list)   # 값을 모르는 이름 (그대로 둔다)
    blank: list = field(default_factory=list)     # 값이 빈 칸이던 이름
    parts: list = field(default_factory=list)     # 고친 조각 이름


def as_text(value) -> str:
    """칸 값을 넣을 글자로. 빈 칸은 빈 글자다.

    None 을 그대로 str() 하면 위촉장에 «None» 이 인쇄된다. 빈 칸이던 자리는
    보고에 담아 부르는 쪽이 알리게 한다.
    """
    if value is None:
        return ""
    return str(value)


def escape_text(value) -> str:
    return escape(ILLEGAL.sub("", as_text(value)))


def unescape_text(text: str) -> str:
    from xml.sax.saxutils import unescape

    out = unescape(text, {"&quot;": '"', "&apos;": "'"})
    return re.sub(r"&#(x[0-9a-fA-F]+|\d+);",
                  lambda m: chr(int(m.group(1)[1:], 16) if m.group(1)[0] in "xX"
                                else int(m.group(1))), out)


def part_patterns(raw: bytes, *, para: str = "p", text: str = "t"):
    """(문단 정규식, 글자 정규식, 이름공간 접두사)."""
    """이 조각의 문단·글자 정규식. 이름공간 접두사는 파일에서 읽는다.

    접두사를 «w:» 로 굳혀 두면 다른 프로그램이 만든 파일에서 조용히
    아무것도 못 채운다.
    """
    body = raw.decode("utf-8", "replace")
    found = re.search(rf"<([A-Za-z0-9_.-]+:)?{text}(?=[ />])", body)
    if not found:
        return None
    mark = found.group(1) or ""
    return (re.compile(rf"<{mark}{para}(?:\s[^>]*)?>.*?</{mark}{para}>", re.S),
            re.compile(rf"(<{mark}{text})((?:\s[^>]*)?)(>)(.*?)(</{mark}{text}>)",
                       re.S),
            mark)


def slots_in(text: str) -> list[str]:
    return [m.group(1).strip() for m in SLOT.finditer(text)]


def _fill_paragraph(block: str, text_re, values: dict, report: FillReport, *,
                    mark: str = "", text_tag: str = "t",
                    line_break: str = "br") -> str:
    """문단 한 덩어리를 채운다.

    «{이름}» 이 문서 안에서는 «{이», «름}» 처럼 여러 조각으로 쪼개져 있는 일이
    흔하다(맞춤법 검사·서식 경계). 문단 글자를 이어 붙여 찾고, 걸친 조각의
    글자만 고쳐 쓴다 - 문단을 통째로 다시 쓰면 그 문단의 다른 서식이 날아간다.
    """
    cells = list(text_re.finditer(block))
    if not cells:
        return block
    pieces = [unescape_text(one.group(4)) for one in cells]
    full = "".join(pieces)
    if not SLOT.search(full):
        return block

    plan: dict[int, tuple[int, str]] = {}          # 시작 -> (끝, 넣을 글자)
    for match in SLOT.finditer(full):
        name = match.group(1).strip()
        if name not in values:
            if name not in report.missing:
                report.missing.append(name)
            continue
        made = as_text(values[name])
        plan[match.start()] = (match.end(), made)
        if name not in report.used:
            report.used.append(name)
        if not made.strip() and name not in report.blank:
            report.blank.append(name)
        report.filled += 1
    if not plan:
        return block

    out, spot, last = [], 0, 0
    for one, piece in zip(cells, pieces):
        made = []
        for index, ch in enumerate(piece, spot):
            if index in plan:
                made.append(plan[index][1])
            if not any(start <= index < end for start, (end, _v) in plan.items()):
                made.append(ch)
        spot += len(piece)
        new = "".join(made)
        attrs = one.group(2)
        # 앞뒤 빈칸이 있는 글자는 그렇다고 적어야 지워지지 않는다
        if new != new.strip() and "xml:space" not in attrs:
            attrs += PRESERVE
        out.append(block[last:one.start()])
        # 값에 든 줄바꿈은 글자 «\n» 이 아니라 줄바꿈 태그여야 줄이 바뀐다.
        # 그냥 넣으면 워드·한글이 빈칸 하나로 보여 준다
        body = (f"</{mark}{text_tag}><{mark}{line_break}/>"
                f"<{mark}{text_tag}{attrs}>").join(
            escape_text(줄) for 줄 in new.split("\n"))
        out.append(one.group(1) + attrs + one.group(3) + body + one.group(5))
        last = one.end()
    out.append(block[last:])
    return "".join(out)


def fill_part(raw: bytes, values: dict, report: FillReport, *,
              line_break: str = "br", **kw) -> bytes | None:
    """조각 하나를 채운다. 바뀐 것이 없으면 None."""
    patterns = part_patterns(raw, **kw)
    if patterns is None:
        return None
    para, text_re, mark = patterns
    body = raw.decode("utf-8")
    made = para.sub(
        lambda m: _fill_paragraph(m.group(0), text_re, values, report, mark=mark,
                                  text_tag=kw.get("text", "t"),
                                  line_break=line_break),
        body)
    return made.encode("utf-8") if made != body else None


def slots_in_part(raw: bytes, **kw) -> list[str]:
    """조각에 든 «{이름}» 자리. 나온 차례대로."""
    patterns = part_patterns(raw, **kw)
    if patterns is None:
        return []
    para, text_re, _mark = patterns
    body = raw.decode("utf-8", "replace")
    out: list[str] = []
    for block in para.finditer(body):
        joined = "".join(unescape_text(one.group(4))
                         for one in text_re.finditer(block.group(0)))
        for one in slots_in(joined):
            if one not in out:
                out.append(one)
    return out


def fill_zip(source: Path, dest: Path, values: dict, *, parts, error, **kw):
    """zip 을 통째로 베끼고 고른 조각만 채운다. (보고)

    조각마다 원본의 압축 방식을 그대로 쓴다 - hwpx 의 mimetype 처럼 눌리지
    않은 채로 맨 앞에 있어야 하는 조각이 있다.
    """
    source, dest = Path(source), Path(dest)
    report = FillReport()
    try:
        with zipfile.ZipFile(source) as z:
            items = list(z.infolist())
            keep = {item.filename: z.read(item.filename) for item in items}
    except zipfile.BadZipFile:
        raise error(f"zip 이 아닙니다: {source.name}") from None
    except OSError as exc:
        raise error(f"열지 못했습니다: {exc}") from None

    for name in sorted(keep):
        if not parts(name):
            continue
        made = fill_part(keep[name], values, report, **kw)
        if made is not None:
            keep[name] = made
            report.parts.append(name)

    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as out:
        for item in items:                  # 차례와 압축 방식을 그대로 둔다
            spot = zipfile.ZipInfo(item.filename, date_time=item.date_time)
            spot.compress_type = item.compress_type
            spot.external_attr = item.external_attr
            out.writestr(spot, keep[item.filename])
    return report
