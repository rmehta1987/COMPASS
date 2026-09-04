"""Step 3 — no dead internal link, anchor or fetch target.

``href``/``src`` values without a scheme must resolve to a file under
``site/``; ``#fragment`` links must name an existing ``id``; a bare ``#`` is
a dead link (use a button). Every ``fetch`` target must exist. Duplicate ids
fail because a fragment can only reach the first.
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from common import SITE, fail, loaded_artefacts, ok, pages


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.refs: list[tuple[str, str, int]] = []

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        a = dict(attrs)
        if a.get("id"):
            self.ids.append(a["id"])
        for k in ("href", "src", "data", "poster", "action"):
            if a.get(k) is not None:
                self.refs.append((tag, a[k], self.getpos()[0]))


def main() -> None:
    problems: list[str] = []
    checked = 0
    for page in pages():
        p = _Links()
        p.feed(page.read_text(encoding="utf-8"))
        rel = page.relative_to(SITE)
        dup = sorted({i for i in p.ids if p.ids.count(i) > 1})
        problems.extend(f"{rel}: duplicate id {d!r}" for d in dup)
        for tag, ref, line in p.refs:
            checked += 1
            if ref.startswith(("http://", "https://", "mailto:", "data:")):
                continue
            if ref.startswith("#"):
                if ref == "#" or ref[1:] not in p.ids:
                    problems.append(f"{rel}:{line} <{tag}> dead anchor {ref!r}")
                continue
            target = (page.parent / ref.split("#")[0].split("?")[0]).resolve()
            if not target.is_file():
                problems.append(f"{rel}:{line} <{tag}> {ref!r} does not resolve")
    for art in loaded_artefacts():
        checked += 1
        if not (SITE / art).is_file():
            problems.append(f"fetch target {art!r} does not exist")
    if problems:
        for s in problems:
            print("      " + s)
        fail(f"links: {len(problems)} problem(s)")
    ok(f"links: {checked} reference(s) resolve")


if __name__ == "__main__":
    main()
