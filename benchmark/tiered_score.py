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
import sys
from enum import Enum
from typing import NamedTuple

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
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
