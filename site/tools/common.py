"""Shared helpers for the site checks. Stdlib only; no network.

Conventions the checks rely on:

* The page is every ``*.html`` under ``site/``.
* Data reaches the page only through ``artefacts/index.json`` (which lists
  the other artefact files under ``files``) and literal ``fetch("...")``
  calls in the page's scripts. ``loaded_artefacts`` returns the union, so a
  file the page loads can never escape steps 1, 3 and 6.
* ``SITE_ROOT`` overrides the site directory; the planted-violation harness
  uses it to run a check against a doctored copy.
"""
from __future__ import annotations

import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SITE = Path(os.environ.get("SITE_ROOT", REPO / "site")).resolve()
ARTEFACTS = SITE / "artefacts"
INDEX = "artefacts/index.json"

# only a complete literal counts; fetch("artefacts/"+f) is covered by the index
FETCH_RE = re.compile(r"""fetch\(\s*(["'])([^"']+)\1\s*\)""")
SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S | re.I)
STYLE_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.S | re.I)


def pages() -> list[Path]:
    """Every HTML page under the site root, sorted."""
    return sorted(SITE.glob("*.html"))


def scripts(html: str) -> list[str]:
    """Inline script bodies in document order."""
    return [m.group(1) for m in SCRIPT_RE.finditer(html)]


def strip_style(html: str) -> str:
    """HTML with ``<style>`` blocks and inline ``style=`` attributes removed."""
    html = STYLE_RE.sub("", html)
    return re.sub(r"""\sstyle=(["']).*?\1""", "", html, flags=re.S)


def loaded_artefacts() -> list[str]:
    """Site-relative paths the page loads, index first, duplicates removed."""
    seen: list[str] = []

    def add(p: str) -> None:
        p = p.lstrip("./")
        if p not in seen:
            seen.append(p)

    for page in pages():
        for body in scripts(page.read_text(encoding="utf-8")):
            for m in FETCH_RE.finditer(body):
                add(m.group(2))
    idx = SITE / INDEX
    if idx.exists():
        add(INDEX)
        try:
            for f in json.loads(idx.read_text(encoding="utf-8")).get("files", []):
                add(f if f.startswith("artefacts/") else f"artefacts/{f}")
        except json.JSONDecodeError:
            pass  # step 1 reports the parse failure with the file name
    return seen


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):  # noqa: ANN001
        if not self._skip:
            self.parts.append(data)


def visible_text(html: str) -> str:
    """Rendered text of a page: tags dropped, entities decoded, code skipped."""
    p = _Text()
    p.feed(html)
    return " ".join(p.parts)


def fail(msg: str) -> None:
    """Print one red line and exit non-zero."""
    print(f"FAIL  {msg}")
    sys.exit(1)


def ok(msg: str) -> None:
    """Print one green line."""
    print(f"ok    {msg}")
