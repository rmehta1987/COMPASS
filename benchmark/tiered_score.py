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
from collections.abc import Callable
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



# --- item 5: tier assignment ----------------------------------------------
#
# BUILT here, EXECUTED for real in the scoring clone. Tiers derive from the
# inventory and inventory/case_map.json, and neither may ever be in this
# clone, so every acceptance below is against tests/fake_tiered_inventory.json
# and nothing here may be checked against the handoff's tier_counts.


class SideState(Enum):
    """How a paper's exposure or outcome side reaches the instrument.

    Attributes:
        PRESENT: The instrument holds the variable itself.
        MODALITY: The instrument holds a different measurement of it, named by
            the row's `analogue_key`.
        UNREACHABLE: Neither, under the rule in force.
    """

    PRESENT = "present"
    MODALITY = "modality"
    UNREACHABLE = "unreachable"


class UnclassifiablePaper(ValueError):
    """A paper the stated tier predicate does not place.

    Both sides reachable only through a modality analogue is such a shape: it
    is not A (neither side is present), not B (B is one present and one
    modality), and not C or D (both sides are reachable). The predicate is the
    operator's, published in the handoff's `tier_rule_definition`; a harness
    that binned this shape somewhere plausible would report a tier nobody
    defined, so it raises instead.
    """


def side_state(rows: list[dict[str, Any]], *,
               require_confident: bool = True) -> SideState:
    """Classify one side of a paper.

    The keyed conjunct never discriminates on the real inventory -- every
    present row is keyed and every modality row carries an analogue -- so
    `confident` does the work. It is kept because it is defensive: a row that
    lost its key would otherwise read as reachable.

    Args:
        rows: The side's inventory rows, as data.
        require_confident: The `confident_anchor` rule when True. False is the
            bare-status reading, which exists only so a test can show the two
            disagree; it is never the rule the harness scores under.

    Returns:
        The side's state.
    """
    def usable(row: dict[str, Any], status: str, key_field: str) -> bool:
        return (row.get("status") == status
                and row.get(key_field) is not None
                and (row.get("confident") is True or not require_confident))

    if any(usable(r, "present", "key") for r in rows):
        return SideState.PRESENT
    if any(usable(r, "modality", "analogue_key") for r in rows):
        return SideState.MODALITY
    return SideState.UNREACHABLE


def tier_of(paper: dict[str, Any], *, require_confident: bool = True) -> str:
    """Assign a paper's tier from its two sides.

    Args:
        paper: One inventory paper, with `exposures` and `outcomes`.
        require_confident: See `side_state`.

    Returns:
        `A`, `B`, `C` or `D`.

    Raises:
        UnclassifiablePaper: On a shape the stated predicate does not place.
    """
    e = side_state(paper["exposures"], require_confident=require_confident)
    o = side_state(paper["outcomes"], require_confident=require_confident)
    states = {e, o}
    if states == {SideState.PRESENT}:
        return "A"
    if states == {SideState.PRESENT, SideState.MODALITY}:
        return "B"
    reachable = sum(1 for s in (e, o) if s is not SideState.UNREACHABLE)
    if reachable == 1:
        return "C"
    if reachable == 0:
        return "D"
    raise UnclassifiablePaper(
        f"{paper.get('paper', '?')}: exposure {e.value}, outcome {o.value} is not "
        f"placed by the tier rule (A both present; B one present one modality; "
        f"C exactly one side reachable; D neither). Ask the operator rather than "
        f"binning it.")


def tiers_of(papers: list[dict[str, Any]],
             *, require_confident: bool = True) -> dict[str, str]:
    """Assign every paper's tier.

    Args:
        papers: The inventory's papers.
        require_confident: See `side_state`.

    Returns:
        Paper id to tier, in input order.

    Raises:
        UnclassifiablePaper: Propagated from `tier_of`.
    """
    return {str(p["paper"]): tier_of(p, require_confident=require_confident)
            for p in papers}



# --- item 6: anchor resolution --------------------------------------------
#
# The inventory names variable keys; the run resolves a term to a CONSTRUCT,
# so the two are compared at construct level through a key -> construct map
# the caller supplies. Comparing a variable key with a construct key would
# score every case as a miss.


class Anchor(Enum):
    """What became of one side's anchor.

    Attributes:
        KEY: Resolved to the construct holding the inventory's own key.
        ELSEWHERE: Resolved, but to another construct.
        ABSTAINED: Nothing cleared the threshold, so no construct was chosen.
        NOT_SCOREABLE: The side is not PRESENT in the inventory, so there is
            no key to resolve to. Modality sides are item 8's and absent sides
            are item 7's; scoring them here would double-count them.
    """

    KEY = "resolved_to_key"
    ELSEWHERE = "resolved_elsewhere"
    ABSTAINED = "abstained"
    NOT_SCOREABLE = "not_scoreable"


#: A key to the construct that holds it, or None when the build has neither.
ConstructOf = Callable[[str], str | None]


def target_constructs(rows: list[dict[str, Any]], construct_of: ConstructOf, *,
                      key_field: str = "key",
                      status: str = "present") -> frozenset[str]:
    """The constructs a side's confident rows point at.

    Args:
        rows: The side's inventory rows.
        construct_of: Key to construct.
        key_field: `key` for a present row, `analogue_key` for a modality row.
        status: The row status to read.

    Returns:
        The acceptable constructs, empty when the side has no such row.
    """
    keys = [r[key_field] for r in rows
            if r.get("status") == status and r.get(key_field) is not None
            and r.get("confident") is True]
    return frozenset(c for c in (construct_of(k) for k in keys) if c is not None)


def anchor_verdict(side: dict[str, Any], rows: list[dict[str, Any]],
                   construct_of: ConstructOf) -> Anchor:
    """Score one side's anchor resolution against the inventory.

    Args:
        side: The case index's `exposure` or `outcome` block, carrying
            `construct_key` and `abstained`.
        rows: That side's inventory rows.
        construct_of: Key to construct.

    Returns:
        The verdict.
    """
    if side_state(rows) is not SideState.PRESENT:
        return Anchor.NOT_SCOREABLE
    got = side.get("construct_key")
    if got is None or side.get("abstained"):
        return Anchor.ABSTAINED
    return (Anchor.KEY if got in target_constructs(rows, construct_of)
            else Anchor.ELSEWHERE)


class AnchorScore(NamedTuple):
    """One case's anchor verdicts.

    Attributes:
        case_id: The opaque case id.
        exposure: The exposure side's verdict.
        outcome: The outcome side's verdict.
    """

    case_id: str
    exposure: Anchor
    outcome: Anchor

    @property
    def scoreable(self) -> int:
        """How many of the two sides this component could score at all."""
        return sum(1 for v in (self.exposure, self.outcome)
                   if v is not Anchor.NOT_SCOREABLE)

    @property
    def hits(self) -> int:
        """How many sides landed on the inventory's own key."""
        return sum(1 for v in (self.exposure, self.outcome) if v is Anchor.KEY)


def anchor_scores(cases: list[dict[str, Any]], paper_of: dict[str, dict[str, Any]],
                  construct_of: ConstructOf) -> list[AnchorScore]:
    """Score anchor resolution for every case that has a paper.

    Args:
        cases: Case index rows, from `pipeline.pose_terms.read_case_index`.
        paper_of: Case id to its inventory paper. In the scoring clone this
            join runs through `inventory/case_map.json`; here it is the fake
            inventory's own pairs.
        construct_of: Key to construct.

    Returns:
        One row per case present in `paper_of`, in case order.
    """
    out: list[AnchorScore] = []
    for case in cases:
        paper = paper_of.get(str(case["case_id"]))
        if paper is None:
            continue
        out.append(AnchorScore(
            str(case["case_id"]),
            anchor_verdict(case["exposure"], paper["exposures"], construct_of),
            anchor_verdict(case["outcome"], paper["outcomes"], construct_of)))
    return out


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
