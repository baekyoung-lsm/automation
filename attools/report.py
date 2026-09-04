"""표를 읽기 좋은 HTML 보고서로 만든다. 의존성 없이 SVG 를 직접 그린다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from html import escape

# 값은 dataviz 기준 팔레트에서 가져왔다. 계열이 하나뿐이라 파란색 시퀀셜만 쓴다.
# 두 모드 모두 명도 대역·채도·대비 검사를 통과한 조합이다.
CSS = """
.viz {
  --surface:#fcfcfb; --plane:#f9f9f7;
  --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --hairline:rgba(11,11,11,0.10);
  --series:#2a78d6; --series-soft:#cde2fb;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .viz {
    --surface:#1a1a19; --plane:#0d0d0d;
    --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --hairline:rgba(255,255,255,0.10);
    --series:#3987e5; --series-soft:#184f95;
  }
}
:root[data-theme="dark"] .viz {
  --surface:#1a1a19; --plane:#0d0d0d;
  --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --hairline:rgba(255,255,255,0.10);
  --series:#3987e5; --series-soft:#184f95;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--plane); color:var(--ink);
  font:14px/1.6 system-ui,-apple-system,"Segoe UI","Malgun Gothic",sans-serif;
  word-break:keep-all; }
.viz { max-width:64rem; margin:0 auto; padding:2.5rem 1.5rem 5rem; }
h1 { font-size:1.35rem; margin:0 0 .25rem; letter-spacing:-0.01em; }
.sub { color:var(--ink2); font-size:.85rem; margin-bottom:2rem; }
section { background:var(--surface); border:1px solid var(--hairline);
  border-radius:12px; padding:1.5rem; margin-bottom:1.25rem; }
h2 { font-size:1rem; margin:0 0 1.25rem; }
h2 .note { color:var(--muted); font-weight:400; font-size:.8rem; margin-left:.5rem; }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));
  gap:1.25rem; }
.kpi .label { color:var(--ink2); font-size:.8rem; }
.kpi .value { font-size:1.9rem; line-height:1.2; letter-spacing:-0.02em; }
.kpi .foot { color:var(--muted); font-size:.78rem; }
table { width:100%; border-collapse:collapse; font-size:.86rem; }
th, td { text-align:left; padding:.5rem .6rem; border-bottom:1px solid var(--grid);
  white-space:nowrap; }
th { color:var(--ink2); font-weight:600; font-size:.78rem; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
tbody tr:last-child td { border-bottom:0; }
.scroll { overflow-x:auto; }
svg { display:block; width:100%; height:auto; overflow:visible; }
svg text { font:11px/1 system-ui,-apple-system,"Malgun Gothic",sans-serif;
  fill:var(--muted); }
svg text.label { fill:var(--ink2); }
svg text.value { fill:var(--ink2); font-variant-numeric:tabular-nums; }
.mark { fill:var(--series); }
.mark:hover, .mark:focus { fill:var(--series); filter:brightness(1.12); outline:none; }
.hit { fill:transparent; cursor:default; }
.gridline { stroke:var(--grid); stroke-width:1; }
.axis { stroke:var(--axis); stroke-width:1; }
.line { fill:none; stroke:var(--series); stroke-width:2;
  stroke-linejoin:round; stroke-linecap:round; }
.dot { fill:var(--series); stroke:var(--surface); stroke-width:2; }
#tip { position:fixed; pointer-events:none; opacity:0; transition:opacity .1s;
  background:var(--surface); color:var(--ink); border:1px solid var(--hairline);
  border-radius:8px; padding:.4rem .6rem; font-size:.8rem;
  box-shadow:0 4px 16px rgba(0,0,0,.14); z-index:9; white-space:nowrap; }
details { margin-top:1rem; }
summary { cursor:pointer; color:var(--ink2); font-size:.85rem; }
footer { color:var(--muted); font-size:.78rem; text-align:center; margin-top:2rem; }
@media print {
  body { background:#fff; }
  section { break-inside:avoid; border-color:#ddd; }
  #tip { display:none; }
}
"""

TOOLTIP_JS = """
const tip = document.getElementById("tip");
function show(e) {
  const text = e.currentTarget.dataset.tip;
  if (!text) return;
  tip.textContent = text;
  tip.style.opacity = 1;
  const pad = 14;
  const x = Math.min(e.clientX + pad, window.innerWidth - tip.offsetWidth - 8);
  tip.style.left = x + "px";
  tip.style.top = (e.clientY + pad) + "px";
}
function hide() { tip.style.opacity = 0; }
for (const el of document.querySelectorAll("[data-tip]")) {
  el.addEventListener("mousemove", show);
  el.addEventListener("mouseleave", hide);
  el.addEventListener("focus", e => {
    const r = e.currentTarget.getBoundingClientRect();
    show({ currentTarget: e.currentTarget, clientX: r.left + r.width / 2,
           clientY: r.top });
  });
  el.addEventListener("blur", hide);
}
"""


@dataclass
class Tile:
    label: str
    value: str
    foot: str = ""


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:,.1f}" if abs(value) < 1000 else f"{value:,.0f}"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return "" if value is None else str(value)


def _bar_path(x: float, y: float, width: float, height: float, radius: float = 4) -> str:
    """오른쪽 끝만 둥근 가로 막대. 기준선 쪽은 각지게 둔다."""
    r = max(0.0, min(radius, width, height / 2))
    if width <= 0:
        return ""
    return (f"M{x},{y} H{x + width - r} A{r},{r} 0 0 1 {x + width},{y + r} "
            f"V{y + height - r} A{r},{r} 0 0 1 {x + width - r},{y + height} "
            f"H{x} Z")


def bar_chart(rows: list[tuple[str, float]], *, unit: str = "",
              label_width: int = 150, row_height: int = 26) -> str:
    """가로 막대. 계열이 하나라 범례 없이 값을 직접 붙인다."""
    if not rows:
        return "<p>보여줄 값이 없습니다.</p>"

    gap = 2                      # 이웃한 막대 사이 표면 간격
    bar = row_height - gap * 2
    width, right = 720, 90
    plot = width - label_width - right
    peak = max(abs(v) for _, v in rows) or 1
    height = len(rows) * row_height + 8

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="상위 {len(rows)}개 막대 그래프">']
    for i, (name, value) in enumerate(rows):
        y = i * row_height + gap
        length = max(0.0, abs(value) / peak * plot)
        tip = escape(f"{name}: {_fmt(value)}{unit}")
        parts.append(
            f'<text class="label" x="{label_width - 8}" y="{y + bar / 2 + 4}" '
            f'text-anchor="end">{escape(_cut(name, 18))}</text>')
        parts.append(f'<path class="mark" d="{_bar_path(label_width, y, length, bar)}"/>')
        parts.append(
            f'<text class="value" x="{label_width + length + 8}" '
            f'y="{y + bar / 2 + 4}">{_fmt(value)}{escape(unit)}</text>')
        parts.append(
            f'<rect class="hit" x="0" y="{y - gap}" width="{width}" '
            f'height="{row_height}" tabindex="0" data-tip="{tip}"/>')
    parts.append(f'<line class="axis" x1="{label_width}" y1="0" '
                 f'x2="{label_width}" y2="{height - 8}"/>')
    parts.append("</svg>")
    return "".join(parts)


def line_chart(rows: list[tuple[str, float]], *, unit: str = "") -> str:
    """시간 흐름 한 계열. 점은 지름 8px 이상."""
    if len(rows) < 2:
        return "<p>추이를 그리려면 두 시점 이상 필요합니다.</p>"

    width, height = 720, 240
    left, right, top, bottom = 54, 16, 16, 30
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [v for _, v in rows]
    peak = max(values) or 1
    low = min(0, min(values))
    span = (peak - low) or 1

    def x_at(i: int) -> float:
        return left + (i / (len(rows) - 1)) * plot_w

    def y_at(v: float) -> float:
        return top + plot_h - (v - low) / span * plot_h

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="기간별 추이 선 그래프">']
    for step in range(5):
        value = low + span * step / 4
        y = y_at(value)
        parts.append(f'<line class="gridline" x1="{left}" y1="{y:.1f}" '
                     f'x2="{width - right}" y2="{y:.1f}"/>')
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" '
                     f'text-anchor="end">{_fmt(round(value))}</text>')

    points = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, (_, v) in enumerate(rows))
    parts.append(f'<polyline class="line" points="{points}"/>')

    every = max(1, len(rows) // 8)
    for i, (name, value) in enumerate(rows):
        x, y = x_at(i), y_at(value)
        parts.append(f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="4"/>')
        parts.append(f'<rect class="hit" x="{x - plot_w / len(rows) / 2:.1f}" y="{top}" '
                     f'width="{plot_w / len(rows):.1f}" height="{plot_h}" tabindex="0" '
                     f'data-tip="{escape(f"{name}: {_fmt(value)}{unit}")}"/>')
        if i % every == 0 or i == len(rows) - 1:
            parts.append(f'<text x="{x:.1f}" y="{height - 10}" '
                         f'text-anchor="middle">{escape(name)}</text>')

    parts.append(f'<line class="axis" x1="{left}" y1="{top + plot_h}" '
                 f'x2="{width - right}" y2="{top + plot_h}"/>')
    parts.append("</svg>")
    return "".join(parts)


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def tiles_html(tiles: list[Tile]) -> str:
    cells = "".join(
        f'<div class="kpi"><div class="label">{escape(t.label)}</div>'
        f'<div class="value">{escape(t.value)}</div>'
        + (f'<div class="foot">{escape(t.foot)}</div>' if t.foot else "")
        + "</div>" for t in tiles)
    return f'<div class="kpis">{cells}</div>'


def table_html(headers: list[str], rows: list[list[str]], *,
               numeric: set[int] | None = None) -> str:
    numeric = numeric or set()
    head = "".join(f'<th class="{"num" if i in numeric else ""}">{escape(h)}</th>'
                   for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(
            f'<td class="{"num" if i in numeric else ""}">{escape(c)}</td>'
            for i, c in enumerate(row)) + "</tr>"
        for row in rows)
    return (f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def page(title: str, subtitle: str, sections: list[str], *, note: str = "") -> str:
    body = "\n".join(sections)
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="viz">
  <h1>{escape(title)}</h1>
  <div class="sub">{escape(subtitle)}</div>
{body}
  <footer>{escape(note)}</footer>
</div>
<div id="tip" role="status"></div>
<script>{TOOLTIP_JS}</script>
</body>
</html>
"""
