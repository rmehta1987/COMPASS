"""The run driver: a frame of pairs becomes hypothesis artefacts and a ledger.

    frame (D1 = narrow)  ->  gate --allow-unestimable  ->  auto intake
        ->  ResolvedPair  ->  specify (PairLike)  ->  validators
        ->  HypothesisRecord, redacted  ->  artefacts/<run_id>/  +  ledger

Every pair that passes the gate gets exactly one ledger row, whatever became
of it: emitted, discarded by a blocking critique, refused by the environment,
or no valid record. Artefacts are written redacted, so the run directory can
be committed to the public tree; the generation stamp is added by `stamp_run`
after the push, since the stamp names the pushed sha.

The frame under D1 = narrow takes exposures from the medication and
reproductive-hormonal strata and outcomes from the chronic-condition stratum,
the strata the retrieval benchmark measured, through the funnel's S1-S4. A
seeded subset caps the run at a size that fits the wall clock; the ledger
records whatever size ran.

Nothing here chooses what the model does next: the frame is enumerated, the
gate is a pure function, and selection inside `specify` is `_rank`.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent.backends import Backend
from agent.specifier import Result, RunIdentity, specify
from generate.funnel import Candidate, Construct, load_constructs
from generate.funnel import run as funnel_run
from generate.live_specifier import run_identity
from pipeline import auto_intake, hypothesis, resolved_pair, validators
from pipeline.gate import gate
from pipeline.generation_env import GenerationEnv
from pipeline.ledger import Ledger, RunSummary
from pipeline.retrieve import load_retriever, load_template
from pipeline.strata import Strata

ROOT = Path(__file__).resolve().parent.parent
ARTEFACTS = ROOT / "artefacts"
MODEL = "claude-haiku-4-5"
NARROW_EXPOSURE_STRATA = ("medication", "reproductive_hormonal")
NARROW_OUTCOME_STRATA = ("chronic_condition",)

Resolver = Callable[[Candidate], auto_intake.PairResolution]


def constructs_by_stratum(constructs: dict[str, Construct], strata: Strata,
                          targets: list[dict[str, Any]]) -> dict[str, list[Construct]]:
    """Group dictionary constructs by the stratum of their deployed targets.

    Args:
        constructs: `load_constructs().constructs`.
        strata: Built from the deployed targets.
        targets: The deployed targets, for `dict_construct_key`.

    Returns:
        Stratum name to constructs, each list sorted by key. A construct whose
        targets fall in several strata takes the first target's.
    """
    seen: dict[str, str] = {}
    for t in targets:
        ck = str(t.get("dict_construct_key", t["construct_key"]))
        seen.setdefault(ck, strata.stratum_of[int(t["target_id"])])
    out: dict[str, list[Construct]] = {}
    for ck, s in seen.items():
        if ck in constructs:
            out.setdefault(s, []).append(constructs[ck])
    for lst in out.values():
        lst.sort(key=lambda c: c.construct_key)
    return out


def narrow_frame(constructs: dict[str, Construct], strata: Strata,
                 targets: list[dict[str, Any]]) -> tuple[list[Candidate], dict[str, int]]:
    """The D1 = narrow frame through the funnel.

    Args:
        constructs: The dictionary's constructs.
        strata: The deployed strata.
        targets: The deployed targets.

    Returns:
        `(live_candidates, funnel_counts)`.
    """
    by = constructs_by_stratum(constructs, strata, targets)
    exposures = [c for s in NARROW_EXPOSURE_STRATA for c in by.get(s, [])]
    outcomes = [c for s in NARROW_OUTCOME_STRATA for c in by.get(s, [])]
    cands, counts = funnel_run(exposures, outcomes)
    return [c for c in cands if c.state == "live"], counts


def subset(cands: list[Candidate], limit: int | None, seed: int) -> list[Candidate]:
    """A seeded, order-stable subset.

    Args:
        cands: The live candidates.
        limit: Keep at most this many; None keeps all.
        seed: The sampling seed.

    Returns:
        The chosen candidates in their original order.
    """
    if limit is None or limit >= len(cands):
        return list(cands)
    idx = sorted(random.Random(seed).sample(range(len(cands)), limit))
    return [cands[i] for i in idx]


def default_resolver(retriever: Any, strata: Strata) -> Resolver:
    """A resolver over the deployed bundle.

    Args:
        retriever: The loaded bundle.
        strata: Its strata.

    Returns:
        A callable mapping a candidate to its `PairResolution`.
    """
    tpl = load_template()
    return lambda cand: auto_intake.resolve_pair(retriever, cand, strata, tpl)


def _first_line(e: BaseException) -> str:
    return (str(e).splitlines() or ["?"])[0][:200]


def _specify_surviving_one_error(backend: Backend, pair: resolved_pair.ResolvedPair, *,
                                 k: int,
                                 workers: int, parked_dir: Path,
                                 identity: RunIdentity, retry_pause: float,
                                 log: Callable[[str], None]) -> tuple[Result, bool]:
    """Specify a pair; on the backend raising once, wait and try the pair again.

    The 48-pair run of 2026-09-04 died at pair 16 on a single `claude -p`
    exiting 1 with an empty stderr, one sample of five, and took the other four
    samples' work and the remaining 32 pairs with it. One retry after a pause
    covers a transient failure; a second failure is the caller's to record.

    Args:
        backend: The reasoning backend.
        pair: The resolved pair.
        k: Samples per pair.
        workers: Samples in flight at once.
        parked_dir: Where losing records go.
        identity: The run's identity fields.
        retry_pause: Seconds to wait before the retry.
        log: Progress sink.

    Returns:
        The result and whether it came from the retry.

    Raises:
        RuntimeError: When the backend failed on the retry as well.
    """
    try:
        return specify(backend, pair, k=k, mode="benchmark", workers=workers,
                       parked_dir=parked_dir, identity=identity), False
    except RuntimeError as e:
        log(f"  backend error, retrying the pair once after {retry_pause:g}s: "
            f"{_first_line(e)}")
        time.sleep(retry_pause)
        return specify(backend, pair, k=k, mode="benchmark", workers=workers,
                       parked_dir=parked_dir, identity=identity), True


def run(cands: list[Candidate], *, backend: Backend, resolver: Resolver,
        constructs: dict[str, Construct], version: str, screened_from: int,
        run_dir: Path, k: int = 5, workers: int = 1,
        allow_unestimable: bool = False, retry_pause: float = 30.0,
        log: Callable[[str], None] = print) -> RunSummary:
    """Take every candidate through the pipeline and write the run.

    Args:
        cands: Live funnel candidates.
        backend: The reasoning backend; its `name` is the model id.
        resolver: Candidate to `PairResolution`.
        constructs: The dictionary's constructs, for the resolved pair.
        version: The dictionary hash.
        screened_from: The funnel's enumerated count, the denominator the
            record carries.
        run_dir: Where artefacts and the ledger go.
        k: Samples per pair.
        workers: Samples in flight at once; see `agent.specifier.specify`.
        retry_pause: Seconds to wait before a pair's single retry after the
            backend raised; a second failure is a `backend_error` row.
        allow_unestimable: The gate's bypass; every passed pair is marked.
        log: Progress sink.

    Returns:
        The written summary.
    """
    ledger = Ledger(run_dir)
    result = gate(cands, allow_unestimable=allow_unestimable)
    by_id = {c.pair_id: c for c in cands}
    log(f"gate: {len(result.passed)} of {len(result.verdicts)} pass "
        f"(allow_unestimable={allow_unestimable}); missing exports "
        f"{', '.join(result.missing_exports) or 'none'}")
    for v in result.blocked:
        c = by_id[v.pair_id]
        ledger.append(pair_id=v.pair_id, exposure_key=c.exposure.construct_key,
                      outcome_key=c.outcome.construct_key, exposure_stratum="unknown",
                      outcome_stratum="unknown", estimability=v.estimability,
                      outcome="gate_blocked", note=", ".join(v.blocked_on))
    for n, v in enumerate(result.passed, 1):
        cand = by_id[v.pair_id]
        pr = resolver(cand)
        e_stratum = pr.exposure.hit.stratum if pr.exposure.hit else "unresolved"
        o_stratum = pr.outcome.hit.stratum if pr.outcome.hit else "unresolved"
        common = dict(pair_id=v.pair_id, exposure_key=cand.exposure.construct_key,
                      outcome_key=cand.outcome.construct_key,
                      exposure_stratum=e_stratum, outcome_stratum=o_stratum,
                      estimability=v.estimability)
        if not pr.both_resolved:
            ledger.append(**common, outcome="discarded",
                          note=f"auto_intake: exposure_resolved={pr.exposure_resolved}, "
                               f"outcome_resolved={pr.outcome_resolved}")
            log(f"[{n}/{len(result.passed)}] {v.pair_id}: unresolved, discarded")
            continue
        pair = resolved_pair.from_pair_resolution(pr, constructs, v.estimability)
        identity = run_identity(pair, version, screened_from, backend.name)
        try:
            res, retried = _specify_surviving_one_error(
                backend, pair, k=k, workers=workers, parked_dir=run_dir / "parked",
                identity=identity, retry_pause=retry_pause, log=log)
        except RuntimeError as e:
            # The backend's own failure (a non-zero `claude -p`, a reported
            # error); anything else is a bug and still stops the run.
            ledger.append(**common, outcome="backend_error", note=_first_line(e))
            log(f"[{n}/{len(result.passed)}] {v.pair_id}: backend error twice, recorded")
            continue
        retry_note = "retried once after a backend error; " if retried else ""
        if res.selected is None:
            if res.refusal is not None:
                ledger.append(**common, outcome="refused",
                              note=retry_note + str(getattr(res.refusal, "reason", "")))
                log(f"[{n}/{len(result.passed)}] {v.pair_id}: refused")
            else:
                ledger.append(**common, outcome="no_valid_record",
                              note=retry_note + res.reason)
                log(f"[{n}/{len(result.passed)}] {v.pair_id}: no valid record")
            continue
        rec = validators.apply(hypothesis.build(res.selected, pair), pair)
        red = rec.redacted()
        name = f"{res.selected.protocol_id}.{res.selected.record_hash()}.json"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / name).write_text(red.to_json() + "\n")
        blocked = validators.blocking(rec.critiques)
        ledger.append(**common, outcome="discarded" if blocked else "emitted",
                      protocol_id=res.selected.protocol_id,
                      record_hash=res.selected.record_hash(), artefact=name,
                      note=retry_note + (validators.rejected_note(rec.critiques)
                                         if blocked else ""))
        state = ("discarded by " + validators.rejected_note(rec.critiques) if blocked
                 else "emitted")
        log(f"[{n}/{len(result.passed)}] {v.pair_id}: {state} -> {name}")
    ledger.write_summary()
    return ledger.summary()


def stamp_run(run_dir: Path, env: GenerationEnv) -> int:
    """Attach the generation stamp to every artefact in a run directory.

    Args:
        run_dir: The run directory.
        env: The stamp, measured after the push.

    Returns:
        How many artefacts were stamped.

    Raises:
        RuntimeError: When the stamp is not clean for scoring.
    """
    if not env.clean_for_scoring:
        raise RuntimeError("refusing to stamp: the answer key was reachable")
    n = 0
    for f in sorted(run_dir.glob("*.json")):
        if f.name == "summary.json":
            continue
        rec = hypothesis.HypothesisRecord.from_json(f.read_text())
        f.write_text(rec.stamped(env).to_json() + "\n")
        n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    """Command line for phase 1.

    Args:
        argv: Arguments; `sys.argv[1:]` when None.

    Returns:
        Process exit code.
    """
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_id")
    ap.add_argument("--limit", type=int, default=None, help="seeded subset size")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--workers", type=int, default=5,
                    help="samples in flight at once; 1 runs them in series")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--allow-unestimable", action="store_true")
    ap.add_argument("--frame-only", action="store_true",
                    help="print the frame's size and exit")
    a = ap.parse_args(argv)
    from agent.cli_backend import ClaudeCliBackend

    C, version = load_constructs()
    retriever = load_retriever()
    strata = Strata.from_retriever(retriever)
    live, counts = narrow_frame(C, strata, retriever.targets)
    chosen = subset(live, a.limit, a.seed)
    print(f"frame: enumerated {counts['enumerated']}, live {len(live)}, "
          f"running {len(chosen)} (seed {a.seed})")
    if a.frame_only:
        return 0
    # ClaudeCliBackend is what generate/live_specifier.py runs the Specifier
    # on; it is not a structural `Backend` for mypy (the same gap that driver
    # carries), so it is typed loosely here rather than widening the Protocol.
    backend: Any = ClaudeCliBackend(model=a.model, mode="benchmark")
    summary = run(chosen, backend=backend, resolver=default_resolver(retriever, strata),
                  constructs=C, version=version, screened_from=counts["enumerated"],
                  run_dir=ARTEFACTS / a.run_id, k=a.k, workers=a.workers,
                  allow_unestimable=a.allow_unestimable)
    print(f"run {a.run_id}: total_generated_this_run {summary.total_generated_this_run} "
          f"{summary.by_outcome}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
