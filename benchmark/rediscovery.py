"""benchmark/rediscovery.py — the paper's recorded design beside the pipeline's.

T2 of the 2026-09-14 refocus: everything a worked n=1-3 rediscovery needs
EXCEPT the key rows. The rows are the operator's. No agent writes one, and this
module holds none: it reads the three places the project already keeps that
content and puts them beside a `ProtocolSpecification` the pipeline produced.

🛑 THIS IS NOT A SCORE, and nothing here may become one without C21 saying how.
`TASKS.md` C21 stages the rediscovery metric explicitly — a scorer, then a
CONFIRMED pair, then a correlation statistic with k and the pair count fixed
BEFORE the run. A side-by-side report is the thing you read before any of that
exists, and it deliberately emits no total, no percentage and no verdict on the
protocol. Every comparison that has no mechanical definition says so
(`REVIEW`), rather than being reduced to a match rate that would look like a
result.

WHERE A ROW GOES. `benchmark/design_key.py::DESIGN_KEY`, since C36 was
authorised on 2026-09-14. One row per paper, BOTH sides, typed anchors, and
that module is WITHHELD from every clone but the scoring one — which is the
whole point of C36. Before it, the exposure column lived in
`benchmark/scorability.py` in the clone where prompts, `agent/schema.py`
docstrings and `env/tools.py` are edited, and the first row would have made the
editing clone the clone holding the rediscovery answers. The FORM is the
operator's (`TASKS.md`, C12 and C36) and this module does not reopen it:

    DESIGN_KEY: tuple[DesignKeyRow, ...] = (
        DesignKeyRow(
            pmid="<pmid>",
            exposure=(Anchor("<design-line phrase>", "variable",
                             key="m3:Q16.1_1"),),
            outcome=(Anchor("<design-line phrase>", "not_in_instrument"),),
            provenance="<where in the paper, and its retrievability>",
            filled_by="<who>"),
    )

The row-level checks live in `benchmark/design_anchor.py::validate_design_key`,
with the anchor type; this module runs them and reports them. That is C12's
ACCEPT criterion generalised to both sides: every `variable` anchor resolves
live through `env/tools.py::resolve_variable` with `outcome == "unique"`, every
`derivation` anchor names a signed file, and an `area_measure` anchor carrying a
key is refused because no authority resolves one. Run it the moment a row
lands; a key that names a battery or a construct is rejected with the key
named, because a blocker that says only "a key did not resolve" leaves the
operator to find which.

BOTH SIDES ARE WITHHELD HERE, and that is a change. Before C36 the exposure
column was readable in this clone and the outcome column was not, so the
side-by-side was half-live. `benchmark.design_key` now lives in the scoring
clone only, so NEITHER side is readable here. That is reported as an INCOMPLETE
run (exit 2), never as a mismatch and never as a clean pass — the same
three-way status `benchmark/contamination_check.py` uses and for the same
reason (`AGENTS.md` §Verification Discipline).

PAPER CONTENT. This module composes a published paper's recorded design, so it
belongs under `benchmark/` with the bibliography and the keys, and
`contamination_check.py::check_holdout_not_reachable` names it. Nothing it
reads or prints may reach `curated/`, `env/`, an `agent/` docstring or a
prompt.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.schema import ProtocolSpecification  # noqa: E402
from benchmark import scorability as SC  # noqa: E402
from benchmark.cohort_papers import COHORT_PAPERS, CohortPaper  # noqa: E402
from benchmark.contamination_check import WITHHELD_MODULES  # noqa: E402
from benchmark.design_anchor import (  # noqa: E402
    DesignKeyRow,
    validate_design_key,
)
from benchmark.design_quality import ref_keys  # noqa: E402

#: The module holding the design-arrow key: one row per paper, both sides.
#: Withheld from every clone but the scoring one (C36).
DESIGN_KEY = "benchmark.design_key"

#: Exit statuses, in `benchmark/contamination_check.py`'s spelling so a reader
#: meets one convention rather than two. 2 is the normal state in every clone
#: but the scoring one and is not a pass.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_INCOMPLETE = 2

#: The states one field of the side-by-side can be in. Four, not two, and the
#: last two are what keep this a report rather than a score.
MATCH = "MATCH"
DIFFERS = "DIFFERS"
#: Both sides are present but no mechanical comparison is defined — a design
#: line's method token against a `model_spec.form`, or a paper's printed n
#: against an analytic n. A reader decides; this module does not guess.
REVIEW = "REVIEW"
#: One side has no recorded value in this clone. Never a miss: `AGENTS.md`
#: §Verification Discipline, "could not detect X" is never "X is absent".
UNAVAILABLE = "UNAVAILABLE"


def design_key_present() -> bool:
    """Whether the design-arrow answer key is importable in this clone.

    Named and not broad, in the shape `tests/withheld.py` uses: the module is
    checked against `WITHHELD_MODULES`, so an ordinary broken import can never
    be laundered into "the key is elsewhere".

    Returns:
        True when `benchmark.design_key` can be imported here.

    Raises:
        RuntimeError: If the design key stops being a withheld module, in which
            case this guard is excusing something it should not.
    """
    if DESIGN_KEY not in WITHHELD_MODULES:
        raise RuntimeError(
            f"{DESIGN_KEY} is no longer in WITHHELD_MODULES, so its "
            f"absence is a defect and not a holdout. Remove this guard.")
    return importlib.util.find_spec(DESIGN_KEY) is not None


# --------------------------------------------------------------------------- #
# the key rows, and what makes one usable
# --------------------------------------------------------------------------- #


def validate(rows: tuple[DesignKeyRow, ...] | None = None) -> list[str]:
    """C12's ACCEPT criterion, run over the design key.

    A THIN DELEGATION, on purpose. The checks used to live here as
    `validate_exposure_keys` over a `dict[str, tuple[str, ...]]`; C36 moved them
    to `benchmark/design_anchor.py::validate_design_key`, beside the type they
    check, so the anchor's `__post_init__` and the table's validator cannot
    drift apart and so both are testable in a clone without the rows. This
    module keeps the operator-facing entry point and the exit statuses.

    Args:
        rows: The table to check, defaulting to the live `DESIGN_KEY`.

    Returns:
        One complaint per problem, empty when every row is usable. Empty is
        also the answer for an empty table — nothing asserted is nothing wrong
        — so a caller that wants to know whether any row EXISTS must count the
        rows, not read this.

    Raises:
        ModuleNotFoundError: If `rows` is None in a clone without the key.
    """
    return validate_design_key(rows)


# --------------------------------------------------------------------------- #
# the recorded design, assembled from the three places it already lives
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RecordedDesign:
    """What this project records about one published paper's design.

    Assembled rather than stored, so this module adds no paper content the
    repository did not already hold.

    Attributes:
        pmid: PubMed identifier.
        design_line: `cohort_papers.py`'s one-line design, verbatim.
        reported_n: The paper's realised n as that file prints it.
        exposure_keys: Keys the design key's exposure anchors name, empty when
            the row is unfilled or its anchors carry none.
        outcome_keys: The same for the outcome side.
        design_key_readable: False when `benchmark.design_key` is withheld from
            this clone, so EITHER side being empty says nothing. One flag, not
            two, because since C36 both sides come from one table — before it
            the exposure side was readable here and the outcome side was not.
    """

    pmid: str
    design_line: str
    reported_n: str
    exposure_keys: tuple[str, ...]
    outcome_keys: tuple[str, ...]
    design_key_readable: bool


def paper(pmid: str) -> CohortPaper:
    """The bibliography row for a pmid.

    Args:
        pmid: PubMed identifier.

    Returns:
        The paper.

    Raises:
        KeyError: If the bibliography does not carry it.
    """
    for p in COHORT_PAPERS:
        if p.pmid == pmid:
            return p
    raise KeyError(f"{pmid} is not in benchmark/cohort_papers.py")


def recorded_design(pmid: str) -> RecordedDesign:
    """Everything the project records about one paper's design.

    Args:
        pmid: PubMed identifier.

    Returns:
        The assembled record. Both sides are empty AND flagged unreadable in a
        clone without the design key, which are two different facts and are
        carried separately.

    Raises:
        KeyError: Propagated from `paper`.
    """
    p = paper(pmid)
    readable = design_key_present()
    row = SC.design_key_row(pmid) if readable else None
    return RecordedDesign(
        pmid=pmid, design_line=p.design, reported_n=p.n,
        exposure_keys=_anchor_keys(row.exposure if row else ()),
        outcome_keys=_anchor_keys(row.outcome if row else ()),
        design_key_readable=readable)


def _anchor_keys(anchors: tuple[object, ...]) -> tuple[str, ...]:
    """The keys a side's anchors name, in the order they were recorded.

    An anchor may carry no key — `area_measure` names a delivery and
    `not_in_instrument` names nothing — and those are dropped rather than
    rendered as a blank, because the side-by-side compares KEY SETS and an
    empty string is not a key. The verdict that reads those kinds is
    `scorability.py::_side`, not this.

    Args:
        anchors: That side's anchors.

    Returns:
        The keys, deduplicated, in recorded order.
    """
    out: list[str] = []
    for anchor in anchors:
        key = getattr(anchor, "key", None)
        if key and key not in out:
            out.append(key)
    return tuple(out)


# --------------------------------------------------------------------------- #
# the side-by-side
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FieldComparison:
    """One field of the paper's design beside the pipeline's.

    Attributes:
        field: The field's name.
        recorded: What the project records for the paper, rendered.
        specified: What the protocol says, rendered.
        state: `MATCH`, `DIFFERS`, `REVIEW` or `UNAVAILABLE`.
        why: Why the state is what it is, for the two states a reader cannot
            infer from the two values alone.
    """

    field: str
    recorded: str
    specified: str
    state: str
    why: str = ""


def _keys(field: str, recorded: tuple[str, ...], specified: set[str],
          readable: bool, unreadable_why: str) -> FieldComparison:
    """Compare one key set, keeping "unfilled" apart from "unequal".

    Args:
        field: The field's name.
        recorded: The recorded keys.
        specified: The protocol's keys.
        readable: False when the recorded side could not be read at all.
        unreadable_why: What is missing, when it could not be.

    Returns:
        The comparison.
    """
    got = " ".join(sorted(specified)) or "-"
    if not readable:
        return FieldComparison(field, "-", got, UNAVAILABLE, unreadable_why)
    if not recorded:
        return FieldComparison(field, "-", got, UNAVAILABLE,
                               "no row for this paper yet")
    want = " ".join(sorted(recorded))
    return FieldComparison(field, want, got,
                           MATCH if set(recorded) == specified else DIFFERS)


def compare(recorded: RecordedDesign,
            p: ProtocolSpecification) -> list[FieldComparison]:
    """The paper's recorded design beside one protocol, field by field.

    The key sides are compared mechanically and everything else is handed to a
    reader. That is not a gap to be filled later by a string similarity: a
    design line's method token and a `model_spec.form` are written in different
    vocabularies by different authors for different purposes, and a match rate
    over them would be a number with no defensible denominator.

    Args:
        recorded: The paper's recorded design.
        p: A validated protocol for the same pair.

    Returns:
        One comparison per field, in reading order. No total, deliberately.
    """
    return [
        _keys("exposure_keys", recorded.exposure_keys, ref_keys(p.exposure),
              recorded.design_key_readable,
              f"{DESIGN_KEY} is withheld from this clone"),
        _keys("outcome_keys", recorded.outcome_keys, ref_keys(p.outcome),
              recorded.design_key_readable,
              f"{DESIGN_KEY} is withheld from this clone"),
        FieldComparison(
            "adjusted_covariate_keys", "-",
            " ".join(sorted({k for e in p.adjusted_covariates
                             for k in ref_keys(e.variable)})) or "-",
            UNAVAILABLE,
            "the design key records the arrow's two sides and no covariate "
            "column; a covariate anchor is not in C36's shape"),
        FieldComparison("model_form", recorded.design_line, p.model_spec.form,
                        REVIEW,
                        "a design line's method token and a model_spec.form "
                        "are not the same vocabulary"),
        FieldComparison(
            "analytic_n", recorded.reported_n,
            f"{p.estimability.analytic_n} ({p.estimability.n_source.value})",
            UNAVAILABLE if p.estimability.analytic_n is None else REVIEW,
            "the pipeline invents no n; estimate_n returns null until the "
            "study team's co-completion counts arrive"
            if p.estimability.analytic_n is None
            else "the paper's n is printed as the venue gave it"),
        FieldComparison("expected_direction", "-",
                        p.expected_direction.direction.value, UNAVAILABLE,
                        "the bibliography records no direction"),
    ]


def render(recorded: RecordedDesign,
           rows: Sequence[FieldComparison]) -> str:
    """The side-by-side as text.

    Args:
        recorded: The paper's recorded design.
        rows: The comparisons.

    Returns:
        The rendered report.
    """
    out = ["=" * 78,
           f"REDISCOVERY SIDE-BY-SIDE   pmid {recorded.pmid}   "
           f"NOT A SCORE (TASKS.md C21)",
           "=" * 78,
           f"  paper   {recorded.design_line}",
           f"  n       {recorded.reported_n}",
           "-" * 78]
    for r in rows:
        out.append(f"  {r.state:<12} {r.field}")
        out.append(f"               paper    {r.recorded}")
        out.append(f"               pipeline {r.specified}")
        if r.why:
            out.append(f"               ({r.why})")
    out.append("=" * 78)
    return "\n".join(out)


def scaffold_status() -> dict[str, object]:
    """How far the worked rediscovery has got, with nothing inferred.

    Returns:
        The number of design-key rows, the bibliography size, whether the
        design key is readable here, any validation complaints, and
        `status_counts` when it can be computed. `status_counts` is None — not
        a row of zeroes — in a clone that cannot read the key, and
        `design_key_rows` is None there for the same reason: zero rows and an
        unreadable table are different facts, and the old
        `len(SC.EXPOSURE_KEYS)` could not tell them apart because that column
        was always readable here.
    """
    readable = design_key_present()
    complaints = validate() if readable else []
    return {
        "design_key_rows": _row_count() if readable else None,
        "bibliography": len(COHORT_PAPERS),
        "design_key_readable": readable,
        "complaints": complaints,
        "status_counts": SC.status_counts() if readable else None,
    }


def _row_count() -> int:
    """How many rows the design key holds.

    Returns:
        The row count.

    Raises:
        ModuleNotFoundError: In every clone but the scoring one.
    """
    from benchmark.design_key import DESIGN_KEY as ROWS

    return len(ROWS)


def _main(argv: Sequence[str] | None = None) -> int:
    """Validate the key rows, or print one paper beside one protocol.

    Args:
        argv: Command line, or None to read `sys.argv`.

    Returns:
        `EXIT_OK` when everything asked for ran and was clean, `EXIT_FAILED` on
        a complaint, `EXIT_INCOMPLETE` when nothing failed but the outcome-side
        key could not be read here. A failure outranks an incomplete run.
    """
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--pmid", help="a paper in benchmark/cohort_papers.py")
    ap.add_argument("--record", type=Path,
                    help="a ProtocolSpecification JSON to compare against")
    args = ap.parse_args(argv)

    status = scaffold_status()
    complaints = status["complaints"]
    assert isinstance(complaints, list)

    if args.pmid is None:
        print(json.dumps(status, indent=1))
    else:
        rec = recorded_design(args.pmid)
        if args.record is None:
            ap.error("--pmid needs --record: a side-by-side needs both sides")
        p = ProtocolSpecification.model_validate_json(args.record.read_text())
        print(render(rec, compare(rec, p)))

    for line in complaints:
        print(f"  COMPLAINT  {line}")
    if complaints:
        return EXIT_FAILED
    if not status["design_key_readable"]:
        print(f"\n  {DESIGN_KEY} is withheld from this clone, so NEITHER side "
              f"ran.\n  Nothing visible failed and I could not see "
              f"everything. NOT a pass.")
        return EXIT_INCOMPLETE
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_main())
