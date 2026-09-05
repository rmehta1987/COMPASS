"""Harness mode 2: score posed-pair hypotheses against the paper inventory.

Discovery asks whether the funnel lands on a paper's pair unprompted
(`benchmark/baseline_score.py`). Specification asks the other question: given
the pair, does the pipeline adjust for what the paper adjusted for, under the
paper's design, in the paper's direction. The two are reported side by side
here and never pooled: they have different denominators and answer different
questions.

Same refusals, verdicts and all-or-nothing loading as mode 1, plus two of
its own: every record must carry `selection_mode=externally_posed` and
`screened_from=0`, the codebase's rule for a pair the model was handed, and
the run must carry the inventory provenance `pipeline.pose` writes, which is
printed first because a number scored against a synthetic inventory is a
rehearsal, not a measurement.

What is reported, with n on every figure:

* covariate recall and precision of the record's adjustment set against
  the paper's scorable covariates, per paper and pooled;
* the same for the modal covariate set alone, the conventional adjustment
  set most papers share, and the margin of the specifier over it, which is
  the result: raw recall is a ceiling effect;
* design agreement against the paper's design, with the majority base rate,
  or omitted when the inventory's designs are degenerate;
* direction agreement against the paper's reported direction, with the
  majority base rate; a `mixed` paper is not scored on direction;
* rows the inventory excluded (`found_by_search`, not confident, absent)
  and papers that are unreproducible because an anchor is absent, counted
  apart from failures;
* the ceiling: recall is over recoverable covariates only, so the share of
  each paper's covariates the instrument holds bounds what any hypothesis
  could recover;
* the discovery baseline's numbers beside, from its JSON, never pooled.

Keys are compared exactly, variable key to variable key, on both sides.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from benchmark.baseline_score import (
    HALTING,
    Loaded,
    Refused,
    keys_of,
    load_artefacts,
    run_verdicts,
)
from benchmark.paper_inventory import (
    DESIGN_TO_PIPELINE,
    Degeneracy,
    PaperInventory,
    degeneracy,
    modal_covariates,
)
from pipeline.generation_env import GenerationEnv
from pipeline.hypothesis import HypothesisRecord
from pipeline.pose import EXTERNALLY_POSED, read_provenance
from pipeline.retrieve import RetrieverLike


class PaperScore(BaseModel):
    """One record scored against one paper.

    Attributes:
        pmid: The paper.
        artefact: The record's file name.
        paper_covariates: Scorable covariates the paper adjusted for (n for
            recall).
        adjusted: Keys in the record's adjustment set (n for precision).
        hits: Their intersection.
        recall: `hits / paper_covariates`; None when the paper has none.
        precision: `hits / adjusted`; None when the record adjusted for none.
        modal_hits: Modal set intersected with the paper's covariates.
        modal_recall: The modal set's recall on this paper.
        modal_precision: The modal set's precision on this paper.
        margin_recall: `recall - modal_recall`; None when either is None.
        margin_precision: Likewise for precision.
        design_agree: Record design equals the paper's; None when omitted.
        direction_agree: Record direction equals the paper's; None for a
            `mixed` paper.
        excluded: The paper's excluded rows by reason.
        recoverable: Scorable covariates over all the paper's covariates.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    pmid: str
    artefact: str
    paper_covariates: int = Field(ge=0)
    adjusted: int = Field(ge=0)
    hits: int = Field(ge=0)
    recall: float | None
    precision: float | None
    modal_hits: int = Field(ge=0)
    modal_recall: float | None
    modal_precision: float | None
    margin_recall: float | None
    margin_precision: float | None
    design_agree: bool | None
    direction_agree: bool | None
    excluded: dict[str, int]
    recoverable: tuple[int, int]


class Pooled(BaseModel):
    """Micro-averaged over every scored (record, paper) row.

    Attributes:
        n: Rows pooled.
        hits: Sum of hits.
        paper_covariates: Sum of scorable paper covariates.
        adjusted: Sum of adjustment-set sizes.
        recall: `hits / paper_covariates`.
        precision: `hits / adjusted`.
        modal_hits: Sum of modal hits.
        modal_size_total: Modal set size times n, the modal set's adjusted
            total.
        modal_recall: `modal_hits / paper_covariates`.
        modal_precision: `modal_hits / modal_size_total`.
        margin_recall: `recall - modal_recall`.
        margin_precision: `precision - modal_precision`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    n: int = Field(ge=0)
    hits: int
    paper_covariates: int
    adjusted: int
    recall: float | None
    precision: float | None
    modal_hits: int
    modal_size_total: int
    modal_recall: float | None
    modal_precision: float | None
    margin_recall: float | None
    margin_precision: float | None


class Agreement(BaseModel):
    """One agreement metric with its base rate, or the reason it is omitted.

    Attributes:
        n: Rows scored.
        agree: Rows where the record agreed with the paper.
        rate: `agree / n`.
        majority: The inventory's majority value and its share, the base rate.
        majority_agreement: Share of the scored rows whose paper value is the
            majority value: what "always say the majority" would score.
        omitted: Why the metric is not reported, when it is not.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    n: int = Field(ge=0)
    agree: int = Field(ge=0)
    rate: float | None
    majority: tuple[str, float] | None
    majority_agreement: float | None
    omitted: str | None = None


class Specification(BaseModel):
    """The mode-2 report, whole.

    Attributes:
        provenance: What `pipeline.pose` recorded about the inventory.
        synthetic: Whether that inventory was invented.
        run_id: The run scored.
        tree_sha: The stamped sha every record carries.
        generation: The stamp.
        papers_in_inventory: Papers the inventory holds.
        papers_posable: Papers with both anchors scorable.
        papers_unreproducible: Papers with an anchor the instrument lacks.
        papers_without_record: Posable papers no record was emitted for.
        n: Rows scored.
        rows: Per (record, paper) scores.
        pooled: The micro-average.
        modal_set: The modal covariate keys, sorted.
        degeneracy: The inventory's design and direction distributions.
        design: Design agreement, or its omission.
        direction: Direction agreement.
        excluded_rows: Inventory rows excluded, by reason, over the inventory.
        recoverable: Scorable over all covariates, summed over scored papers.
        discovery: The discovery baseline's numbers, when given; never pooled.
        verdicts: Named check to its verdict.
        denominator: The posed run's `total_generated_this_run`.
        by_outcome: The posed run's rows per outcome.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    provenance: dict[str, Any]
    synthetic: bool
    run_id: str
    tree_sha: str
    generation: GenerationEnv
    papers_in_inventory: int
    papers_posable: int
    papers_unreproducible: int
    papers_without_record: int
    n: int
    rows: tuple[PaperScore, ...]
    pooled: Pooled
    modal_set: tuple[str, ...]
    degeneracy: Degeneracy
    design: Agreement
    direction: Agreement
    excluded_rows: dict[str, int]
    recoverable: tuple[int, int]
    discovery: dict[str, Any] | None
    verdicts: dict[str, str]
    denominator: int
    by_outcome: dict[str, int]


# ---------------------------------------------------------------- pieces


def _ratio(a: int, b: int) -> float | None:
    return None if b == 0 else a / b


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def posed_fields(rec: HypothesisRecord) -> tuple[str | None, int | None]:
    """The record's selection mode and screened-from, wherever the protocol keeps them.

    Args:
        rec: The record.

    Returns:
        `(selection_mode, screened_from)`, None for a missing field.
    """
    found: dict[str, Any] = {}

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("selection_mode", "screened_from") and k not in found:
                    found[k] = v
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(rec.artefact.protocol)
    return found.get("selection_mode"), found.get("screened_from")


def refuse_unless_posed(loaded: Sequence[Loaded]) -> None:
    """Refuse any record the funnel screened rather than a driver posed.

    Args:
        loaded: The accepted artefacts.

    Raises:
        Refused: On a record whose selection mode is not `externally_posed`
            or whose screened_from is not 0.
    """
    for path, rec in loaded:
        mode, screened = posed_fields(rec)
        if mode != EXTERNALLY_POSED or screened != 0:
            raise Refused(f"{path.name}: selection_mode={mode!r}, screened_from="
                          f"{screened!r}; only externally posed records with "
                          f"screened_from 0 are scored here")


def papers_for(rec: HypothesisRecord, inventory: Sequence[PaperInventory],
               ) -> list[PaperInventory]:
    """The papers whose scorable anchors the record's anchors hit.

    Args:
        rec: The record.
        inventory: The papers.

    Returns:
        Matching papers, in inventory order.
    """
    e = keys_of(rec.artefact.retrieval["exposure"])
    o = keys_of(rec.artefact.retrieval["outcome"])
    return [p for p in inventory
            if e & p.scorable_keys("exposure") and o & p.scorable_keys("outcome")]


def score_row(path: Path, rec: HypothesisRecord, paper: PaperInventory,
              modal: frozenset[str], design_omitted: bool) -> PaperScore:
    """Score one record against one paper.

    Args:
        path: The artefact file.
        rec: The record.
        paper: The paper.
        modal: The modal covariate set.
        design_omitted: Whether design agreement is being reported.

    Returns:
        The row.
    """
    adjusted = frozenset(rec.structure.adjustment_set)
    cov = paper.scorable_keys("covariate")
    hits = len(adjusted & cov)
    mhits = len(modal & cov)
    recall, precision = _ratio(hits, len(cov)), _ratio(hits, len(adjusted))
    mrecall, mprecision = _ratio(mhits, len(cov)), _ratio(mhits, len(modal))
    design: bool | None = None
    if not design_omitted:
        design = DESIGN_TO_PIPELINE.get(paper.design) == rec.structure.design
    direction: bool | None = None
    if paper.direction != "mixed":
        direction = rec.structure.expected_direction == paper.direction
    return PaperScore(
        pmid=paper.pmid, artefact=path.name, paper_covariates=len(cov),
        adjusted=len(adjusted), hits=hits, recall=recall, precision=precision,
        modal_hits=mhits, modal_recall=mrecall, modal_precision=mprecision,
        margin_recall=_diff(recall, mrecall),
        margin_precision=_diff(precision, mprecision),
        design_agree=design, direction_agree=direction, excluded=dict(paper.excluded()),
        recoverable=(len(cov), len(paper.covariates)))


def pool(rows: Sequence[PaperScore], modal_size: int) -> Pooled:
    """Micro-average the rows; see `Pooled`.

    Args:
        rows: The scored rows.
        modal_size: The modal set's size.

    Returns:
        The pooled figures.
    """
    hits = sum(r.hits for r in rows)
    cov = sum(r.paper_covariates for r in rows)
    adj = sum(r.adjusted for r in rows)
    mhits = sum(r.modal_hits for r in rows)
    mtotal = modal_size * len(rows)
    recall, precision = _ratio(hits, cov), _ratio(hits, adj)
    mrecall, mprecision = _ratio(mhits, cov), _ratio(mhits, mtotal)
    return Pooled(n=len(rows), hits=hits, paper_covariates=cov, adjusted=adj,
                  recall=recall, precision=precision, modal_hits=mhits,
                  modal_size_total=mtotal, modal_recall=mrecall,
                  modal_precision=mprecision, margin_recall=_diff(recall, mrecall),
                  margin_precision=_diff(precision, mprecision))


def agreement(rows: Sequence[PaperScore], inventory: Sequence[PaperInventory],
              field: str, deg: Degeneracy) -> Agreement:
    """Agreement on `design` or `direction` with its base rate.

    Args:
        rows: The scored rows.
        inventory: The papers, for the majority value.
        field: `design` or `direction`.
        deg: The degeneracy report.

    Returns:
        The agreement, omitted when design is degenerate.
    """
    if field == "design" and deg.design_degenerate:
        maj = deg.design_majority
        return Agreement(n=0, agree=0, rate=None, majority=maj, majority_agreement=None,
                         omitted=(f"every paper in the inventory is "
                                  f"{maj[0] if maj else '?'}; always saying so scores "
                                  f"1.00, so design agreement is not a metric"))
    scored = [r for r in rows if getattr(r, f"{field}_agree") is not None]
    majority = deg.design_majority if field == "design" else deg.direction_majority
    by_pmid = {p.pmid: getattr(p, field) for p in inventory}
    maj_agree = None
    if majority is not None and scored:
        maj_agree = sum(1 for r in scored if by_pmid[r.pmid] == majority[0]) / len(scored)
    agree = sum(1 for r in scored if getattr(r, f"{field}_agree"))
    return Agreement(n=len(scored), agree=agree, rate=_ratio(agree, len(scored)),
                     majority=majority, majority_agreement=maj_agree)


# ---------------------------------------------------------------- scoring


def score(paths: Sequence[Path], *, inventory: Sequence[PaperInventory],
          retriever: RetrieverLike, verdicts: dict[str, str],
          require_sha: str | None = None,
          discovery: dict[str, Any] | None = None) -> Specification:
    """Score one posed run against the inventory.

    Args:
        paths: The run's emitted artefacts.
        inventory: The paper inventory, from the key branch or a test.
        retriever: The deployed retriever, or a double; its manifest names
            the dictionary every record must carry.
        verdicts: From `run_verdicts`, or supplied by a test.
        require_sha: The sha being scored; every stamp must match it.
        discovery: The discovery baseline's JSON, to report beside.

    Returns:
        The report.

    Raises:
        Refused: On any mode-1 refusal, a halting verdict, a missing
            provenance, a record the funnel screened, or a record that hits
            no paper in the inventory.
    """
    halted = [k for k in HALTING if verdicts.get(k, "missing") != "ok"]
    if halted:
        raise Refused("halting verdict: " + ", ".join(
            f"{k}={verdicts.get(k, 'missing')}" for k in halted))
    if not paths:
        raise Refused("no artefact paths given")
    run_dir = Path(paths[0]).resolve().parent
    try:
        provenance = read_provenance(run_dir)
    except FileNotFoundError as e:
        raise Refused(str(e)) from e
    dictionary_hash = str(retriever.manifest["dictionary_version_hash"])
    loaded, summary = load_artefacts(paths, dictionary_hash=dictionary_hash,
                                     require_sha=require_sha)
    refuse_unless_posed(loaded)
    deg = degeneracy(inventory)
    modal = modal_covariates(inventory)
    rows: list[PaperScore] = []
    scored_pmids: set[str] = set()
    for path, rec in loaded:
        papers = papers_for(rec, inventory)
        if not papers:
            raise Refused(f"{path.name}: its anchors hit no paper in the inventory")
        for paper in papers:
            rows.append(score_row(path, rec, paper, modal, deg.design_degenerate))
            scored_pmids.add(paper.pmid)
    env = loaded[0].record.generation
    assert env is not None
    posable = [p for p in inventory if p.posable]
    excluded: dict[str, int] = {}
    for p in inventory:
        for k, v in p.excluded().items():
            excluded[k] = excluded.get(k, 0) + v
    return Specification(
        provenance=provenance, synthetic=bool(provenance.get("synthetic")),
        run_id=summary.run_id, tree_sha=env.tree_sha, generation=env,
        papers_in_inventory=len(inventory), papers_posable=len(posable),
        papers_unreproducible=sum(1 for p in inventory if not p.reproducible),
        papers_without_record=sum(1 for p in posable if p.pmid not in scored_pmids),
        n=len(rows), rows=tuple(rows), pooled=pool(rows, len(modal)),
        modal_set=tuple(sorted(modal)), degeneracy=deg,
        design=agreement(rows, inventory, "design", deg),
        direction=agreement(rows, inventory, "direction", deg),
        excluded_rows=excluded,
        recoverable=(sum(r.recoverable[0] for r in rows),
                     sum(r.recoverable[1] for r in rows)),
        discovery=discovery, verdicts=verdicts,
        denominator=summary.total_generated_this_run, by_outcome=summary.by_outcome)


# ---------------------------------------------------------------- report


def _f(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def _signed(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.3f}"


def render(s: Specification) -> str:
    """The report as `SPECIFICATION.md`.

    Args:
        s: The report.

    Returns:
        Markdown.
    """
    head = (f"**Inventory: {s.provenance.get('inventory', '?')}"
            + (" — SYNTHETIC. Nothing below is a measurement; it is the harness "
               "exercised end to end.**" if s.synthetic else ".**"))
    p = s.pooled
    lines = [
        f"# Specification {s.run_id}",
        "",
        head,
        "",
        "Specification and discovery are reported apart and never pooled: they "
        "answer different questions with different denominators.",
        "",
        f"n: {s.n} scored rows from {s.papers_posable} posable papers of "
        f"{s.papers_in_inventory} in the inventory; {s.papers_unreproducible} "
        f"unreproducible (an anchor the instrument lacks), "
        f"{s.papers_without_record} posable but no record emitted. At this n the "
        f"figures are directional.",
        "",
        "## Covariates (pooled, micro-averaged)",
        "",
        "| figure | specifier | modal set | margin | n |",
        "|---|---|---|---|---|",
        f"| recall | {_f(p.recall)} | {_f(p.modal_recall)} | "
        f"{_signed(p.margin_recall)} | {p.n} rows, {p.paper_covariates} covariates |",
        f"| precision | {_f(p.precision)} | {_f(p.modal_precision)} | "
        f"{_signed(p.margin_precision)} | {p.n} rows, {p.adjusted} adjusted |",
        "",
        f"modal set ({len(s.modal_set)} keys, majority share over papers with a "
        f"scorable covariate): {', '.join(s.modal_set) or '(none)'}",
        f"ceiling: recall is over recoverable covariates only, {s.recoverable[0]} of "
        f"{s.recoverable[1]} in the scored papers; the rest no hypothesis can recover.",
        "",
        "## Per paper",
        "",
        "| pmid | artefact | recall | precision | modal recall | modal precision | "
        "margin recall | margin precision | design | direction | n cov | n adj |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in s.rows:
        lines.append(
            f"| {r.pmid} | {r.artefact} | {_f(r.recall)} | {_f(r.precision)} | "
            f"{_f(r.modal_recall)} | {_f(r.modal_precision)} | "
            f"{_signed(r.margin_recall)} | "
            f"{_signed(r.margin_precision)} | "
            f"{'-' if r.design_agree is None else r.design_agree} | "
            f"{'-' if r.direction_agree is None else r.direction_agree} | "
            f"{r.paper_covariates} | {r.adjusted} |")
    lines += ["", "## Design and direction", ""]
    d = s.design
    if d.omitted:
        lines.append(f"- design agreement: OMITTED — {d.omitted}")
    else:
        lines.append(f"- design agreement: {_f(d.rate)} (n={d.n}); base rate: majority "
                     f"{d.majority[0] if d.majority else '?'} at "
                     f"{_f(d.majority[1] if d.majority else None)} of the inventory, "
                     f"always-majority scores {_f(d.majority_agreement)} on these rows")
    x = s.direction
    lines.append(f"- direction agreement: {_f(x.rate)} (n={x.n}; mixed papers not "
                 f"scored); base rate: majority {x.majority[0] if x.majority else '?'} "
                 f"at {_f(x.majority[1] if x.majority else None)} of the inventory, "
                 f"always-majority scores {_f(x.majority_agreement)} on these rows")
    lines.append(f"- inventory: designs {s.degeneracy.designs}, directions "
                 f"{s.degeneracy.directions}")
    lines += ["", "## Excluded and unreproducible", "",
              f"- inventory rows excluded from scoring: {s.excluded_rows or '{}'} "
              f"(found_by_search and not_confident never score; absent cannot)",
              f"- papers unreproducible (an anchor the instrument lacks): "
              f"{s.papers_unreproducible}, counted apart from failures",
              f"- posed run ledger: denominator {s.denominator}, by outcome "
              f"{s.by_outcome}"]
    lines += ["", "## Discovery, beside (never pooled)", ""]
    if s.discovery is None:
        lines.append("(no discovery baseline given)")
    else:
        dv = s.discovery
        c = dv.get("ceiling") or {}
        lines.append(f"- run {dv.get('run_id')}: matched {dv.get('matched')} / scored "
                     f"{dv.get('scored')}, rate {_f(dv.get('rate'))}, denominator "
                     f"{dv.get('denominator')}, ceiling max rate "
                     f"{_f(c.get('max_rate'))}")
    lines += ["", "## Verdicts", ""]
    lines += [f"- {k}: {v}" for k, v in s.verdicts.items()]
    lines += ["", f"tree: {s.tree_sha}   generation stamp: {s.generation.model_dump()}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Score a posed run and write `SPECIFICATION.md` beside it.

    Args:
        argv: Command line; `sys.argv[1:]` when None.

    Returns:
        0 when scored and written, 2 when refused or halted.
    """
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="+", type=Path, help="artefact files, one posed run")
    ap.add_argument("--sha", required=True, help="the sha being scored")
    ap.add_argument("--inventory", default="key",
                    help="'key' for benchmark.paper_inventory_key on scoring-key, or "
                         "'synthetic' for tests/fake_inventory.py")
    ap.add_argument("--discovery", type=Path, default=None,
                    help="the discovery baseline's BASELINE.json, reported beside")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    from pipeline.retrieve import load_retriever

    if a.inventory == "synthetic":
        from tests.fake_inventory import FAKE_INVENTORY
        inventory: Sequence[PaperInventory] = FAKE_INVENTORY
    else:
        from benchmark.paper_inventory import load_inventory
        inventory = load_inventory()
    discovery = json.loads(a.discovery.read_text()) if a.discovery else None
    retriever = load_retriever()
    verdicts = run_verdicts(a.paths)
    for k, v in verdicts.items():
        print(f"  {k}: {v}")
    try:
        s = score(a.paths, inventory=inventory, retriever=retriever, verdicts=verdicts,
                  require_sha=a.sha, discovery=discovery)
    except Refused as e:
        print(f"REFUSED: {e}")
        return 2
    out = a.out or Path(a.paths[0]).resolve().parent / "SPECIFICATION.md"
    out.write_text(render(s))
    out.with_suffix(".json").write_text(s.model_dump_json(indent=2) + "\n")
    print(f"{'SYNTHETIC ' if s.synthetic else ''}n={s.n} recall {_f(s.pooled.recall)} "
          f"(modal {_f(s.pooled.modal_recall)}, margin "
          f"{_signed(s.pooled.margin_recall)}) "
          f"precision {_f(s.pooled.precision)} (modal {_f(s.pooled.modal_precision)}, "
          f"margin {_signed(s.pooled.margin_precision)})")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
