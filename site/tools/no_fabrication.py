"""Step 1 — every number on the page traces to an artefact.

Two halves, both hard failures:

1. The page carries no numeric literal outside CSS except the allowlist
   below. Each entry is a *context* regex, not a value, so ``i+1`` is allowed
   where it indexes the rail and nowhere else. Widening this list to let a
   figure through is the failure this check exists to prevent: a figure needs
   an artefact.
2. Every file in ``site/artefacts`` is listed by the index, is valid JSON, and
   carries a ``provenance`` object naming its ``source`` and a ``run_id``,
   ``commit`` or ``frozen`` date. A figure inside a *string* (``"cos 0.7316"``)
   is a retyped number, not data: any string value outside ``provenance``
   that carries a decimal, a thousands-grouped or a three-plus-digit integer
   fails, except request text and names (a model, a column label), which
   are words, not values.
"""
from __future__ import annotations

import json
import re

from common import ARTEFACTS, INDEX, SITE, fail, loaded_artefacts, ok, pages, strip_style

# (context regex, why it is not a figure). Keep this short and literal.
ALLOW: list[tuple[str, str]] = [
    (r"initial-scale=1\b", "viewport meta"),
    (r"\bi\+1\b", "1-based rail index"),
    (r"\.toFixed\(\d\)", "display precision, not a value"),
    (r"\|\|\s*1\b", "devicePixelRatio fallback"),
    (r"\bscale\(\s*dpr\s*,\s*dpr\s*\)|\*\s*dpr\b|/\s*dpr\b", "canvas scaling by dpr"),
    (r"width=\"100%\"|height=\"100%\"", "foreignObject fills the SVG"),
    (r"\b(?:indent|null,\s*)2\)", "JSON.stringify indent"),
    (r"setTimeout\([^)]*,\s*0\)", "yield to the event loop"),
]
NUM_RE = re.compile(r"(?<![\w#.\-/])\d[\d,]*(?:\.\d+)?")
FIGURE_RE = re.compile(r"\d+\.\d+|\d{1,3}(?:,\d{3})+|(?<![\w.-])\d{3,}(?![\w.-])")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?:T[\d:]+Z?)?")
# verbatim inputs and names: a request, a model name, a column label. Never a value.
REQUEST_KEYS = {"request", "query", "rendered_query", "construct", "instances", "text", "label", "model", "name", "columns", "arm_columns"}


def page_literals() -> list[str]:
    bad: list[str] = []
    for page in pages():
        body = strip_style(page.read_text(encoding="utf-8"))
        for m in NUM_RE.finditer(body):
            ctx = body[max(0, m.start() - 24): m.end() + 24]
            if any(re.search(rx, ctx) for rx, _ in ALLOW):
                continue
            line = body.count("\n", 0, m.start()) + 1
            bad.append(f"{page.relative_to(SITE)}:{line} literal {m.group(0)!r} in {ctx.strip()!r}")
    return bad


def walk_strings(node, path: tuple[str, ...], out: list[str]) -> None:  # noqa: ANN001
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "provenance":
                continue
            walk_strings(v, path + (k,), out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk_strings(v, path + (str(i),), out)
    elif isinstance(node, str):
        if path and path[-1] in REQUEST_KEYS or any(p in REQUEST_KEYS for p in path[-2:]):
            return
        s = DATE_RE.sub("", node)
        if FIGURE_RE.search(s):
            out.append(f"{'.'.join(path)} = {node!r}")


def artefact_provenance() -> list[str]:
    bad: list[str] = []
    on_disk = sorted(p.name for p in ARTEFACTS.glob("*.json")) if ARTEFACTS.exists() else []
    loaded = loaded_artefacts()
    listed = sorted(p.split("/", 1)[1] for p in loaded if p.startswith("artefacts/"))
    for name in on_disk:
        if name not in listed:
            bad.append(f"artefacts/{name} is on disk but nothing loads it")
    for rel in loaded:
        p = SITE / rel
        if not p.is_file():
            bad.append(f"{rel} is loaded by the page but is not a file")
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            bad.append(f"{rel} is not valid JSON: {e}")
            continue
        prov = data.get("provenance") if isinstance(data, dict) else None
        if not isinstance(prov, dict) or not str(prov.get("source", "")).strip():
            bad.append(f"{rel} has no provenance.source")
        elif not any(str(prov.get(k, "")).strip() for k in ("run_id", "commit", "frozen")):
            bad.append(f"{rel} provenance names no run_id, commit or frozen date")
        if rel != INDEX:
            strings: list[str] = []
            walk_strings(data, (), strings)
            bad.extend(f"{rel}: figure retyped inside a string: {s}" for s in strings)
    return bad


def main() -> None:
    problems = page_literals() + artefact_provenance()
    if problems:
        for p in problems:
            print("      " + p)
        fail(f"no_fabrication: {len(problems)} problem(s)")
    ok(f"no_fabrication: {len(pages())} page(s), {len(loaded_artefacts())} artefact(s) traced")


if __name__ == "__main__":
    main()
