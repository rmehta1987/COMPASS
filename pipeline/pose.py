"""The posed-pair driver: a paper's pair goes in, the pipeline specifies it.

The funnel baseline asks whether the pipeline DISCOVERS a paper's pair; with
48 pairs drawn from 16,138 it cannot, by construction. This driver asks the
other question: given the pair, does the pipeline SPECIFY the study the way
the paper did, covariates, design and direction. The two must never share a
denominator: every record this driver produces carries `screened_from=0` and
`selection_mode=externally_posed`, the codebase's existing rule for a pair
the model was handed rather than one the funnel screened.

Input is a JSONL file of `{"exposure_key": ..., "outcome_key": ...}` rows,
instrument variable keys only; `benchmark.paper_inventory.posed_pairs`
writes them from the inventory on the key branch, with a `pmid` column the
driver ignores. The pair reaches the model exactly as a funnel pair would:
each key's construct is looked up in the built dictionary, both sides are
retrieved from the construct's own stem through the deployed retriever, the
pair passes the estimability gate with its marker, and `pipeline.run.run`
does the rest, so the artefacts, ledger and stamp are the same shape and the
same harness refusals apply. A pair whose construct the retriever cannot
resolve from its own stem is discarded at intake and recorded, which is
itself a finding about that variable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from generate.funnel import Candidate, Construct, load_constructs
from pipeline.ledger import RunSummary
from pipeline.retrieve import load_retriever
from pipeline.run import (
    ARTEFACTS,
    MODEL,
    default_resolver,
    run,
)
from pipeline.strata import Strata

EXTERNALLY_POSED = "externally_posed"
#: Written beside the artefacts: which inventory posed the pairs, and whether
#: it was synthetic. The harness refuses a run without it and prints it first.
PROVENANCE_NAME = "inventory_provenance.json"


def read_pairs(path: Path) -> list[tuple[str, str]]:
    """Read the posed pairs, keys only.

    Args:
        path: A JSONL file; each row has `exposure_key` and `outcome_key`.
            Any other field, the inventory's `pmid` included, is ignored.

    Returns:
        `(exposure_key, outcome_key)` per row, in file order, duplicates kept
        so the ledger shows every posed row.

    Raises:
        ValueError: On a row missing either key.
    """
    out: list[tuple[str, str]] = []
    for i, line in enumerate(path.read_text().splitlines()):
        if not line.strip():
            continue
        row = json.loads(line)
        try:
            out.append((str(row["exposure_key"]), str(row["outcome_key"])))
        except KeyError as e:
            raise ValueError(f"{path}:{i + 1}: missing {e}") from e
    return out


def construct_index(constructs: dict[str, Construct]) -> dict[str, Construct]:
    """Map every variable key, and every construct key, to its construct.

    Args:
        constructs: `load_constructs()` output, keyed by construct key.

    Returns:
        The index.
    """
    idx: dict[str, Construct] = {}
    for c in constructs.values():
        idx[c.construct_key] = c
        for k in c.member_keys:
            idx.setdefault(k, c)
    return idx


def candidates_for(pairs: list[tuple[str, str]],
                   constructs: dict[str, Construct]) -> list[Candidate]:
    """Build one funnel candidate per posed pair.

    Args:
        pairs: `(exposure_key, outcome_key)` rows.
        constructs: The built dictionary's constructs.

    Returns:
        Candidates in input order, `state="live"`, tagged `posed`.

    Raises:
        KeyError: When a key is in neither the variable nor the construct
            index; a posed key that the dictionary lacks is a key error, not
            a discard.
    """
    idx = construct_index(constructs)
    out: list[Candidate] = []
    for e, o in pairs:
        for k in (e, o):
            if k not in idx:
                raise KeyError(f"{k} is not a variable or construct in the dictionary")
        out.append(Candidate(exposure=idx[e], outcome=idx[o],
                             tags={"posed": True, "exposure_key": e, "outcome_key": o}))
    return out


def write_provenance(run_dir: Path, inventory: str, synthetic: bool,
                     pairs: int) -> Path:
    """Record which inventory posed the pairs, beside the artefacts.

    Args:
        run_dir: The run's directory; created if needed.
        inventory: Where the pairs came from, e.g. `scoring-key <sha>` or
            `tests/fake_inventory.py`.
        synthetic: True when the inventory was invented, so nothing scored
            against it is a measurement.
        pairs: How many pairs were posed.

    Returns:
        The file written.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / PROVENANCE_NAME
    out.write_text(json.dumps({"inventory": inventory, "synthetic": synthetic,
                               "pairs": pairs, "selection_mode": EXTERNALLY_POSED},
                              indent=2) + "\n")
    return out


def read_provenance(run_dir: Path) -> dict[str, Any]:
    """Read what `write_provenance` wrote.

    Args:
        run_dir: The run's directory.

    Returns:
        The provenance dict.

    Raises:
        FileNotFoundError: When the run carries none; a posed run without it
            cannot say what it was posed from.
    """
    path = run_dir / PROVENANCE_NAME
    if not path.exists():
        raise FileNotFoundError(f"{path}: no inventory provenance; not a posed run")
    return dict(json.loads(path.read_text()))


def pose(pairs: list[tuple[str, str]], *, backend: Any, constructs: dict[str, Construct],
         version: str, run_dir: Path, retriever: Any, inventory: str, synthetic: bool,
         strata: Strata | None = None, k: int = 5, workers: int = 1,
         allow_unestimable: bool = False, retry_pause: float = 30.0,
         log: Any = print) -> RunSummary:
    """Run posed pairs through the pipeline.

    Args:
        pairs: `(exposure_key, outcome_key)` rows.
        backend: The reasoning backend.
        inventory: Where the pairs came from; written beside the artefacts.
        synthetic: Whether that inventory was invented; written beside them.
        constructs: The built dictionary's constructs.
        version: The dictionary version hash.
        run_dir: Where artefacts and the ledger go.
        retriever: The deployed retriever, or a test double.
        strata: Precomputed strata; built from the retriever when None.
        k: Samples per pair.
        workers: Samples in flight at once.
        allow_unestimable: Pass the gate with its marker.
        retry_pause: See `pipeline.run.run`.
        log: Progress sink.

    Returns:
        The written summary.
    """
    strata = strata or Strata.from_retriever(retriever)
    cands = candidates_for(pairs, constructs)
    write_provenance(run_dir, inventory, synthetic, len(pairs))
    return run(cands, backend=backend, resolver=default_resolver(retriever, strata),
               constructs=constructs, version=version, screened_from=0,
               selection_mode=EXTERNALLY_POSED, run_dir=run_dir, k=k, workers=workers,
               allow_unestimable=allow_unestimable, retry_pause=retry_pause, log=log)


def main(argv: list[str] | None = None) -> int:
    """Command line.

    Args:
        argv: Arguments; `sys.argv[1:]` when None.

    Returns:
        Process exit code.
    """
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_id")
    ap.add_argument("--pairs", type=Path, required=True, help="JSONL of posed key pairs")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--allow-unestimable", action="store_true")
    ap.add_argument("--inventory", required=True,
                    help="where the pairs came from, e.g. 'scoring-key <sha>'")
    ap.add_argument("--synthetic", action="store_true",
                    help="the inventory was invented; nothing scored is a measurement")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve the pairs to constructs and exit")
    a = ap.parse_args(argv)
    from agent.cli_backend import ClaudeCliBackend

    pairs = read_pairs(a.pairs)
    C, version = load_constructs()
    cands = candidates_for(pairs, C)
    print(f"posed: {len(pairs)} pairs, {len({c.pair_id for c in cands})} distinct; "
          f"inventory {a.inventory!r}{' (SYNTHETIC)' if a.synthetic else ''}")
    if a.dry_run:
        for c in cands:
            print(f"  {c.pair_id}")
        return 0
    retriever = load_retriever()
    backend: Any = ClaudeCliBackend(model=a.model, mode="benchmark")
    summary = pose(pairs, backend=backend, constructs=C, version=version,
                   run_dir=ARTEFACTS / a.run_id, retriever=retriever,
                   inventory=a.inventory, synthetic=a.synthetic, k=a.k,
                   workers=a.workers, allow_unestimable=a.allow_unestimable)
    print(f"run {a.run_id}: total_generated_this_run {summary.total_generated_this_run} "
          f"{summary.by_outcome}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
