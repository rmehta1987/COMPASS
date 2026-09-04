"""Auto intake: a funnel pair becomes two requests, and both are resolved.

The funnel (`generate/funnel.py`) enumerates exposure-outcome pairs over
dictionary constructs, so a pair already names its two construct keys. What
retrieval adds is the trace: every variable a hypothesis rests on carries the
`RetrievalRecord` that selected it, and for a funnel pair that record must land
on the construct the funnel started from. A pair whose request comes back on a
different construct, or abstains, is a pair the deployed retriever cannot see
the way the dictionary does; it is reported, not emitted.

The request's construct phrase is the dictionary construct's own stem, so the
record is instrument-sourced (`RequestSnapshot.source == "instrument"`): its
`construct_text` and `query` are withheld wording and must be redacted before
an artefact is committed to the public tree. The keys in it are not wording.

Measured 2026-09-04 on the worked-example frame (module 3 Q16.x exposures by
module 2 Q5.x outcomes, 6 x 64, 256 live pairs after S2): 6/6 exposure and
62/64 outcome constructs resolve to their own construct; 248/256 live pairs
resolve on both sides; the two misses (m2:Q5.15, m2:Q5.64) abstain on 21-word
grid-battery stems. `FRAME_BOTH_FLOOR` pins that as a floor: red only when it
worsens.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

from pipeline.retrieval_record import RetrievalRecord
from pipeline.retrieve import RetrieverLike, load_retriever, load_template, retrieve
from pipeline.strata import Strata

#: Live pairs of the worked-example frame that resolved on both sides,
#: 2026-09-04, frozen bundle. A floor, never a target.
FRAME_BOTH_FLOOR = 248
FRAME_LIVE = 256


@dataclass(frozen=True)
class PairResolution:
    """Both sides of a funnel pair, retrieved.

    Attributes:
        pair_id: The funnel's `Candidate.pair_id`.
        exposure: The exposure's record.
        outcome: The outcome's record.
        exposure_resolved: The hit's dictionary construct is the funnel's.
        outcome_resolved: Likewise for the outcome.
    """

    pair_id: str
    exposure: RetrievalRecord
    outcome: RetrievalRecord
    exposure_resolved: bool
    outcome_resolved: bool

    @property
    def both_resolved(self) -> bool:
        """True when the pair can be emitted with both variables traced.

        Returns:
            The conjunction.
        """
        return self.exposure_resolved and self.outcome_resolved


def requests_for(cand: Any, template: Any = None) -> tuple[Any, Any]:
    """Two `RetrievalRequest`s for a funnel candidate, exposure then outcome.

    Args:
        cand: A `generate.funnel.Candidate` (anything with `.exposure` and
            `.outcome` carrying `stem_text`).
        template: The shipped template module; loaded when None.

    Returns:
        `(exposure_request, outcome_request)`. No instances, no population:
        the funnel names constructs, not instances, and the contract is
        instances only.
    """
    tpl = template or load_template()
    return (tpl.RetrievalRequest(construct=cand.exposure.stem_text,
                                 role=tpl.VariableRole.EXPOSURE),
            tpl.RetrievalRequest(construct=cand.outcome.stem_text,
                                 role=tpl.VariableRole.OUTCOME))


def resolved_to(rec: RetrievalRecord, construct_key: str) -> bool:
    """Whether a record selected the given dictionary construct.

    Args:
        rec: The record.
        construct_key: The funnel construct's key.

    Returns:
        False on an abstention or a different construct.
    """
    return rec.hit is not None and rec.hit.dict_construct_key == construct_key


def resolve_pair(retriever: RetrieverLike, cand: Any, strata: Strata | None = None,
                 template: Any = None) -> PairResolution:
    """Retrieve both sides of a funnel candidate.

    Args:
        retriever: The loaded bundle.
        cand: The candidate.
        strata: Precomputed strata; built when None.
        template: The shipped template module; loaded when None.

    Returns:
        The resolution.
    """
    strata = strata or Strata.from_retriever(retriever)
    req_e, req_o = requests_for(cand, template)
    rec_e = retrieve(retriever, req_e, strata=strata, source="instrument")
    rec_o = retrieve(retriever, req_o, strata=strata, source="instrument")
    return PairResolution(
        pair_id=cand.pair_id, exposure=rec_e, outcome=rec_o,
        exposure_resolved=resolved_to(rec_e, cand.exposure.construct_key),
        outcome_resolved=resolved_to(rec_o, cand.outcome.construct_key))


def worked_frame() -> tuple[list[Any], dict[str, int]]:
    """The worked example's frame through the funnel: live candidates and counts.

    Module 3 Q16.x exposures by module 2 Q5.x outcomes, the same selection
    `generate/worked_example.py` and `generate/live_specifier.py` make inline.

    Returns:
        `(live_candidates, funnel_counts)`.
    """
    from generate.funnel import load_constructs, run
    C, _ = load_constructs()
    exposures = sorted([c for c in C.values()
                        if c.module == "3" and c.base_id.startswith("Q16.")],
                       key=lambda c: c.base_id)
    outcomes = sorted([c for c in C.values()
                       if c.module == "2" and c.base_id.startswith("Q5.")],
                      key=lambda c: c.base_id)
    cands, counts = run(exposures, outcomes)
    return [c for c in cands if c.state == "live"], counts


def main(argv: list[str] | None = None) -> int:
    """Command line.

    `--pair E O` resolves one stated pair and exits 0 only when both sides
    resolve. `--frame` resolves every live pair of the worked-example frame,
    prints the counts, and exits 0 only when both-resolved is at or above
    `FRAME_BOTH_FLOOR`.

    Args:
        argv: Arguments; `sys.argv[1:]` when None.

    Returns:
        Process exit code.
    """
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pair", nargs=2, metavar=("EXPOSURE_KEY", "OUTCOME_KEY"))
    ap.add_argument("--frame", action="store_true")
    a = ap.parse_args(argv)
    if not a.pair and not a.frame:
        ap.print_help()
        return 0
    from generate.funnel import Candidate, load_constructs
    retriever = load_retriever()
    strata = Strata.from_retriever(retriever)
    tpl = load_template()
    rc = 0
    if a.pair:
        C, _ = load_constructs()
        cand = Candidate(exposure=C[a.pair[0]], outcome=C[a.pair[1]])
        pr = resolve_pair(retriever, cand, strata, tpl)
        for side, rec, ok in (("exposure", pr.exposure, pr.exposure_resolved),
                              ("outcome", pr.outcome, pr.outcome_resolved)):
            print(f"  {'ok  ' if ok else 'MISS'} {side:8} -> {rec.nearest_key} "
                  f"margin {rec.margin:+.4f}")
        print(f"pair {pr.pair_id}: both resolved = {pr.both_resolved}")
        rc |= 0 if pr.both_resolved else 1
    if a.frame:
        live, counts = worked_frame()
        cache: dict[tuple[str, str], RetrievalRecord] = {}

        def rec_for(con: Any, role: Any) -> RetrievalRecord:
            k = (con.construct_key, role.value)
            if k not in cache:
                req = tpl.RetrievalRequest(construct=con.stem_text, role=role)
                cache[k] = retrieve(retriever, req, strata=strata, source="instrument")
            return cache[k]

        both = sum(1 for c in live
                   if resolved_to(rec_for(c.exposure, tpl.VariableRole.EXPOSURE),
                                  c.exposure.construct_key)
                   and resolved_to(rec_for(c.outcome, tpl.VariableRole.OUTCOME),
                                   c.outcome.construct_key))
        print(f"frame: live {len(live)} (enumerated {counts['enumerated']}), "
              f"both resolved {both}, floor {FRAME_BOTH_FLOOR}/{FRAME_LIVE}")
        rc |= 0 if (len(live) == FRAME_LIVE and both >= FRAME_BOTH_FLOOR) else 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
