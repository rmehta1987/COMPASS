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
from collections import Counter
from collections.abc import Callable, Iterable
from enum import Enum
from math import ceil, sqrt
from pathlib import Path
from typing import Any, NamedTuple

from agent.schema import Direction
from benchmark.paper_inventory import MODAL_SHARE

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



# --- item 7: refusal on an unreachable anchor -----------------------------
#
# "Absent" here means the side is UNREACHABLE under the tier rule, which is
# the shape tiers C and D are made of: rows the instrument does not hold, and
# also a modality row nobody could pin (`confident=false`). Both are anchors
# the pipeline has no honest variable for, and approximating one is the
# failure this component looks for.
#
# Never pooled with `benchmark/absence/`'s flag fixture: that scorer reads a
# JSON fixture and retrieval output and answers a different question.


class Refusal(Enum):
    """What the pipeline did with an anchor the instrument cannot supply.

    Attributes:
        AT_RETRIEVAL: The term abstained, so no construct was chosen and no
            model call was spent. A refusal, and the cheapest kind.
        BY_SPECIFIER: A construct was chosen but the specifier refused to
            emit a protocol.
        APPROXIMATED: A construct was chosen and a record was produced
            anyway: the failure this component exists to count.
        NOT_SCOREABLE: The side is reachable, so there was nothing to refuse.
    """

    AT_RETRIEVAL = "refused_at_retrieval"
    BY_SPECIFIER = "refused_by_specifier"
    APPROXIMATED = "approximated"
    NOT_SCOREABLE = "not_scoreable"


#: Case states that mean the pipeline declined to emit a protocol at all.
REFUSING_STATES = ("refused", "unresolved_anchor")


def refusal_verdict(side: dict[str, Any], rows: list[dict[str, Any]],
                    state: str) -> Refusal:
    """Score one side's refusal, if that side is unreachable.

    Args:
        side: The case index's block for this side.
        rows: That side's inventory rows.
        state: The case's state, from the case index.

    Returns:
        The verdict.
    """
    if side_state(rows) is not SideState.UNREACHABLE:
        return Refusal.NOT_SCOREABLE
    if side.get("abstained") or side.get("construct_key") is None:
        return Refusal.AT_RETRIEVAL
    if state == "refused":
        return Refusal.BY_SPECIFIER
    return Refusal.APPROXIMATED


class RefusalScore(NamedTuple):
    """One case's refusal verdicts.

    Attributes:
        case_id: The opaque case id.
        exposure: The exposure side's verdict.
        outcome: The outcome side's verdict.
    """

    case_id: str
    exposure: Refusal
    outcome: Refusal

    @property
    def scoreable(self) -> int:
        """Unreachable sides this case contributes."""
        return sum(1 for v in (self.exposure, self.outcome)
                   if v is not Refusal.NOT_SCOREABLE)

    @property
    def refused(self) -> int:
        """Unreachable sides the pipeline declined, either way."""
        return sum(1 for v in (self.exposure, self.outcome)
                   if v in (Refusal.AT_RETRIEVAL, Refusal.BY_SPECIFIER))

    @property
    def approximated(self) -> int:
        """Unreachable sides the pipeline answered anyway."""
        return sum(1 for v in (self.exposure, self.outcome)
                   if v is Refusal.APPROXIMATED)


def refusal_scores(cases: list[dict[str, Any]],
                   paper_of: dict[str, dict[str, Any]]) -> list[RefusalScore]:
    """Score refusal for every case that has a paper.

    Args:
        cases: Case index rows.
        paper_of: Case id to its inventory paper; the join is
            `inventory/case_map.json`'s in the scoring clone.

    Returns:
        One row per case present in `paper_of`, in case order.
    """
    out: list[RefusalScore] = []
    for case in cases:
        paper = paper_of.get(str(case["case_id"]))
        if paper is None:
            continue
        state = str(case.get("state", ""))
        out.append(RefusalScore(
            str(case["case_id"]),
            refusal_verdict(case["exposure"], paper["exposures"], state),
            refusal_verdict(case["outcome"], paper["outcomes"], state)))
    return out



# --- item 8: modality analogue resolution (half available) ----------------
#
# Two halves, and only one exists today:
#   * did the run resolve the side to the analogue the inventory names? YES,
#     scoreable now, below;
#   * did the pipeline flag the substitution as a modality mismatch? NO. No
#     record field carries it -- `modality_mismatch` appears nowhere in the
#     tree -- and it needs pipeline items 16-19.
# The second half is REPORTED AS UNAVAILABLE, never omitted: a row that
# disappears reads as "not applicable" when it means "not yet built".

#: Whether a record can say it substituted a different measurement. False
#: until pipeline items 16-19 land; read by the renderer, never assumed.
MODALITY_MISMATCH_AVAILABLE = False
#: What the blocked half waits on, printed beside the row it cannot fill.
MODALITY_MISMATCH_BLOCKER = (
    "no record field carries modality_mismatch; needs pipeline items 16-19")


def analogue_verdict(side: dict[str, Any], rows: list[dict[str, Any]],
                     construct_of: ConstructOf) -> Anchor:
    """Score one side against the analogue the inventory names.

    Args:
        side: The case index's block for this side.
        rows: That side's inventory rows.
        construct_of: Key to construct.

    Returns:
        The verdict, with `NOT_SCOREABLE` for a side that is not MODALITY --
        a present side is item 6's and an unreachable one is item 7's.
    """
    if side_state(rows) is not SideState.MODALITY:
        return Anchor.NOT_SCOREABLE
    got = side.get("construct_key")
    if got is None or side.get("abstained"):
        return Anchor.ABSTAINED
    targets = target_constructs(rows, construct_of, key_field="analogue_key",
                               status="modality")
    return Anchor.KEY if got in targets else Anchor.ELSEWHERE


class AnalogueScore(NamedTuple):
    """One case's analogue verdicts, and the half that is not built.

    Attributes:
        case_id: The opaque case id.
        exposure: The exposure side's verdict.
        outcome: The outcome side's verdict.
        mismatch_flagged: Whether the pipeline flagged the substitution.
            Always None while `MODALITY_MISMATCH_AVAILABLE` is False -- an
            unbuilt half reports as unknown, never as False, which would read
            as "the pipeline failed to flag it".
    """

    case_id: str
    exposure: Anchor
    outcome: Anchor
    mismatch_flagged: bool | None = None

    @property
    def scoreable(self) -> int:
        """Modality sides this case contributes."""
        return sum(1 for v in (self.exposure, self.outcome)
                   if v is not Anchor.NOT_SCOREABLE)

    @property
    def hits(self) -> int:
        """Modality sides that landed on the inventory's analogue."""
        return sum(1 for v in (self.exposure, self.outcome) if v is Anchor.KEY)


def analogue_scores(cases: list[dict[str, Any]], paper_of: dict[str, dict[str, Any]],
                    construct_of: ConstructOf) -> list[AnalogueScore]:
    """Score analogue resolution for every case that has a paper.

    Args:
        cases: Case index rows.
        paper_of: Case id to its inventory paper.
        construct_of: Key to construct.

    Returns:
        One row per case present in `paper_of`, in case order. Every row's
        `mismatch_flagged` is None while that half is unbuilt.

    Raises:
        NotImplementedError: If `MODALITY_MISMATCH_AVAILABLE` is flipped on
            without this function learning where the flag lives. Better than
            silently reporting None as a measurement.
    """
    if MODALITY_MISMATCH_AVAILABLE:
        raise NotImplementedError(
            "MODALITY_MISMATCH_AVAILABLE is on but nothing here reads the flag; "
            "wire it to the record field pipeline items 16-19 add.")
    out: list[AnalogueScore] = []
    for case in cases:
        paper = paper_of.get(str(case["case_id"]))
        if paper is None:
            continue
        out.append(AnalogueScore(
            str(case["case_id"]),
            analogue_verdict(case["exposure"], paper["exposures"], construct_of),
            analogue_verdict(case["outcome"], paper["outcomes"], construct_of),
            mismatch_flagged=None))
    return out



# --- item 9: covariate recall, raw ----------------------------------------
#
# Covariates are compared VARIABLE KEY TO VARIABLE KEY, the convention
# benchmark/specification_score.py already uses, because both sides are
# variable keys: the record's adjustment set is what the model selected, and
# the inventory's covariate rows are what the author resolved. The anchors are
# compared at construct level instead because one side of that comparison
# comes from retrieval, which returns constructs. The two are not inconsistent;
# they compare what each source actually holds.
#
# The arithmetic is not shared with specification_score because that module's
# types are the two-state inventory (in_instrument / resolution), which the
# tiered inventory's schema replaces; sharing would mean converting rows into
# a schema the key branch no longer uses.


def _ratio(hits: int, total: int) -> float | None:
    """Hits over total, or None when the denominator is zero.

    Args:
        hits: Numerator.
        total: Denominator.

    Returns:
        The ratio, or None -- never 0.0, which would read as a measured zero.
    """
    return None if total == 0 else hits / total


def scorable_covariates(paper: dict[str, Any]) -> frozenset[str]:
    """The covariate keys the harness may score a record against.

    Args:
        paper: One inventory paper.

    Returns:
        Keys of rows that are present, keyed and confident.
    """
    return frozenset(
        str(r["key"]) for r in paper.get("covariates", [])
        if r.get("status") == "present" and r.get("key") is not None
        and r.get("confident") is True)


def covariate_exclusions(paper: dict[str, Any]) -> dict[str, int]:
    """Why the harness left covariate rows out, counted by reason.

    Reported beside recall: a denominator that quietly shrank is a different
    number from the one a reader thinks they are looking at.

    Args:
        paper: One inventory paper.

    Returns:
        Reason to count, empty when every row is scorable.
    """
    out: dict[str, int] = {}
    for row in paper.get("covariates", []):
        if row.get("status") == "absent":
            reason = "absent"
        elif row.get("status") == "modality":
            reason = "modality"
        elif row.get("key") is None:
            reason = "unkeyed"
        elif row.get("confident") is not True:
            reason = "not_confident"
        else:
            continue
        out[reason] = out.get(reason, 0) + 1
    return dict(sorted(out.items()))


class CovariateScore(NamedTuple):
    """One case's covariate recovery against its paper.

    Attributes:
        case_id: The opaque case id.
        paper: The inventory paper's id.
        adjusted: How many covariates the record adjusted for.
        recoverable: How many of the paper's covariates the harness may score,
            which is the denominator of `recall` and is not the paper's total.
        hits: The overlap.
        recall: Hits over recoverable; None when nothing is recoverable.
        precision: Hits over adjusted; None when the record adjusted for
            nothing.
        excluded: Rows left out, by reason.
        paper_covariates: Every covariate row the paper has, so the reader can
            see what `recoverable` cost.
    """

    case_id: str
    paper: str
    adjusted: int
    recoverable: int
    hits: int
    recall: float | None
    precision: float | None
    excluded: dict[str, int]
    paper_covariates: int


def covariate_score(case_id: str, paper: dict[str, Any],
                    adjustment_set: Iterable[str]) -> CovariateScore:
    """Score one record's adjustment set against one paper.

    Args:
        case_id: The opaque case id.
        paper: The inventory paper.
        adjustment_set: The record's adjustment set, variable keys.

    Returns:
        The row.
    """
    adjusted = frozenset(adjustment_set)
    cov = scorable_covariates(paper)
    hits = len(adjusted & cov)
    return CovariateScore(
        case_id=case_id, paper=str(paper.get("paper", "?")), adjusted=len(adjusted),
        recoverable=len(cov), hits=hits, recall=_ratio(hits, len(cov)),
        precision=_ratio(hits, len(adjusted)), excluded=covariate_exclusions(paper),
        paper_covariates=len(paper.get("covariates", [])))



# --- item 10: the margin over the modal set -------------------------------
#
# The modal set is COMPUTED from the inventory's keyed covariate rows at run
# time and is never written down here: handoff/for_harness.json ships only
# `modal_covariate_set_size`, so no covariate term or key crosses into this
# clone. A test asserts this module holds no variable-key literal at all.
#
# Raw recall is a ceiling effect -- a specifier that always proposes age, sex,
# race, income, BMI and smoking scores well on almost any paper without one
# hypothesis-specific thought. THE MARGIN IS THE RESULT; the raw number is not.


def modal_covariates(papers: list[dict[str, Any]],
                     share: float = MODAL_SHARE) -> frozenset[str]:
    """The conventional adjustment set, computed from the inventory.

    Args:
        papers: The inventory's papers.
        share: A key is modal when at least this share of the papers with a
            scorable covariate adjusted for it. `MODAL_SHARE` is read from
            `benchmark.paper_inventory`, which owns it.

    Returns:
        The modal keys; empty when no paper has a scorable covariate.
    """
    with_cov = [p for p in papers if scorable_covariates(p)]
    if not with_cov:
        return frozenset()
    threshold = max(1, ceil(share * len(with_cov)))
    counts: Counter[str] = Counter()
    for paper in with_cov:
        counts.update(scorable_covariates(paper))
    return frozenset(k for k, n in counts.items() if n >= threshold)


def modal_size_disagreement(modal: frozenset[str], handoff: Handoff) -> str | None:
    """Compare the computed modal set with the size the key branch published.

    A cross-check for the scoring clone, where the inventory is real. In the
    generation clone the fixture is synthetic and a disagreement is expected,
    so this REPORTS rather than raises: the size is a fact about the real
    inventory, not about the fake.

    Args:
        modal: The computed modal set.
        handoff: The handoff header.

    Returns:
        A message, or None when the sizes agree.
    """
    if len(modal) == handoff.modal_covariate_set_size:
        return None
    return (f"modal set computed here holds {len(modal)} keys; the handoff says "
            f"the real inventory's holds {handoff.modal_covariate_set_size}. "
            f"Expected against a synthetic inventory; in the scoring clone it "
            f"means the modal rule or the inventory moved.")


class MarginScore(NamedTuple):
    """One case's recall against the modal baseline.

    Attributes:
        case_id: The opaque case id.
        paper: The inventory paper's id.
        recall: The record's recall over the recoverable covariates.
        modal_recall: What the modal set alone would have recovered, over the
            same denominator.
        margin: `recall - modal_recall`, the result; None when either side is.
        modal_size: How many keys the modal set holds, so the baseline can be
            read without it.
    """

    case_id: str
    paper: str
    recall: float | None
    modal_recall: float | None
    margin: float | None
    modal_size: int


def margin_score(score: CovariateScore, paper: dict[str, Any],
                 modal: frozenset[str]) -> MarginScore:
    """Put one case's recall beside what convention alone would have scored.

    Args:
        score: The case's raw covariate score.
        paper: Its inventory paper.
        modal: The computed modal set.

    Returns:
        The row.
    """
    cov = scorable_covariates(paper)
    modal_recall = _ratio(len(modal & cov), len(cov))
    margin = (None if score.recall is None or modal_recall is None
              else score.recall - modal_recall)
    return MarginScore(case_id=score.case_id, paper=score.paper, recall=score.recall,
                       modal_recall=modal_recall, margin=margin,
                       modal_size=len(modal))



# --- item 11: direction agreement, weighted per paper ---------------------
#
# The inventory records a direction per PAIR, and the pairs are not evenly
# spread: one real paper holds 23 of the 95 triples and four hold 56%. An
# unweighted rate over the pairs measures that paper. This reports the
# per-paper weighted rate as the headline, the unweighted per-pair rate
# beside it, the concentration that separates them, and the majority base
# rate a specifier that always guessed one direction would score.


#: The directions a RECORD can hold, from the schema's own enum. Narrower than
#: benchmark.paper_inventory.DIRECTIONS, which also holds `mixed` for a paper
#: whose pairs disagree: a record has no member for that, so a `mixed` row is
#: carried unscored rather than counted as a disagreement.
RECORD_DIRECTIONS: tuple[str, ...] = tuple(d.value for d in Direction)


def directions_by_case(papers: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    """Map each case id to its paper and the direction the paper reported.

    Args:
        papers: The inventory's papers, each with a `pairs` list of
            `case_id` and `direction`.

    Returns:
        Case id to `(paper id, direction)`.
    """
    out: dict[str, tuple[str, str]] = {}
    for paper in papers:
        for pair in paper.get("pairs", []):
            out[str(pair["case_id"])] = (str(paper.get("paper", "?")),
                                         str(pair["direction"]))
    return out


class DirectionScore(NamedTuple):
    """One case's direction agreement.

    Attributes:
        case_id: The opaque case id.
        paper: The inventory paper's id, which is the weighting unit.
        reported: The paper's direction.
        specified: The record's expected direction, None when no record was
            emitted.
        agree: Whether they match; None when the case produced no record, or
            the paper's direction is not one the record vocabulary can hold.
    """

    case_id: str
    paper: str
    reported: str
    specified: str | None
    agree: bool | None


def direction_scores(specified: dict[str, str | None], papers: list[dict[str, Any]],
                     *, vocabulary: Iterable[str] = RECORD_DIRECTIONS,
                     ) -> list[DirectionScore]:
    """Score every case whose paper reported a direction.

    Args:
        specified: Case id to the record's expected direction, or None where
            the case produced no record.
        papers: The inventory's papers.
        vocabulary: Directions a record can hold; anything else in the
            inventory (`mixed`, say) is carried with `agree=None` rather than
            scored as a disagreement.

    Returns:
        One row per case the inventory has a direction for, in inventory
        order.
    """
    allowed = frozenset(vocabulary)
    out: list[DirectionScore] = []
    for case_id, (paper, reported) in directions_by_case(papers).items():
        got = specified.get(case_id)
        agree = None if got is None or reported not in allowed else got == reported
        out.append(DirectionScore(case_id, paper, reported, got, agree))
    return out


class DirectionSummary(NamedTuple):
    """Direction agreement, weighted and unweighted, with what separates them.

    Attributes:
        scored: Cases with a verdict.
        papers: Papers those cases came from -- the weighted rate's
            denominator.
        per_pair: The unweighted rate over scored cases.
        per_paper: The mean of each paper's own rate: the headline, because
            the pairs are concentrated.
        largest_paper_share: The share of scored cases the biggest paper
            holds, which is why the two rates differ.
        base_rate: What always guessing the inventory's majority direction
            would score, over the scored cases.
        base_direction: That majority direction.
        unscored: Cases carried but not scored, because no record was emitted
            or the direction is outside the record vocabulary.
    """

    scored: int
    papers: int
    per_pair: float | None
    per_paper: float | None
    largest_paper_share: float | None
    base_rate: float | None
    base_direction: str | None
    unscored: int


def direction_summary(rows: list[DirectionScore]) -> DirectionSummary:
    """Summarise direction agreement without letting one paper carry it.

    Args:
        rows: The scored cases.

    Returns:
        The summary. Every rate is None rather than 0.0 when nothing was
        scored, so an unmeasured direction never prints as a measured failure.
    """
    scored = [r for r in rows if r.agree is not None]
    unscored = len(rows) - len(scored)
    if not scored:
        return DirectionSummary(0, 0, None, None, None, None, None, unscored)
    by_paper: dict[str, list[DirectionScore]] = {}
    for row in scored:
        by_paper.setdefault(row.paper, []).append(row)
    per_paper_rates = [sum(1 for r in rs if r.agree) / len(rs)
                       for rs in by_paper.values()]
    counts = Counter(r.reported for r in scored)
    base_direction, base_n = counts.most_common(1)[0]
    biggest = max(len(rs) for rs in by_paper.values())
    return DirectionSummary(
        scored=len(scored), papers=len(by_paper),
        per_pair=_ratio(sum(1 for r in scored if r.agree), len(scored)),
        per_paper=sum(per_paper_rates) / len(per_paper_rates),
        largest_paper_share=biggest / len(scored),
        base_rate=_ratio(base_n, len(scored)), base_direction=str(base_direction),
        unscored=unscored)



# --- item 12: tiers A and B are case studies, never rates -----------------
#
# Tier A is ONE paper and tier B is two: 9 of the 19 cells sit at n <= 2. A
# percentage over one case is not a measurement of anything, so these tiers
# are rendered as case studies -- name the case, name each component, say what
# happened, in counts. The renderer prints no ratio at all, and a test enforces
# it, because "tier A: 100%" is exactly the sentence this report must not
# produce.


class CaseReport(NamedTuple):
    """Every component's verdict for one case, ready to render.

    Attributes:
        case_id: The opaque case id.
        paper: The inventory paper's id.
        tier: `A`, `B`, `C` or `D`.
        state: What the run did with the case, from the case index.
        anchor: Anchor resolution, or None where the case was not scored.
        analogue: Analogue resolution, or None.
        refusal: Refusal, or None.
        covariate: Covariate recall, or None where no record was emitted.
        margin: The margin over the modal set, or None.
        direction: Direction agreement, or None.
    """

    case_id: str
    paper: str
    tier: str
    state: str
    anchor: AnchorScore | None = None
    analogue: AnalogueScore | None = None
    refusal: RefusalScore | None = None
    covariate: CovariateScore | None = None
    margin: MarginScore | None = None
    direction: DirectionScore | None = None


def _sides(verdicts: tuple[Any, Any]) -> str:
    e, o = verdicts
    return f"exposure {e.value}, outcome {o.value}"


def _case_study(report: CaseReport) -> list[str]:
    """One case, in counts, with every component named including the empty ones.

    Args:
        report: The case.

    Returns:
        Lines, indented under the case's heading.
    """
    def row(name: str, text: str) -> str:
        return f"    {name:<28}{text}"

    out = [f"  {report.paper} / {report.case_id}  ({report.state})"]
    a, g, r = report.anchor, report.analogue, report.refusal
    out.append(row("anchor resolution",
                   _sides((a.exposure, a.outcome)) if a else "not scored"))
    out.append(row("modality analogue",
                   (_sides((g.exposure, g.outcome)) if g else "not scored")
                   + f"; mismatch flag UNAVAILABLE ({MODALITY_MISMATCH_BLOCKER})"))
    out.append(row("refusal on absent anchor",
                   _sides((r.exposure, r.outcome)) if r else "not scored"))
    c, m = report.covariate, report.margin
    if c is None:
        out.append(row("covariate recall", "no record emitted"))
    else:
        excl = (", ".join(f"{n} {why}" for why, n in c.excluded.items())
                or "none excluded")
        out.append(row("covariate recall",
                       f"{c.hits} of {c.recoverable} recovered; adjusted for "
                       f"{c.adjusted}; {c.paper_covariates} rows in the paper, "
                       f"{excl}"))
    if m is None or c is None:
        out.append(row("margin over modal", "no record emitted"))
    else:
        modal_hits = round((m.modal_recall or 0.0) * c.recoverable)
        out.append(row("margin over modal",
                       f"record {c.hits} of {c.recoverable}, the modal set alone "
                       f"{modal_hits} of {c.recoverable} ({m.modal_size} keys)"))
    d = report.direction
    if d is None:
        out.append(row("direction", "not scored"))
    elif d.agree is None:
        out.append(row("direction",
                       f"paper {d.reported}, record "
                       f"{d.specified or 'none emitted'}, not scored"))
    else:
        out.append(row("direction", f"paper {d.reported}, record {d.specified}, "
                                    f"{'agreed' if d.agree else 'disagreed'}"))
    return out


def render_case_studies(reports: list[CaseReport], tier: str) -> str:
    """Render one small tier as case studies.

    Args:
        reports: Every case in the tier, scored or not.
        tier: The tier's name, for the heading.

    Returns:
        The section. A tier with no case reads UNMEASURED, never 0 of 0: an
        empty tier is a question that could not be asked, and tier A is one
        paper with one case, so it can vanish entirely (14a).
    """
    papers = sorted({r.paper for r in reports})
    head = (f"TIER {tier} - {len(papers)} paper(s), {len(reports)} case(s). "
            f"Case studies, not rates: n is too small for a rate to mean anything.")
    if not reports:
        return (f"TIER {tier} - UNMEASURED: no case in this run reached this "
                f"tier with a scoreable outcome. Not a rate of zero, and not "
                f"evidence about the pipeline.")
    lines = [head]
    for report in sorted(reports, key=lambda r: (r.paper, r.case_id)):
        lines.extend(_case_study(report))
    return "\n".join(lines)



# --- item 13: tiers C and D carry rates, with an interval and an n --------
#
# Tier C is 7 papers and tier D is 6, so a rate is meaningful here in a way it
# is not in A or B -- but only just. At n = 6 and 7 a Wilson interval is very
# wide, and that width IS the honest presentation: one case flipping moves the
# point estimate by more than a tenth. Every figure carries its n, and a tier
# that scored nothing reads UNMEASURED rather than zero.


def wilson(hits: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """The 95% Wilson score interval for a proportion.

    The formula `src/char_strata.py::wilson` uses. Not imported from there:
    `src/` is the retrieval tree, excluded from ruff and mypy, and importing
    it would pull an unannotated module into the pipeline's typed surface.

    Args:
        hits: Successes.
        n: Trials.
        z: The normal quantile; 1.96 for 95%.

    Returns:
        `(low, high)`, or `(None, None)` when n is zero -- an interval over no
        trials is not a wide interval, it is no interval.
    """
    if n <= 0:
        return (None, None)
    p = hits / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round((centre - half) / d, 3), round((centre + half) / d, 3))


class Rate(NamedTuple):
    """One component's rate in one tier, with everything needed to read it.

    Attributes:
        name: The component's name, as the matrix names it.
        hits: Numerator.
        n: Denominator -- sides, cases or papers, whichever the component
            counts; `unit` says which.
        unit: What `n` counts.
        low: Wilson lower bound, None when n is zero or the figure is not a
            proportion.
        high: Wilson upper bound, likewise.
        note: Anything the reader needs to not misread it, including
            `UNMEASURED` when n is zero.
    """

    name: str
    hits: int
    n: int
    unit: str
    low: float | None
    high: float | None
    note: str = ""

    @property
    def rate(self) -> float | None:
        """Hits over n, or None when nothing was scored."""
        return _ratio(self.hits, self.n)


def _rate(name: str, hits: int, n: int, unit: str, note: str = "") -> Rate:
    low, high = wilson(hits, n)
    if n == 0:
        # UNMEASURED leads, because it is the fact that changes how every other
        # word on the line is read.
        note = ("UNMEASURED: no case in this tier produced a scoreable outcome; "
                "this is not a rate of zero") + (f". {note}" if note else "")
    return Rate(name, hits, n, unit, low, high, note.strip())


def component_rates(reports: list[CaseReport]) -> list[Rate]:
    """Every component's rate for one tier, in matrix order.

    Args:
        reports: The tier's cases.

    Returns:
        One `Rate` per component, including the components that scored
        nothing: a component dropped from the list would read as inapplicable.
    """
    anchors = [r.anchor for r in reports if r.anchor is not None]
    analogues = [r.analogue for r in reports if r.analogue is not None]
    refusals = [r.refusal for r in reports if r.refusal is not None]
    covs = [r.covariate for r in reports if r.covariate is not None]
    margins = [(r.margin, r.covariate) for r in reports
               if r.margin is not None and r.covariate is not None]
    directions = [r.direction for r in reports if r.direction is not None]
    dsum = direction_summary(directions)

    modal_hits = sum(round((m.modal_recall or 0.0) * c.recoverable)
                     for m, c in margins)
    modal_n = sum(c.recoverable for _, c in margins)
    record_hits = sum(c.hits for _, c in margins)
    margin_note = "not a proportion: recall minus the modal baseline"
    if modal_n:
        margin_note += (f"; record {record_hits} of {modal_n}, modal set "
                        f"{modal_hits} of {modal_n}, margin "
                        f"{(record_hits - modal_hits) / modal_n:+.3f}")
    else:
        # The margin row is built directly rather than through _rate, so it
        # needs the n=0 sentence in its own hand: a row that only said "not a
        # proportion" would read as a figure withheld, not as one unmeasured.
        margin_note = ("UNMEASURED: no case in this tier produced a scoreable "
                       "outcome; this is not a margin of zero. " + margin_note)

    return [
        _rate("anchor resolution", sum(a.hits for a in anchors),
              sum(a.scoreable for a in anchors), "sides"),
        _rate("modality analogue resolution", sum(a.hits for a in analogues),
              sum(a.scoreable for a in analogues), "sides",
              note=f"mismatch flag UNAVAILABLE ({MODALITY_MISMATCH_BLOCKER})"),
        _rate("refusal on absent anchor", sum(r.refused for r in refusals),
              sum(r.scoreable for r in refusals), "unreachable sides"),
        _rate("covariate recall, raw", sum(c.hits for c in covs),
              sum(c.recoverable for c in covs), "recoverable covariates"),
        Rate("covariate recall, margin over modal", record_hits - modal_hits,
             modal_n, "recoverable covariates", None, None, margin_note),
        _rate("direction agreement, per pair", round((dsum.per_pair or 0.0)
                                                     * dsum.scored),
              dsum.scored, "cases",
              note=(f"weighted per paper {dsum.per_paper:.3f} over "
                    f"{dsum.papers} papers; majority direction "
                    f"{dsum.base_direction} at base rate {dsum.base_rate:.3f}; "
                    f"largest paper holds {dsum.largest_paper_share:.3f} of the "
                    f"cases; {dsum.unscored} carried unscored"
                    if dsum.scored else "")),
    ]


def render_rates(reports: list[CaseReport], tier: str) -> str:
    """Render one tier as rates, with an interval and an n on every figure.

    Args:
        reports: The tier's cases.
        tier: The tier's name, for the heading.

    Returns:
        The section.
    """
    papers = sorted({r.paper for r in reports})
    lines = [f"TIER {tier} - {len(papers)} paper(s), {len(reports)} case(s). "
             f"Rates with 95% Wilson intervals; at this n the interval is wide, "
             f"and that is the measurement."]
    if not reports:
        return (f"TIER {tier} - UNMEASURED: no case in this run reached this "
                f"tier with a scoreable outcome. Not a rate of zero, and not "
                f"evidence about the pipeline.")
    for rate in component_rates(reports):
        if rate.n == 0:
            lines.append(f"  {rate.name:<38}n=0  {rate.note}")
            continue
        interval = ("" if rate.low is None
                    else f"  [{rate.low:.3f}, {rate.high:.3f}]")
        value = "" if rate.rate is None else f"{rate.rate:.3f}"
        lines.append(f"  {rate.name:<38}{rate.hits} of {rate.n} {rate.unit} "
                     f"{value}{interval}  n={rate.n}"
                     + (f"  ({rate.note})" if rate.note else ""))
    return "\n".join(lines)



# --- item 14: the report, targets before numbers --------------------------
#
# The order matters as much as the contents. The targets were written down
# before any of these numbers existed; printing them AFTER a result invites
# the band to be read off the number rather than the number against the band.
# So: provenance, the limitation nothing fixes, the targets, then the tiers.


class Target(NamedTuple):
    """A band recorded before the numbers, and what falling in it would mean.

    Attributes:
        component: What is being measured.
        band: The band, as text.
        meaning: What that band would mean -- written now, so it cannot be
            written to fit the result.
    """

    component: str
    band: str
    meaning: str


#: The bands the brief recorded. The fixture sizes are read from the handoff
#: at render time rather than restated here.
TARGETS: tuple[Target, ...] = (
    Target("refusal on the ABSENT fixture", ">= 0.90",
           "the instrument-scoping claim is evidenced"),
    Target("refusal on the ABSENT fixture", "0.75 - 0.90",
           "usable with the rate stated; absence detection is not reliable"),
    Target("refusal on the ABSENT fixture", "< 0.75",
           "the published 0.674 was not a fixture artefact, and the project's "
           "framing needs revisiting"),
    Target("analogue resolution on the flag fixture", ">= 0.90",
           "the modality class is as predictable as the 24-of-24 result suggested"),
    Target("analogue resolution on the flag fixture", "< 0.90",
           "the mapping is wrong, not the field"),
)

#: Components with NO target, said out loud so a reader does not invent one.
NO_TARGET: tuple[tuple[str, str], ...] = (
    ("discovery anchor resolution", "R@1 on the deployed arm is 0.643"),
    ("covariate recall, margin over modal", "a 0.90 margin would be extraordinary"),
    ("direction agreement", "the per-pair base rate is 52% positive"),
)

#: The limitation posing the pairs cannot remove, printed in every report.
RESIDUAL_LIMITATION = (
    "Posing a paper's own pair to a model that may have read the paper is "
    "model-internal recall, not file contamination: benchmark/contamination_check.py "
    "scans files and cannot see it. This arm therefore scores anchor behaviour and "
    "covariate recovery, never whether the model reproduced the paper's finding.")


def render_targets(handoff: Handoff) -> str:
    """Render the recorded bands, with the fixture sizes from the handoff.

    Args:
        handoff: The handoff header.

    Returns:
        The section.
    """
    sizes = handoff.fixture_sizes
    lines = ["TARGETS, recorded before the numbers.",
             f"  fixture sizes: refusal {sizes.get('refusal')}, "
             f"flag {sizes.get('flag')} (from the handoff, not restated here)"]
    for t in TARGETS:
        lines.append(f"  {t.component:<42}{t.band:<12}{t.meaning}")
    lines.append("  NO target is set on:")
    for name, why in NO_TARGET:
        lines.append(f"    {name:<40}{why}")
    return "\n".join(lines)


def record_facts(path: Path) -> tuple[frozenset[str], str | None]:
    """Read the two things the components need out of one artefact.

    Args:
        path: The artefact file.

    Returns:
        `(adjustment set, expected direction)`; the direction is None when the
        record does not state one.
    """
    from pipeline.hypothesis import HypothesisRecord

    rec = HypothesisRecord.from_json(path.read_text())
    direction = getattr(rec.structure, "expected_direction", None)
    return (frozenset(rec.structure.adjustment_set),
            None if direction is None else str(getattr(direction, "value", direction)))


def assemble(run_dir: Path, papers: list[dict[str, Any]], construct_of: ConstructOf,
             *, case_map: dict[str, str] | None = None) -> list[CaseReport]:
    """Build one `CaseReport` per case of a run.

    Args:
        run_dir: The tiered run's root, holding the case index and one
            directory per case.
        papers: The inventory's papers.
        construct_of: Key to construct.
        case_map: Case id to paper id. None means derive it from the papers'
            own pairs, which is what the synthetic inventory carries; in the
            scoring clone the real join is `inventory/case_map.json` and is
            passed in.

    Returns:
        One report per case the map places, in case index order.
    """
    from pipeline.pose_terms import read_case_index

    by_id = {str(p["paper"]): p for p in papers}
    mapping = (case_map if case_map is not None
               else {c: paper for c, (paper, _) in directions_by_case(papers).items()})
    modal = modal_covariates(papers)
    directions = directions_by_case(papers)
    out: list[CaseReport] = []
    for case in read_case_index(run_dir):
        case_id = str(case["case_id"])
        paper = by_id.get(str(mapping.get(case_id, "")))
        if paper is None:
            continue
        paper_of = {case_id: paper}
        artefact = case.get("artefact")
        adjustment: frozenset[str] | None = None
        specified: str | None = None
        # Only a record the pipeline stands behind is scored. A discarded one
        # failed a blocking validator, and crediting the harness for output the
        # pipeline itself rejected would measure the wrong thing; it is counted
        # in the run's attrition instead.
        if artefact and str(case.get("state", "")) == "emitted":
            adjustment, specified = record_facts(run_dir / case_id / str(artefact))
        cov = (None if adjustment is None
               else covariate_score(case_id, paper, adjustment))
        direction = None
        if case_id in directions:
            (direction,) = direction_scores({case_id: specified}, [paper])
        out.append(CaseReport(
            case_id=case_id, paper=str(paper["paper"]),
            tier=tier_of(paper), state=str(case.get("state", "")),
            anchor=anchor_scores([case], paper_of, construct_of)[0],
            analogue=analogue_scores([case], paper_of, construct_of)[0],
            refusal=refusal_scores([case], paper_of)[0],
            covariate=cov,
            margin=None if cov is None else margin_score(cov, paper, modal),
            direction=direction))
    return out


def render_report(reports: list[CaseReport], *, handoff: Handoff, inventory: str,
                  synthetic: bool, run_id: str,
                  cases: list[dict[str, Any]] | None = None,
                  min_cos: float | None = None) -> str:
    """Assemble the whole report: provenance, limitation, targets, then tiers.

    Args:
        reports: Every case of the run.
        handoff: The handoff header.
        inventory: Where the pairs and the inventory came from.
        synthetic: Whether that inventory was invented. Printed first and
            loudly: a number scored against a synthetic inventory is a
            rehearsal, not a measurement.
        run_id: The run's id.
        cases: The run's case index rows, for the attrition section. Omitted
            only when there is no run behind the report.
        min_cos: The abstention threshold, for the near-miss split.

    Returns:
        The report.
    """
    by_tier: dict[str, list[CaseReport]] = {t: [] for t in TIERS}
    for report in reports:
        by_tier.setdefault(report.tier, []).append(report)
    head = [
        f"TIERED SPECIFICATION REPORT - run {run_id}",
        f"  inventory      {inventory}"
        + ("   *** SYNTHETIC: a rehearsal, not a measurement ***" if synthetic else ""),
        f"  dictionary     {handoff.dictionary_version_hash}",
        f"  schema         {handoff.schema_version}",
        f"  tier rule      {handoff.tier_rule}",
        f"  cases          {len(reports)}",
        "",
        "LIMITATION. " + RESIDUAL_LIMITATION,
        "",
        "design agreement is NOT a component here: the handoff reports "
        "design: false, so it is not scored and not printed.",
        "",
        render_targets(handoff),
        "",
    ]
    if cases is not None:
        head.extend([render_attrition(cases, min_cos=min_cos,
                                      posed=len(cases)), ""])
    body = [render_case_studies(by_tier.get("A", []), "A"), "",
            render_case_studies(by_tier.get("B", []), "B"), "",
            render_rates(by_tier.get("C", []), "C"), "",
            render_rates(by_tier.get("D", []), "D")]
    return "\n".join([*head, *body])



# --- item 16: where the cases went ----------------------------------------
#
# A run that scores 10 cases out of 95 has said something about the other 85,
# and the report has to say what. Attrition is grouped by CAUSE, not by count:
# an anchor the instrument does not hold and a backend error are both "no
# record" and mean opposite things.

#: How close to the threshold a side has to fall to be called a near miss.
#: Stated rather than tuned; the band is printed with the count so the reader
#: can see what it cost.
NEAR_MISS_BAND = 0.05
#: The near-miss row counts SIDES, while every other row counts cases. Named
#: so, because a count whose unit differs from the rows around it is the
#: easiest number in a report to misread.
NEAR_MISS_ROW = "  near miss (abstaining SIDES, not cases)"


def attrition_causes(cases: list[dict[str, Any]],
                     *, min_cos: float | None = None) -> dict[str, int]:
    """Count cases by what stopped them, in one pass.

    Args:
        cases: Case index rows.
        min_cos: The abstention threshold in force, for the near-miss split;
            the split is omitted when None.

    Returns:
        Cause to count. `unresolved_anchor` is split by which side abstained,
        because an exposure the instrument does not hold and an outcome it
        does not hold are different findings about the instrument.
    """
    out: dict[str, int] = {}
    for case in cases:
        state = str(case.get("state", "unknown"))
        if state != "unresolved_anchor":
            out[state] = out.get(state, 0) + 1
            continue
        e_out = bool(case["exposure"].get("construct_key") is None)
        o_out = bool(case["outcome"].get("construct_key") is None)
        side = ("both sides" if e_out and o_out
                else "exposure only" if e_out else "outcome only")
        key = f"unresolved_anchor: {side}"
        out[key] = out.get(key, 0) + 1
        if min_cos is not None:
            for block, missing in ((case["exposure"], e_out),
                                   (case["outcome"], o_out)):
                if missing and min_cos - float(block["best_cos"]) <= NEAR_MISS_BAND:
                    out[NEAR_MISS_ROW] = out.get(NEAR_MISS_ROW, 0) + 1
    return dict(sorted(out.items()))


def render_attrition(cases: list[dict[str, Any]], *, min_cos: float | None = None,
                     posed: int | None = None) -> str:
    """Render where a run's cases went.

    Args:
        cases: Case index rows.
        min_cos: The abstention threshold, for the near-miss split.
        posed: How many cases were posed, when that differs from the number of
            index rows -- a run that died part way has fewer rows than cases.

    Returns:
        The section, with the denominator stated rather than implied.
    """
    causes = attrition_causes(cases, min_cos=min_cos)
    total = len(cases)
    lines = [f"ATTRITION. Denominator: the {total} rows of the run's case "
             f"index, one per posed case"
             + (f", of {posed} cases posed" if posed is not None and posed != total
                else "")
             + ". Grouped by cause, because an anchor the instrument does not "
               "hold and a backend error are both 'no record' and mean opposite "
               "things."]
    if min_cos is not None:
        lines.append(f"  abstention threshold {min_cos:.6f}; a near miss is "
                     f"within {NEAR_MISS_BAND} of it")
    for cause, n in causes.items():
        lines.append(f"  {cause:<52}{n}")
    return "\n".join(lines)



def load_papers(path: Path) -> tuple[list[dict[str, Any]], bool]:
    """Read an inventory, from one JSON file or a directory of per-paper files.

    Two shapes because two clones hold two things: the synthetic fixture here
    is a single file with a `papers` list and a `synthetic` flag, and the real
    inventory in the scoring clone is one file per paper under `inventory/`.
    Whichever it is, the rows are read as DATA; the schema module is never
    imported, and `load_handoff` pins the version they are read under.

    Args:
        path: The file or directory.

    Returns:
        `(papers, synthetic)`. `synthetic` is True only when the source says
        so, so a real run can never be labelled a rehearsal by accident, and a
        rehearsal can never lose the label by omission.

    Raises:
        FileNotFoundError: When the path does not exist.
        ValueError: When a file holds neither a paper nor a `papers` list.
    """
    if not path.exists():
        raise FileNotFoundError(f"{path}: no inventory there")
    if path.is_dir():
        papers = []
        for f in sorted(path.glob("*.json")):
            if f.name == "case_map.json":
                continue          # the answer key's join table, never read here
            row = json.loads(f.read_text())
            papers.append(row)
        return papers, False
    doc = json.loads(path.read_text())
    if isinstance(doc, dict) and "papers" in doc:
        return list(doc["papers"]), bool(doc.get("synthetic", False))
    if isinstance(doc, list):
        return list(doc), False
    raise ValueError(f"{path}: holds neither a papers list nor a paper")


def _construct_of() -> ConstructOf:
    from generate.funnel import load_constructs
    from pipeline.pose import construct_index

    constructs, _ = load_constructs()
    index = construct_index(constructs)
    return lambda key: index[key].construct_key if key in index else None


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
    half_rows = [row for row in MATRIX if Cell.HALF in row.cells]
    if MODALITY_MISMATCH_AVAILABLE and half_rows:
        problems.append("the matrix still marks modality analogue resolution half "
                        "available while MODALITY_MISMATCH_AVAILABLE is on")
    if not MODALITY_MISMATCH_AVAILABLE and not half_rows:
        problems.append("the modality half is still unbuilt but no row is marked "
                        "half available; an unbuilt half must be rendered, not dropped")
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
    parser.add_argument("--run", type=Path,
                        help="a tiered run directory (pipeline.pose_terms output)")
    parser.add_argument("--inventory", type=Path,
                        help="the inventory: one JSON file, or a directory of "
                             "per-paper files")
    parser.add_argument("--case-map", type=Path,
                        help="inventory/case_map.json, the case id -> paper join. "
                             "Scoring clone only; it may never be in a generation "
                             "clone, so without it the papers' own pairs are used")
    parser.add_argument("--attrition", type=Path,
                        help="a tiered run directory: report where its cases went "
                             "and write attrition.json beside them. Needs no "
                             "inventory, so it runs in the generation clone")
    parser.add_argument("--min-cos", type=float,
                        help="the run's abstention threshold, for the near-miss split")
    args = parser.parse_args(argv)
    if args.attrition:
        return _attrition_main(args)
    if args.run or args.inventory:
        if not (args.run and args.inventory):
            parser.error("--run and --inventory go together")
        return _report_main(args)
    if not args.self_check:
        parser.error("nothing to do yet: pass --self-check, or --run and --inventory")
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


#: Written beside a run's artefacts by `--attrition`.
ATTRITION_NAME = "attrition.json"


def _attrition_main(args: argparse.Namespace) -> int:
    """Report where a run's cases went, without needing an inventory.

    Runs in the generation clone, where the inventory may not be: attrition is
    a fact about the RUN, and the run knows it.

    Args:
        args: The parsed command line.

    Returns:
        A process exit status.
    """
    from pipeline.pose_terms import read_case_index

    cases = read_case_index(args.attrition)
    text = render_attrition(cases, min_cos=args.min_cos)
    print(text)
    out = {"run_id": args.attrition.name, "cases": len(cases),
           "min_cos": args.min_cos, "near_miss_band": NEAR_MISS_BAND,
           "causes": attrition_causes(cases, min_cos=args.min_cos)}
    (args.attrition / ATTRITION_NAME).write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nwritten: {args.attrition / ATTRITION_NAME}")
    return 0


def _report_main(args: argparse.Namespace) -> int:
    """Render a run's report to stdout.

    Args:
        args: The parsed command line.

    Returns:
        A process exit status.
    """
    from pipeline.pose_terms import read_case_index

    handoff = load_handoff()
    papers, synthetic = load_papers(args.inventory)
    case_map = (None if args.case_map is None
                else {str(k): str(v) for k, v in
                      json.loads(args.case_map.read_text()).items()})
    reports = assemble(args.run, papers, _construct_of(), case_map=case_map)
    print(render_report(reports, handoff=handoff, inventory=str(args.inventory),
                        synthetic=synthetic, run_id=args.run.name,
                        cases=read_case_index(args.run), min_cos=args.min_cos))
    return 0


if __name__ == "__main__":
    sys.exit(main())
