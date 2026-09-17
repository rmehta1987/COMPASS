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


def roc_section_names_its_arm(html: str) -> list[str]:
    """The heading over the score table must name the arm `roc.json` came from.

    The panel carries two query arms. `roc.json` is one of them and the threshold
    row beneath it is the other, and for a while neither said so: the three
    numbers, both curves and the operating point were arm S -- which does not
    ship -- sitting directly above an arm-I threshold row labelled `shipped`.
    They disagreed visibly, the operating point at arm S's coverage and the table
    at arm I's, one positive row apart.

    The arm is identified by matching the artifact's own headline against the
    published arms rather than by trusting the label, so relabelling the section
    without rebuilding the artifact, or rebuilding it from the other arm without
    relabelling, both redden.

    Args:
        html: The page source.

    Returns:
        One line naming the mismatch, or empty when the heading names the arm the
        artifact matches; also empty when the page draws no ROC.
    """
    roc, mea = ARTIFACTS / "roc.json", ARTIFACTS / "measurements.json"
    if ".roc{" not in html.replace(" ", "") or not (roc.exists() and mea.exists()):
        return []
    i = html.find("+scoreTable(")
    if i < 0:
        return ["the page draws a ROC but never calls scoreTable(, so the arm the figures "
                "come from cannot be located"]
    heads = re.findall(r'<p class="sec">(.*?)</p>', html[max(0, i - 4000):i], re.S)
    if not heads:
        return ["no `<p class=\"sec\">` heading introduces the score table, so nothing on "
                "the page can name the arm its figures come from"]
    R = json.loads(roc.read_text(encoding="utf-8"))
    arms = json.loads(mea.read_text(encoding="utf-8"))["shipped"]["arms"]
    want = round(R["curves"][0]["auroc"], 4)
    match = [k for k, a in arms.items()
             if a.get("recall_at_1") == R["top1_accuracy"]
             and round(a.get("auroc_absent_vs_present", -1), 4) == want]
    if len(match) != 1:
        return [f"roc.json's headline figures match {len(match)} of the "
                f"{len(arms)} published arms ({', '.join(match) or 'none'}), so which arm "
                "the curves belong to cannot be established from the artifacts"]
    if f"arm {match[0]}" not in heads[-1]:
        return [f"roc.json's figures are arm {match[0]}, but the heading over the score "
                f"table does not say so: {heads[-1].strip()!r}"]
    return []


def roc_axes_are_named_and_scaled(html: str) -> list[str]:
    """`rocFig` must name both axes and take their bounds from the artifact.

    MEASURED 2026-09-16: neither axis was named or scaled anywhere on the page.
    Searching it for either rate's name found nothing, and "the axis is 0..1"
    existed only in a source comment. The consequence was not cosmetic: the
    reference band was drawn on the wrong diagonal, and with no axis names and
    no bounds a reader had nothing to check it against -- the legend asserted
    which line was chance and the page offered no way to disagree.

    Both halves are required. A name with no bounds leaves the scale unknown,
    and bounds retyped into the page rather than read from `roc.json::axes`
    would be an untraceable figure, which is the whole reason the builder emits
    percentages.

    Args:
        html: The page source.

    Returns:
        One line per missing piece; empty when both axes are named and scaled,
        and when the page draws no ROC.
    """
    if ".roc{" not in html.replace(" ", ""):
        return []
    m = re.search(r"function rocFig\(.*?\n\}", html, re.S)
    if not m:
        return ["the page draws a ROC but has no `rocFig` to label its axes"]
    body = m.group(0)
    out = []
    if 'class="yl"' not in body:
        out.append("rocFig names no vertical axis (no `.yl` label), so a reader cannot "
                   "tell what height means or which way better runs")
    if 'class="xl"' not in body:
        out.append("rocFig names no horizontal axis (no `.xl` row), so a reader cannot "
                   "tell what width means")
    if "ax.min" not in body or "ax.max" not in body:
        out.append("rocFig prints no axis bounds from `roc.json::axes`, so the plot has "
                   "no scale -- and the page may not hold a numeral of its own, so the "
                   "bounds have to come from the artifact")
    return out


def fixture_shape_agrees_across_artifacts(html: str) -> list[str]:
    """The two artifacts that state the fixture's shape must agree on it.

    The page now says the shape twice, from different sources. `howMeasured`
    takes it from `roc.json::fixture`, where `build_roc.py` derives it from the
    rows and asserts that every entry carries the same number of phrasings.
    `topicFig` takes it from `measurements.json::limitations.phrasing`, which
    `build_measurements.py` parses out of the manifest's own sentence.

    Two sources for one quantity is the arrangement this project distrusts, and
    the failure is a page that says the 224 requests are 56 entries in one
    paragraph and something else further down. Neither builder can see the
    other's output, so the agreement is checked here, where both are on disk.

    Args:
        html: The page source.

    Returns:
        One line when they disagree, else empty; also empty when the page does
        not state the shape, or an artifact is missing.
    """
    roc, mea = ARTIFACTS / "roc.json", ARTIFACTS / "measurements.json"
    if "topicFig(" not in html or not (roc.exists() and mea.exists()):
        return []
    f = json.loads(roc.read_text(encoding="utf-8")).get("fixture", {})
    ph = json.loads(mea.read_text(encoding="utf-8"))["limitations"]["phrasing"]
    if "n_gold_items" not in f or "phrasings_per_item" not in f:
        return []
    pairs = ((f["n_gold_items"], ph["gold_items"], "entries"),
             (f["phrasings_per_item"], ph["phrasings_per_item"], "phrasings per entry"))
    return [f"roc.json says {a} {what} and measurements.json says {b}, so the page "
            "states the fixture's shape twice from two artifacts that disagree"
            for a, b, what in pairs if a != b]


def score_spread_is_not_called_a_median(html: str) -> list[str]:
    """`whyGap` must not call `roc.json::scores`'s nearest-rank figures medians.

    MEASURED 2026-09-16: it did, for four figures, and two of them were not
    medians. `src/char_report.py::pct` is a nearest-rank percentile -- on an
    even-sized group the value just above the middle rather than the average of
    the two -- and the `absent` and `answerable` groups are even-sized, so the
    page printed 0.5961 and 0.8795 where the medians are 0.5908 and 0.8781. The
    other two matched only because 127 and 97 are odd.

    Scoped to `whyGap`, and to the word used as a LABEL -- next to one of the
    figures it names. "median" is correct elsewhere on the page, where a latency
    really is one, and the paragraph itself has to be free to say that these are
    NOT medians. Writing that sentence is what first reddened this check.

    A word check, so it catches the label coming back and not every vague way of
    describing the same figure; the arithmetic is held by `build_roc.py`, which
    re-derives all six figures from the rows.

    Args:
        html: The page source.

    Returns:
        One line when the label is back, else empty; also empty when the page has
        no `whyGap`.
    """
    m = re.search(r"function whyGap\(.*?\n\}", html, re.S)
    if not m:
        return []
    body = m.group(0)
    label = re.compile(r"median[^\n]{0,24}\$\{s\.|\$\{s\.[^}]*\}[^\n]{0,24}median")
    if not label.search(body):
        return []
    return ["whyGap calls its figures medians, and they are nearest-rank percentiles "
            "-- on an even-sized group the value just above the middle, not the average "
            "of the two, so two of the four are not the median they would claim to be. "
            "Say what the figure is instead: at least half the group scored at or below "
            "it, and it is one of the scores that occurred"]


def topic_bars_cover_the_fixture(html: str) -> list[str]:
    """Every test question must sit in some bar of the by-topic chart.

    MEASURED 2026-09-16: the chart drew the three topics
    `deploy/manifest.json::known_limitations[1]` names -- the two worst and the
    biggest -- because the builder regexed them out of that sentence and
    asserted it had found three. They covered 100 of the fixture's 224 rows and
    the caption told the reader "the rest are not grouped by topic", which was
    false: `out/char_task4_strata.json` already carried all eleven topics,
    summing to the whole fixture. Because the three shown were the extremes,
    every topic above the best one shown was suppressed, including one at 1.000.

    The completeness of the chart is asserted here rather than left to the
    sentence beneath it. `no_fabrication` cannot cover that sentence: the false
    clause carried no digit, so nothing traced it.

    Args:
        html: The page source.

    Returns:
        One line when the rows do not account for the fixture, else empty; also
        empty when the page draws no by-topic chart.
    """
    path = ARTIFACTS / "measurements.json"
    if "topicFig(" not in html or not path.exists():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    topics = doc["limitations"]["topics"]
    total = doc["fixture"]["n_positive_rows"]
    covered = sum(t["n"] for t in topics)
    if covered == total:
        return []
    return [f"the by-topic chart's {len(topics)} row(s) cover {covered} of the fixture's "
            f"{total} requests, so {total - covered} of them are drawn nowhere. A chart "
            "that omits rows has to say which and how many; the caption that used to "
            "stand here said they were not grouped by topic, and that was false"]


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
        problems.extend(f"{rel}: {e}" for e in roc_section_names_its_arm(html))
        problems.extend(f"{rel}: {e}" for e in roc_axes_are_named_and_scaled(html))
        problems.extend(f"{rel}: {e}" for e in fixture_shape_agrees_across_artifacts(html))
        problems.extend(f"{rel}: {e}" for e in score_spread_is_not_called_a_median(html))
        problems.extend(f"{rel}: {e}" for e in topic_bars_cover_the_fixture(html))
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
