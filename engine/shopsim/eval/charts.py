"""Deterministic, dependency-free SVG charts.

Why not matplotlib: this repo is byte-reproducibility-obsessed (Law 13 hashes,
`make eval` must "reproduce every number and plot from scratch"), and a PNG from
a plotting library varies with the library version, the font stack and the
platform. Hand-written SVG is the same bytes on every machine, diffs cleanly in
git so a calibration change SHOWS as a chart change in review, needs no wheel to
be installed, and renders anywhere. The cost is that this file has to do its own
axes; that is about 200 lines, paid once.

Every chart is theme-neutral (explicit colours on an explicit background) because
these end up in the README, in `/eval`, and on the dashboard.
"""

from __future__ import annotations

import math
from pathlib import Path

W, H = 720, 400
PAD_L, PAD_R, PAD_T, PAD_B = 68, 24, 44, 52

INK = "#1c1c1c"
MUTED = "#6b6b6b"
GRID = "#e4e4e4"
BG = "#ffffff"
BAND = "#dff0e0"
BAND_EDGE = "#8cc79a"
SERIES = ("#2f6fb0", "#c0562e", "#3f8f5f", "#8a5fb0", "#b08a2f", "#5f5f5f")


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _fmt(v: float) -> str:
    """Axis labels without float noise — 0.1 must not render as 0.10000000000000001."""
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 100:
        return f"{v:.0f}"
    if a >= 1:
        return f"{v:.2f}".rstrip("0").rstrip(".")
    if a >= 0.01:
        return f"{v:.3f}".rstrip("0").rstrip(".")
    return f"{v:.4f}".rstrip("0").rstrip(".")


def _nice(lo: float, hi: float, ticks: int = 5) -> tuple[float, float, list[float]]:
    """A rounded axis range: 1/2/5 x 10^k steps, the convention every plotting
    library converges on because arbitrary steps make charts unreadable."""
    if hi <= lo:
        hi = lo + 1.0
    raw = (hi - lo) / max(ticks, 2)
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1.0
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            step = m * mag
            break
    else:
        step = 10 * mag
    start = math.floor(lo / step) * step
    end = math.ceil(hi / step) * step
    n = int(round((end - start) / step))
    return start, end, [round(start + i * step, 10) for i in range(n + 1)]


class Chart:
    def __init__(self, title: str, *, subtitle: str = "", x_label: str = "",
                 y_label: str = "", width: int = W, height: int = H):
        self.title, self.subtitle = title, subtitle
        self.x_label, self.y_label = x_label, y_label
        self.w, self.h = width, height
        self.parts: list[str] = []
        self.legend: list[tuple[str, str]] = []
        self.x0 = self.x1 = self.y0 = self.y1 = 0.0

    # -- geometry ----------------------------------------------------------
    @property
    def px0(self): return PAD_L

    @property
    def px1(self): return self.w - PAD_R

    @property
    def py0(self): return PAD_T

    @property
    def py1(self): return self.h - PAD_B

    def sx(self, x: float) -> float:
        if self.x1 == self.x0:
            return self.px0
        return self.px0 + (x - self.x0) / (self.x1 - self.x0) * (self.px1 - self.px0)

    def sy(self, y: float) -> float:
        if self.y1 == self.y0:
            return self.py1
        return self.py1 - (y - self.y0) / (self.y1 - self.y0) * (self.py1 - self.py0)

    def axes(self, xs, ys, *, x_ticks=None, y_from_zero=True, x_categories=None):
        lo_y = min([0.0] + list(ys)) if y_from_zero else min(ys)
        self.y0, self.y1, yt = _nice(lo_y, max(ys) if ys else 1.0)
        if x_categories is not None:
            self.x0, self.x1 = -0.5, len(x_categories) - 0.5
            xt = list(range(len(x_categories)))
        else:
            self.x0, self.x1, xt = _nice(min(xs), max(xs), ticks=6)
            if x_ticks is not None:
                xt = list(x_ticks)
        g = []
        for v in yt:
            y = self.sy(v)
            g.append(f'<line x1="{self.px0}" y1="{y:.1f}" x2="{self.px1}" y2="{y:.1f}" '
                     f'stroke="{GRID}" stroke-width="1"/>')
            g.append(f'<text x="{self.px0 - 8}" y="{y + 4:.1f}" text-anchor="end" '
                     f'font-size="11" fill="{MUTED}">{_fmt(v)}</text>')
        for i, v in enumerate(xt):
            x = self.sx(v)
            label = _esc(x_categories[i]) if x_categories is not None else _fmt(v)
            g.append(f'<text x="{x:.1f}" y="{self.py1 + 18}" text-anchor="middle" '
                     f'font-size="11" fill="{MUTED}">{label}</text>')
        g.append(f'<line x1="{self.px0}" y1="{self.py1}" x2="{self.px1}" y2="{self.py1}" '
                 f'stroke="{INK}" stroke-width="1.2"/>')
        self.parts = g + self.parts
        return self

    # -- marks -------------------------------------------------------------
    def band(self, lo: float, hi: float, label: str = ""):
        y_hi, y_lo = self.sy(hi), self.sy(lo)
        self.parts.append(
            f'<rect x="{self.px0}" y="{y_hi:.1f}" width="{self.px1 - self.px0}" '
            f'height="{max(0.0, y_lo - y_hi):.1f}" fill="{BAND}" '
            f'stroke="{BAND_EDGE}" stroke-width="1" stroke-dasharray="4 3"/>')
        if label:
            self.parts.append(
                f'<text x="{self.px1 - 6}" y="{y_hi - 5:.1f}" text-anchor="end" '
                f'font-size="10" fill="#4d7a58">{_esc(label)}</text>')
        return self

    def line(self, points, *, color=SERIES[0], label="", dashed=False, dots=True):
        if not points:
            return self
        d = " ".join(("M" if i == 0 else "L") + f"{self.sx(x):.1f},{self.sy(y):.1f}"
                     for i, (x, y) in enumerate(points))
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        self.parts.append(f'<path d="{d}" fill="none" stroke="{color}" '
                          f'stroke-width="2.2" stroke-linejoin="round"{dash}/>')
        if dots:
            for x, y in points:
                self.parts.append(f'<circle cx="{self.sx(x):.1f}" cy="{self.sy(y):.1f}" '
                                  f'r="2.8" fill="{color}"/>')
        if label:
            self.legend.append((label, color))
        return self

    def bars(self, values, *, colors=None, labels=None, value_fmt=_fmt):
        n = len(values)
        if not n:
            return self
        slot = (self.px1 - self.px0) / n
        bw = slot * 0.56
        for i, v in enumerate(values):
            cx = self.px0 + slot * (i + 0.5)
            y = self.sy(v)
            color = (colors[i] if colors else SERIES[i % len(SERIES)])
            self.parts.append(
                f'<rect x="{cx - bw / 2:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                f'height="{max(0.0, self.py1 - y):.1f}" fill="{color}" rx="2"/>')
            self.parts.append(
                f'<text x="{cx:.1f}" y="{y - 6:.1f}" text-anchor="middle" '
                f'font-size="11" fill="{INK}">{_esc(value_fmt(v))}</text>')
            if labels:
                self.parts.append(
                    f'<text x="{cx:.1f}" y="{self.py1 + 18}" text-anchor="middle" '
                    f'font-size="11" fill="{MUTED}">{_esc(labels[i])}</text>')
        return self

    def note(self, text: str):
        self.parts.append(
            f'<text x="{self.px0}" y="{self.h - 8}" font-size="10" fill="{MUTED}">'
            f'{_esc(text)}</text>')
        return self

    # -- output ------------------------------------------------------------
    def render(self) -> str:
        head = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}" font-family="ui-sans-serif,-apple-system,'
            f'Segoe UI,Helvetica,Arial,sans-serif">',
            f'<rect width="{self.w}" height="{self.h}" fill="{BG}"/>',
            f'<text x="{PAD_L}" y="24" font-size="15" font-weight="600" fill="{INK}">'
            f'{_esc(self.title)}</text>',
        ]
        if self.subtitle:
            head.append(f'<text x="{PAD_L}" y="39" font-size="11" fill="{MUTED}">'
                        f'{_esc(self.subtitle)}</text>')
        if self.y_label:
            head.append(f'<text x="14" y="{(self.py0 + self.py1) / 2:.0f}" font-size="11" '
                        f'fill="{MUTED}" transform="rotate(-90 14 '
                        f'{(self.py0 + self.py1) / 2:.0f})" text-anchor="middle">'
                        f'{_esc(self.y_label)}</text>')
        if self.x_label:
            head.append(f'<text x="{(self.px0 + self.px1) / 2:.0f}" y="{self.py1 + 38}" '
                        f'font-size="11" fill="{MUTED}" text-anchor="middle">'
                        f'{_esc(self.x_label)}</text>')
        legend = []
        lx = self.px0
        for label, color in self.legend:
            legend.append(f'<rect x="{lx}" y="{self.py0 - 22}" width="10" height="10" '
                          f'fill="{color}" rx="2"/>')
            legend.append(f'<text x="{lx + 15}" y="{self.py0 - 13}" font-size="11" '
                          f'fill="{INK}">{_esc(label)}</text>')
            lx += 22 + 7 * len(label)
        return "\n".join(head + legend + self.parts + ["</svg>"]) + "\n"

    def save(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render())
        return path
