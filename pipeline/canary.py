"""Three canaries, run by check.sh on every iteration.

Each asserts the retriever's CURRENT behaviour on a request the pipeline will
meet, so a change anywhere in the request path is noticed the iteration it
happens rather than three commits later.

C1  a chronic-condition request resolves, in a stratum the benchmark measured.
C2  five constructs the instrument does not hold (ambient PM2.5, the area
    deprivation index, census tract, biospecimens, genetic ancestry) abstain.
C3  the individual-versus-area conflation: "what kind of neighborhood income
    level they live in", with the instance "median household income" a
    specifier would plausibly add, clears the threshold by 2.1e-3 and selects
    m1:Q5.4, yearly HOUSEHOLD income. A disparities hypothesis would build an
    area-SES mediator on that hit. This canary asserts the current behaviour so
    the conflation cannot become invisible; if a change makes the request
    abstain, that is an improvement: update the expectation and say so in
    PROGRESS.md. Pre-registered as negative n42; the manifest's knife-edge
    block records the same 0.731576.

`python -m pipeline.canary` loads the bundle and exits 1 on any failure.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

from pipeline.retrieval_record import RetrievalRecord
from pipeline.retrieve import RetrieverLike, load_retriever, load_template, retrieve
from pipeline.strata import Strata


@dataclass(frozen=True)
class Canary:
    """One request and what its record must say.

    Attributes:
        name: C1, C2a.., C3.
        construct: The request's construct phrase.
        instances: Caller-supplied instances, the shipped contract.
        abstained: Whether the record must abstain.
        key: The selected key when resolved, or None to leave it unasserted.
        stratum: The selected target's stratum, when resolved.
        unmeasured: Whether that stratum must be flagged unmeasured.
        margin_4dp: The margin over the threshold, rounded to 4 dp, or None.
    """

    name: str
    construct: str
    instances: tuple[str, ...] = ()
    abstained: bool = False
    key: str | None = None
    stratum: str | None = None
    unmeasured: bool | None = None
    margin_4dp: float | None = None


CANARIES: tuple[Canary, ...] = (
    Canary("C1", "age when first told they had diabetes", abstained=False,
           key="m2:Q5.7", stratum="chronic_condition", unmeasured=False),
    Canary("C2a", "ambient PM2.5 exposure at the residence", abstained=True),
    Canary("C2b", "area deprivation index of the census tract", abstained=True),
    Canary("C2c", "census tract of residence", abstained=True),
    Canary("C2d", "biospecimen collection", abstained=True),
    Canary("C2e", "genetic ancestry", abstained=True),
    Canary("C3", "what kind of neighborhood income level they live in",
           instances=("median household income",), abstained=False,
           key="m1:Q5.4", stratum="ses_employment", unmeasured=True,
           margin_4dp=0.0021),
)


def evaluate(canary: Canary, rec: RetrievalRecord) -> list[str]:
    """Compare a record with a canary's expectations.

    Args:
        canary: The expectations.
        rec: What the adapter returned.

    Returns:
        One line per violated expectation; empty when the canary holds.
    """
    bad: list[str] = []
    if rec.abstained != canary.abstained:
        bad.append(f"abstained={rec.abstained}, expected {canary.abstained} "
                   f"(best_cos {rec.best_cos:.6f}, margin {rec.margin:+.6f}, "
                   f"nearest {rec.nearest_key})")
    if rec.hit is not None:
        if canary.key is not None and rec.hit.key != canary.key:
            bad.append(f"key={rec.hit.key}, expected {canary.key}")
        if canary.stratum is not None and rec.hit.stratum != canary.stratum:
            bad.append(f"stratum={rec.hit.stratum}, expected {canary.stratum}")
        unm = rec.hit.unmeasured_stratum
        if canary.unmeasured is not None and unm != canary.unmeasured:
            bad.append(f"unmeasured_stratum={unm}, expected {canary.unmeasured}")
    if canary.margin_4dp is not None and round(rec.margin, 4) != canary.margin_4dp:
        bad.append(f"margin={rec.margin:+.6f}, expected {canary.margin_4dp:+.4f} at 4 dp")
    return bad


def run(retriever: RetrieverLike, canaries: tuple[Canary, ...] = CANARIES,
        template: Any = None) -> list[tuple[Canary, RetrievalRecord, list[str]]]:
    """Run every canary through the adapter.

    Args:
        retriever: The loaded bundle.
        canaries: The canaries to run.
        template: The shipped template module; loaded when None.

    Returns:
        `(canary, record, violations)` per canary, in order.
    """
    tpl = template or load_template()
    strata = Strata.from_retriever(retriever)
    out = []
    for c in canaries:
        req = tpl.RetrievalRequest(construct=c.construct, role=tpl.VariableRole.EXPOSURE,
                                   instances=c.instances)
        rec = retrieve(retriever, req, strata=strata)
        out.append((c, rec, evaluate(c, rec)))
    return out


def main() -> int:
    """Print one line per canary with its margin; exit 1 on any violation.

    Returns:
        Process exit code.
    """
    failed = 0
    for c, rec, bad in run(load_retriever()):
        state = "ABSTAIN" if rec.abstained else f"{rec.nearest_key}"
        print(f"  {'FAIL' if bad else 'ok  '} {c.name:3} {c.construct!r} -> {state} "
              f"margin {rec.margin:+.6f}" + (f"  {'; '.join(bad)}" if bad else ""))
        failed += bool(bad)
    print(f"canaries: {len(CANARIES) - failed}/{len(CANARIES)} hold")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
