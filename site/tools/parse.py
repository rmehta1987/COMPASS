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

import os
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from common import SITE, fail, ok, pages, scripts

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
