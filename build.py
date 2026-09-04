"""build.py — regenerate build/ from raw/ + this file's rules.

    python build.py

Reads the three COMPASS module codebook CSVs (2 columns, no header; the survey
instrument, withheld from the public repository -- README.md) and emits a
deterministic, version-hashed dictionary plus the collision, grid and origin tables.

Everything in build/ is disposable: delete it and re-run. Nothing here imports a
model or touches the network. codebook.csv in the project root is NOT project data
and is never read.

Facts asserted at the bottom of this file are checked on every run. A failing
assertion means either the codebooks changed or a rule here is wrong — both are
things you want to hear about loudly.
"""

from __future__ import annotations

import csv
import hashlib
import inspect
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
BUILD = ROOT / "build"

SOURCES = {
    "1": "module_1_codebook_full.csv",
    "2": "module_2_codebook_full.csv",
    "3": "module_3_codebook_full.csv",
}

MODULE_TITLES = {
    "1": "Module 1 — contact information, household roster, demographics",
    "2": "Module 2 — health conditions, insurance, utilisation, residence and commute",
    "3": "Module 3 — physical activity, tobacco, alcohol, sleep, neighbourhood perceptions",
}

# The nine identifier shapes present in the instrument. Ordered most-specific first:
# the first pattern that matches wins, so QN.N#N_N_N must precede QN.N#N_N.
SHAPES: list[tuple[str, str, str]] = [
    ("N_QN.N#N_N",  r"^(?P<roster>\d+)_Q(?P<q>\d+\.\d+)#(?P<blk>\d+)_(?P<col>\d+)$",
     "roster row x matrix block x column"),
    ("N_QN.N",      r"^(?P<roster>\d+)_Q(?P<q>\d+\.\d+)$",
     "roster row prefix"),
    ("QN.N#N_N_N",  r"^Q(?P<q>\d+\.\d+)#(?P<blk>\d+)_(?P<col>\d+)_(?P<sub>\d+)$",
     "matrix, three indices"),
    ("QN.N#N_N",    r"^Q(?P<q>\d+\.\d+)#(?P<blk>\d+)_(?P<col>\d+)$",
     "matrix block x column"),
    ("QN.N_N_TEXT", r"^Q(?P<q>\d+\.\d+)_(?P<sub>\d+)_TEXT$",
     "free-text 'other, specify' companion"),
    ("QN.N_N",      r"^Q(?P<q>\d+\.\d+)_(?P<sub>\d+)$",
     "grid sub-item"),
    ("QN.N",        r"^Q(?P<q>\d+\.\d+)$",
     "plain item"),
    ("QN_N",        r"^Q(?P<q>\d+)_(?P<sub>\d+)$",
     "grid sub-item, bare stem"),
    ("QN",          r"^Q(?P<q>\d+)$",
     "bare item"),
]

MOJIBAKE_MARKERS = ("â€", "Ã‚", "Ã©", "Ã¨", "Ã¡", "â€™", "â€œ")

# Free-text detection. DERIVED: deterministic, regenerates with the dictionary
# hash. Deliberately conservative — an imperative instruction to the respondent,
# or the _TEXT companion shape. A bare /describe/ would also catch closed items
# like "Which of the following best describes your Hispanic origin", which are
# multiple choice, and over-pruning silently deletes candidates. Any prune
# criterion defaults to DO NOT PRUNE where it is unsure.
RE_FREE_TEXT = re.compile(
    r"please\s+(?:take a moment to\s+|briefly\s+)?(?:describe|list|explain|specify)",
    re.I)

# The grid-collapse rule. Written down because the distinct-construct count follows
# from it and is meaningless without it.
RE_ROSTER_PREFIX = re.compile(r"^\d+_")
RE_MATRIX_SUFFIX = re.compile(r"#\d+(?:_\d+)*$")
RE_SUBITEM_SUFFIX = re.compile(r"_\d+(?:_TEXT)?$")

# Identifier tags. TAGS, NEVER PRUNES — build.py deletes no row, and the same
# default-to-DO-NOT-PRUNE posture as RE_FREE_TEXT applies: a phrase that is not
# clearly an identifier is left untagged rather than guessed at.
#
# WHY THE SCHEMA NEEDED THEM. Nothing in Entry distinguished a participant's
# street address from a cancer variable, so any retrieval path over this
# dictionary returns "What is your first name and last name? - First Name"
# (`m1:Q2.2_1`) as a selectable candidate on equal footing with `m2:Q5.8`.
#
# TWO TIERS, because they carry different obligations. A direct identifier names
# the participant on its own. A quasi-identifier does not, but narrows a
# population enough that a few of them together can — which is why birth year
# and ZIP are here and sex is not: the tier is about re-identification leverage,
# not about sensitivity.
RE_DIRECT_IDENTIFIER = re.compile(
    r"first name|last name|middle name|maiden name|full name"
    r"|street address|mailing address|home address|apartment number"
    r"|phone number|telephone|cell number|e-?mail"
    r"|social security|medical record number"
    r"|date of birth|month.{0,12}born|day.{0,12}born",
    re.I)

# Deliberately NOT matching a bare /age/: "How old were you when you first
# smoked a cigarette" is an age-at-event exposure, not a quasi-identifier, and
# tagging it would put a tier on most of module 3.
RE_QUASI_IDENTIFIER = re.compile(
    r"\bzip code\b|\bpostal code\b|what (?:city|county|state)"
    r"|city (?:and|or) state|county (?:of|in) which"
    r"|year (?:you )?(?:were )?born|birth year"
    r"|what is your (?:current )?age|age in years",
    re.I)

#: A human-readable label for the rule generation, printed beside the hash. It is
#: NO LONGER what provenance rests on — `_rule_fingerprint` is — so forgetting to
#: bump it can no longer leave two different rule sets sharing one `version_hash`.
BUILD_RULES_VERSION = "3"


# --------------------------------------------------------------------------- #
# mojibake repair
# --------------------------------------------------------------------------- #

def _to_original_bytes(s: str) -> bytes:
    """Re-encode a string that was UTF-8 decoded as cp1252 back to its bytes.

    cp1252 leaves five byte positions undefined (0x81 0x8D 0x8F 0x90 0x9D). Text
    carrying those bytes round-trips through the C1 control block instead, and a
    plain .encode('cp1252') raises on them — which is why the naive repair
    silently no-ops on the five rows containing a mojibaked right double quote.
    Fall back to latin-1 per character, which maps U+0080..U+009F to 0x80..0x9F.
    """
    out = bytearray()
    for ch in s:
        try:
            out += ch.encode("cp1252")
        except UnicodeEncodeError:
            out += ch.encode("latin-1")
    return bytes(out)


def repair_mojibake(s: str) -> str:
    """Repair UTF-8-decoded-as-cp1252 damage. Guarded and non-destructive."""
    if not any(m in s for m in MOJIBAKE_MARKERS):
        return s
    try:
        fixed = _to_original_bytes(s).decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s
    # Only accept a repair that actually removes damage.
    return fixed if not any(m in fixed for m in MOJIBAKE_MARKERS) else s


# --------------------------------------------------------------------------- #
# identifier parsing
# --------------------------------------------------------------------------- #

@dataclass
class Entry:
    key: str                 # dictionary key, e.g. "m3:Q16.1_1"
    module: str
    qid: str                 # verbatim id as it appears in the codebook
    occurrence: int          # 1-based; >1 only where a qid repeats inside a module
    occurrence_count: int
    shape: str
    shape_meaning: str
    question_text: str       # mojibake-repaired, verbatim otherwise
    text_repaired: bool
    stem_text: str | None    # for grid sub-items, the shared stem
    subitem_text: str | None  # the part after the final " - "
    searchable_text: str
    base_id: str             # collapsed construct id within the module
    construct_key: str       # "m{module}:{base_id}"
    group_key: str | None    # "group:m{module}:{stem}" when this row is a grid sub-item
    roster_row: int | None
    matrix_block: int | None
    matrix_col: int | None
    subitem_index: int | None
    is_text_companion: bool
    is_roster_repeat: bool
    is_grid_subitem: bool
    is_free_text: bool
    # Identifier tiers. TAGS, not prunes: no row is deleted for carrying one, and
    # a consumer that must withhold them does so at its own boundary.
    is_direct_identifier: bool
    is_quasi_identifier: bool
    origin: str
    study_team_confirmed: bool
    # How many roster members share this question. Filled by a second pass in
    # `build`, because the count is a property of the GROUP and no single row
    # can see it. Null where the row is not a roster repeat — a question asked
    # once has no family size, and 1 would read as "a family of one".
    roster_family_size: int | None = None
    # Facts the two-column codebooks structurally cannot carry. Null by construction,
    # not because nobody checked. tests/ asserts these stay null for all 2,804 rows.
    value_labels: None = None
    response_options: None = None
    value_type: None = None
    missing_codes: None = None
    measurement_level: None = None
    branch_dependency: None = None


def parse_shape(qid: str) -> tuple[str, str, dict]:
    for name, pattern, meaning in SHAPES:
        m = re.match(pattern, qid)
        if m:
            return name, meaning, m.groupdict()
    raise ValueError(f"identifier matches none of the nine known shapes: {qid!r}")


def collapse_to_base(qid: str) -> str:
    """Collapse a codebook id to its distinct-construct id, per the rule above."""
    s = RE_ROSTER_PREFIX.sub("", qid)
    s = RE_MATRIX_SUFFIX.sub("", s)
    s = RE_SUBITEM_SUFFIX.sub("", s)
    return s


def split_stem(text: str) -> tuple[str | None, str | None]:
    """Split 'stem - subitem' on the final ' - '. Returns (None, None) if absent.

    Grid sub-item text is only interpretable with its stem, and two thirds of rows
    are fragments without it. We keep both halves so a display can show the stem
    beside the sub-item rather than a near-duplicate.
    """
    idx = text.rfind(" - ")
    if idx == -1:
        return None, None
    return text[:idx].strip(), text[idx + 3:].strip()


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #

def read_module(module: str, path: Path) -> list[tuple[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    for i, r in enumerate(rows):
        if len(r) != 2:
            raise ValueError(f"{path.name} record {i}: expected 2 columns, got {len(r)}")
    return [(r[0].strip(), r[1]) for r in rows]


#: The rules whose text is hashed as a PATTERN, because their semantic content is
#: the pattern and nothing else. A comment or whitespace edit beside one of these
#: does not move the hash, which is what we want.
_HASHED_PATTERNS = (
    "RE_FREE_TEXT", "RE_ROSTER_PREFIX", "RE_MATRIX_SUFFIX", "RE_SUBITEM_SUFFIX",
    "RE_DIRECT_IDENTIFIER", "RE_QUASI_IDENTIFIER",
)

#: The rules whose text is hashed as SOURCE, because they are function bodies
#: with no pattern to extract. THE COST IS REAL AND IS THE POINT: editing a
#: docstring or a comment inside one of these moves `version_hash` even though
#: behaviour did not change. That is the price of catching a logic edit that no
#: pattern can see, and anyone editing them should expect the move rather than
#: discover it. `_to_original_bytes` is here because `repair_mojibake`'s output
#: depends on it, so hashing the caller alone would miss a change to the callee.
_HASHED_SOURCES = ("collapse_to_base", "parse_shape", "split_stem",
                   "repair_mojibake", "_to_original_bytes")

#: Every other module-level function here, each with the reason it is NOT a
#: hashed rule. `tests/test_dictionary.py` asserts this set plus
#: `_HASHED_SOURCES` is exactly the module-level functions of this file, so
#: adding a function forces a deliberate choice instead of silently landing
#: outside the fingerprint.
#:
#: TWO OF THESE ARE DECLARED GAPS, not clean exclusions. `build` and
#: `read_module` DO decide rows, and they are excluded because hashing them
#: would move `version_hash` on every refactor of a ~130-line function — the
#: same noise problem already accepted for docstrings, at much higher frequency.
#: Declaring the gap is the honest move; closing it is not this file's job, and
#: the reasons below are the whole record of it.
_NOT_HASHED: dict[str, str] = {
    "build": "DECLARED GAP — the Entry-assembly loop decides field assignment, "
             "including the ~{occ} key separator, the _TEXT clauses, the group: "
             "namespace and the construct_key format. Not hashed because the "
             "hash would move on every refactor of a 130-line function.",
    "read_module": "DECLARED GAP — sets every row's question_text from the raw "
                   "CSV. Not hashed for the same reason as build; the raw files "
                   "themselves are hashed, which covers their content but not "
                   "the reading of it.",
    "_rule_fingerprint": "computes the fingerprint; hashing the hasher is "
                         "circular and says nothing about any row.",
    "_version_hash": "assembles the payload; same reason as _rule_fingerprint.",
    "_write_csv": "writes a table to disk and decides nothing about a row.",
    "_fill_roster_family_size": "counts members of a group after every row is "
                                "built; derives no row's identity or text.",
    "collision_rows": "reports on entries after they are built.",
    "grid_summary_rows": "reports on entries after they are built.",
    "origin_table_rows": "reports on entries after they are built.",
}


def _version_hash(file_hashes: dict[str, str], n_entries: int) -> str:
    """The build's identity: its inputs, its rules and its size.

    Extracted from `build()` so a test can ask what a rule edit does to the hash
    without running a build — which would write `build/` and move the artefact
    it is asking about.

    Args:
        file_hashes: sha256 of each raw source file, keyed by filename.
        n_entries: How many entries the build produced.

    Returns:
        The first 12 hex characters of the payload's sha256.
    """
    payload = json.dumps(
        {"files": file_hashes, "rules": BUILD_RULES_VERSION,
         "rule_fingerprint": _rule_fingerprint(), "n": n_entries},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _rule_fingerprint() -> dict:
    """Everything in this file that decides what a row becomes, as hashed text.

    WHY THIS EXISTS. The payload was `{files, BUILD_RULES_VERSION, n}`. None of
    the regexes, the shape table or any parsing function was in it, so editing
    `RE_FREE_TEXT` changed `is_free_text` on individual rows and the `free_text`
    count while `version_hash` stayed put — unless a human remembered to bump a
    string. This file's whole design removes human-discipline dependencies, and
    that was the last one in it.

    Two representations, chosen per rule; see `_HASHED_PATTERNS` and
    `_HASHED_SOURCES` for which and why.

    Returns:
        A JSON-serialisable mapping, stable under dict ordering because the
        caller dumps it with `sort_keys=True`.
    """
    g = globals()
    return {
        "patterns": {n: g[n].pattern for n in _HASHED_PATTERNS},
        "shapes": [list(row) for row in SHAPES],
        "mojibake_markers": list(MOJIBAKE_MARKERS),
        "sources": {n: inspect.getsource(g[n]) for n in _HASHED_SOURCES},
    }


def _fill_roster_family_size(entries: list[Entry]) -> None:
    """Fill `roster_family_size` in place, once every entry exists.

    DISTINCT `roster_row` values over `(module, base_id)`, not the maximum.
    The two agree on all 74 roster families in build c272da5de196 — checked, not
    assumed, by `tests/test_dictionary.py` — but they answer different questions:
    a roster numbered 1, 2, 5 has three members and a maximum of five, and the
    field is a count of members.

    A SECOND PASS, because the count is a property of the group and the loop
    that builds an entry sees one row. Assigning after construction is why the
    field carries a default.

    WHY IT LIVES HERE. `benchmark/resolver_eval.py` derived it by grouping, and
    `agent/prompt_contract.py` names it in prompt text while never being able to
    import the module that computed it. One artefact field, one definition.

    Args:
        entries: Every built entry, mutated in place.
    """
    members: dict[tuple[str, str], set[int]] = defaultdict(set)
    for e in entries:
        if e.roster_row is not None:
            members[(e.module, e.base_id)].add(e.roster_row)
    for e in entries:
        if e.is_roster_repeat:
            e.roster_family_size = len(members[(e.module, e.base_id)])


def collision_rows(entries: list[Entry]) -> list[dict]:
    """One row per qid that more than one entry uses.

    Args:
        entries: Every built entry.

    Returns:
        The collision table, ordered by qid.
    """
    by_qid: dict[str, list[Entry]] = defaultdict(list)
    for e in entries:
        by_qid[e.qid].append(e)
    rows = []
    for qid, es in sorted(by_qid.items()):
        if len(es) > 1:
            rows.append({
                "qid": qid,
                "n": len(es),
                "scope": ("within_module" if len({e.module for e in es}) == 1
                          else "cross_module"),
                "keys": " | ".join(e.key for e in es),
                "texts": " || ".join(
                    e.question_text[:70].replace("\n", " ") for e in es),
            })
    return rows


def grid_summary_rows(entries: list[Entry]) -> list[dict]:
    """One row per module counting its grid sub-items and their stems.

    Args:
        entries: Every built entry.

    Returns:
        The grid table, one row per source module.
    """
    rows = []
    standalone = {(e.module, e.qid) for e in entries}
    for module in SOURCES:
        subs = [e for e in entries if e.module == module and e.is_grid_subitem]
        stems = {RE_SUBITEM_SUFFIX.sub("", RE_ROSTER_PREFIX.sub("", e.qid))
                 for e in subs}
        rows.append({
            "module": module,
            "subitems": len(subs),
            "stems": len(stems),
            "stems_without_own_row": len(
                {s for s in stems if (module, s) not in standalone}),
            "subitems_with_stem_text_split": sum(1 for e in subs if e.stem_text),
        })
    return rows


def origin_table_rows(entries: list[Entry]) -> list[dict]:
    """One row per entry recording where it came from.

    Coverage here is true by construction and therefore cannot fail. The metric
    that CAN go red is study-team-confirmed rows, which is currently zero.

    Args:
        entries: Every built entry.

    Returns:
        The origin table, in entry order.
    """
    return [{
        "key": e.key, "module": e.module, "origin": e.origin,
        "study_team_confirmed": e.study_team_confirmed,
    } for e in entries]


def build() -> dict:
    if not RAW.exists():
        raise SystemExit(f"missing {RAW}/ — copy the three codebook CSVs there and re-run")

    raw_by_module: dict[str, list[tuple[str, str]]] = {}
    file_hashes: dict[str, str] = {}
    for module, filename in SOURCES.items():
        path = RAW / filename
        if not path.exists():
            raise SystemExit(f"missing {path} — build cannot proceed. This is not a warning.")
        file_hashes[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
        raw_by_module[module] = read_module(module, path)

    # occurrence ordinals, scoped to the module
    counts: dict[tuple[str, str], int] = Counter(
        (m, qid) for m, rows in raw_by_module.items() for qid, _ in rows
    )
    seen: dict[tuple[str, str], int] = defaultdict(int)

    entries: list[Entry] = []
    for module, rows in raw_by_module.items():
        for qid, raw_text in rows:
            shape, meaning, parts = parse_shape(qid)
            text = repair_mojibake(raw_text)

            seen[(module, qid)] += 1
            occ = seen[(module, qid)]
            occ_count = counts[(module, qid)]
            # The suffix is present only where it is needed to disambiguate, so
            # 2,802 of 2,804 keys stay clean. '~' appears in no identifier shape.
            key = f"m{module}:{qid}" + (f"~{occ}" if occ_count > 1 else "")

            base_id = collapse_to_base(qid)
            is_grid_subitem = bool(RE_SUBITEM_SUFFIX.search(qid))
            stem_text, subitem_text = split_stem(text) if is_grid_subitem else (None, None)

            group_key = None
            if is_grid_subitem:
                stem_id = RE_SUBITEM_SUFFIX.sub("", RE_ROSTER_PREFIX.sub("", qid))
                group_key = f"group:m{module}:{stem_id}"

            entries.append(Entry(
                key=key,
                module=module,
                qid=qid,
                occurrence=occ,
                occurrence_count=occ_count,
                shape=shape,
                shape_meaning=meaning,
                question_text=text,
                text_repaired=(text != raw_text),
                stem_text=stem_text,
                subitem_text=subitem_text,
                searchable_text=text,
                base_id=base_id,
                construct_key=f"m{module}:{base_id}",
                group_key=group_key,
                roster_row=int(parts["roster"]) if parts.get("roster") else None,
                matrix_block=int(parts["blk"]) if parts.get("blk") else None,
                matrix_col=int(parts["col"]) if parts.get("col") else None,
                subitem_index=int(parts["sub"]) if parts.get("sub") else None,
                is_text_companion=qid.endswith("_TEXT"),
                is_roster_repeat=bool(RE_ROSTER_PREFIX.match(qid)),
                is_grid_subitem=is_grid_subitem,
                is_free_text=bool(RE_FREE_TEXT.search(text)) or qid.endswith("_TEXT"),
                is_direct_identifier=bool(RE_DIRECT_IDENTIFIER.search(text)),
                is_quasi_identifier=bool(RE_QUASI_IDENTIFIER.search(text)),
                origin="questionnaire",
                study_team_confirmed=False,
            ))

    _fill_roster_family_size(entries)

    collisions = collision_rows(entries)
    grid_rows = grid_summary_rows(entries)
    origin_rows = origin_table_rows(entries)

    # ----- version hash ------------------------------------------------------ #
    version_hash = _version_hash(file_hashes, len(entries))

    BUILD.mkdir(exist_ok=True)
    dictionary = {
        "version_hash": version_hash,
        "rules_version": BUILD_RULES_VERSION,
        "source_files": file_hashes,
        "module_titles": MODULE_TITLES,
        "collapse_rule": (
            "strip ^\\d+_ roster prefix, then #\\d+(_\\d+)* matrix suffix, "
            "then _\\d+(_TEXT)? sub-item suffix"
        ),
        "key_rule": (
            "m{module}:{qid}, plus ~{occurrence} only where a qid repeats within its "
            "module. A grid stem is a group id in the 'group:' namespace and may "
            "never be named by a protocol."
        ),
        "counts": {
            "total": len(entries),
            "by_module": {m: len(rows) for m, rows in raw_by_module.items()},
            "distinct_constructs": len({e.construct_key for e in entries}),
            "distinct_constructs_by_module": {
                m: len({e.base_id for e in entries if e.module == m}) for m in SOURCES
            },
            "text_repaired": sum(1 for e in entries if e.text_repaired),
            "roster_repeats": sum(1 for e in entries if e.is_roster_repeat),
            "grid_subitems": sum(1 for e in entries if e.is_grid_subitem),
            "text_companions": sum(1 for e in entries if e.is_text_companion),
            "free_text": sum(1 for e in entries if e.is_free_text),
            "direct_identifiers": sum(1 for e in entries
                                      if e.is_direct_identifier),
            "quasi_identifiers": sum(1 for e in entries
                                     if e.is_quasi_identifier),
            "roster_families": len({(e.module, e.base_id) for e in entries
                                    if e.is_roster_repeat}),
            "ids_with_hash": sum(1 for e in entries if "#" in e.qid),
            "non_unique_qids": len(collisions),
            "shapes": dict(Counter(e.shape for e in entries).most_common()),
            "study_team_confirmed": sum(1 for e in entries if e.study_team_confirmed),
        },
        "entries": [asdict(e) for e in entries],
    }
    (BUILD / "dictionary.json").write_text(json.dumps(dictionary, indent=1, ensure_ascii=False))
    _write_csv(BUILD / "collisions.csv", collisions, ["qid", "n", "scope", "keys", "texts"])
    _write_csv(BUILD / "grid_summary.csv", grid_rows,
               ["module", "subitems", "stems", "stems_without_own_row",
                "subitems_with_stem_text_split"])
    _write_csv(BUILD / "origin.csv", origin_rows,
               ["key", "module", "origin", "study_team_confirmed"])
    (BUILD / "version.json").write_text(json.dumps(
        {"version_hash": version_hash, "rules_version": BUILD_RULES_VERSION,
         "source_files": file_hashes, "entry_count": len(entries)}, indent=1))
    return dictionary


def _write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    d = build()
    c = d["counts"]
    print(f"build {d['version_hash']}  ({c['total']} entries, "
          f"{c['distinct_constructs']} distinct constructs)")
    for name, n in c["shapes"].items():
        print(f"  {n:5d}  {name}")
    print(f"  repaired {c['text_repaired']} mojibake rows, "
          f"{c['non_unique_qids']} colliding qids, "
          f"{c['study_team_confirmed']} study-team-confirmed rows")
    # Imported here, not at the top: `checks.py` imports MOJIBAKE_MARKERS from
    # this file, and a module-level import in both directions would read it
    # before it is defined.
    import checks

    groups = checks.run(d)
    if any(groups.values()):
        print(checks.report(groups))
        sys.exit(1)
    print(f"  all checks hold — {len(groups)} groups, "
          f"structural and snapshot")
