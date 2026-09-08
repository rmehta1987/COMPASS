"""What the WORLD can see on a public branch — `AGENTS.md` §Publication Boundary.

A different threat model from `tests/test_contamination_surface.py`, which is why this
is a separate module. That file governs what the MODEL can see inside a sealed run and
works by enumerating markers (`ACCEPTANCE_MARKERS`); enumeration is sound there because
those strings are innocuous in isolation and only their PLACEMENT signals a leak.

That property inverts here. A list of forbidden instrument terms would itself be a list
of inventory terms, on a public branch, and a reader who diffed it against the instrument
could recover much of what the list exists to protect. Enumerating the secret to guard the
secret. So this module detects the SHAPE of key material instead of naming any term:

* `KEY_TOKEN` matches the instrument's key syntax, `m<module>:Q<number>` with the
  optional `.<n>`, `#<n>_<n>` and `~<suffix>` forms the tree actually uses.
* A module outside `REAL_MODULES` is an INVENTED key. `pipeline/retrieval_record.py`
  ::Hit.module is the owning statement that the instrument has modules "1", "2" or "3",
  so `m9:Q99.9` cannot name a row. This is the sanctioned way to illustrate a rule:
  invent the module and nothing real is published.
* Proximity between a real key token and a status word is the defect this exists to
  catch, because a term paired with a status or a resolved key is exactly what the
  boundary withholds.

**What this does NOT catch, stated so nobody reads green as clean.** A term paired with a
status in prose, with no key token anywhere near it, is invisible here — detecting that
would need a list of instrument terms, which is the shape ruled out above. The six
term→status pairings disclosed in `ITEMS_16_17_MODALITY.md` are of that kind and this
module does not see them. Green means no key-shaped material crossed, never "no row-level
material crossed".

Ceilings are grandfathered exposure that predates the boundary and is covered by
disclosure. They are NOT approval, and they may only FALL (`AGENTS.md` §Testing
Patterns). A file with no entry must be clean.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: The instrument's three modules. Owned by `pipeline/retrieval_record.py::Hit.module`
#: ("The instrument module, \"1\", \"2\" or \"3\""), restated here only as a pattern.
#: Any other module number is an invented key and is always allowed.
REAL_MODULES = ("1", "2", "3")

#: `m<module>:Q<number>`, plus the `.sub`, `#col_row` and `~variant` forms in the tree.
KEY_TOKEN = re.compile(
    r"\bm(?P<module>[0-9]+):Q[0-9]+(?:\.[0-9]+)?(?:#[0-9]+_[0-9]+)?(?:~[A-Za-z0-9_]+)?")

#: Words that turn a key token into a row of the answer key: an inventory status, or a
#: field naming what a term resolved to. Shape, not vocabulary — none of these is an
#: instrument term.
STATUS_WORD = re.compile(
    r"\b(absent|modality|analogue|present|resolved|expected_key|analogue_key"
    r"|nearest_key|construct_key)\b", re.IGNORECASE)

#: Characters either side of a key token that count as "paired with" in prose.
WINDOW = 40

#: Agent reports, which the boundary governs from the moment they are written.
#: A new report is added here and must be clean; it does not get a ceiling.
REPORTS = ("ITEMS_16_17_MODALITY.md",)

#: Real-module key tokens inside a REPORT. Grandfathered, may only fall.
#: ITEMS_16_17_MODALITY.md: two are `check.sh` step 8 output (a key->key worked pair with
#: no term attached) and two are the seeded-failure example, which pairs one fixture term
#: with the keys it moved between. Disclosed, not approved; `AGENTS.md` §Publication
#: Boundary forbids editing the committed report to make the exposure look smaller.
REPORT_KEY_CEILING: dict[str, int] = {"ITEMS_16_17_MODALITY.md": 4}

#: Key token within WINDOW of a status word, per tracked markdown file. Everything not
#: listed must be 0. The two retrieval-tree entries PREDATE this boundary and are real
#: term->key pairings; they are recorded, not endorsed.
PROXIMITY_CEILING: dict[str, int] = {
    "ITEMS_16_17_MODALITY.md": 4,
    "CHARACTERISATION.md": 1,
    "docs/arm-d-results.md": 1,
}


def tracked_markdown() -> list[str]:
    """Every tracked `*.md` path, repo-relative.

    Returns:
        Sorted paths; empty when git cannot be reached, which skips the scans.
    """
    try:
        out = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, check=True,
                             capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return sorted(p for p in out.split("\n") if p)


def real_key_tokens(text: str) -> list[str]:
    """Key tokens naming a module the instrument actually has.

    Args:
        text: The file's text.

    Returns:
        Matched tokens; invented modules are excluded.
    """
    return [m.group(0) for m in KEY_TOKEN.finditer(text)
            if m.group("module") in REAL_MODULES]


def proximity_hits(text: str) -> list[str]:
    """Real key tokens sitting within `WINDOW` characters of a status word.

    Args:
        text: The file's text.

    Returns:
        One excerpt per hit, for the failure message.
    """
    hits = []
    for m in KEY_TOKEN.finditer(text):
        if m.group("module") not in REAL_MODULES:
            continue
        seg = text[max(0, m.start() - WINDOW):m.end() + WINDOW]
        if STATUS_WORD.search(seg):
            hits.append(" ".join(seg.split()))
    return hits


# --------------------------------------------------------------- the two scans

def test_no_report_carries_more_key_material_than_its_ceiling():
    """An agent report names no instrument key. New reports have no ceiling at all."""
    for rel in REPORTS:
        p = ROOT / rel
        if not p.exists():
            continue
        n = len(real_key_tokens(p.read_text(encoding="utf-8")))
        ceil = REPORT_KEY_CEILING.get(rel, 0)
        assert n <= ceil, (
            f"{rel} carries {n} instrument key tokens, ceiling {ceil}. A report puts "
            f"aggregates on the public branch and row-level detail in its "
            f"*.withheld.md companion. Use an invented module (m9:Q99.9) for examples.")


@pytest.mark.parametrize("rel", tracked_markdown() or ["<no git>"])
def test_no_tracked_markdown_pairs_a_key_with_a_status(rel):
    """A key token beside a status word is a row of the answer key, in prose."""
    if rel == "<no git>":
        pytest.skip("git unavailable; the publication scan needs the tracked file list")
    p = ROOT / rel
    if not p.exists():
        return
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    hits = proximity_hits(text)
    ceil = PROXIMITY_CEILING.get(rel, 0)
    assert len(hits) <= ceil, (
        f"{rel}: {len(hits)} key-token/status-word pairings, ceiling {ceil}.\n"
        + "\n".join(f"  ... {h} ..." for h in hits[:5])
        + "\nAGENTS.md §Publication Boundary: a term paired with a status or a "
          "resolved key is withheld. Move it to the *.withheld.md companion.")


def test_every_ceiling_names_a_file_that_exists():
    """A stale ceiling silently widens the guard; deleting a file must lower it."""
    tracked = set(tracked_markdown())
    if not tracked:
        pytest.skip("git unavailable")
    for rel in {**REPORT_KEY_CEILING, **PROXIMITY_CEILING}:
        assert rel in tracked, f"{rel} has a ceiling but is not tracked; drop the entry"


# ------------------------------------------------------------ anti-vacuity probes

def test_the_pattern_matches_every_key_form_the_tree_uses():
    """A guard that matches nothing passes everywhere."""
    for form in ("m1:Q82", "m2:Q5.7", "m3:Q1.4_2", "m1:Q5.4~dup", "m2:Q26.12",
                 "m2:Q9.105", "m3:Q870_2"):
        assert real_key_tokens(f"see {form} here"), form


def test_an_invented_module_is_never_flagged():
    """The sanctioned escape hatch: invent the module and the example is safe."""
    assert real_key_tokens("m9:Q99.9") == []
    assert proximity_hits("`m9:Q99.9` <- `borborygmus frequency`, status `absent`") == []


def test_the_proximity_rule_fires_on_a_planted_pairing():
    """The defect this module exists to catch, constructed from invented parts."""
    assert proximity_hits("m2:Q5.7 status absent")
    assert proximity_hits("the analogue_key for that term is m3:Q287")
    assert proximity_hits("m1:Q82") == []          # a bare key is not a pairing


def test_the_window_is_a_window_and_not_the_whole_file():
    """Proximity must be local, or every long document trips on unrelated prose."""
    far = "m2:Q5.7" + ("x" * (WINDOW + 50)) + "absent"
    assert proximity_hits(far) == []
