"""The pre-metadata baseline: score committed hypotheses against the papers, once.

Phase 2 of the loop's item 15. Runs in the scoring clone only, where the answer
key exists; the generation clone never runs it. It takes artefact PATHS and
nothing else: no run id to look up, no frame to regenerate, no model. What it
cannot read from the files it refuses to invent.

Refusals, all fatal (a skipped artefact would silently move the denominator):

* an artefact without a generation stamp, or whose stamp says the key or its
  ref was reachable, or whose tree was dirty when stamped;
* an artefact whose stamp names a sha other than the one being scored;
* an artefact that is not the redacted, committable form;
* an artefact whose records were retrieved under a dictionary other than the
  retriever's;
* a set of paths that is not exactly the ledger's emitted set, or that spans
  more than one run directory.

Match rule (`STATE.md` item 15b). A hypothesis matches a paper when BOTH hold:

* outcome: one of the paper's outcome-role instrument keys, as the held-out
  key records them (`benchmark/scorability.py::outcome_keys_on_record`), is
  the hypothesis's outcome variable, one of its target's folded members, or
  its construct;
* exposure: the paper's exposure terms, taken from the bibliography's design
  line (`benchmark/scorability.py::exposure_terms`), resolve through the
  deployed retriever to the same variable, member or construct as the
  hypothesis's exposure. `scorability.EXPOSURE_KEYS` is empty by design; the
  exposure side of the key has terms only, so the retriever is the resolver.

A paper with no outcome key on record, or whose exposure terms all abstain,
can match nothing; the report says how many papers that leaves.

Verdicts travel with the numbers: `benchmark.contamination_check --live` and
`benchmark.input_leakage` halt the run when red, `benchmark.unearned_assertions`
is advisory and reported. The key-side modules are imported inside functions,
so this module and its tests load where the key is unreachable.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from pipeline import ledger as L
from pipeline.generation_env import GenerationEnv
from pipeline.hypothesis import HypothesisRecord
from pipeline.intake import parse_request
from pipeline.retrieval_record import RetrievalRecord
from pipeline.retrieve import RetrieverLike, retrieve
from pipeline.strata import Strata

ROOT = Path(__file__).resolve().parent.parent

#: The question the number answers, verbatim from the brief; it travels with
#: the number permanently, since the number is meaningless without it.
QUALIFIER = ("does the pipeline land on associations the literature found, "
             "given only self-report variables and no estimability check")

HALTING = ("contamination_check", "input_leakage")


class PaperKey(NamedTuple):
    """What the scorer needs of one paper: its pmid, exposure terms, outcome keys.

    Attributes:
        pmid: PubMed identifier.
        exposure_terms: From the design line; empty for a descriptive paper.
        outcome_keys: Instrument keys the held-out key records as outcome;
            empty when it records none.
    """

    pmid: str
    exposure_terms: tuple[str, ...]
    outcome_keys: tuple[str, ...]


class Refused(ValueError):
    """An artefact set the harness will not score, with the reason."""


class Loaded(NamedTuple):
    """One accepted artefact.

    Attributes:
        path: Where it was read from.
        record: The parsed record.
    """

    path: Path
    record: HypothesisRecord


class Match(NamedTuple):
    """One hypothesis-paper match.

    Attributes:
        artefact: The artefact's file name.
        pmid: The paper.
        exposure_key: The shared exposure key.
        outcome_key: The shared outcome key.
    """

    artefact: str
    pmid: str
    exposure_key: str
    outcome_key: str


class Ceiling(BaseModel):
    """The most the match rule could have found, given the key and the frame.

    The rule is conjunctive, so the rate is bounded by a product: a paper must
    carry an outcome key on record AND an exposure term the retriever resolved
    before any artefact can match it, and an artefact must hit a matchable
    paper on both sides. `max_matched` counts artefacts that hit some
    matchable paper's outcome keys and some matchable paper's resolved
    exposure keys, not necessarily the same paper, so it is an upper bound on
    `matched`. A run at its ceiling says the harness works; it does not
    measure hypothesis quality, and the report says which.

    Attributes:
        papers_matchable: Papers with an outcome key on record and at least
            one exposure term resolved.
        outcome_side: Artefacts whose outcome keys hit a matchable paper.
        exposure_side: Artefacts whose exposure keys hit a matchable paper.
        max_matched: Artefacts hitting on both sides; `matched` cannot exceed it.
        max_rate: `max_matched / scored`; None when nothing was scored.
        at_ceiling: `matched == max_matched`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    papers_matchable: int = Field(ge=0)
    outcome_side: int = Field(ge=0)
    exposure_side: int = Field(ge=0)
    max_matched: int = Field(ge=0)
    max_rate: float | None
    at_ceiling: bool

    def sentence(self, matched: int, scored: int) -> str:
        """The reading a rate must travel with.

        Args:
            matched: N.
            scored: M.

        Returns:
            One paragraph.
        """
        head = (f"Ceiling: at most {self.max_matched} of {scored} artefacts could "
                f"match under this key and frame ({self.papers_matchable} matchable "
                f"papers); observed {matched}.")
        if self.max_matched == 0:
            return (head + " The observed rate IS the ceiling. What this run "
                    "establishes is that the harness runs end to end, refuses "
                    "unstamped artefacts and emits clean verdicts; it is not a "
                    "measurement of hypothesis quality.")
        if self.at_ceiling:
            return head + " The observed rate is at its ceiling."
        return head + " The gap below the ceiling is the pipeline's."


class Baseline(BaseModel):
    """The baseline, whole: the four numbers, their qualifier, and provenance.

    Attributes:
        qualifier: `QUALIFIER`.
        run_id: The run scored.
        tree_sha: The stamped sha every artefact carries.
        dictionary_hash: The dictionary every record was retrieved under.
        generation: The stamp, identical on every artefact.
        scored: M, artefacts accepted, equal to the ledger's emitted count.
        matched: N, artefacts matching at least one paper.
        rate: N / M; None when M is 0.
        denominator: The ledger's `total_generated_this_run`.
        by_outcome: The ledger's rows per outcome.
        strata: Every stratum an anchor fell in, from the ledger.
        papers: Papers in the table.
        papers_with_outcome_key: Papers the key records an outcome for.
        papers_exposure_resolved: Papers with at least one exposure term the
            retriever resolved.
        papers_matched: Distinct papers matched by any artefact.
        exposure_abstentions: Per pmid, the exposure terms that abstained.
        matches: Every match, in artefact order.
        verdicts: Named check to its verdict string.
        ceiling: The most the rule could have found; see `Ceiling`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    qualifier: str = QUALIFIER
    run_id: str
    tree_sha: str
    dictionary_hash: str
    generation: GenerationEnv
    scored: int = Field(ge=0)
    matched: int = Field(ge=0)
    rate: float | None
    denominator: int = Field(ge=0)
    by_outcome: dict[str, int]
    strata: tuple[str, ...]
    papers: int = Field(ge=0)
    papers_with_outcome_key: int = Field(ge=0)
    papers_exposure_resolved: int = Field(ge=0)
    papers_matched: int = Field(ge=0)
    exposure_abstentions: dict[str, tuple[str, ...]]
    matches: tuple[Match, ...]
    verdicts: dict[str, str]
    ceiling: Ceiling


# ---------------------------------------------------------------- loading


def _refuse_stamp(path: Path, rec: HypothesisRecord, require_sha: str | None) -> None:
    env = rec.generation
    if env is None:
        raise Refused(f"{path.name}: no generation stamp; stamp_run was not run")
    if not env.clean_for_scoring:
        raise Refused(f"{path.name}: the answer key was reachable at generation "
                      f"(key_present={env.key_present}, "
                      f"key_fetchable={env.key_fetchable})")
    if not env.tree_clean:
        raise Refused(f"{path.name}: stamped on a dirty tree")
    if require_sha is not None and not env.tree_sha.startswith(require_sha):
        raise Refused(f"{path.name}: stamped at {env.tree_sha[:12]}, scoring "
                      f"{require_sha[:12]}")
    if not rec.artefact.redacted:
        raise Refused(f"{path.name}: not the redacted form; the committed "
                      f"artefact is the only one scored")


def load_artefacts(paths: Sequence[Path], *, dictionary_hash: str,
                   require_sha: str | None = None) -> tuple[list[Loaded], L.RunSummary]:
    """Read, check and accept a run's artefacts, all or none.

    Args:
        paths: The artefact files; their parent is the run directory.
        dictionary_hash: The retriever's; every record must carry it.
        require_sha: When given, every stamp's `tree_sha` must start with it.

    Returns:
        The accepted artefacts in path order and the ledger's verified summary.

    Raises:
        Refused: On any of the module docstring's refusals.
    """
    if not paths:
        raise Refused("no artefact paths given")
    run_dirs = {Path(p).resolve().parent for p in paths}
    if len(run_dirs) != 1:
        raise Refused(f"paths span {len(run_dirs)} run directories; score one run")
    run_dir = run_dirs.pop()
    try:
        summary = L.verify(run_dir)
    except ValueError as e:
        raise Refused(f"ledger: {e}") from e
    emitted = {r.artefact for r in L.read_rows(run_dir / L.LEDGER_NAME)
               if r.outcome == "emitted" and r.artefact}
    given = {Path(p).name for p in paths}
    if given != emitted:
        raise Refused(f"paths are not the ledger's emitted set: "
                      f"{sorted(given - emitted)} not emitted, "
                      f"{sorted(emitted - given)} emitted but not given")
    out: list[Loaded] = []
    stamps: set[GenerationEnv] = set()
    for p in (Path(x) for x in paths):
        rec = HypothesisRecord.from_json(p.read_text())
        _refuse_stamp(p, rec, require_sha)
        assert rec.generation is not None
        stamps.add(rec.generation)
        for side, r in rec.artefact.retrieval.items():
            if r.dictionary_hash != dictionary_hash:
                raise Refused(f"{p.name}: {side} record retrieved under "
                              f"{r.dictionary_hash}, scoring {dictionary_hash}")
        out.append(Loaded(p, rec))
    if len(stamps) != 1:
        raise Refused(f"artefacts carry {len(stamps)} different stamps")
    return out, summary


# ---------------------------------------------------------------- the key


def load_key_table() -> tuple[PaperKey, ...]:
    """Build the paper table from the bibliography and the held-out key.

    Returns:
        One `PaperKey` per cohort paper.

    Raises:
        ImportError: Where the key is unreachable, which is every clone but
            the scoring one.
    """
    from benchmark.cohort_papers import COHORT_PAPERS
    from benchmark.scorability import exposure_terms, outcome_keys_on_record

    return tuple(PaperKey(p.pmid, exposure_terms(p), outcome_keys_on_record(p.pmid))
                 for p in COHORT_PAPERS)


def keys_of(rec: RetrievalRecord) -> frozenset[str]:
    """Every key a resolved record can be matched on.

    Args:
        rec: A record.

    Returns:
        The variable, its folded members and both construct names; empty for
        an abstention.
    """
    h = rec.hit
    if h is None:
        return frozenset()
    return frozenset({h.key, h.construct_key, h.dict_construct_key, *h.members})


def resolve_exposures(table: Iterable[PaperKey], retriever: RetrieverLike,
                      strata: Strata | None = None,
                      ) -> tuple[dict[str, frozenset[str]], dict[str, tuple[str, ...]]]:
    """Resolve every paper's exposure terms through the deployed retriever.

    Args:
        table: The papers.
        retriever: The loaded bundle, or a test double.
        strata: Precomputed; built from the retriever when None.

    Returns:
        Per pmid, the union of `keys_of` over its resolved terms; and per
        pmid, the terms that abstained (present only when any did).
    """
    if strata is None:
        strata = Strata.from_retriever(retriever)
    keys: dict[str, frozenset[str]] = {}
    abstained: dict[str, tuple[str, ...]] = {}
    for paper in table:
        found: set[str] = set()
        missed: list[str] = []
        for term in paper.exposure_terms:
            req = parse_request(term, role="exposure").request
            rec = retrieve(retriever, req, strata=strata, source="user")
            if rec.abstained:
                missed.append(term)
            else:
                found |= keys_of(rec)
        keys[paper.pmid] = frozenset(found)
        if missed:
            abstained[paper.pmid] = tuple(missed)
    return keys, abstained


# ---------------------------------------------------------------- scoring


def match(rec: HypothesisRecord, paper: PaperKey,
          exposure_keys: frozenset[str]) -> tuple[str, str] | None:
    """Apply the match rule to one hypothesis and one paper.

    Args:
        rec: The hypothesis.
        paper: The paper.
        exposure_keys: `resolve_exposures` output for this paper.

    Returns:
        `(exposure_key, outcome_key)` on a match, None otherwise.
    """
    ours_e = keys_of(rec.artefact.retrieval["exposure"])
    ours_o = keys_of(rec.artefact.retrieval["outcome"])
    e = sorted(ours_e & exposure_keys)
    o = sorted(k for k in paper.outcome_keys if k in ours_o)
    if not e or not o:
        return None
    return e[0], o[0]


def ceiling(loaded: Sequence[Loaded], table: Sequence[PaperKey],
            exposure_keys: dict[str, frozenset[str]], matched: int) -> Ceiling:
    """Bound the match count from above; see `Ceiling`.

    Args:
        loaded: The accepted artefacts.
        table: The papers.
        exposure_keys: `resolve_exposures` output.
        matched: The observed N.

    Returns:
        The ceiling.
    """
    matchable = [p for p in table if p.outcome_keys and exposure_keys[p.pmid]]
    out_keys = frozenset(k for p in matchable for k in p.outcome_keys)
    exp_keys = frozenset(k for p in matchable for k in exposure_keys[p.pmid])
    o_hit = e_hit = both = 0
    for _, rec in loaded:
        o = bool(keys_of(rec.artefact.retrieval["outcome"]) & out_keys)
        e = bool(keys_of(rec.artefact.retrieval["exposure"]) & exp_keys)
        o_hit += o
        e_hit += e
        both += o and e
    scored = len(loaded)
    return Ceiling(papers_matchable=len(matchable), outcome_side=o_hit,
                   exposure_side=e_hit, max_matched=both,
                   max_rate=None if scored == 0 else both / scored,
                   at_ceiling=matched == both)


def score(paths: Sequence[Path], *, table: Sequence[PaperKey],
          retriever: RetrieverLike, verdicts: dict[str, str],
          require_sha: str | None = None, strata: Strata | None = None) -> Baseline:
    """Score one run's committed artefacts against the paper table.

    Args:
        paths: The artefact files.
        table: The paper table, from `load_key_table` or a test.
        retriever: The deployed retriever, or a test double.
        verdicts: From `run_verdicts`, or supplied by a test.
        require_sha: The sha being scored; every stamp must match it.
        strata: Precomputed strata, when the caller has them.

    Returns:
        The baseline.

    Raises:
        Refused: When any artefact fails a refusal, or a halting verdict is red.
    """
    halted = [k for k in HALTING if verdicts.get(k, "missing") != "ok"]
    if halted:
        raise Refused("halting verdict: " + ", ".join(
            f"{k}={verdicts.get(k, 'missing')}" for k in halted))
    dictionary_hash = str(retriever.manifest["dictionary_version_hash"])
    loaded, summary = load_artefacts(paths, dictionary_hash=dictionary_hash,
                                     require_sha=require_sha)
    exposure_keys, abstained = resolve_exposures(table, retriever, strata)
    matches: list[Match] = []
    matched_artefacts: set[str] = set()
    for path, rec in loaded:
        for paper in table:
            m = match(rec, paper, exposure_keys[paper.pmid])
            if m is not None:
                matches.append(Match(path.name, paper.pmid, *m))
                matched_artefacts.add(path.name)
    env = loaded[0].record.generation
    assert env is not None
    scored = len(loaded)
    return Baseline(
        run_id=summary.run_id, tree_sha=env.tree_sha, dictionary_hash=dictionary_hash,
        generation=env, scored=scored, matched=len(matched_artefacts),
        rate=None if scored == 0 else len(matched_artefacts) / scored,
        denominator=summary.total_generated_this_run, by_outcome=summary.by_outcome,
        strata=summary.strata, papers=len(table),
        papers_with_outcome_key=sum(1 for p in table if p.outcome_keys),
        papers_exposure_resolved=sum(1 for p in table if exposure_keys[p.pmid]),
        papers_matched=len({m.pmid for m in matches}),
        exposure_abstentions=abstained, matches=tuple(matches), verdicts=verdicts,
        ceiling=ceiling(loaded, table, exposure_keys, len(matched_artefacts)))


# ---------------------------------------------------------------- verdicts


def run_verdicts(paths: Sequence[Path], root: Path = ROOT,
                 runner: Callable[[list[str]], int] | None = None) -> dict[str, str]:
    """Run the three checks that travel with the number.

    Args:
        paths: The artefacts, for the advisory scan.
        root: The clone to run the checks in.
        runner: Runs a command line and returns its exit status; a subprocess
            in `root` when None.

    Returns:
        `contamination_check`, `input_leakage`, `unearned_assertions` to `ok`
        or a reason. The first two halt scoring when not `ok`.
    """
    def _run(cmd: list[str]) -> int:
        return subprocess.run(cmd, cwd=root, check=False).returncode

    run = runner or _run
    out: dict[str, str] = {}
    rc = run([sys.executable, "-m", "benchmark.contamination_check", "--live"])
    out["contamination_check"] = "ok" if rc == 0 else f"FAIL (exit {rc})"

    from benchmark.input_leakage import check_input_does_not_contain_the_answer
    leaks = check_input_does_not_contain_the_answer()
    out["input_leakage"] = "ok" if not leaks else f"FAIL ({len(leaks)} leaks)"

    from benchmark.unearned_assertions import scan_record
    hits = 0
    for p in paths:
        rec = HypothesisRecord.from_json(Path(p).read_text())
        hits += len(scan_record(rec.artefact.protocol))
    out["unearned_assertions"] = "ok" if hits == 0 else f"advisory ({hits} hits)"
    return out


# ---------------------------------------------------------------- report


def render(b: Baseline) -> str:
    """The baseline as the committed `BASELINE.md`.

    Args:
        b: The baseline.

    Returns:
        Markdown.
    """
    rate = "n/a" if b.rate is None else f"{b.rate:.3f}"
    lines = [
        f"# Baseline {b.run_id}",
        "",
        f"**{b.ceiling.sentence(b.matched, b.scored)}**",
        "",
        f"Question answered: {b.qualifier}.",
        "",
        "| number | value |",
        "|---|---|",
        f"| matched (N) | {b.matched} |",
        f"| scored, the ledger's emitted count (M) | {b.scored} |",
        f"| match rate N/M | {rate} |",
        f"| ledger denominator, total_generated_this_run | {b.denominator} |",
        f"| ceiling: max matched / max rate | {b.ceiling.max_matched} / "
        f"{'n/a' if b.ceiling.max_rate is None else f'{b.ceiling.max_rate:.3f}'} |",
        "",
        f"ledger by outcome: {b.by_outcome}",
        f"strata: {', '.join(b.strata) or '(none)'}",
        f"dictionary: {b.dictionary_hash}   tree: {b.tree_sha}",
        f"generation stamp: {b.generation.model_dump()}",
        "",
        "## Papers",
        "",
        f"papers in the table: {b.papers}; with an outcome key on record: "
        f"{b.papers_with_outcome_key}; with an exposure the retriever resolved: "
        f"{b.papers_exposure_resolved}; matched by any hypothesis: "
        f"{b.papers_matched}",
    ]
    if b.exposure_abstentions:
        lines += ["", "exposure terms that abstained:"]
        lines += [f"- {pmid}: {len(terms)} of the line's terms"
                  for pmid, terms in sorted(b.exposure_abstentions.items())]
    lines += ["", "## Verdicts", ""]
    lines += [f"- {k}: {v}" for k, v in b.verdicts.items()]
    lines += ["", "## Matches", ""]
    if not b.matches:
        lines.append("(none)")
    lines += [f"- {m.artefact} ~ PMID {m.pmid}: exposure {m.exposure_key}, "
              f"outcome {m.outcome_key}" for m in b.matches]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Score a run's artefacts and write `BASELINE.md` beside them.

    Args:
        argv: Command line; `sys.argv[1:]` when None.

    Returns:
        0 when scored and written, 2 when refused or halted.
    """
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="+", type=Path, help="artefact files, one run")
    ap.add_argument("--sha", required=True, help="the sha being scored")
    ap.add_argument("--out", type=Path, default=None,
                    help="where to write the report; <run dir>/BASELINE.md when unset")
    a = ap.parse_args(argv)
    from pipeline.retrieve import load_retriever

    retriever = load_retriever()
    verdicts = run_verdicts(a.paths)
    for k, v in verdicts.items():
        print(f"  {k}: {v}")
    try:
        b = score(a.paths, table=load_key_table(), retriever=retriever,
                  verdicts=verdicts, require_sha=a.sha)
    except Refused as e:
        print(f"REFUSED: {e}")
        return 2
    out = a.out or Path(a.paths[0]).resolve().parent / "BASELINE.md"
    out.write_text(render(b))
    print(f"matched {b.matched} / scored {b.scored} ; denominator {b.denominator}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
