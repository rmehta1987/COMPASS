"""Step 2 — no instrument wording, and no variable key, anywhere under site/.

The five-word-run rule is the pipeline's own
(``tests/test_query_rewrite.py::test_the_prompt_carries_no_instrument_wording``):
collapse whitespace, lower-case, and forbid any five consecutive words shared
with a dictionary entry's ``searchable_text``, ``question_text`` or
``stem_text``. Every file under ``site/`` is scanned twice, raw and as
rendered text, because markup breaks runs the reader still sees whole.

Tier A adds a second rule: no variable key (module, colon, question id) may appear. The
pseudonym map lives with the run artifacts on the private side, never here.

The dictionary is withheld from the public tree. Without it this check cannot
certify anything, so it exits 2 rather than passing vacuously. Point
``COMPASS_DICTIONARY`` at ``dictionary.json`` (the training machine keeps one
at the repo root of the operator's clone).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from common import REPO, SITE, fail, ok, visible_text

# The scan's three rules -- the key pattern, the five-word run and where the
# dictionary is found -- are `serve/redact.py`'s, imported rather than ported.
# The copies drifted once: the shape this file used to carry,
# `\bm\d+:Q\d+(?:[._~]\w+)*`, could not match a numeric roster prefix between
# the colon and the `Q`, so it saw 1,284 of the 2,804 item keys and missed 1,520
# (MEASURED 2026-09-09 against `key`). `redact.py` is stdlib-only, so importing it
# costs this standalone script nothing. `REPO` is the checkout this file lives in,
# never the `SITE_ROOT` copy, which is what `plant.py` relies on.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from serve.redact import KEY_RE, _load_index, dictionary_path
from serve.redact import _grams as grams

SKIP_SUFFIXES = {".safetensors", ".png", ".pt", ".bin"}
# Generated caches are not site content, and counting them made the scanned
# total a property of whatever was last imported rather than of the tree:
# MEASURED 2026-09-16, it read 29, 30, 31 and 32 within one session with the
# site unchanged. The scan was never weaker for it -- it covered MORE than it
# had to -- but a printed denominator that moves on its own is the defect this
# project audits pages for. `plant.py` already ignores the same directory.
SKIP_DIRS = {".git", "__pycache__"}


def key_re_coverage(dic: Path) -> tuple[list[str], int]:
    """Report the key shapes ``KEY_RE`` cannot fully match.

    The gate greps for keys with one regex, so the regex IS the guarantee. A
    pattern that silently stops covering part of the key space downgrades this
    step to a partial scan that still prints ``ok``. Checking it against the
    dictionary already in hand costs nothing and cannot go vacuous, because the
    same file supplies both the corpus and the assertion. This exists because the
    shipped pattern covered 1,284 of 2,804 item keys while reading as complete
    (MEASURED 2026-09-09).

    Digits are masked to ``N`` in the output: a gate that forbids keys under
    ``site/`` must not print one into a build log to say so.

    Args:
        dic: Path to the built dictionary, already located by `dictionary_path`.

    Returns:
        A pair: one problem line per uncovered shape, and the number of keys
        checked. The count is printed on green so the step cannot claim to have
        verified coverage against a dictionary it never read.
    """
    seen: dict[str, int] = {}
    total = 0
    for e in json.loads(dic.read_text(encoding="utf-8"))["entries"]:
        for f in ("key", "construct_key"):
            v = e.get(f)
            if not isinstance(v, str):
                continue
            total += 1
            if KEY_RE.fullmatch(v) is None:
                shape = re.sub(r"\d+", "N", v)
                seen[shape] = seen.get(shape, 0) + 1
    return ([f"KEY_RE does not cover {c} of {total} key(s) of shape {s!r}"
             for s, c in sorted(seen.items())], total)


def site_files(root: Path | None = None) -> list[Path]:
    """Every file under the site root that the scan can read.

    Args:
        root: Directory to walk. Defaults to the site root, which is what
            `main` uses; a test passes its own tree so the exclusions are
            checkable without reaching for the real one.

    Returns:
        The files, sorted, with generated caches and binary formats dropped.
    """
    base = SITE if root is None else root
    return sorted(p for p in base.rglob("*")
                  if p.is_file() and p.suffix not in SKIP_SUFFIXES
                  and not SKIP_DIRS & set(p.parts))


def main() -> None:
    dic = dictionary_path()
    if dic is None:
        print("FAIL  no_instrument: dictionary not found; set COMPASS_DICTIONARY. "
              "A scan that cannot see the instrument certifies nothing.")
        sys.exit(2)
    corpus = _load_index(dic).corpus
    key_problems, keys_checked = key_re_coverage(dic)
    problems: list[str] = list(key_problems)
    n = 0
    for p in site_files():
        n += 1
        raw = p.read_text(encoding="utf-8", errors="replace")
        texts = [raw]
        if p.suffix in (".html", ".htm"):
            texts.append(visible_text(raw))
        rel = p.relative_to(SITE)
        for k in sorted(set(KEY_RE.findall(raw))):
            problems.append(f"{rel}: variable key {k!r} (tier A forbids keys)")
        shared: set[tuple[str, ...]] = set()
        for t in texts:
            shared |= grams(t) & corpus
        for g in sorted(shared):
            problems.append(f"{rel}: five-word run shared with the instrument: {' '.join(g)!r}")
    if problems:
        for s in problems:
            print("      " + s)
        fail(f"no_instrument: {len(problems)} problem(s) across {n} file(s)")
    ok(f"no_instrument: {n} file(s) under {SITE.name}/ scanned, excluding "
       f"{'/'.join(sorted(SKIP_DIRS))} and {len(SKIP_SUFFIXES)} binary suffix(es), "
       f"against {len(corpus)} five-word runs and {keys_checked} key(s), all covered "
       f"by KEY_RE, from {dic.name}")


if __name__ == "__main__":
    main()
