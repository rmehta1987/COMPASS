"""Harness mode 3: score posed-pair artefacts by the tier of their paper.

Mode 2 (`benchmark/specification_score.py`) scores a posed pair against the
paper's inventory and reports one pooled figure per component. This module
asks the question that figure hides: the papers are not alike. A paper whose
exposure and outcome are both in the instrument is a different measurement
from one where neither is, and pooling them reports mostly the mix.

Tiers, from the inventory's per-side reachability (`tier_of`, once item 5
lands): A both sides present, B one present one modality, C exactly one side
reachable, D neither. On the real inventory that is A=1 B=2 C=7 D=6, so most
cells here carry n <= 2 and are case studies, not rates.

What this module may and may not do, since both are easy to get wrong:

* It runs in the GENERATION clone, against synthetic fixtures only. Tier
  assignment needs the inventory and `inventory/case_map.json`, and neither
  may ever be in this clone; the real run is an operator step in the scoring
  clone. Every acceptance here is against the fakes.
* It reads inventory rows as data, not as instances of the inventory's own
  schema module. That module lives with the key; copying it here would be
  the two-copies failure this project has already been bitten by. The
  vocabulary comes from `handoff/for_harness.json` at run time and the
  schema version is pinned (item 4), so a schema change reddens this rather
  than being read under stale field names.

`MATRIX` is the report's shape, declared before any number exists. A
component that cannot be scored yet keeps its row and is rendered
unavailable: a row that disappears reads as "not applicable" when it means
"not yet built", and that is a claim about the pipeline this harness must
not make by omission.
"""

from __future__ import annotations

import argparse
import json
import sys
from enum import Enum
from pathlib import Path
from typing import Any, NamedTuple

#: The report's tiers, in report order. Not derived from any data here: the
#: tier of a case is assigned in the scoring clone, never in this one.
TIERS: tuple[str, ...] = ("A", "B", "C", "D")


class Cell(Enum):
    """Whether a component can be scored in a tier, and how completely.

    Attributes:
        FULL: Scoreable today from the artefacts this clone generates.
        HALF: One half scoreable today, the other blocked on work named in
            `Component.blocked`; rendered with the blocked half marked.
        NA: The component does not apply in this tier — no anchor is present
            to resolve, say. Rendered as a dash, never as a zero.
    """

    FULL = "full"
    HALF = "half"
    NA = "na"


class Component(NamedTuple):
    """One row of the report matrix.

    A named tuple so the matrix stays a literal a reader can check against
    the brief's table without running anything.

    Attributes:
        name: The component's name as the report prints it.
        cells: One `Cell` per tier, in `TIERS` order.
        blocked: What the blocked half waits on, for a `HALF` row; empty for
            every other row.
    """

    name: str
    cells: tuple[Cell, ...]
    blocked: str = ""


_F, _H, _N = Cell.FULL, Cell.HALF, Cell.NA

#: The 19 scoreable cells of the brief's matrix, as data. Anchor resolution
#: has nothing to resolve in tier D and refusal has nothing to refuse where
#: both anchors are present, so those cells are NA rather than zero.
MATRIX: tuple[Component, ...] = (
    Component("anchor resolution", (_F, _F, _F, _N)),
    Component("modality analogue resolution", (_N, _H, _H, _N),
              blocked="modality_mismatch needs pipeline items 16-19"),
    Component("refusal on absent anchor", (_N, _N, _F, _F)),
    Component("covariate recall, raw", (_F, _F, _F, _F)),
    Component("covariate recall, margin over modal", (_F, _F, _F, _F)),
    Component("direction agreement, weighted per paper", (_F, _F, _F, _F)),
)

#: How many cells the matrix claims are scoreable at all, full or half. Read
#: from the brief's table and pinned here so a row silently dropped from
#: `MATRIX` reddens `self_check` instead of shortening the report.
SCOREABLE_CELLS = 19



# --- item 4: the handoff header -------------------------------------------

#: The two operator inputs, relative to the repository root. Both came from the
#: orphan branch `handoff-public`, which shares no history with the key branch.
HANDOFF_PATH = Path("handoff/for_harness.json")
POSED_PAIRS_PATH = Path("posed_pairs.json")
BUILD_VERSION_PATH = Path("build/version.json")

#: What the harness pins the handoff against. Each is asserted, never warned
#: about, because each failure is silent otherwise:
#:   * a key resolved against another build names a different variable;
#:   * a schema change moves fields this module reads as plain data, and the
#:     rows would be read under stale names rather than rejected;
#:   * the bare-status reading of the tier rule gives C=8 D=5 against
#:     confident_anchor's C=7 D=6 -- both sum to 16, so a mismatched rule
#:     shows up in no total.
EXPECT_SCHEMA_VERSION = "inventory/schema.py@292571ccc682"
EXPECT_TIER_RULE = "confident_anchor"

#: The fields `load_handoff` requires. Anything else in the file is carried
#: through untouched; a missing one is a mismatch, not a default.
REQUIRED_HANDOFF_FIELDS = (
    "dictionary_version_hash", "schema_version", "status_values",
    "modality_values", "row_counts", "tier_rule", "tier_counts",
    "fixture_sizes", "components_available", "modal_covariate_set_size",
)


class HandoffMismatch(RuntimeError):
    """The handoff header does not describe the tree the harness is running in.

    Raised, never warned about: this is the discipline
    `deploy/retriever.py::DictionaryHashMismatch` uses on the dictionary hash,
    for the same reason -- a stale header scores real records against the
    wrong build, the wrong schema or the wrong tier rule, and returns a number
    rather than an error.
    """


class Handoff(NamedTuple):
    """The counts and vocabularies the key branch published to this clone.

    It carries no term, no key, no pmid and no covariate row, so nothing here
    is an answer. `tier_counts` is the real inventory's tier distribution and
    is checkable only in the scoring clone, where tiers can actually be
    assigned; nothing in the generation clone may assert against it.

    Attributes:
        dictionary_version_hash: The build the inventory's keys were resolved
            against.
        schema_version: `path@blob` of the inventory schema this harness reads
            rows under, pinned because the schema module is never imported.
        tier_rule: Which reading of the tier predicate the counts were made
            under.
        status_values: The inventory's status vocabulary.
        modality_values: The inventory's modality vocabulary.
        row_counts: Rows by status across the inventory.
        tier_counts: Papers per tier; scoring clone only.
        fixture_sizes: Sizes of the refusal and flag fixtures.
        components_available: Which components the key branch says are
            scoreable, e.g. `design: false`.
        modal_covariate_set_size: How many covariates the modal set holds, so
            the margin can be reported without a covariate term crossing the
            boundary.
        raw: The file as read, so a field added later is not lost here.
    """

    dictionary_version_hash: str
    schema_version: str
    tier_rule: str
    status_values: tuple[str, ...]
    modality_values: tuple[str, ...]
    row_counts: dict[str, int]
    tier_counts: dict[str, int]
    fixture_sizes: dict[str, int]
    components_available: dict[str, Any]
    modal_covariate_set_size: int
    raw: dict[str, Any]


def built_dictionary_hash(path: Path = BUILD_VERSION_PATH) -> str:
    """Read the hash of the dictionary actually present in this tree.

    Read from the build's own `version.json` rather than restated in this
    module: a constant here would agree with itself after a rebuild moved the
    dictionary underneath the harness.

    Args:
        path: `build/version.json`.

    Returns:
        The built dictionary's `version_hash`.

    Raises:
        HandoffMismatch: When the file is missing, since a harness that cannot
            see which dictionary it holds cannot check the handoff at all.
    """
    if not path.exists():
        raise HandoffMismatch(
            f"{path}: no built dictionary in this tree, so the handoff's "
            f"dictionary_version_hash cannot be checked. Run build.py.")
    return str(json.loads(path.read_text())["version_hash"])


def load_handoff(path: Path | None = None,
                 *, dictionary_hash: str | None = None) -> Handoff:
    """Load the handoff header and refuse a tree it does not describe.

    Args:
        path: The header; `HANDOFF_PATH` when None, resolved at call time so a
            test can point the module at another file.
        dictionary_hash: The build to check against; read from
            `build/version.json` when None.

    Returns:
        The header.

    Raises:
        HandoffMismatch: When the file is absent, a required field is missing,
            or any of the three pinned values disagrees.
    """
    path = HANDOFF_PATH if path is None else path
    if not path.exists():
        raise HandoffMismatch(
            f"{path}: absent. It is an operator step -- the file is published on "
            f"the orphan branch handoff-public and never fetched from the key "
            f"branch. Without it the harness has no vocabulary and no pins.")
    raw = dict(json.loads(path.read_text()))
    missing = [f for f in REQUIRED_HANDOFF_FIELDS if f not in raw]
    if missing:
        raise HandoffMismatch(f"{path}: missing {missing}")

    want_dict = (dictionary_hash if dictionary_hash is not None
                 else built_dictionary_hash())
    problems: list[str] = []
    if raw["dictionary_version_hash"] != want_dict:
        problems.append(f"dictionary_version_hash {raw['dictionary_version_hash']!r} "
                        f"but this tree holds {want_dict!r}: the inventory's keys "
                        f"were resolved against another build and name other "
                        f"variables here")
    if raw["schema_version"] != EXPECT_SCHEMA_VERSION:
        problems.append(f"schema_version {raw['schema_version']!r} but this harness "
                        f"reads rows under {EXPECT_SCHEMA_VERSION!r}; it never imports "
                        f"the schema module, so a moved schema is silent unless "
                        f"pinned here")
    if raw["tier_rule"] != EXPECT_TIER_RULE:
        problems.append(f"tier_rule {raw['tier_rule']!r} but this harness implements "
                        f"{EXPECT_TIER_RULE!r}; the bare-status reading gives C=8 D=5 "
                        f"against C=7 D=6 and both sum to 16, so the disagreement "
                        f"appears in no total")
    if problems:
        raise HandoffMismatch(f"{path}: " + "; ".join(problems))

    return Handoff(dictionary_version_hash=str(raw["dictionary_version_hash"]),
                   schema_version=str(raw["schema_version"]),
                   tier_rule=str(raw["tier_rule"]),
                   status_values=tuple(raw["status_values"]),
                   modality_values=tuple(raw["modality_values"]),
                   row_counts=dict(raw["row_counts"]),
                   tier_counts=dict(raw["tier_counts"]),
                   fixture_sizes=dict(raw["fixture_sizes"]),
                   components_available=dict(raw["components_available"]),
                   modal_covariate_set_size=int(raw["modal_covariate_set_size"]),
                   raw=raw)


def self_check() -> list[str]:
    """Check the report's declared shape against its own invariants.

    Run by `check.sh`, so that the gate exercises this module from the commit
    that introduces it rather than from the commit that finishes it. It
    checks only what is built; each later item adds its own checks here.

    Returns:
        One message per violation, empty when the module is consistent.
    """
    problems: list[str] = []
    for row in MATRIX:
        if len(row.cells) != len(TIERS):
            problems.append(f"{row.name}: {len(row.cells)} cells for {len(TIERS)} tiers")
        half = any(c is Cell.HALF for c in row.cells)
        if half and not row.blocked:
            problems.append(f"{row.name}: a half-available row must name what blocks it")
        if row.blocked and not half:
            problems.append(f"{row.name}: names a blocker but has no half-available cell")
    names = [row.name for row in MATRIX]
    if len(set(names)) != len(names):
        problems.append(f"duplicate component names: {names}")
    scoreable = sum(1 for row in MATRIX for c in row.cells if c is not Cell.NA)
    if scoreable != SCOREABLE_CELLS:
        problems.append(f"matrix has {scoreable} scoreable cells, expected "
                        f"{SCOREABLE_CELLS}; a row was dropped or a cell moved")
    try:
        handoff = load_handoff()
    except HandoffMismatch as e:
        problems.append(str(e))
    else:
        if handoff.components_available.get("design") is not False:
            problems.append("the handoff no longer reports design: false; design "
                            "agreement is not a component here and the report says so")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Run the module's command line.

    Args:
        argv: Arguments, or None to read `sys.argv`.

    Returns:
        A process exit status: 0 when every check passed.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-check", action="store_true",
                        help="check the report's declared shape and exit")
    args = parser.parse_args(argv)
    if not args.self_check:
        parser.error("nothing to do yet: pass --self-check")
    problems = self_check()
    for problem in problems:
        print(f"tiered_score: {problem}")
    print(f"tiered_score self-check: {len(MATRIX)} components, "
          f"{SCOREABLE_CELLS} scoreable cells, {len(problems)} problems")
    if not problems:
        h = load_handoff()
        print(f"handoff pinned: dictionary {h.dictionary_version_hash}, "
              f"schema {h.schema_version}, tier_rule {h.tier_rule}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
