"""Retrieval adapter: a `RetrievalRequest` in, a `RetrievalRecord` out.

The only place the pipeline touches the deployed retriever. The bundle under
`deploy/` is frozen and validated by `deploy/smoke_test.py`; this module calls
it through its public `search()` and records what came back. It never re-ranks,
never rewrites the query and never chooses a threshold of its own: the
abstention threshold is the manifest's unless the caller overrides it.

Contract, from the manifest: instances are caller-supplied and `population`
stays None. Nothing here reads a gold target's fields to build a request; that
is the fixture's stand-in for a specifier and lives in `src/`, not here.

`python -m pipeline.retrieve --reproduce` runs the 224 pre-registered positives
through `retrieve()` and compares rank-1 accuracy with the smoke test's pinned
expectation for the shipped arm, read from `deploy/smoke_test.py` rather than
restated here.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Protocol

from pipeline.retrieval_record import Hit, RequestSnapshot, RetrievalRecord
from pipeline.strata import Strata

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
PREREG = ROOT / "out" / "qx_preregistration.json"

#: How many hits to ask for so an exact tie at the top can be resolved. The
#: deployed target set holds exact duplicates (`stem_option_dup`, kept by
#: design), whose vectors are identical, so ties are real and common enough to
#: move R@1: five of the 224 pre-registered rows tie at rank 1. The acceptance
#: test resolves a tie with `argmax`, i.e. the lowest target id; `topk` does not
#: promise an order among equals. `retrieve()` applies the acceptance rule so
#: the two paths select the same target. Measured 2026-09-04: without it the
#: adapter scored 141/224 against the pinned 144/224.
TIE_K = 8


class RetrieverLike(Protocol):
    """What `retrieve()` needs from a retriever.

    `deploy/retriever.py` satisfies it. Declared here so this package is typed
    without mypy following the unannotated bundle.
    """

    min_cos: float
    manifest: dict[str, Any]
    targets: list[dict[str, Any]]

    def search(self, query: str, k: int = 10) -> list[dict[str, Any]]:
        """Top-k hits by cosine, regardless of confidence."""
        ...


def load_retriever(root: Path = DEPLOY, **kwargs: Any) -> RetrieverLike:
    """Load the deployed retriever from its bundle.

    Imported lazily: the bundle pulls in torch and transformers, which the
    record types and the tests that use a fake retriever do not need.

    Args:
        root: The bundle directory.
        **kwargs: Passed to `CompassRetriever` (`threads`, `verify_checksums`).

    Returns:
        The retriever.
    """
    mod = importlib.import_module("deploy.retriever")
    retriever: RetrieverLike = mod.CompassRetriever(root, **kwargs)
    return retriever


def load_template() -> Any:
    """The shipped query template module, loaded the way the retriever loads it.

    Returns:
        The module holding `RetrievalRequest` and `VariableRole`.
    """
    name = "compass_deploy_template"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, DEPLOY / "template.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {DEPLOY / 'template.py'}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def retrieve(retriever: RetrieverLike, req: Any,
             min_cos: float | None = None,
             strata: Strata | None = None,
             source: str = "user") -> RetrievalRecord:
    """Run one request through the deployed retriever and record the outcome.

    Args:
        retriever: The loaded bundle.
        req: A `RetrievalRequest`; its `to_query()` is what the encoder sees.
        min_cos: Abstention threshold; the manifest's when None.
        strata: Precomputed strata; built from the retriever when None. Pass
            one when calling in a loop, it classifies every target.
        source: `user` or `instrument`; see `RequestSnapshot.source`.

    Returns:
        The record, resolved or abstained. Never raises on a miss: an
        abstention is an outcome, not an error.
    """
    thr = retriever.min_cos if min_cos is None else min_cos
    query = req.to_query()
    top = retriever.search(query, k=TIE_K)
    best_cos = float(top[0]["cos"])
    # lowest target id among exact ties: the acceptance test's argmax rule
    best = min((h for h in top if float(h["cos"]) == best_cos),
               key=lambda h: int(h["target_id"]))
    abstained = best_cos < thr
    margin_12 = None if abstained else round(best_cos - float(top[1]["cos"]), 6)
    hit: Hit | None = None
    if not abstained:
        if strata is None:
            strata = Strata.from_retriever(retriever)
        tid = int(best["target_id"])
        stratum, unmeasured = strata.of(tid)
        row = retriever.targets[tid - 1]          # bundle guarantees row i == id i+1
        hit = Hit.from_hit(best, stratum=stratum, unmeasured_stratum=unmeasured,
                           dict_construct_key=row.get("dict_construct_key"))
    return RetrievalRecord(
        request=RequestSnapshot.from_request(req, source), query=query,
        dictionary_hash=str(retriever.manifest["dictionary_version_hash"]),
        min_cos=thr, best_cos=best_cos, margin=best_cos - thr,
        margin_12=margin_12, abstained=abstained,
        nearest_key=str(best["key"]), hit=hit)


def shipped_expectation() -> float:
    """The smoke test's pinned R@1 for the shipped arm, read, not restated.

    Returns:
        The expected rank-1 accuracy.
    """
    spec = importlib.util.spec_from_file_location("compass_smoke",
                                                  DEPLOY / "smoke_test.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {DEPLOY / 'smoke_test.py'}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return float(mod.EXPECTED["I"]["R@1"])


def reproduce(retriever: RetrieverLike, prereg: Path = PREREG) -> dict[str, Any]:
    """Score the pre-registered positives through `retrieve()`, arm I.

    Rank-1 by the smoke test's rule: correct when the nearest target is the one
    whose members include the gold key, whether or not it cleared the threshold.
    Abstentions are counted beside it, not folded into it.

    Args:
        retriever: The loaded bundle.
        prereg: The tracked pre-registration file (queries, instances, gold keys).

    Returns:
        `n`, `rank1`, `R@1` (3 dp, as the smoke test pins it), `abstained`.
    """
    tpl = load_template()
    rows = json.loads(prereg.read_text())["positives"]
    by_key = {m: t["target_id"] for t in retriever.targets for m in t["members"]}
    strata = Strata.from_targets(retriever.targets, [r["gold_key"] for r in rows])
    rank1 = abstained = 0
    for row in rows:
        req = tpl.RetrievalRequest(construct=row["query"], role=tpl.VariableRole.EXPOSURE,
                                   instances=tuple(row["instances"]))
        rec = retrieve(retriever, req, strata=strata)
        rank1 += by_key[rec.nearest_key] == by_key[row["gold_key"]]
        abstained += rec.abstained
    return {"n": len(rows), "rank1": rank1, "R@1": round(rank1 / len(rows), 3),
            "abstained": abstained}


def main(argv: list[str] | None = None) -> int:
    """Command line: `--reproduce` scores arm I and compares with the pin.

    Args:
        argv: Arguments; `sys.argv[1:]` when None.

    Returns:
        0 when R@1 equals the smoke test's expectation, 1 otherwise.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reproduce", action="store_true",
                    help="score the 224 positives through retrieve() and compare")
    a = ap.parse_args(argv)
    if not a.reproduce:
        ap.print_help()
        return 0
    got = reproduce(load_retriever())
    want = shipped_expectation()
    print(f"arm I through pipeline.retrieve: R@1 {got['R@1']} "
          f"({got['rank1']}/{got['n']}), abstained {got['abstained']}; "
          f"smoke_test pins {want}")
    return 0 if got["R@1"] == want else 1


if __name__ == "__main__":
    sys.exit(main())
