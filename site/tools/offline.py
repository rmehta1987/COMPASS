"""Step 5 — the page makes zero external requests.

Fails on any ``src``, non-anchor ``href``, ``data``, ``poster`` or ``action``
that names a scheme or a protocol-relative host; on any URL inside a script
or stylesheet (``fetch``, ``@import``, ``url(http…)``, ``@font-face``); on
``<iframe>``, ``<link rel=preconnect|dns-prefetch|preload>`` to a host; and
on ``sendBeacon`` / ``XMLHttpRequest``. ``<a href="https://…">`` is navigation
the reader chooses, not a request the page makes, and is allowed.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

from common import SITE, STYLE_RE, fail, ok, pages, scripts

URL_RE = re.compile(r"(?:https?:)?//[\w.-]+\.[a-z]{2,}", re.I)
CODE_BAD = [
    (URL_RE, "URL in code"),
    (re.compile(r"@import\b"), "@import"),
    (re.compile(r"XMLHttpRequest|sendBeacon|new\s+WebSocket|EventSource\("), "network API"),
    (re.compile(r"""import\(\s*["']"""), "dynamic import"),
]


class _Ext(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.problems: list[str] = []

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        a = dict(attrs)
        line = self.getpos()[0]
        if tag == "iframe":
            self.problems.append(f"line {line}: <iframe>")
        if tag == "link" and str(a.get("rel", "")).lower() in ("preconnect", "dns-prefetch", "preload", "prefetch"):
            self.problems.append(f"line {line}: <link rel={a.get('rel')}>")
        for k in ("src", "href", "data", "poster", "action", "srcset"):
            v = a.get(k)
            if v is None:
                continue
            if tag == "a" and k == "href":
                continue
            if re.match(r"^\s*(?:[a-z][a-z0-9+.-]*:)?//", v, re.I) or re.match(r"^\s*[a-z][a-z0-9+.-]*:", v, re.I) and not v.startswith("data:"):
                self.problems.append(f"line {line}: <{tag} {k}={v!r}>")


def main() -> None:
    problems: list[str] = []
    for page in pages():
        rel = page.relative_to(SITE)
        html = page.read_text(encoding="utf-8")
        p = _Ext()
        p.feed(html)
        problems.extend(f"{rel}: {s}" for s in p.problems)
        code = scripts(html) + [m.group(1) for m in STYLE_RE.finditer(html)]
        for body in code:
            for rx, why in CODE_BAD:
                for m in rx.finditer(body):
                    problems.append(f"{rel}: {why}: {m.group(0)!r}")
    if problems:
        for s in problems:
            print("      " + s)
        fail(f"offline: {len(problems)} external reference(s)")
    ok(f"offline: {len(pages())} page(s) make no external request")


if __name__ == "__main__":
    main()
