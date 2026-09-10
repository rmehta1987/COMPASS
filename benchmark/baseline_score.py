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
from collections.abc import Callable, Iterable, Mapping, Sequence
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

#: The `SideCounts` fields the report prints, in order. Read from the counts
#: the caller hands over, so a field added to `inventory_key.SideCounts` shows
#: up as a missing column here rather than being silently dropped.
_EXCLUSION_COLUMNS = ("papers", "matchable_sides", "excluded_sides",
                      "rows_present_confident", "rows_present_not_confident",
                      "rows_modality", "rows_absent", "rows_unresolvable",
                      "rows_not_confident_any_status")


class PaperKey(NamedTuple):
    """What the scorer needs of one paper: its pmid, exposure terms, outcome keys.

    Attributes:
        pmid: PubMed identifier.
        exposure_terms: From the design line; empty for a descriptive paper,
            and empty for every row an inventory built, which names keys.
        outcome_keys: Instrument keys the held-out key records as outcome;
            empty when it records none.
        exposure_keys: Instrument keys for the exposure side, when the table's
            source names them. Empty by default, so every call site that
            predates `benchmark/inventory_key.py` is unchanged and still
            resolves its exposure side through the retriever.
    """

    pmid: str
    exposure_terms: tuple[str, ...]
    outcome_keys: tuple[str, ...]
    exposure_keys: tuple[str, ...] = ()


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


class InventoryInput(NamedTuple):
    """The inventory rule's inputs, prepared by the caller.

    One parameter rather than five, and a NamedTuple rather than a model,
    because `score` treats it as opaque: it never reads an inventory row, never
    imports the inventory's schema and never enumerates a frame. Building this
    is `benchmark/inventory_key.py::inventory_input`'s job, and the frame comes
    from the funnel itself (`INVENTORY_DISCOVERY.md` rule 4).

    Attributes:
        table: One `PaperKey` per paper, both sides already folded to
            constructs; `exposure_terms` empty, so the retriever is never
            asked.
        in_frame: The pmids whose construct pair the run's frame contained.
            None means the frame was NOT ENUMERATED, which is reported as
            unknown and never as zero.
        excluded_sides: `side_exclusions` output, per side, as plain ints.
        analogue_only: Papers reachable on both sides only through an
            analogue, hence unmatchable under rule 2 and named rather than
            binned.
        synthetic: Whether the source declared itself a rehearsal. True only
            when it said so, so a real run cannot be labelled synthetic by
            accident and a rehearsal cannot lose the label by omission.
    """

    table: tuple[PaperKey, ...]
    in_frame: frozenset[str] | None
    excluded_sides: dict[str, dict[str, int]]
    analogue_only: int
    synthetic: bool = False


class InventoryCeiling(BaseModel):
    """The most the match rule could have found under the variable inventory.

    Beside `Ceiling`, never in place of it. The two are computed from different
    key sources and are NEVER pooled: no average, no sum, no single sentence
    covering both. A reader who combines them has invented a rule nobody
    pre-registered.

    The record ceiling is gated on the FRAME. A paper the run could never have
    reached bounds nothing, however well the inventory keys it, so
    `records_could_match` counts artefacts against papers that are matchable
    AND in frame. Where the frame was not enumerated the gate is not applied
    and `in_frame` is None, which the report prints as unknown.

    Attributes:
        papers: The table's size, the denominator of every paper line.
        scored: Artefacts accepted, the denominator of every record line.
        papers_with_outcome_key: Papers with a confident present outcome key.
        papers_with_exposure_key: Papers with a confident present exposure key.
        papers_matchable: Papers with both.
        in_frame: Papers matchable AND in the run's frame; None when the frame
            was not enumerated.
        records_could_match: Artefacts hitting a matchable, in-frame paper on
            both sides. An upper bound on `matched`.
        records_could_match_under_prevalence_key: `Ceiling.max_matched`,
            restated on its own line for comparison only.
        matched: Artefacts matching some matchable paper under rule 2,
            IN FRAME OR NOT. Observed matches are never gated on the frame:
            gating them would hide a real match behind a frame test, and the
            frame test is the newer and less trustworthy of the two.
        rate: `matched / scored`; None when nothing was scored.
        at_ceiling: `matched == records_could_match`.
        excluded_sides: Per side, every row and paper-side the rule excluded.
        analogue_only: Papers reachable on both sides only through an analogue.
        synthetic: The inventory declared itself a rehearsal; see
            `InventoryInput`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    papers: int = Field(ge=0)
    scored: int = Field(ge=0)
    papers_with_outcome_key: int = Field(ge=0)
    papers_with_exposure_key: int = Field(ge=0)
    papers_matchable: int = Field(ge=0)
    in_frame: int | None
    records_could_match: int = Field(ge=0)
    records_could_match_under_prevalence_key: int = Field(ge=0)
    matched: int = Field(ge=0)
    rate: float | None
    at_ceiling: bool
    excluded_sides: dict[str, dict[str, int]]
    analogue_only: int = Field(ge=0)
    synthetic: bool = False

    def sentence(self) -> str:
        """The reading the inventory rate must travel with.

        Returns:
            One paragraph, naming which ceiling this rate is compared to and
            what bounds it.
        """
        warn = ("SYNTHETIC INVENTORY, a rehearsal and not a measurement. "
                if self.synthetic else "")
        frame = ("not enumerated" if self.in_frame is None
                 else f"{self.in_frame} of {self.papers}")
        head = (f"{warn}Ceiling under the inventory: at most {self.records_could_match} "
                f"of {self.scored} artefacts could match "
                f"({self.papers_matchable} of {self.papers} papers matchable, "
                f"{frame} of those in the run's frame); observed {self.matched}.")
        if self.matched > self.records_could_match:
            # Observed matches are not gated on the frame and the ceiling is,
            # so this is reachable: a record can meet a paper through a folded
            # member without the exact construct pair appearing in the frame.
            # It is a defect in the FRAME TEST, not a pipeline result, and
            # saying "the gap below this ceiling is the pipeline's" here would
            # describe a negative gap as an achievement.
            return (head + " The observed count EXCEEDS this ceiling, which "
                    "cannot happen if both are right. Matches are not gated "
                    "on the frame and the ceiling is, so the frame test has "
                    "missed a pair the run demonstrably produced. Treat the "
                    "ceiling as wrong and re-derive it before quoting either "
                    "number.")
        if self.in_frame == 0:
            return (head + " No matchable paper was in the frame the run was "
                    "generated from, so the observed rate is zero by "
                    "construction and measures nothing about hypothesis "
                    "quality. Widening or re-choosing the frame is the only "
                    "thing that can move it.")
        if self.in_frame is None:
            return (head + " The frame was not enumerated, so the in-frame "
                    "count is UNKNOWN, not zero, and this ceiling is not yet "
                    "the bound a rate may be read against.")
        if self.records_could_match == 0:
            return (head + " The observed rate IS this ceiling; it is not a "
                    "measurement of hypothesis quality.")
        if self.at_ceiling:
            return head + " The observed rate is at this ceiling."
        return head + " The gap below this ceiling is the pipeline's."


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
        inventory_ceiling: The same question asked of the variable inventory,
            beside the prevalence-key ceiling and never pooled with it; None
            when the run was scored without an inventory. See
            `InventoryCeiling`.
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
    inventory_ceiling: InventoryCeiling | None = None


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
                      override: Mapping[str, tuple[str, ...]] | None = None,
                      ) -> tuple[dict[str, frozenset[str]], dict[str, tuple[str, ...]]]:
    """Resolve every paper's exposure keys, through the retriever only where needed.

    Three sources, in precedence order, so a key that is already known is
    never re-derived by a retriever that could miss it:

    1. `override[pmid]`, the caller's keys for that paper;
    2. `PaperKey.exposure_keys`, when the table's own source named them;
    3. the deployed retriever, over `PaperKey.exposure_terms`.

    Only 3 can abstain, so only 3 appears in the returned abstentions. Papers
    settled by 1 or 2 reach the retriever zero times, and where NO paper needs
    it the strata are not built either -- the point of an inventory-backed
    table is that a retriever miss can no longer be read as an absence.

    Args:
        table: The papers.
        retriever: The loaded bundle, or a test double.
        strata: Precomputed; built from the retriever when None and needed.
        override: Per pmid, exposure keys that replace both other sources.

    Returns:
        Per pmid, the union of `keys_of` over its resolved terms; and per
        pmid, the terms that abstained (present only when any did).
    """
    override = {} if override is None else override
    papers = list(table)
    needs_retriever = [p for p in papers
                       if p.pmid not in override and not p.exposure_keys]
    if strata is None and needs_retriever:
        strata = Strata.from_retriever(retriever)
    keys: dict[str, frozenset[str]] = {}
    abstained: dict[str, tuple[str, ...]] = {}
    for paper in papers:
        if paper.pmid in override:
            keys[paper.pmid] = frozenset(override[paper.pmid])
            continue
        if paper.exposure_keys:
            keys[paper.pmid] = frozenset(paper.exposure_keys)
            continue
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


def inventory_ceiling(loaded: Sequence[Loaded], inventory: InventoryInput,
                      ) -> InventoryCeiling:
    """Bound the match count under the variable inventory; see `InventoryCeiling`.

    Args:
        loaded: The accepted artefacts.
        inventory: The rule's prepared inputs.

    Returns:
        The ceiling, with the observed count beside it.
    """
    table = inventory.table
    matchable = [p for p in table if p.outcome_keys and p.exposure_keys]
    reachable = ([p for p in matchable if p.pmid in inventory.in_frame]
                 if inventory.in_frame is not None else matchable)
    out_keys = frozenset(k for p in reachable for k in p.outcome_keys)
    exp_keys = frozenset(k for p in reachable for k in p.exposure_keys)
    could = 0
    matched: set[str] = set()
    for path, rec in loaded:
        ours_o = keys_of(rec.artefact.retrieval["outcome"])
        ours_e = keys_of(rec.artefact.retrieval["exposure"])
        if (ours_o & out_keys) and (ours_e & exp_keys):
            could += 1
        for paper in matchable:
            if match(rec, paper, frozenset(paper.exposure_keys)) is not None:
                matched.add(path.name)
    scored = len(loaded)
    return InventoryCeiling(
        papers=len(table), scored=scored,
        papers_with_outcome_key=sum(1 for p in table if p.outcome_keys),
        papers_with_exposure_key=sum(1 for p in table if p.exposure_keys),
        papers_matchable=len(matchable),
        in_frame=None if inventory.in_frame is None else len(reachable),
        records_could_match=could, records_could_match_under_prevalence_key=0,
        matched=len(matched), at_ceiling=len(matched) == could,
        rate=None if scored == 0 else len(matched) / scored,
        excluded_sides=inventory.excluded_sides,
        analogue_only=inventory.analogue_only, synthetic=inventory.synthetic)


def score(paths: Sequence[Path], *, table: Sequence[PaperKey],
          retriever: RetrieverLike, verdicts: dict[str, str],
          require_sha: str | None = None, strata: Strata | None = None,
          exposure_keys_override: Mapping[str, tuple[str, ...]] | None = None,
          inventory: InventoryInput | None = None) -> Baseline:
    """Score one run's committed artefacts against the paper table.

    Args:
        paths: The artefact files.
        table: The paper table, from `load_key_table` or a test.
        retriever: The deployed retriever, or a test double.
        verdicts: From `run_verdicts`, or supplied by a test.
        require_sha: The sha being scored; every stamp must match it.
        strata: Precomputed strata, when the caller has them.
        exposure_keys_override: Per pmid, exposure keys that replace the
            retriever for that paper. `papers_exposure_resolved` then counts
            it as resolved, because it is: the keys are named, not guessed at
            by a search that could have missed. See `resolve_exposures`.
        inventory: The variable inventory's prepared inputs. When given, a
            SECOND ceiling is computed from them and reported beside the
            prevalence-key one; the prevalence-key numbers are untouched, so
            the same paths and table give the same `ceiling` with or without
            it.

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
    exposure_keys, abstained = resolve_exposures(table, retriever, strata,
                                                exposure_keys_override)
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
    old = ceiling(loaded, table, exposure_keys, len(matched_artefacts))
    inv = None
    if inventory is not None:
        # The prevalence-key ceiling is restated on the inventory ceiling's own
        # line so the two can be READ side by side. They are never pooled: the
        # figure below is a copy for comparison, not a term in a combination.
        inv = inventory_ceiling(loaded, inventory).model_copy(
            update={"records_could_match_under_prevalence_key": old.max_matched})
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
        ceiling=old, inventory_ceiling=inv)


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


def _inventory_section(c: InventoryCeiling) -> list[str]:
    """The inventory ceiling, beside the prevalence-key one and never pooled.

    Every line carries its own denominator, because the two ceilings have
    DIFFERENT ones -- papers for the four above, scored artefacts for the two
    below -- and a reader who reads a paper count as a record count has
    combined them.

    Args:
        c: The ceiling.

    Returns:
        The section's lines.
    """
    frame = "unknown (frame not enumerated)" if c.in_frame is None else str(c.in_frame)
    lines = [
        "",
        "## Ceiling under the variable inventory",
        "",
        f"**{c.sentence()}**",
        "",
        "| line | n | denominator |",
        "|---|---|---|",
        f"| papers with a confident present outcome key | "
        f"{c.papers_with_outcome_key} | {c.papers} papers |",
        f"| papers with a confident present exposure key | "
        f"{c.papers_with_exposure_key} | {c.papers} papers |",
        f"| papers matchable under the inventory (both sides) | "
        f"{c.papers_matchable} | {c.papers} papers |",
        f"| papers matchable AND in the run's frame | {frame} | "
        f"{c.papers} papers |",
        f"| records that could have matched under the inventory | "
        f"{c.records_could_match} | {c.scored} scored records |",
        f"| records that could have matched under the prevalence key + "
        f"retriever (today) | {c.records_could_match_under_prevalence_key} | "
        f"{c.scored} scored records |",
        f"| records observed matching under the inventory | {c.matched} | "
        f"{c.scored} scored records |",
        "",
        "The two ceilings above are computed from DIFFERENT key sources and "
        "are never pooled: they are not averaged, summed or covered by one "
        "sentence. The observed rate under the inventory rule is compared to "
        "the inventory ceiling, and the observed rate under today's rule to "
        "the prevalence-key ceiling, each in its own section.",
        "",
        "What bounds the inventory rate is the IN-FRAME count: a paper the run "
        "could never have reached bounds nothing, however well the inventory "
        "keys it. Where that count is unknown the frame was not enumerated, "
        "which is not the same as no paper being in it.",
    ]
    if c.analogue_only:
        lines += [
            "",
            f"{c.analogue_only} paper(s) of {c.papers} are reachable on both "
            f"sides only through a modality analogue. An analogue is a "
            f"different measurement, so rule 2 makes them UNMATCHABLE rather "
            f"than binning them into a tier that would flatter the rate. The "
            f"fifth clause that would place them is the operator's.",
        ]
    lines += ["", "### Sides excluded from matching, and why", "",
              "| side | " + " | ".join(_EXCLUSION_COLUMNS) + " |",
              "|---" * (1 + len(_EXCLUSION_COLUMNS)) + "|"]
    for side, counts in sorted(c.excluded_sides.items()):
        cells = " | ".join(str(counts.get(k, 0)) for k in _EXCLUSION_COLUMNS)
        lines.append(f"| {side} | {cells} |")
    lines += ["", "A `confident == false` row is excluded from matching and "
              "counted here, never silently dropped. The five row columns are "
              "a partition and sum to the rows read; the last column overlaps "
              "them, because a non-confident row can also be a modality or "
              "absent row."]
    return lines


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
    if b.inventory_ceiling is not None:
        lines += _inventory_section(b.inventory_ceiling)
    lines += ["", "## Verdicts", ""]
    lines += [f"- {k}: {v}" for k, v in b.verdicts.items()]
    lines += ["", "## Matches", ""]
    if not b.matches:
        lines.append("(none)")
    lines += [f"- {m.artefact} ~ PMID {m.pmid}: exposure {m.exposure_key}, "
              f"outcome {m.outcome_key}" for m in b.matches]
    return "\n".join(lines) + "\n"


def frame_pairs(retriever: RetrieverLike) -> list[tuple[str, str]]:
    """Enumerate the run's frame as construct pairs, from the funnel itself.

    Rule 4 of `INVENTORY_DISCOVERY.md`: never a hand-typed list. This calls
    `pipeline.run.narrow_frame`, the same code path `pipeline.run --frame-only`
    prints its count from, so the pairs cannot drift from the frame the run
    was generated under without the count drifting too.

    Args:
        retriever: The loaded bundle, for the strata and targets the frame
            is built over.

    Returns:
        `(exposure_construct_key, outcome_construct_key)` per live candidate.
    """
    from generate.funnel import load_constructs
    from pipeline.run import narrow_frame

    constructs, _ = load_constructs()
    strata = Strata.from_retriever(retriever)
    live, _counts = narrow_frame(constructs, strata, retriever.targets)
    return [(c.exposure.construct_key, c.outcome.construct_key) for c in live]


def _load_inventory(inventory: Path, harness: Path,
                    retriever: RetrieverLike) -> InventoryInput:
    """Read the inventory and prepare the second ceiling's inputs.

    Args:
        inventory: The rows, as `tiered_score.load_papers` accepts them.
        harness: `handoff/for_harness.json`.
        retriever: For the frame.

    Returns:
        The prepared input.
    """
    from benchmark.inventory_key import inventory_input
    from benchmark.tiered_score import load_handoff, load_papers

    papers, synthetic = load_papers(inventory)
    prepared = inventory_input(papers, load_handoff(harness),
                               frame_pairs=frame_pairs(retriever))
    return prepared._replace(synthetic=synthetic)


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
    ap.add_argument("--inventory", type=Path, default=None,
                    help="the variable inventory, one file per paper in a "
                         "directory or one file with a papers list. Without "
                         "it the CLI behaves exactly as before: one ceiling, "
                         "from the prevalence key and the retriever.")
    ap.add_argument("--harness", type=Path, default=None,
                    help="handoff/for_harness.json, whose schema_version pins "
                         "the field names the inventory rows are read under. "
                         "Required with --inventory, never defaulted: a "
                         "harness guessed at is a pin that checks nothing.")
    a = ap.parse_args(argv)
    if (a.inventory is None) != (a.harness is None):
        ap.error("--inventory and --harness are given together or not at all")
    if a.out is not None and a.out == a.out.with_suffix(".json"):
        # The JSON is written to <out>.with_suffix(".json"), so a .json report
        # path IS that path: the markdown would be written and overwritten a
        # line later, leaving the operator with JSON, no report and no error.
        # Checked here rather than at write time so it costs nothing -- by
        # then a retriever is loaded and a live contamination check has run.
        ap.error(f"--out {a.out.name} would be overwritten by the JSON written "
                 f"beside it. Name the report .md; the JSON takes the same stem.")
    from pipeline.retrieve import load_retriever

    retriever = load_retriever()
    verdicts = run_verdicts(a.paths)
    for k, v in verdicts.items():
        print(f"  {k}: {v}")
    try:
        inventory = (None if a.inventory is None
                     else _load_inventory(a.inventory, a.harness, retriever))
        b = score(a.paths, table=load_key_table(), retriever=retriever,
                  verdicts=verdicts, require_sha=a.sha, inventory=inventory)
    except Refused as e:
        print(f"REFUSED: {e}")
        return 2
    out = a.out or Path(a.paths[0]).resolve().parent / "BASELINE.md"
    out.write_text(render(b))
    # the same numbers as JSON, so harness mode 2 can report discovery beside
    # specification without parsing markdown
    out.with_suffix(".json").write_text(b.model_dump_json(indent=2) + "\n")
    print(f"matched {b.matched} / scored {b.scored} ; denominator {b.denominator}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
