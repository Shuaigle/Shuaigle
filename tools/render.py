#!/usr/bin/env python3
"""Render the SVG graphics used by README.md.

Every string is converted to glyph outlines, so the images look the same on
every machine and need no web fonts. Each graphic is written once per GitHub
colour scheme; README.md picks the right one with <picture>.

    pip install fonttools brotli uharfbuzz
    python3 tools/render.py
"""

import io
from html import escape
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "tools" / "fonts"
OUT = ROOT / "assets"

# Primer foreground colours, so the art sits on GitHub's own page colours.
# One accent, used sparingly: vermilion, the colour of a signature seal.
THEMES = {
    "light": {"ink": "#1f2328", "mute": "#59636e", "rule": "#d1d9e0", "accent": "#d0391b"},
    "dark": {"ink": "#e6edf3", "mute": "#9198a1", "rule": "#3d444d", "accent": "#ff7452"},
}

NAME = "Shuaigle"
ROLE = "Senior backend engineer"
REMIT = "scalable systems × software that thinks"

# A request trace of the profile itself: (span, depth, start ms, end ms).
# The last span has no end. It is still streaming.
SPANS = [
    ("GET /shuaigle", 0, 0, 1000),
    ("backend.architecture", 1, 10, 520),
    ("distributed.systems", 2, 40, 330),
    ("performance.tuning", 2, 250, 500),
    ("fullstack.web", 1, 400, 610),
    ("data.pipelines", 1, 520, 720),
    ("ml.deep_learning", 1, 620, 840),
    ("llm.rag.agents", 1, 760, None),
]
TRACE_MS = 1000
STREAM_UNTIL_MS = 950  # where the open span's bar stops while it streams
PLAYBACK_S = 2.2  # seconds of animation for the full 1000 ms trace
PLAYBACK_DELAY_S = 0.35

PRINCIPLES = [
    ("Write code that scales.", "O(log n)"),
    ("Build systems that last.", "99.99%"),
    ("Never stop learning.", "while (true)"),
]


def num(value, places=2):
    """Format a number compactly: no trailing zeros, no more decimals than needed."""
    text = f"{value:.{places}f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


class Face:
    def __init__(self, key, filename):
        font = TTFont(FONTS / filename)
        font.flavor = None  # HarfBuzz wants plain sfnt data, not WOFF
        data = io.BytesIO()
        font.save(data)
        self.key = key
        self.upem = font["head"].unitsPerEm
        self.glyphs = font.getGlyphSet()
        self.order = font.getGlyphOrder()
        self.hb = hb.Font(hb.Face(data.getvalue()))

    def shape(self, text):
        """Return [(glyph name, x in font units)] and the total advance."""
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb, buf)
        placed, x = [], 0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            placed.append((self.order[info.codepoint], x + pos.x_offset))
            x += pos.x_advance
        return placed, x

    def ink(self, text):
        """Horizontal extent of the inked outlines of `text`, in font units."""
        placed, _ = self.shape(text)
        left, right = [], []
        for name, x in placed:
            pen = BoundsPen(self.glyphs)
            self.glyphs[name].draw(pen)
            if pen.bounds:
                left.append(x + pen.bounds[0])
                right.append(x + pen.bounds[2])
        return min(left), max(right)

    def outline(self, name):
        pen = SVGPathPen(self.glyphs, ntos=num)
        self.glyphs[name].draw(pen)
        return pen.getCommands()

    def contours(self, name):
        """Split a glyph into its contours, ordered top to bottom."""
        rec = DecomposingRecordingPen(self.glyphs)
        self.glyphs[name].draw(rec)
        contours, current = [], []
        for op, args in rec.value:
            current.append((op, args))
            if op in ("closePath", "endPath"):
                contours.append(current)
                current = []
        result = []
        for contour in contours:
            top = max(pt[1] for _, args in contour for pt in args)
            pen = SVGPathPen(self.glyphs, ntos=num)
            for op, args in contour:
                getattr(pen, op)(*args)
            result.append((top, pen.getCommands()))
        return [d for _, d in sorted(result, reverse=True)]


SERIF = Face("s", "instrument-serif-latin-400-normal.woff")
MONO = Face("m", "ibm-plex-mono-latin-400-normal.woff")
MONO_MEDIUM = Face("b", "ibm-plex-mono-latin-500-normal.woff")


class Canvas:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.defs = {}  # glyph key -> (id, path data)
        self.body = []

    def glyph(self, face, name, d=None):
        key = (face.key, name, d)
        if key not in self.defs:
            outline = face.outline(name) if d is None else d
            self.defs[key] = (f"{face.key}{len(self.defs):x}", outline)
        gid, outline = self.defs[key]
        return gid if outline else None

    def text(self, face, text, x, y, size, cls, anchor="start", attrs="", split=None):
        """Place a run of outlined text with its baseline at y.

        `split` maps a glyph name to the CSS classes of its contours, top
        contour first, so one glyph can carry more than one colour.
        """
        placed, advance = face.shape(text)
        scale = size / face.upem
        width = advance * scale
        if anchor == "end":
            x -= width
        elif anchor == "middle":
            x -= width / 2
        uses = []
        for name, ux in placed:
            pos = f' x="{num(ux)}"' if ux else ""
            if split and name in split:
                for piece, piece_cls in zip(face.contours(name), split[name]):
                    gid = self.glyph(face, name, piece)
                    uses.append(f'<use href="#{gid}"{pos} class="{piece_cls}"/>')
                continue
            gid = self.glyph(face, name)
            if gid:
                uses.append(f'<use href="#{gid}"{pos}/>')
        self.body.append(
            f'<g class="{cls}" transform="translate({num(x)} {num(y)}) '
            f'scale({num(scale, 5)} {num(-scale, 5)})"{attrs}>{"".join(uses)}</g>'
        )
        return width

    def add(self, markup):
        self.body.append(markup)

    def render(self, title, desc, theme, css=""):
        colours = THEMES[theme]
        defs = "".join(f'<path id="{gid}" d="{d}"/>' for gid, d in self.defs.values() if d)
        style = (
            f".ink{{fill:{colours['ink']}}}.mute{{fill:{colours['mute']}}}"
            f".accent{{fill:{colours['accent']}}}"
            f".rule{{stroke:{colours['rule']};stroke-width:1;fill:none}}"
            f".wire{{stroke:{colours['mute']};stroke-width:1;fill:none}}"
            f".hair{{stroke:{colours['ink']};stroke-width:1;fill:none}}"
            + css
            + "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" '
            f'height="{self.height}" viewBox="0 0 {self.width} {self.height}" '
            f'role="img" aria-labelledby="title desc">'
            f'<title id="title">{escape(title)}</title><desc id="desc">{escape(desc)}</desc>'
            f"<style>{style}</style><defs>{defs}</defs>{''.join(self.body)}</svg>\n"
        )


WIDTH = 880

TRACE_CSS = (
    "@keyframes grow{from{transform:scaleX(0)}}"
    "@keyframes show{from{opacity:0}}"
    "@keyframes blink{50%{opacity:0}}"
    ".bar{transform-box:fill-box;transform-origin:0 0;animation:grow linear both}"
    ".in{animation:show .3s ease-out both}"
    ".cursor{animation:show 0s linear both,blink 1.06s steps(1) infinite}"
)


def at(ms):
    """Seconds into the animation at which the trace reaches `ms`."""
    return PLAYBACK_DELAY_S + PLAYBACK_S * ms / TRACE_MS


def delay(seconds, duration=None):
    style = f"animation-delay:{num(seconds)}s"
    if duration is not None:
        style += f";animation-duration:{num(duration)}s"
    return f' style="{style}"'


def hero(theme):
    # Set the name wall to wall: its ink, not its advance, spans the width.
    ink_left, ink_right = SERIF.ink(NAME)
    name_size = WIDTH * SERIF.upem / (ink_right - ink_left)
    name_x = -ink_left * name_size / SERIF.upem
    name_base = 232
    role_base = 326
    trace_top = 372
    row = 32
    label_size = 16
    small = 13
    label_x = 0
    indent = 22
    bars_x, bars_w = 280, 500
    bar_h = 10

    rows_top = trace_top + 30
    height = rows_top + row * len(SPANS) + 72  # room below the footer before the prose
    canvas = Canvas(WIDTH, height)

    # The tittle of the i is the only spot of colour in the name.
    canvas.text(SERIF, NAME, name_x, name_base, name_size, "ink",
                split={"i": ["accent", "ink"]})

    canvas.text(MONO_MEDIUM, ROLE, 0, role_base, 18, "ink")
    canvas.text(MONO, REMIT, WIDTH, role_base, 18, "mute", anchor="end")
    canvas.add(f'<path class="hair" d="M0 {role_base + 22.5}H{WIDTH}"/>')

    # Axis.
    def x_of(ms):
        return bars_x + bars_w * ms / TRACE_MS

    axis_base = trace_top + 6
    ticks = range(0, TRACE_MS + 1, 250)
    canvas.text(MONO, "span", label_x, axis_base, small, "mute")
    for ms in ticks:
        label = f"{ms}ms" if ms == TRACE_MS else str(ms)
        anchor = "start" if ms == 0 else "middle"
        canvas.text(MONO, label, x_of(ms), axis_base, small, "mute", anchor=anchor)
    grid_at = len(canvas.body)  # gridlines go under the bars, drawn once spans are known

    # Spans.
    parents = {}  # depth -> (label x, row centre) of the latest span at that depth
    wires = []
    notes = []  # (row, left, right) of the text printed after each bar
    for i, (label, depth, start, end) in enumerate(SPANS):
        centre = rows_top + row * i + row / 2
        base = centre + label_size * 0.33
        lx = label_x + indent * depth
        shown = at(start)
        if depth:
            px, pc = parents[depth - 1]
            stem = px + 5.5
            wires.append(f'<path class="wire in"{delay(shown)} '
                         f'd="M{num(stem)} {num(pc + label_size * 0.6)}V{num(centre)}H{num(lx - 6)}"/>')
        parents[depth] = (lx, centre)
        face = MONO_MEDIUM if depth == 0 else MONO
        canvas.text(face, label, lx, base, label_size, "ink in", attrs=delay(shown))

        stop = end if end is not None else STREAM_UNTIL_MS
        x0, x1 = x_of(start), x_of(stop)
        colour = "accent" if end is None else "ink"
        canvas.add(
            f'<rect class="{colour} bar" x="{num(x0)}" y="{num(centre - bar_h / 2)}" '
            f'width="{num(x1 - x0)}" height="{bar_h}"'
            f'{delay(shown, at(stop) - shown)}/>'
        )
        if end is None:
            canvas.add(
                f'<rect class="accent cursor" x="{num(x1 + 4)}" y="{num(centre - 8)}" '
                f'width="7" height="16"{delay(at(stop))}/>'
            )
            width = canvas.text(MONO, "streaming", x1 + 18, base, small + 1, "accent in",
                                attrs=delay(at(stop)))
            notes.append((i, x1, x1 + 18 + width))
        else:
            took = f"{(end - start) / 1000:.2f}s" if depth == 0 else f"{end - start}ms"
            width = canvas.text(MONO, took, x1 + 8, base, small, "mute in",
                                attrs=delay(at(end)))
            notes.append((i, x1 + 8, x1 + 8 + width))
    canvas.add("".join(wires))

    # Gridlines, broken wherever a row's note would sit on top of one.
    grid = []
    for ms in ticks:
        x = x_of(ms)
        clear = [not any(r == i and left - 4 < x < right + 4 for r, left, right in notes)
                 for i in range(len(SPANS))]
        i = 0
        while i < len(SPANS):
            if not clear[i]:
                i += 1
                continue
            first = i
            while i < len(SPANS) and clear[i]:
                i += 1
            top = rows_top + row * first + (-8 if first == 0 else 3)
            bottom = rows_top + row * i - (6 if i == len(SPANS) else 3)
            grid.append(f"M{num(x + 0.5)} {num(top)}V{num(bottom)}")
    canvas.body.insert(grid_at, f'<path class="rule" d="{"".join(grid)}"/>')

    foot = rows_top + row * len(SPANS) + 16
    canvas.add(f'<path class="hair" d="M0 {foot + 0.5}H{WIDTH}"/>')
    canvas.text(MONO, f"{len(SPANS)} spans · 1 still open", 0, foot + 26, small, "mute")
    canvas.text(MONO, "trace 5hua1g1e", WIDTH, foot + 26, small, "mute", anchor="end")

    labels = ", ".join(label for label, *_ in SPANS[1:-1])
    return canvas.render(
        f"{NAME} — {ROLE}",
        f"{NAME}, {ROLE.lower()}: {REMIT}. A request trace of GET /shuaigle fans out "
        f"into {labels}, and llm.rag.agents, which is still streaming.",
        theme,
        TRACE_CSS,
    )


def principles(theme):
    row = 84
    size = 64
    height = row * len(PRINCIPLES) + 2
    canvas = Canvas(WIDTH, height)
    rules = ["M0 0.5H{w}".format(w=WIDTH)]
    for i, (line, gloss) in enumerate(PRINCIPLES):
        top = row * i
        base = top + row / 2 + size * 0.24
        canvas.text(MONO, f"{i + 1:02d}", 0, base - size * 0.28, 12, "accent")
        canvas.text(SERIF, line, 64, base, size, "ink")
        canvas.text(MONO, gloss, WIDTH, base - size * 0.28, 14, "mute", anchor="end")
        rules.append(f"M0 {top + row + 0.5}H{WIDTH}")
    canvas.add(f'<path class="hair" d="{"".join(rules)}"/>')
    text = " ".join(line for line, _ in PRINCIPLES)
    return canvas.render("Principles", text, theme)


def main():
    OUT.mkdir(exist_ok=True)
    for theme in THEMES:
        for name, build in (("hero", hero), ("principles", principles)):
            path = OUT / f"{name}-{theme}.svg"
            path.write_text(build(theme))
            print(f"{path.relative_to(ROOT)}  {path.stat().st_size / 1024:.1f} KiB")


if __name__ == "__main__":
    main()
