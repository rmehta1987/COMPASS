"""Build the COMPASS selection-target set from the built dictionary.

Pure stdlib. No model, no network.

A selection target is one distinct (construct_key, subitem_text, matrix_col).
The roster dimension folds; the option dimension never does.

    python src/compass_build.py --dictionary dictionary.json --out out/targets.json
    python src/compass_build.py --dictionary dictionary.json --exclude-free-text \
        --out out/targets_ft.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

EXPECTED_HASH = "3dc8415eccfe"

# ---------------------------------------------------------------- identifiers

# {repeat}_Q{block}.{question}#{grid}_{part}_{subpart}, all optional but the stem.
QID_GRAMMAR = re.compile(
    r"""^
    (?:(?P<repeat>\d+)_)?          # roster repeat prefix
    Q(?P<block>\d+)                # block  (the stem; never optional)
    (?:\.(?P<question>\d+))?       # question within block
    (?:\#(?P<grid>\d+))?           # matrix / grid block
    (?:_(?P<part>\d+))?            # matrix column or sub-item index
    (?:_(?P<subpart>\d+))?         # second-level sub-item
    (?P<text>_TEXT)?               # free-text companion marker
    $""",
    re.VERBOSE,
)


class UnparseableIdentifier(ValueError):
    """Raised rather than falling back: a silent fallback mis-groups constructs."""


def parse_qid(qid: str) -> dict:
    m = QID_GRAMMAR.match(qid)
    if not m:
        raise UnparseableIdentifier(f"identifier does not match grammar: {qid!r}")
    g = m.groupdict()
    return {
        "repeat": int(g["repeat"]) if g["repeat"] else None,
        "block": int(g["block"]),
        "question": int(g["question"]) if g["question"] else None,
        "grid": int(g["grid"]) if g["grid"] else None,
        "part": int(g["part"]) if g["part"] else None,
        "subpart": int(g["subpart"]) if g["subpart"] else None,
        "is_text": bool(g["text"]),
        "base": f"Q{g['block']}" + (f".{g['question']}" if g["question"] else ""),
    }


# ------------------------------------------------------------- text hygiene

# Piped Qualtrics references leak into wording, mid-string as well as at the
# tail:  "...work days or weekdays? - Q2.4#1 - Time it takes to fall asleep".
# A tail-anchored pattern leaves 12 of them behind, so match anywhere.
PIPED_REF = re.compile(
    r"\s*-\s*\d*_?Q\d+(?:\.\d+)?(?:\#\d+)?(?:_\d+)*(?:_TEXT)?(?=\s|$|\s*-)"
)
# a bare roster index left stranded once its reference is gone: "... - 12"
TRAILING_INDEX = re.compile(r"\s*-\s*\d+\s*$")
MOJIBAKE = ("Ã", "â€", "Â", "�")


def clean_stem(text: str) -> str:
    """Strip identifier-shaped tokens wherever they appear, then normalise space."""
    prev = None
    s = text
    while prev != s:
        prev = s
        s = PIPED_REF.sub("", s).strip()
        s = TRAILING_INDEX.sub("", s).strip()
    return re.sub(r"\s+", " ", s).strip(" -")


def repair_mojibake(text: str) -> tuple[str, bool]:
    """latin-1 -> utf-8 round trip, accepted only if it removes every marker."""
    if not any(m in text for m in MOJIBAKE):
        return text, False
    try:
        fixed = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text, False
    if any(m in fixed for m in MOJIBAKE):
        return text, False
    return fixed, True


# ------------------------------------------------------------------- builder

def build(entries: list[dict], exclude_free_text: bool) -> tuple[list[dict], dict]:
    skipped = {"direct_identifier": 0, "free_text_or_companion": 0}
    seen: dict[tuple, dict] = {}
    targets: list[dict] = []
    parse_mismatches: list[str] = []

    for e in entries:
        # Parse every identifier, including ones we go on to skip: an
        # unparseable id anywhere means the grammar is wrong.
        p = parse_qid(e["qid"])
        # Cross-check the parse against the dictionary's own derived fields.
        if p["repeat"] != e["roster_row"]:
            parse_mismatches.append(f"{e['key']}: repeat {p['repeat']} vs roster_row {e['roster_row']}")
        expect_construct = f"m{e['module']}:{p['base']}"
        if expect_construct != e["construct_key"]:
            parse_mismatches.append(
                f"{e['key']}: construct {expect_construct} vs {e['construct_key']}")

        # Governance: direct identifiers may never be a candidate.
        if e["is_direct_identifier"]:
            skipped["direct_identifier"] += 1
            continue
        # Known bug, behind a flag, retained only to reproduce a published number.
        if exclude_free_text and (e["is_free_text"] or e["is_text_companion"]):
            skipped["free_text_or_companion"] += 1
            continue

        # A qid repeating within a module (m2:Q785, twice) shares one
        # construct_key while being two unrelated questions. Fold on the
        # occurrence-qualified construct, or the second question vanishes into
        # the first and stops being reachable at all.
        occ_construct = e["construct_key"]
        if e["occurrence_count"] > 1:
            occ_construct += f"~{e['occurrence']}"

        key = (occ_construct, e["subitem_text"], e["matrix_col"])
        if key in seen:
            t = seen[key]
            t["members"].append(e["key"])
            t["roster_rows"].append(e["roster_row"])
            continue

        raw_stem = e["stem_text"] or e["question_text"]
        stem, _ = repair_mojibake(raw_stem)
        option_raw = e["subitem_text"]
        option, _ = repair_mojibake(option_raw) if option_raw else (option_raw, False)
        wording, _ = repair_mojibake(e["question_text"])  # byte-verbatim source

        t = {
            "target_id": len(targets) + 1,
            "canonical_key": e["key"],
            "construct_key": occ_construct,
            "dict_construct_key": e["construct_key"],
            "module": e["module"],
            "stem": clean_stem(stem),
            "option": option,
            "matrix_col": e["matrix_col"],
            "roster_family_size": e["roster_family_size"],
            "wording": wording,
            "is_free_text": bool(e["is_free_text"]),
            "is_text_companion": bool(e["is_text_companion"]),
            "members": [e["key"]],
            "roster_rows": [e["roster_row"]],
        }
        seen[key] = t
        targets.append(t)

    if parse_mismatches:
        raise UnparseableIdentifier(
            f"{len(parse_mismatches)} identifier parses disagree with the "
            f"dictionary's derived fields; first 5: {parse_mismatches[:5]}")

    by_construct: dict[str, list[int]] = {}
    for t in targets:
        by_construct.setdefault(t["construct_key"], []).append(t["target_id"])
    for t in targets:
        t["siblings"] = [i for i in by_construct[t["construct_key"]]
                         if i != t["target_id"]]
        t["fold_size"] = len(t["members"])

    stats = {
        "n_targets": len(targets),
        "n_multi_option": sum(1 for t in targets if t["siblings"]),
        "n_folded_family": sum(1 for t in targets if t["fold_size"] > 1),
        "n_singleton": sum(1 for t in targets if t["fold_size"] == 1),
        "skipped": skipped,
        "largest_construct": max((len(v) for v in by_construct.values()), default=0),
        "n_constructs": len(by_construct),
    }
    return targets, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dictionary", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--exclude-free-text", action="store_true",
                    help="KNOWN BUG: skips is_free_text / is_text_companion rows. "
                         "Exists only to reproduce a published measurement.")
    a = ap.parse_args()

    d = json.loads(a.dictionary.read_text())
    version = d["version_hash"]
    if version != EXPECTED_HASH:
        print(f"dictionary hash {version}, expected {EXPECTED_HASH}", file=sys.stderr)
        return 2
    entries = d["entries"]
    if len(entries) != 2804:
        print(f"expected 2804 entries, got {len(entries)}", file=sys.stderr)
        return 2

    targets, stats = build(entries, a.exclude_free_text)

    out = {
        "schema": "compass_targets/1",
        "dictionary_version_hash": version,
        "exclude_free_text": a.exclude_free_text,
        **stats,
        "targets": targets,
    }
    a.out.write_text(json.dumps(out, indent=1))

    print(f"dictionary            {version}")
    print(f"exclude-free-text     {a.exclude_free_text}")
    print(f"targets               {stats['n_targets']}")
    print(f"  in multi-option     {stats['n_multi_option']}")
    print(f"  folded families     {stats['n_folded_family']}")
    print(f"  singletons          {stats['n_singleton']}")
    print(f"  skipped identifier  {stats['skipped']['direct_identifier']}")
    print(f"  skipped free text   {stats['skipped']['free_text_or_companion']}")
    print(f"largest construct     {stats['largest_construct']} options")
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
