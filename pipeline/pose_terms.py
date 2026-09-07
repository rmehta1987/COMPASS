"""The tiered arm's driver: a paper's pair goes in as TERMS, not as keys.

`pipeline/pose.py` poses a pair the inventory has already resolved to
instrument keys, so it measures what the pipeline does with a variable it was
handed. This driver poses the paper's own wording for the exposure and the
outcome and makes the pipeline find the variable itself, which is what the
tiered harness scores: whether the anchor resolves at all, whether it resolves
to the analogue where the instrument holds a different measurement, and
whether an absent anchor is refused rather than approximated.

Input is `posed_pairs.json`: 95 rows of exactly `case_id`, `exposure` and
`outcome`, published on the orphan branch `handoff-public`. The case id is
opaque; the map from it back to a paper is `inventory/case_map.json` and stays
on the key branch, so nothing this driver writes can be joined to a paper in
this clone. `read_cases` RAISES on a row carrying anything else -- a pmid, a
tier, a direction, a variable key -- rather than filtering it out: a file that
leaked the answer is an operator problem to fix at the source, and a driver
that quietly dropped the field would leave the leak in place.

One run directory per case, named by the case id. That is the whole of how a
case id reaches the artefacts: it never enters the prompt, the record schema
or a variable key, and two cases that resolve to the same construct pair stay
separate rather than colliding in one ledger. `pipeline.run.run` does the rest
unchanged, so the artefacts, ledger, validators and refusals are the pipeline's
own, and every record carries `screened_from=0` with
`selection_mode=externally_posed`: a posed pair was screened from nothing.

Reused rather than rebuilt: `pipeline.retrieve.retrieve` for retrieval,
`pipeline.run.run` for the run loop, ledger, validators and artefacts,
`pipeline.pose.write_provenance` for the inventory provenance, and
`generate.funnel` for constructs. New here: reading the case file, turning a
term into a construct, and the per-case index.

The residual limitation, which nothing in this file fixes: posing a paper's
pair to a model that may have read the paper is model-internal recall, and
`benchmark/contamination_check.py` scans files and cannot see it. That is why
this arm scores covariate recovery and anchor behaviour, never whether the
model reproduced the paper's finding.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple

from generate.funnel import Candidate, Construct, load_constructs
from pipeline.ledger import Ledger
from pipeline.pose import EXTERNALLY_POSED, write_provenance
from pipeline.retrieve import RetrieverLike, load_retriever, load_template, retrieve
from pipeline.run import ARTEFACTS, MODEL, default_resolver, run
from pipeline.strata import Strata

#: Exactly the fields a case row may carry. Anything else is a leak, not a
#: field to ignore: `pmid`, `tier` and `direction` are the answer.
CASE_FIELDS = ("case_id", "exposure", "outcome")
#: Written at the run root: one row per case, the join the scorer reads.
CASE_INDEX = "case_index.jsonl"
#: Anything shaped like an instrument variable key, and anything shaped like a
#: pmid. A term that carried either would be the inventory speaking, not the
#: paper's own wording.
KEY_SHAPE = re.compile(r"\bm[123]:Q\d")
PMID_SHAPE = re.compile(r"\b\d{8}\b")
#: The state of a case that never reached the model because an anchor did not
#: resolve. Not a failure of the run: for a tier D case it is the correct
#: answer, and the harness scores it as such.
UNRESOLVED_ANCHOR = "unresolved_anchor"


class LeakedField(ValueError):
    """A case row carried something the generation clone may not see.

    Raised rather than filtered. The brief's rule, and the reason for it: a
    driver that dropped the field would leave the file leaking for whatever
    reads it next.
    """


class Case(NamedTuple):
    """One posed case: an opaque id and the paper's two terms.

    Attributes:
        case_id: Opaque; joins to a paper only through `inventory/case_map.json`,
            which is on the key branch.
        exposure: The paper's own wording for the exposure.
        outcome: The paper's own wording for the outcome.
    """

    case_id: str
    exposure: str
    outcome: str


class SideResolution(NamedTuple):
    """What the retriever did with one side's term.

    Attributes:
        term: The term posed.
        abstained: True when nothing cleared the threshold.
        best_cos: The top cosine, recorded even below the threshold.
        nearest_key: The top-1 key regardless of the threshold, so a near miss
            is legible.
        construct_key: The dictionary construct selected, None on an
            abstention.
    """

    term: str
    abstained: bool
    best_cos: float
    nearest_key: str
    construct_key: str | None


class CaseOutcome(NamedTuple):
    """What became of one case.

    Attributes:
        case_id: The opaque id.
        exposure: The exposure side's resolution.
        outcome: The outcome side's resolution.
        state: The ledger's outcome for the case (`emitted`, `refused`,
            `discarded`, `gate_blocked`, `no_valid_record`, `backend_error`),
            or `unresolved_anchor` when no model call was made.
        artefact: The artefact filename under the case's directory, or None.
        note: The ledger's note, or why the anchor did not resolve.
    """

    case_id: str
    exposure: SideResolution
    outcome: SideResolution
    state: str
    artefact: str | None
    note: str

    def as_row(self) -> dict[str, Any]:
        """The index row for this case, keys and numbers only.

        Returns:
            A JSON-safe dict; no instrument wording, and no paper identity
            beyond the opaque case id.
        """
        return {"case_id": self.case_id, "state": self.state,
                "artefact": self.artefact, "note": self.note,
                "exposure": self.exposure._asdict(),
                "outcome": self.outcome._asdict()}


def read_cases(path: Path) -> list[Case]:
    """Read the posed cases, refusing a file that carries the answer.

    Args:
        path: `posed_pairs.json`.

    Returns:
        The cases in file order.

    Raises:
        LeakedField: On a row with a field outside `CASE_FIELDS`, or a term
            holding a variable key or a pmid.
        ValueError: When the file is not a list of objects.
    """
    rows = json.loads(path.read_text())
    if not isinstance(rows, list):
        raise ValueError(f"{path}: expected a list of case rows")
    cases: list[Case] = []
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{i}: expected an object")
        extra = sorted(set(row) - set(CASE_FIELDS))
        if extra:
            raise LeakedField(
                f"{path}:{i}: carries {extra}. posed_pairs.json is three fields; "
                f"a pmid, tier, direction or key is the answer key and must be "
                f"fixed at the source, not filtered here.")
        missing = [f for f in CASE_FIELDS if f not in row]
        if missing:
            raise ValueError(f"{path}:{i}: missing {missing}")
        for field in ("exposure", "outcome"):
            text = str(row[field])
            if KEY_SHAPE.search(text) or PMID_SHAPE.search(text):
                raise LeakedField(
                    f"{path}:{i}: {field} {text!r} holds a variable key or a pmid; "
                    f"the terms are the paper's wording, and resolving them is the "
                    f"thing being measured.")
        cases.append(Case(str(row["case_id"]), str(row["exposure"]),
                          str(row["outcome"])))
    return cases


def resolve_term(retriever: RetrieverLike, term: str, role: Any, *,
                 strata: Strata | None = None, template: Any = None,
                 min_cos: float | None = None) -> SideResolution:
    """Put one side's term through the deployed retriever.

    The request is caller-supplied text, so it is `source="user"`: the query is
    the paper's wording, not the instrument's, and nothing instrument-sourced
    is written by this call.

    Args:
        retriever: The loaded bundle.
        term: The paper's wording for this side.
        role: The template's `VariableRole` for this side.
        strata: Precomputed strata; built from the retriever when None.
        template: The shipped template module; loaded when None.
        min_cos: Threshold override; the manifest's when None.

    Returns:
        The side's resolution.
    """
    tpl = template or load_template()
    req = tpl.RetrievalRequest(construct=term, role=role)
    rec = retrieve(retriever, req, min_cos=min_cos, strata=strata, source="user")
    return SideResolution(term=term, abstained=rec.abstained,
                          best_cos=round(float(rec.best_cos), 6),
                          nearest_key=rec.nearest_key,
                          construct_key=rec.hit.dict_construct_key if rec.hit else None)


def candidate_for(case: Case, exposure: SideResolution, outcome: SideResolution,
                  constructs: dict[str, Construct]) -> Candidate | None:
    """Build the funnel candidate a resolved case stands for.

    Args:
        case: The case.
        exposure: Its exposure side's resolution.
        outcome: Its outcome side's resolution.
        constructs: The built dictionary's constructs.

    Returns:
        The candidate, or None when either side did not resolve to a construct
        the dictionary holds -- which is an outcome, not an error.
    """
    e, o = exposure.construct_key, outcome.construct_key
    if e is None or o is None or e not in constructs or o not in constructs:
        return None
    return Candidate(exposure=constructs[e], outcome=constructs[o],
                     tags={"posed_terms": True, "case_id": case.case_id})


def _unresolved(case: Case, e: SideResolution, o: SideResolution,
                constructs: dict[str, Construct]) -> CaseOutcome:
    why = []
    for side, res in (("exposure", e), ("outcome", o)):
        if res.abstained:
            why.append(f"{side} abstained at {res.best_cos} (nearest {res.nearest_key})")
        elif res.construct_key is None or res.construct_key not in constructs:
            why.append(f"{side} resolved to {res.construct_key!r}, "
                       f"not a construct in this build")
    return CaseOutcome(case.case_id, e, o, UNRESOLVED_ANCHOR, None, "; ".join(why))


def pose_cases(cases: list[Case], *, backend: Any, constructs: dict[str, Construct],
               version: str, run_dir: Path, retriever: RetrieverLike,
               inventory: str, synthetic: bool, strata: Strata | None = None,
               template: Any = None, resolver: Any = None, k: int = 5,
               workers: int = 1, allow_unestimable: bool = False,
               retry_pause: float = 30.0, min_cos: float | None = None,
               skip_recorded: bool = False, log: Any = print) -> list[CaseOutcome]:
    """Run every posed case through the pipeline, one run directory each.

    Args:
        cases: The posed cases.
        backend: The reasoning backend.
        constructs: The built dictionary's constructs.
        version: The dictionary version hash.
        run_dir: The run root; each case gets `run_dir/<case_id>`.
        retriever: The deployed retriever, or a test double.
        inventory: Where the pairs came from; written beside the artefacts.
        synthetic: Whether that inventory was invented.
        strata: Precomputed strata; built from the retriever when None.
        template: The shipped template module; loaded when None.
        resolver: Intake resolver; `pipeline.run.default_resolver` when None.
        k: Samples per case.
        workers: Samples in flight at once.
        allow_unestimable: Pass the gate with its marker.
        retry_pause: See `pipeline.run.run`.
        min_cos: Threshold override for the term retrieval.
        skip_recorded: Reuse a case whose directory already holds a ledger row
            instead of calling the model again. A run of b2-20260904's shape
            died at pair 16 of 48 on one backend error; without this a restart
            re-spends every completed case.
        log: Progress sink.

    Returns:
        One outcome per case, in input order.
    """
    tpl = template or load_template()
    strata = strata if strata is not None else Strata.from_retriever(retriever)
    resolve = resolver if resolver is not None else default_resolver(retriever, strata)
    write_provenance(run_dir, inventory, synthetic, len(cases))
    out: list[CaseOutcome] = []
    for n, case in enumerate(cases, 1):
        e = resolve_term(retriever, case.exposure, tpl.VariableRole.EXPOSURE,
                         strata=strata, template=tpl, min_cos=min_cos)
        o = resolve_term(retriever, case.outcome, tpl.VariableRole.OUTCOME,
                         strata=strata, template=tpl, min_cos=min_cos)
        cand = candidate_for(case, e, o, constructs)
        if cand is None:
            outcome = _unresolved(case, e, o, constructs)
            log(f"[{n}/{len(cases)}] {case.case_id}: {outcome.note}")
        else:
            case_dir = run_dir / case.case_id
            recorded = Ledger(case_dir).rows() if case_dir.exists() else []
            if skip_recorded and recorded:
                row = recorded[-1]
                outcome = CaseOutcome(case.case_id, e, o, row.outcome,
                                      getattr(row, "artefact", None) or None,
                                      getattr(row, "note", "") or "")
                log(f"[{n}/{len(cases)}] {case.case_id}: {outcome.state} (recorded)")
                out.append(outcome)
                write_case_index(run_dir, out)
                continue
            run([cand], backend=backend, resolver=resolve, constructs=constructs,
                version=version, screened_from=0, selection_mode=EXTERNALLY_POSED,
                run_dir=case_dir, k=k, workers=workers,
                allow_unestimable=allow_unestimable, retry_pause=retry_pause, log=log)
            rows = Ledger(case_dir).rows()
            last = rows[-1] if rows else None
            outcome = CaseOutcome(case.case_id, e, o,
                                  last.outcome if last else "no_ledger_row",
                                  getattr(last, "artefact", None) or None,
                                  getattr(last, "note", "") or "")
            log(f"[{n}/{len(cases)}] {case.case_id}: {outcome.state}")
        out.append(outcome)
        # Rewritten after every case, not once at the end: a run that dies
        # part way still leaves the scorer something to read, and says where
        # it stopped.
        write_case_index(run_dir, out)
    return out


def write_case_index(run_dir: Path, outcomes: list[CaseOutcome]) -> Path:
    """Write the per-case index the scorer joins on.

    Args:
        run_dir: The run root.
        outcomes: One per case.

    Returns:
        The file written.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / CASE_INDEX
    path.write_text("".join(json.dumps(o.as_row()) + "\n" for o in outcomes))
    return path


def read_case_index(run_dir: Path) -> list[dict[str, Any]]:
    """Read what `write_case_index` wrote.

    Args:
        run_dir: The run root.

    Returns:
        The rows, in file order.

    Raises:
        FileNotFoundError: When the run has no index; a tiered run without one
            cannot be scored, since the case id is the only join it has.
    """
    path = run_dir / CASE_INDEX
    if not path.exists():
        raise FileNotFoundError(f"{path}: no case index; not a tiered posed run")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def attrition(outcomes: list[CaseOutcome]) -> dict[str, int]:
    """Count cases by what became of them.

    Args:
        outcomes: One per case.

    Returns:
        State to count, so a run reports where its cases went rather than only
        how many records it produced.
    """
    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o.state] = counts.get(o.state, 0) + 1
    return dict(sorted(counts.items()))


def main(argv: list[str] | None = None) -> int:
    """Command line.

    Args:
        argv: Arguments; `sys.argv[1:]` when None.

    Returns:
        Process exit code.
    """
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_id")
    ap.add_argument("--cases", type=Path, default=Path("posed_pairs.json"))
    ap.add_argument("--limit", type=int, default=None,
                    help="pose only the first N cases; a cutoff, not a sample")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--allow-unestimable", action="store_true")
    ap.add_argument("--inventory", required=True,
                    help="where the cases came from, e.g. 'handoff-public <sha>'")
    ap.add_argument("--synthetic", action="store_true",
                    help="the inventory was invented; nothing scored is a measurement")
    ap.add_argument("--skip-recorded", action="store_true",
                    help="reuse cases whose ledger row already exists")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve the terms and write the index; call no model")
    a = ap.parse_args(argv)

    cases = read_cases(a.cases)[:a.limit]
    C, version = load_constructs()
    retriever = load_retriever()
    print(f"posed: {len(cases)} cases from {a.cases}"
          f"{' (SYNTHETIC)' if a.synthetic else ''}")
    run_dir = ARTEFACTS / a.run_id
    if a.dry_run:
        tpl = load_template()
        strata = Strata.from_retriever(retriever)
        outcomes = []
        for case in cases:
            e = resolve_term(retriever, case.exposure, tpl.VariableRole.EXPOSURE,
                             strata=strata, template=tpl)
            o = resolve_term(retriever, case.outcome, tpl.VariableRole.OUTCOME,
                             strata=strata, template=tpl)
            cand = candidate_for(case, e, o, C)
            outcomes.append(_unresolved(case, e, o, C) if cand is None
                            else CaseOutcome(case.case_id, e, o, "would_run", None, ""))
        write_case_index(run_dir, outcomes)
        print(f"dry run: {attrition(outcomes)} -> {run_dir / CASE_INDEX}")
        return 0

    from agent.cli_backend import ClaudeCliBackend

    backend: Any = ClaudeCliBackend(model=a.model, mode="benchmark")
    outcomes = pose_cases(cases, backend=backend, constructs=C, version=version,
                          run_dir=run_dir, retriever=retriever, inventory=a.inventory,
                          synthetic=a.synthetic, k=a.k, workers=a.workers,
                          allow_unestimable=a.allow_unestimable,
                          skip_recorded=a.skip_recorded)
    print(f"run {a.run_id}: {attrition(outcomes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
