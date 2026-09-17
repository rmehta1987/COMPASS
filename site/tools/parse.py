"""Step 4 — the page parses.

Scripts go through ``node --check`` and then ``render.js`` drives every
panel for every example under a DOM stub, failing on an exception or on
"undefined"/"NaN" in a rendered panel. The HTML is walked with a strict
balanced-tag check (void elements excepted): a stray or missing close tag
renders differently across browsers and no offline validator ships with the
repo, so this is the gate. Also requires ``<title>``, ``lang`` and a single
``<main>``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from common import ARTIFACTS, SITE, fail, ok, pages, scripts


def unstyled_status_classes(html: str) -> list[str]:
    """Status values the rail renders that the stylesheet gives no rule.

    `rail()` interpolates a stage's `status` straight into `class="st ..."`, so
    a value the stylesheet does not define renders with no colour and the chip
    silently says nothing. MEASURED 2026-09-09: `metrics` carries `pass` and
    only `shipped`, `built` and `blocked` had rules, so the one stage that
    passed was the one the rail did not mark.

    Args:
        html: The page source, stylesheet included.

    Returns:
        One line per status value with no matching rule; empty when all are
        defined.
    """
    defined = set(re.findall(r"\.st\.(\w+)\s*\{", html))
    stages = json.loads((ARTIFACTS / "stages.json").read_text(encoding="utf-8"))["stages"]
    used = {s["status"] for s in stages if s.get("status")}
    return [f"stages.json uses status {v!r}, but the stylesheet defines no .st.{v} "
            f"(defined: {', '.join(sorted(defined)) or 'none'})"
            for v in sorted(used - defined)]

_ROC_GRADIENT_RE = re.compile(
    r"\.roc\s*\{[^}]*?linear-gradient\(\s*to\s+(top|bottom)\s+(left|right)", re.S)
_OPPOSITE = {"top": "bottom", "bottom": "top", "left": "right", "right": "left"}


def _corner(point: dict[str, float]) -> str:
    """Which screen corner a curve endpoint is placed in.

    `.roc .p` maps `--x` onto `left` and `--y` onto `top`, both as percentages,
    so the corner is read off the two halves the point falls in.

    Args:
        point: One artifact point, carrying `x` and `y` as percentages.

    Returns:
        The corner, as the two words CSS names it by, e.g. `bottom left`.
    """
    return (f"{'top' if point['y'] < 50 else 'bottom'} "
            f"{'left' if point['x'] < 50 else 'right'}")


def roc_reference_line_corners(html: str) -> list[str]:
    """The band `.roc` draws must cross the corners the curves start and end at.

    A ROC's chance line runs between the two corners every curve shares, and
    `build_roc.py::curve` pins both: its first point is `x 0, y 100` and its last
    is `x 100, y 0`. So the reference band has to cross those same two corners.
    A CSS gradient's constant-colour band is PERPENDICULAR to its axis, which
    inverts the reading of the direction keyword and is the trap this catches.

    MEASURED 2026-09-16: the band was `to top right`, which lays it across the
    top-left and bottom-right corners -- the PERFECT corner joined to the WORST
    one. Both curves crossed it; 264 of curve A's 266 points sit above true
    chance but only 54 sit above the line that was drawn, and the weak curve read
    as below chance over the low-FPR half. The legend names that line chance in
    words, so nothing on the page contradicted it, and `no_fabrication` cannot
    see a stylesheet by design.

    Derived from the artifact rather than pinned as a string, so it also reddens
    if `build_roc.py` ever stops measuring y from the top.

    Args:
        html: The page source, stylesheet included.

    Returns:
        One line naming the mismatch, or empty when the band and the curves
        agree; also empty when the page draws no ROC.
    """
    path = ARTIFACTS / "roc.json"
    if ".roc{" not in html.replace(" ", "") or not path.exists():
        return []
    m = _ROC_GRADIENT_RE.search(html)
    if not m:
        return [".roc draws no `linear-gradient(to <vertical> <horizontal>`, so the line "
                "the ROC legend calls chance is either absent or has no stated direction"]
    vert, horiz = m.group(1), m.group(2)
    band = {f"{vert} {_OPPOSITE[horiz]}", f"{_OPPOSITE[vert]} {horiz}"}
    ends: set[str] = set()
    for c in json.loads(path.read_text(encoding="utf-8"))["curves"]:
        pts = c["points"]
        ends |= {_corner(pts[0]), _corner(pts[-1])}
    if band == ends:
        return []
    return [f"`to {vert} {horiz}` lays .roc's reference band across the "
            f"{' and '.join(sorted(band))} corners, but roc.json's curves begin and end "
            f"at the {' and '.join(sorted(ends))} corners -- so the line the legend calls "
            "chance joins the best corner to the worst one and every curve crosses it. A "
            "gradient's band is perpendicular to its axis: for a y-from-the-top ROC that "
            "is `to bottom right`"]


ENTITY_RE = re.compile(r"&[a-zA-Z][a-zA-Z0-9]*;")


def double_escaped_entities(html: str) -> list[str]:
    """`esc(...)` calls whose ARGUMENT already contains an HTML entity.

    `esc` maps `&` to `&amp;`, so an entity inside its argument reaches the
    reader as literal text: joining a list with `" &middot; "` and escaping the
    RESULT printed `&middot;` between every item. Found in the wild on the
    Specifier panel's tool list, where neither render harness could see it --
    that panel needs a real Specifier run, which no fixture produces. A
    source-level check needs no fixture and covers every panel at once.

    The argument is read with balanced parentheses rather than a line regex:
    `esc(a.join(" x "))` nests, and this page is full of lines that legitimately
    put an entity OUTSIDE an `esc` call, so a same-line match would be noise.

    Args:
        html: The page source.

    Returns:
        One line per offending call; empty when none.
    """
    out: list[str] = []
    for m in re.finditer(r"\besc\(", html):
        i, depth = m.end(), 1
        while i < len(html) and depth:
            if html[i] == "(":
                depth += 1
            elif html[i] == ")":
                depth -= 1
            i += 1
        arg = html[m.end():i - 1]
        hit = ENTITY_RE.search(arg)
        if hit:
            line = html.count("\n", 0, m.start()) + 1
            out.append(f"line {line}: esc() is given {hit.group(0)!r}, which the "
                       f"reader sees as literal text. Escape each item and then "
                       f"join, rather than joining and escaping the result.")
    return out


VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "param", "source", "track", "wbr"}


class _Balance(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, int]] = []
        self.errors: list[str] = []
        self.title = False
        self.lang = False
        self.mains = 0

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag == "html" and dict(attrs).get("lang"):
            self.lang = True
        if tag == "title":
            self.title = True
        if tag == "main":
            self.mains += 1
        if tag not in VOID:
            self.stack.append((tag, self.getpos()[0]))

    def handle_startendtag(self, tag, attrs):  # noqa: ANN001
        if tag not in VOID:
            self.errors.append(f"line {self.getpos()[0]}: self-closing <{tag}/> is not void")

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag in VOID:
            return
        if not self.stack or self.stack[-1][0] != tag:
            opened = self.stack[-1] if self.stack else ("nothing", 0)
            self.errors.append(f"line {self.getpos()[0]}: </{tag}> closes <{opened[0]}> "
                               f"opened at line {opened[1]}")
            while self.stack and self.stack[-1][0] != tag:
                self.stack.pop()
        if self.stack:
            self.stack.pop()


def main() -> None:
    problems: list[str] = []
    for page in pages():
        rel = page.relative_to(SITE)
        html = page.read_text(encoding="utf-8")
        b = _Balance()
        b.feed(html)
        b.close()
        problems.extend(f"{rel}: {e}" for e in b.errors)
        problems.extend(f"{rel}: <{t}> opened at line {ln} never closed" for t, ln in b.stack)
        if not b.title:
            problems.append(f"{rel}: no <title>")
        if not b.lang:
            problems.append(f"{rel}: <html> has no lang")
        if b.mains != 1:
            problems.append(f"{rel}: expected one <main>, found {b.mains}")
        problems.extend(f"{rel}: {e}" for e in double_escaped_entities(html))
        for i, body in enumerate(scripts(html)):
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
                f.write(body)
                path = f.name
            try:
                r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
            finally:
                os.unlink(path)
            if r.returncode:
                problems.append(f"{rel}: script #{i} fails node --check: "
                                f"{r.stderr.strip().splitlines()[-1] if r.stderr.strip() else r.returncode}")
    for page in pages():
        html = page.read_text(encoding="utf-8")
        rel = page.relative_to(SITE)
        problems.extend(f"{rel}: {e}" for e in unstyled_status_classes(html))
        problems.extend(f"{rel}: {e}" for e in roc_reference_line_corners(html))
    r = subprocess.run(["node", str(Path(__file__).with_name("render.js")), str(SITE)],
                       capture_output=True, text=True)
    if r.returncode:
        problems.extend((r.stderr.strip() or r.stdout.strip() or "render failed").splitlines())
    if problems:
        for s in problems:
            print("      " + s)
        fail(f"parse: {len(problems)} problem(s)")
    ok(f"parse: {len(pages())} page(s) balanced, every script passes node --check; {r.stdout.strip()}")


if __name__ == "__main__":
    main()
