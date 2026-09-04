"""The estimability gate: blocking by default, bypassed only with a marker.

No participant count of any kind exists in this project. `env/tools.py::
estimate_n` returns `n_source == "unknown"` for every set until the study team
supplies two exports, and it names them: per-item non-missing counts (single-
module sets) and module co-completion counts (cross-module sets). The funnel's
S3 screen tags cross-module pairs `unknown` on the same ground.

So today the gate passes zero pairs. That is the correct output, not a defect:
a hypothesis whose n cannot be computed is not estimable, and the pipeline
must say so rather than emit it quietly. `--allow-unestimable` lets pairs
through for the pre-metadata baseline (item 15), and every one of them carries
`estimability == "blocked_no_metadata"` with the exports it is blocked on. The
marker is what makes the baseline interpretable later: when the exports
arrive, the same score on gated hypotheses says what the gate bought.

Bypassing the gate without the marker is a hard stop in the brief; there is no
code path here that does it.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

from env.tools import estimate_n

#: The two study-team exports estimability rests on, by the names `estimate_n`
#: and the funnel's S3 screen use. Neither exists yet.
PER_ITEM_NON_MISSING = "per_item_non_missing_counts"
MODULE_CO_COMPLETION = "module_co_completion_counts"
MISSING_EXPORTS: tuple[str, str] = (PER_ITEM_NON_MISSING, MODULE_CO_COMPLETION)

ESTIMABLE = "estimable"
BLOCKED = "blocked_no_metadata"


@dataclass(frozen=True)
class Verdict:
    """What the gate decided for one pair.

    Attributes:
        pair_id: The funnel's `Candidate.pair_id`.
        estimability: `estimable` or `blocked_no_metadata`.
        blocked_on: The exports this pair waits for; empty when estimable.
        n_source: `estimate_n`'s `n_source` for the pair's member keys.
        passed: Whether the pair goes on to the specifier.
    """

    pair_id: str
    estimability: str
    blocked_on: tuple[str, ...]
    n_source: str
    passed: bool


@dataclass(frozen=True)
class GateResult:
    """Everything the gate did in one run.

    Attributes:
        allow_unestimable: Whether the bypass flag was set.
        verdicts: One per input pair, in order.
        missing_exports: The exports named across all blocked pairs.
    """

    allow_unestimable: bool
    verdicts: tuple[Verdict, ...]
    missing_exports: tuple[str, ...]

    @property
    def passed(self) -> tuple[Verdict, ...]:
        """The verdicts that passed."""
        return tuple(v for v in self.verdicts if v.passed)

    @property
    def blocked(self) -> tuple[Verdict, ...]:
        """The verdicts that did not."""
        return tuple(v for v in self.verdicts if not v.passed)


def blockers_for(keys: list[str]) -> tuple[str, tuple[str, ...]]:
    """Ask `estimate_n` what a set of keys is blocked on.

    Args:
        keys: The pair's member keys, both sides.

    Returns:
        `(n_source, blocked_on)`. Empty `blocked_on` only when n was computed.
        A cross-module set is blocked on both exports: `estimate_n` names the
        co-completion counts, and the per-item counts are missing for every
        set, as its own single-module branch records.
    """
    r = estimate_n(keys)
    source = str(r.get("n_source", "unknown"))
    if source == "computed_from_counts":
        return source, ()
    named = r.get("blocked_on")
    if named == MODULE_CO_COMPLETION:
        return source, MISSING_EXPORTS
    return source, (PER_ITEM_NON_MISSING,)


def gate(cands: list[Any], *, allow_unestimable: bool = False) -> GateResult:
    """Decide, for every live candidate, whether it may reach the specifier.

    Args:
        cands: Funnel candidates; only `state == "live"` ones are judged.
        allow_unestimable: Pass blocked pairs through, marked.

    Returns:
        The result. Without the flag, a blocked pair does not pass.
    """
    verdicts: list[Verdict] = []
    missing: list[str] = []
    for c in cands:
        if getattr(c, "state", "live") != "live":
            continue
        keys = list(c.exposure.member_keys) + list(c.outcome.member_keys)
        source, blocked_on = blockers_for(keys)
        estimable = not blocked_on
        for b in blocked_on:
            if b not in missing:
                missing.append(b)
        verdicts.append(Verdict(
            pair_id=c.pair_id,
            estimability=ESTIMABLE if estimable else BLOCKED,
            blocked_on=blocked_on, n_source=source,
            passed=estimable or allow_unestimable))
    return GateResult(allow_unestimable=allow_unestimable,
                      verdicts=tuple(verdicts),
                      missing_exports=tuple(sorted(missing)))


def main(argv: list[str] | None = None) -> int:
    """Gate the worked-example frame and report.

    Args:
        argv: Arguments; `sys.argv[1:]` when None.

    Returns:
        0 when the run is consistent: without the flag, zero pairs passed and
        both missing exports named; with it, every pair passed marked.
    """
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--allow-unestimable", action="store_true",
                    help="pass blocked pairs, each marked estimability="
                         "blocked_no_metadata")
    a = ap.parse_args(argv)
    from pipeline.auto_intake import worked_frame
    live, _ = worked_frame()
    res = gate(live, allow_unestimable=a.allow_unestimable)
    print(f"gate: live {len(res.verdicts)}, passed {len(res.passed)}, "
          f"blocked {len(res.blocked)}, allow_unestimable={res.allow_unestimable}")
    print(f"missing exports: {', '.join(res.missing_exports) or 'none'}")
    if res.passed:
        marks = sorted({v.estimability for v in res.passed})
        print(f"passed pairs carry estimability: {', '.join(marks)}")
    ok = set(res.missing_exports) == set(MISSING_EXPORTS)
    if a.allow_unestimable:
        ok &= len(res.passed) == len(res.verdicts)
        ok &= all(v.estimability == BLOCKED for v in res.passed)
    else:
        ok &= len(res.passed) == 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
