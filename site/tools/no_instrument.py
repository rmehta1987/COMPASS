"""Step 2 — no instrument wording, and no variable key, anywhere under site/.

The five-word-run rule is the pipeline's own
(``tests/test_query_rewrite.py::test_the_prompt_carries_no_instrument_wording``):
collapse whitespace, lower-case, and forbid any five consecutive words shared
with a dictionary entry's ``searchable_text``, ``question_text`` or
``stem_text``. Every file under ``site/`` is scanned twice, raw and as
rendered text, because markup breaks runs the reader still sees whole.

Tier A adds a second rule: no variable key (module, colon, question id) may appear. The
pseudonym map lives with the run artefacts on the private side, never here.

The dictionary is withheld from the public tree. Without it this check cannot
certify anything, so it exits 2 rather than passing vacuously. Point
``COMPASS_DICTIONARY`` at ``dictionary.json`` (the training machine keeps one
at the repo root of the operator's clone).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from common import REPO, SITE, fail, ok, visible_text

# Ported byte for byte from `serve/redact.py::KEY_RE`, which is the corrected
# pattern. The shape this replaced -- `\bm\d+:Q\d+(?:[._~]\w+)*` -- could not match a
# numeric roster prefix between the colon and the `Q`, so it saw 1,284 of the 2,804
# item keys and missed 1,520 (MEASURED 2026-09-09 against `key`; the two undetected
# shapes are `m<N>:<N>_Q<N>.<N>` and `m<N>:<N>_Q<N>.<N>#<N>_<N>`). Measuring
# `construct_key` instead hides the defect: both patterns match 100% of those, because
# the base form carries no roster prefix. IGNORECASE for the reason `redact.py` gives:
# a case-shifted key is reachable through free prose, not hypothetical.
KEY_RE = re.compile(
    r"\bm\d+:(?:\d+_)?Q\d+(?:\.\d+)?(?:#\d+(?:_\d+)*)?(?:_\d+)*(?:_TEXT)?(?:~\d+)?",
    re.IGNORECASE)
N = 5
SKIP_SUFFIXES = {".safetensors", ".png", ".pt", ".bin"}


def grams(text: str) -> set[tuple[str, ...]]:
    w = " ".join(text.lower().split()).split()
    return {tuple(w[i:i + N]) for i in range(len(w) - N + 1)}


def dictionary_path() -> Path | None:
    env = os.environ.get("COMPASS_DICTIONARY")
    cands = [Path(env)] if env else []
    cands += [REPO / "dictionary.json", REPO / "build" / "dictionary.json"]
    return next((p for p in cands if p.is_file()), None)


def corpus_grams(dic: Path) -> set[tuple[str, ...]]:
    out: set[tuple[str, ...]] = set()
    for e in json.loads(dic.read_text(encoding="utf-8"))["entries"]:
        for f in ("searchable_text", "question_text", "stem_text"):
            v = e.get(f)
            if isinstance(v, str):
                out |= grams(v)
    return out


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


def site_files() -> list[Path]:
    return sorted(p for p in SITE.rglob("*")
                  if p.is_file() and p.suffix not in SKIP_SUFFIXES and ".git" not in p.parts)


def main() -> None:
    dic = dictionary_path()
    if dic is None:
        print("FAIL  no_instrument: dictionary not found; set COMPASS_DICTIONARY. "
              "A scan that cannot see the instrument certifies nothing.")
        sys.exit(2)
    corpus = corpus_grams(dic)
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
    ok(f"no_instrument: {n} file(s) scanned against {len(corpus)} five-word runs "
       f"and {keys_checked} key(s), all covered by KEY_RE, from {dic.name}")


if __name__ == "__main__":
    main()
