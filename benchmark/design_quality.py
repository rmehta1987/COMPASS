"""benchmark/design_quality.py — what the pipeline's own records show, with no key.

WHY THIS EXISTS. Every other measurement in `benchmark/` is blocked on something
a person has to deliver: `scorability.py` on the held-out exposure key
(`TASKS.md` C12), the rediscovery arms on that key plus expert ratings, the
study-team counts on the study team. Meanwhile the pipeline emits records every
run and nothing reads them in aggregate. This does. It needs no answer key, no
domain expert and no paper, so the project can read it every iteration.

WHAT IT MEASURES, STATED NARROWLY. Groundedness: whether a record's assertions
are tied to something the environment can be asked about. NOT soundness — no
claim here is about whether a design would answer its question well, and
nothing in this module could tell. `DESIGN.md` §5.3 is the standing form of the
distinction; this module is one more place it binds.

NOTHING HERE IS A GATE. There is no floor, no ratchet and no exit code tied to a
number, deliberately. A dashboard that fails the build teaches people to move
the number; and the corpus it reads is whatever has been run, so any threshold
would be pinning today's corpus (`AGENTS.md` §Testing Patterns). The numbers
move because the runs moved, which is the point of reading them.

WHAT IT REUSES, rather than recomputing (`AGENTS.md` §Efficiency and Commits):

  agent/schema.py                  validation IS the filter. A record that does
                                   not validate is reported as invalid rather
                                   than parsed by hand into a second opinion.
  agent/schema.py::REFUSAL_EVIDENCE / REFUSAL_OUTCOMES
                                   which lookups a refusal reason requires, and
                                   which log outcomes entail it. Declared once,
                                   read here as a fourth caller.
  env/tools.py::resolve_variable   the live resolution check C12's ACCEPT
                                   criterion names.
  benchmark/unaided_specifiability.py::with_instrument
                                   the NEEDS_INSTRUMENT / NO_COHERENT_DESIGN
                                   split, and its calibration-set environment
                                   ruling.

THE DENOMINATOR IS REPORTED, NOT ASSUMED. `AGENTS.md` §Verification Discipline:
an unstated denominator is not a number. So the report carries the directory,
the glob, and every file the glob matched with what became of it. Two
consequences worth knowing before reading a share:

- `pathlib.Path.glob` KEEPS dotfiles where a shell glob drops them, and `run/`
  holds pinned failing records saved as dotfiles precisely so `run/*.json` in a
  shell would miss them. They are counted and named here rather than silently
  included or silently dropped.
- A file that is not a Specifier record at all (a retrieval artifact, an MCP
  config) is classified out by SHAPE before validation is attempted, so
  "invalid" means "a record the current schema rejects" and never "some other
  JSON file".

NO ANSWER KEY LIVES HERE, and none may be added. This module names no study, no
paper, no prevalence and no cohort figure; it reads `run/` and the instrument.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # `python -m benchmark.design_quality` from elsewhere
    sys.path.insert(0, str(ROOT))

from agent.schema import (  # noqa: E402
    REFUSAL_EVIDENCE,
    REFUSAL_OUTCOMES,
    DerivationRef,
    GateDecision,
    NotSpecifiable,
    NSource,
    ProtocolSpecification,
    Status,
    VariableRef,
)

#: Where `generate/live_specifier.py::main` writes a selected record, and where
#: its `.tool_log.jsonl` sibling lands beside it.
RECORD_DIR = ROOT / "run"

#: The unaided probe corpus, `benchmark/unaided_specifiability.py::RUN_DIR`.
UNAIDED_DIR = ROOT / "run" / "unaided"

#: Matched with `pathlib.Path.glob`, which keeps dotfiles. See the module
#: docstring: that is a property of the denominator, not an accident.
RECORD_GLOB = "*.json"

#: The outcome `resolve_variable` returns for a key a protocol may name. The
#: other four — `group`, `construct`, `ambiguous`, `not_found` — are each a
#: failure for an ASSERTED key: a protocol may not name a stem or a construct
#: key (`env/tools.py::resolve_variable`), and the remaining two resolve
#: nothing.
RESOLVED = "unique"

# Dispositions of a file the glob matched. Split on the property the FILE
# carries, so each state names a different defect (or none).
PROTOCOL = "protocol"
REFUSAL = "refusal"
INVALID = "invalid"
NOT_A_RECORD = "not_a_record"
UNREADABLE = "unreadable"

# Per-citation corroboration states for a refusal's evidence. Three, not two,
# for the reason `AGENTS.md` §Verification Discipline gives: "could not detect
# X" is never "X is absent". `CALLED` is the could-not-look case and is never
# folded into either of the others.
ABSENT = "absent"
CALLED = "called"
OUTCOME_MATCHED = "outcome_matched"


@dataclass(frozen=True)
class Share:
    """A counted share, carried with the denominator it is a share OF.

    Attributes:
        n: Numerator.
        of: Denominator.
        basis: What `of` counts, in words a reader can check against the corpus
            listing. Required, because a share whose denominator is implied is
            the failure `AGENTS.md` §Verification Discipline names.
        unmeasurable: Records excluded from `of` because the evidence needed to
            judge them is not present. Reported beside the share and never
            folded into either side of it.
        unmeasurable_why: Why those records could not be judged.
    """

    n: int
    of: int
    basis: str
    unmeasurable: int = 0
    unmeasurable_why: str = ""

    @property
    def fraction(self) -> float | None:
        """The share, or None when there is nothing to take a share of.

        Returns:
            `n / of`, or None when `of` is zero. Never 0.0 for an empty
            denominator: that would report "none of them" where the truth is
            "there were none".
        """
        return None if self.of == 0 else self.n / self.of

    def as_dict(self) -> dict[str, Any]:
        """The share as JSON.

        Returns:
            A mapping carrying the numerator, the denominator, the fraction and
            the basis, so a reader of the JSON needs nothing else.
        """
        out: dict[str, Any] = {"n": self.n, "of": self.of,
                               "fraction": self.fraction, "basis": self.basis}
        if self.unmeasurable or self.unmeasurable_why:
            out["unmeasurable"] = self.unmeasurable
            out["unmeasurable_why"] = self.unmeasurable_why
        return out


@dataclass
class Loaded:
    """One record file, with the log that was written beside it.

    Attributes:
        path: The record file.
        kind: `PROTOCOL`, `REFUSAL`, `INVALID`, `NOT_A_RECORD` or `UNREADABLE`.
        record: The validated record, or None for the three non-record states.
        log: The `.tool_log.jsonl` sibling's entries, or None when there is no
            sibling. None and `[]` are different: no log at all is not the same
            as a log that recorded nothing.
        error: The validation error, for `INVALID` and `UNREADABLE`.
    """

    path: Path
    kind: str
    record: ProtocolSpecification | NotSpecifiable | None = None
    log: list[dict[str, Any]] | None = None
    error: str = ""


@dataclass
class Corpus:
    """Every file the glob matched, sorted into what it turned out to be.

    Attributes:
        directory: The directory walked.
        glob: The pattern used.
        files: Every match, in path order, with its disposition.
    """

    directory: Path
    glob: str
    files: list[Loaded] = field(default_factory=list)

    def of_kind(self, kind: str) -> list[Loaded]:
        """The matches with one disposition.

        Args:
            kind: One of the five disposition constants.

        Returns:
            Those entries, in path order.
        """
        return [f for f in self.files if f.kind == kind]

    @property
    def protocols(self) -> list[ProtocolSpecification]:
        """Every validated protocol.

        Returns:
            The records, in path order.
        """
        return [f.record for f in self.of_kind(PROTOCOL)
                if isinstance(f.record, ProtocolSpecification)]

    def as_dict(self) -> dict[str, Any]:
        """The corpus listing, which IS the denominator statement.

        Returns:
            The directory, the glob, the per-disposition counts, and the path of
            every file that did not become a record, with the reason.
        """
        counts = Counter(f.kind for f in self.files)
        return {
            "directory": str(self.directory.relative_to(ROOT))
                         if self.directory.is_relative_to(ROOT)
                         else str(self.directory),
            "glob": self.glob,
            "glob_keeps_dotfiles": True,
            "matched": len(self.files),
            "dispositions": {k: counts.get(k, 0) for k in
                             (PROTOCOL, REFUSAL, INVALID, NOT_A_RECORD,
                              UNREADABLE)},
            "record_shaped": counts.get(PROTOCOL, 0) + counts.get(REFUSAL, 0)
                             + counts.get(INVALID, 0),
            "not_a_record": [f.path.name for f in self.of_kind(NOT_A_RECORD)],
            "invalid": [{"file": f.path.name, "error": f.error}
                        for f in self.of_kind(INVALID)],
            "unreadable": [{"file": f.path.name, "error": f.error}
                           for f in self.of_kind(UNREADABLE)],
            "logs_present": sum(1 for f in self.files
                                if f.kind in (PROTOCOL, REFUSAL)
                                and f.log is not None),
        }


def record_shape(obj: object) -> str | None:
    """Which record a JSON object is SHAPED like, before validation is tried.

    Shape first, validation second, so `INVALID` can mean "a record the current
    schema rejects" — which is a finding — rather than "any JSON file in the
    directory", which is noise. The discriminating fields are the ones neither
    record can be without: a protocol always carries `protocol_id` and
    `exposure`, a refusal always carries `pair_id`, `reason` and `evidence`.

    Args:
        obj: Parsed JSON.

    Returns:
        `PROTOCOL`, `REFUSAL`, or None when the object is not a Specifier
        record at all.
    """
    if not isinstance(obj, dict):
        return None
    if "protocol_id" in obj and "exposure" in obj:
        return PROTOCOL
    if {"pair_id", "reason", "evidence"} <= set(obj):
        return REFUSAL
    return None


def read_log(record_path: Path) -> list[dict[str, Any]] | None:
    """The tool log written beside a record, if one was.

    Args:
        record_path: The record file.

    Returns:
        The JSONL entries, or None when no sibling log exists. A record with no
        log is not a record whose log is empty, and the two are never merged:
        `AGENTS.md` §Verification Discipline.
    """
    sibling = record_path.with_suffix(".tool_log.jsonl")
    if not sibling.exists():
        return None
    return [json.loads(line) for line in sibling.read_text().splitlines()
            if line.strip()]


def load_corpus(directory: Path = RECORD_DIR,
                glob: str = RECORD_GLOB) -> Corpus:
    """Walk a directory of Specifier output and sort it by what it is.

    Args:
        directory: Where `generate/live_specifier.py` writes records.
        glob: The pattern, matched with `pathlib.Path.glob`.

    Returns:
        A `Corpus` in which every match has a disposition and nothing was
        dropped silently.
    """
    corpus = Corpus(directory=directory, glob=glob)
    if not directory.is_dir():
        return corpus
    for path in sorted(directory.glob(glob)):
        try:
            obj = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            corpus.files.append(Loaded(path, UNREADABLE, error=str(exc)[:200]))
            continue
        shape = record_shape(obj)
        if shape is None:
            corpus.files.append(Loaded(path, NOT_A_RECORD))
            continue
        cls: Any = ProtocolSpecification if shape == PROTOCOL else NotSpecifiable
        try:
            record = cls.model_validate(obj)
        except ValueError as exc:
            corpus.files.append(Loaded(path, INVALID, error=str(exc)[:300]))
            continue
        corpus.files.append(Loaded(path, shape, record=record,
                                   log=read_log(path)))
    return corpus


def ref_keys(ref: object) -> set[str]:
    """The instrument keys one reference names.

    The typed counterpart of `agent/tool_authority.py::_ref_keys`, which reads
    raw JSON for a different purpose: that one builds the key set the access
    gate's call must COVER, and deliberately omits `excluded_variables` because
    an excluded variable consumes no budget. This one is about what the record
    ASSERTS, so an exclusion counts — a key named in an exclusion is a key the
    record claims exists.

    Args:
        ref: An exposure, outcome or covariate reference.

    Returns:
        Its keys. A derivation contributes its components, because that is what
        the tools take. An area measure contributes none: it names no
        instrument variable.
    """
    if isinstance(ref, VariableRef):
        return {ref.key}
    if isinstance(ref, DerivationRef):
        return set(ref.component_keys)
    return set()


def asserted_keys(p: ProtocolSpecification) -> set[str]:
    """Every instrument key a protocol names.

    Args:
        p: A validated protocol.

    Returns:
        The keys from the two anchors and all three covariate lists.
    """
    keys = ref_keys(p.exposure) | ref_keys(p.outcome)
    for lst in (p.adjusted_covariates, p.excluded_variables,
                p.undetermined_covariates):
        for entry in lst:
            keys |= ref_keys(entry.variable)
    return keys


def resolves_live(key: str) -> bool:
    """Does the environment resolve this key to exactly one variable, now?

    A weaker check already runs at validation: `ProtocolSpecification.
    _wording_is_verbatim` looks each VariableRef up in the built dictionary's
    wording map. This is the stronger one C12's ACCEPT criterion names, and it
    differs in two ways that matter — it goes through the tool the model
    actually calls, so a key the registries hide is caught; and it covers a
    DERIVATION's component keys, which `_all_variable_refs` never yields.

    Args:
        key: A fully qualified variable key.

    Returns:
        True when `resolve_variable` returns `unique`.
    """
    from env import tools

    return bool(tools.resolve_variable(key=key).get("outcome") == RESOLVED)


def citation_state(evidence_tool: str, cited_outcome: str,
                   log: list[dict[str, Any]]) -> str:
    """Whether one cited lookup is corroborated by the record's own log.

    Three states, not two. A refusal stamps a PAYLOAD-derived outcome for the
    tools whose log `outcome` field carries no verdict — `registry_coverage`
    returns `ok` and the specifier writes `"linked: coverage none"`, which is
    the emptiness it read out of the result. Treating that mismatch as a failed
    citation would mark every honest `registry_empty` refusal unsupported;
    treating it as a match would claim a check that did not happen. So it gets
    its own state and is reported separately.

    Args:
        evidence_tool: The tool the record cites.
        cited_outcome: The outcome the record claims for it.
        log: The entries of the record's own tool log.

    Returns:
        `ABSENT` when the tool never ran, `OUTCOME_MATCHED` when a call's log
        outcome is the one cited, `CALLED` when it ran but the cited outcome is
        not one the log's `outcome` field carries.
    """
    calls = [c for c in log if c.get("tool") == evidence_tool]
    if not calls:
        return ABSENT
    if any(str(c.get("outcome") or "") == cited_outcome for c in calls):
        return OUTCOME_MATCHED
    return CALLED


def refusal_citations(r: NotSpecifiable,
                      log: list[dict[str, Any]]) -> dict[str, int]:
    """Corroborate every REQUIRED lookup of a refusal against its own log.

    The schema checks that the record CITES the tools its reason requires
    (`NotSpecifiable._refusal_is_earned`) and that the cited outcomes entail the
    reason. Neither says the calls happened. This does, over
    `REFUSAL_EVIDENCE[reason]` rather than over whatever the record chose to
    cite, so padding the evidence list with extra corroborated calls cannot
    raise the count.

    Args:
        r: A validated refusal.
        log: Its own tool log's entries.

    Returns:
        Counts keyed by `ABSENT`, `CALLED` and `OUTCOME_MATCHED`, one per
        required tool. A required tool the record never cited counts `ABSENT`.
    """
    states: Counter[str] = Counter()
    cited = {e.tool: e.outcome for e in r.evidence}
    for tool in sorted(REFUSAL_EVIDENCE.get(r.reason, frozenset())):
        if tool not in cited:
            states[ABSENT] += 1
            continue
        states[citation_state(tool, cited[tool], log)] += 1
    return dict(states)


def entailing_outcomes(r: NotSpecifiable) -> dict[str, list[str]]:
    """The log outcomes that would entail this refusal's reason, per tool.

    Reported beside the citation states so a reader can see which of them the
    log's own vocabulary could ever have produced. `None` in `REFUSAL_OUTCOMES`
    records that the tool's outcome field CANNOT entail the reason; it appears
    here as an empty list, which is why `CALLED` exists as a state.

    Args:
        r: A validated refusal.

    Returns:
        Tool name to the sorted entailing outcomes, empty where there are none.
    """
    wanted = REFUSAL_OUTCOMES.get(r.reason, {})
    return {tool: sorted(wanted.get(tool) or ())
            for tool in sorted(REFUSAL_EVIDENCE.get(r.reason, frozenset()))}


# --------------------------------------------------------------------------- #
# the measures
# --------------------------------------------------------------------------- #


def ready_share(corpus: Corpus) -> Share:
    """How often a valid protocol reached `ready_for_review`.

    Args:
        corpus: A loaded corpus.

    Returns:
        The share, over validated protocols.
    """
    ps = corpus.protocols
    return Share(n=sum(1 for p in ps if p.status is Status.ready_for_review),
                 of=len(ps), basis="validated protocols in the corpus")


#: Why a protocol is still a draft, in the order `agent/schema.py::derive_status`
#: tests the clauses. Named here so the dashboard can say WHICH clause held
#: rather than reporting a bare 0% and letting a reader read it as a quality
#: failure. `tests/test_design_quality.py` pins the agreement: this returns None
#: exactly when `derive_status` returns `ready_for_review`, so the two cannot
#: drift into two different truth tables.
N_UNKNOWN = "n_source_unknown"
HAS_BLOCKERS = "blocked_on_non_empty"
ACCESS_NOT_PASS = "access_not_pass"


def draft_reason(p: ProtocolSpecification) -> str | None:
    """The FIRST clause of the status truth table that holds for this record.

    Args:
        p: A validated protocol.

    Returns:
        `N_UNKNOWN`, `HAS_BLOCKERS` or `ACCESS_NOT_PASS`, or None when no clause
        holds and the record is `ready_for_review`.
    """
    if p.estimability.n_source is NSource.unknown:
        return N_UNKNOWN
    if p.blocked_on:
        return HAS_BLOCKERS
    if p.access.decision is not GateDecision.pass_:
        return ACCESS_NOT_PASS
    return None


def draft_because(corpus: Corpus) -> dict[str, int]:
    """What is holding each draft protocol at `draft`.

    Read this beside `reaches_ready_for_review`. While the study team's
    co-completion counts are outstanding `env/tools.py::estimate_n` returns null
    with `n_source=unknown` on every pair, so the first clause holds on every
    record and the ready share is pinned at zero by an outstanding DELIVERY, not
    by the model. A share whose ceiling is currently zero has to say so.

    Args:
        corpus: A loaded corpus.

    Returns:
        A tally over the clause names, counting only drafts.
    """
    reasons = [draft_reason(p) for p in corpus.protocols]
    return dict(sorted(Counter(r for r in reasons if r is not None).items()))


def refusal_share(corpus: Corpus) -> Share:
    """How much of the corpus is a refusal rather than a design.

    Not a defect in either direction, and never read as one: a refusal is a
    first-class output (`agent/schema.py::NotSpecifiable`). The number says what
    the corpus is made of, which every share below is conditioned on.

    Args:
        corpus: A loaded corpus.

    Returns:
        The share, over validated records of either kind.
    """
    refusals = len(corpus.of_kind(REFUSAL))
    return Share(n=refusals, of=refusals + len(corpus.protocols),
                 basis="validated records of either kind")


def refusal_evidence_share(corpus: Corpus) -> Share:
    """How often every lookup a refusal's reason requires actually ran.

    Args:
        corpus: A loaded corpus.

    Returns:
        The share, over refusals that have a log to check against. Refusals
        with no log beside them are `unmeasurable`, never counted as failures:
        an unchecked citation is not a false one.
    """
    loaded = corpus.of_kind(REFUSAL)
    with_log = [f for f in loaded if f.log is not None]
    ok = 0
    for f in with_log:
        assert isinstance(f.record, NotSpecifiable) and f.log is not None
        if refusal_citations(f.record, f.log).get(ABSENT, 0) == 0:
            ok += 1
    return Share(n=ok, of=len(with_log),
                 basis="validated refusals with a tool log beside them",
                 unmeasurable=len(loaded) - len(with_log),
                 unmeasurable_why="no .tool_log.jsonl sibling, so the "
                                  "citations cannot be checked against the run "
                                  "that made them")


def blocker_disclosure(corpus: Corpus) -> dict[str, Any]:
    """What protocols disclose in `blocked_on`.

    The mean is reported with the distribution beside it, because the mean
    alone cannot distinguish "every record discloses one gap" from "half
    disclose two and half disclose none", and `agent/specifier.py::_rank`
    orders on the count ASCENDING — so the shape of this distribution is what
    selection is acting on.

    Args:
        corpus: A loaded corpus.

    Returns:
        The count, the total, the mean (None when there are no protocols), the
        share disclosing at least one blocker, and the per-member tally.
    """
    ps = corpus.protocols
    counts = [len(p.blocked_on) for p in ps]
    members: Counter[str] = Counter(b.value for p in ps for b in p.blocked_on)
    return {
        "protocols": len(ps),
        "blockers_total": sum(counts),
        "mean_len_blocked_on": (sum(counts) / len(counts)) if counts else None,
        "disclosing_at_least_one": Share(
            n=sum(1 for c in counts if c), of=len(counts),
            basis="validated protocols in the corpus").as_dict(),
        "by_member": dict(sorted(members.items())),
    }


def key_resolution(corpus: Corpus) -> tuple[Share, dict[str, list[str]]]:
    """How many asserted instrument keys the environment resolves live.

    Args:
        corpus: A loaded corpus.

    Returns:
        The share over key MENTIONS — one per key per protocol, so a record
        that names an unresolvable key ten times is ten failures and not one —
        and, beside it, the unresolved keys per record file.
    """
    total = resolved = 0
    unresolved: dict[str, list[str]] = {}
    for f in corpus.of_kind(PROTOCOL):
        assert isinstance(f.record, ProtocolSpecification)
        bad = []
        for key in sorted(asserted_keys(f.record)):
            total += 1
            if resolves_live(key):
                resolved += 1
            else:
                bad.append(key)
        if bad:
            unresolved[f.path.name] = bad
    return Share(n=resolved, of=total,
                 basis="asserted key mentions across validated protocols "
                       "(anchors, derivation components, and all three "
                       "covariate lists)"), unresolved


def numeric_falsifier(corpus: Corpus) -> Share:
    """How often a protocol carries a numeric falsifier rather than only prose.

    `falsifier` prose is mandatory and `falsifier_threshold` is not, on purpose:
    `agent/schema.py` records that model-comparison and ratio-scale falsifiers
    do not reduce to a threshold. So this is not a quality score — a protocol
    without one may be the correct output. It is reported because a threshold
    is the only part of the falsifier the schema can check against the study's
    own detectable effect.

    Args:
        corpus: A loaded corpus.

    Returns:
        The share, over validated protocols.
    """
    ps = corpus.protocols
    return Share(n=sum(1 for p in ps if p.falsifier_threshold is not None),
                 of=len(ps), basis="validated protocols in the corpus")


def instrument_split(directory: Path = UNAIDED_DIR) -> dict[str, Any]:
    """The unaided corpus split by whether the instrument makes the pair designable.

    Straight through `benchmark/unaided_specifiability.py::with_instrument`,
    which is deterministic and model-free and takes its ruling from the
    calibration set's own environment check.

    Args:
        directory: An unaided probe output directory.

    Returns:
        The directory, the number of probe records read, and the tally over
        `SPECIFIABLE` / `NEEDS_INSTRUMENT` / `NO_COHERENT_DESIGN`. `probed` is 0
        when the directory holds no probe records, and the tally is then empty
        rather than a row of zeroes.
    """
    from benchmark.unaided_specifiability import load_records, with_instrument

    records = load_records(directory)
    tally: Counter[str] = Counter()
    for rec in records:
        tally[with_instrument(rec["verdict"],
                              rec["exposure"]["construct_key"],
                              rec["outcome"]["construct_key"])] += 1
    return {
        "directory": str(directory.relative_to(ROOT))
                     if directory.is_relative_to(ROOT) else str(directory),
        "glob": "*.json",
        "filter": "schema == unaided_specifiability/1",
        "probed": len(records),
        "split": dict(sorted(tally.items())),
    }


def report(directory: Path = RECORD_DIR, glob: str = RECORD_GLOB,
           unaided: Path | None = UNAIDED_DIR) -> dict[str, Any]:
    """The whole dashboard, as JSON.

    Args:
        directory: The record corpus.
        glob: The pattern, matched with `pathlib.Path.glob`.
        unaided: The unaided probe corpus, or None to skip that measure. None is
            reported as `null`, never as an empty split: a measure that did not
            run and a measure that found nothing are different.

    Returns:
        The corpus listing and every measure, each with its own denominator.
    """
    corpus = load_corpus(directory, glob)
    keys, unresolved = key_resolution(corpus)
    return {
        "schema": "design_quality/1",
        "corpus": corpus.as_dict(),
        "reaches_ready_for_review": ready_share(corpus).as_dict(),
        "draft_because": draft_because(corpus),
        "refuses_as_not_specifiable": refusal_share(corpus).as_dict(),
        "refusal_lookups_ran": refusal_evidence_share(corpus).as_dict(),
        "refusal_citations": [
            {"file": f.path.name,
             "reason": f.record.reason.value,
             "required_tools": sorted(REFUSAL_EVIDENCE.get(f.record.reason,
                                                           frozenset())),
             "entailing_outcomes": entailing_outcomes(f.record),
             "states": refusal_citations(f.record, f.log)}
            for f in corpus.of_kind(REFUSAL)
            if isinstance(f.record, NotSpecifiable) and f.log is not None],
        "blocked_on": blocker_disclosure(corpus),
        "asserted_keys_resolve_live": keys.as_dict(),
        "unresolved_keys": unresolved,
        "carries_numeric_falsifier": numeric_falsifier(corpus).as_dict(),
        "unaided_with_instrument": (None if unaided is None
                                    else instrument_split(unaided)),
    }


def _pct(share: dict[str, Any]) -> str:
    """One share as a fixed-width `n/of (pct)` cell.

    Args:
        share: A `Share.as_dict()` mapping.

    Returns:
        The rendered cell. An empty denominator renders as `--`, never `0%`.
    """
    frac = share["fraction"]
    tail = "  --  " if frac is None else f"{frac * 100:5.1f}%"
    return f"{share['n']:>4} / {share['of']:<4} {tail}"


def render(rep: dict[str, Any]) -> str:
    """The dashboard as text, denominator first.

    Args:
        rep: A `report` return value.

    Returns:
        The rendered report.
    """
    c = rep["corpus"]
    out = [
        "=" * 78,
        "DESIGN QUALITY — groundedness of the pipeline's own records. No answer key.",
        "=" * 78,
        f"  corpus        {c['directory']}/{c['glob']}   "
        f"matched {c['matched']}  (Path.glob keeps dotfiles)",
        f"  dispositions  {c['dispositions']}",
        f"  logs present  {c['logs_present']} of "
        f"{c['record_shaped'] - c['dispositions'][INVALID]} validated records",
    ]
    for entry in c["invalid"]:
        out.append(f"    INVALID     {entry['file']}")
        out.append(f"                {entry['error'].splitlines()[0][:70]}")
    for name in c["not_a_record"]:
        out.append(f"    not a record  {name}")
    out += [
        "-" * 78,
        f"  reaches ready_for_review     {_pct(rep['reaches_ready_for_review'])}",
        f"      still draft because      {rep['draft_because']}",
        f"  refuses as NotSpecifiable    {_pct(rep['refuses_as_not_specifiable'])}",
        f"  refusal lookups actually ran {_pct(rep['refusal_lookups_ran'])}",
        f"  asserted keys resolve live   {_pct(rep['asserted_keys_resolve_live'])}",
        f"  carries numeric falsifier    {_pct(rep['carries_numeric_falsifier'])}",
    ]
    b = rep["blocked_on"]
    mean = b["mean_len_blocked_on"]
    out += [
        f"  mean len(blocked_on)         "
        f"{'  --' if mean is None else f'{mean:.2f}'}"
        f"   over {b['protocols']} protocols; "
        f"disclosing {_pct(b['disclosing_at_least_one']).strip()}",
    ]
    for member, n in b["by_member"].items():
        out.append(f"      {n:>4}  {member}")
    for row in rep["refusal_citations"]:
        out.append(f"  refusal {row['file'][:46]}  {row['reason']}")
        out.append(f"      required {row['required_tools']}  -> {row['states']}")
    for name, keys in rep["unresolved_keys"].items():
        out.append(f"  UNRESOLVED KEYS  {name}: {keys}")
    u = rep["unaided_with_instrument"]
    out.append("-" * 78)
    if u is None:
        out.append("  unaided split                not run")
    else:
        out.append(f"  unaided split                {u['directory']}  "
                   f"probed {u['probed']}")
        for verdict, n in u["split"].items():
            out.append(f"      {n:>4}  {verdict}")
    out.append("=" * 78)
    return "\n".join(out)


def _main(argv: Sequence[str] | None = None) -> int:
    """Print the dashboard.

    Args:
        argv: Command line, or None to read `sys.argv`.

    Returns:
        0 when the dashboard was computed, 1 when the corpus held no validated
        record at all. Empty is an error and not a clean run: every share would
        report `--`, and a dashboard of nothing must not look like a pass.
    """
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--dir", type=Path, default=RECORD_DIR,
                    help="record corpus (default: run/)")
    ap.add_argument("--glob", default=RECORD_GLOB)
    ap.add_argument("--unaided", type=Path, default=UNAIDED_DIR,
                    help="unaided probe corpus for the with_instrument split")
    ap.add_argument("--no-unaided", action="store_true",
                    help="skip the unaided split rather than reporting it empty")
    ap.add_argument("--json", type=Path, default=None,
                    help="also write the full report here")
    args = ap.parse_args(argv)

    rep = report(args.dir, args.glob,
                 None if args.no_unaided else args.unaided)
    if args.json:
        args.json.write_text(json.dumps(rep, indent=1))
    print(render(rep))
    d = rep["corpus"]["dispositions"]
    if d[PROTOCOL] + d[REFUSAL] == 0:
        print(f"\nno validated record under {rep['corpus']['directory']}/"
              f"{rep['corpus']['glob']} — nothing was measured")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
