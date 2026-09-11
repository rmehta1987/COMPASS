"""generate/funnel.py — S1-S4. Deterministic. No model, no network.

This is where hypotheses are generated, and no agent is involved in it. The
instrument is closed, so the candidate space is finite and can be enumerated
exhaustively rather than searched. Enumeration cannot overlook the evidence
space by construction, it makes the yield denominator meaningful, and it confines
the model to judging stated pairs — which it is comparatively reliable at —
rather than open-ended search, which it is not.

    S1  enumerate      cartesian product over distinct constructs
    S2  prune          mechanical: construct identity, battery, free text, scale
    S3  screen         estimability tag (estimable | unknown), non-blocking.
                       not_estimable is reserved in the type but unassigned:
                       no codebook signal grounds a NEVER-estimable verdict, so
                       nothing currently parks. See s3_screen's docstring.
    S4  tag            literature density — a TAG, never a prune

Every count this module reports names the dictionary hash it was computed from.
A pair that survives to the Specifier arrives with its funnel denominator
attached, because selection from a screened space is part of any eventual
inference.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"

@dataclass
class Construct:
    """A distinct construct, not a codebook row.

    With 1,520 roster-prefixed repeats, enumerating rows would price Q8.2 twenty
    times and create twenty chances for the system to disagree with itself.
    """
    construct_key: str
    module: str
    base_id: str
    stem_text: str
    member_keys: list[str]
    is_group: bool          # a grid battery: needs a derivation to be an anchor
    is_free_text: bool
    roster_instances: int


@dataclass
class Candidate:
    exposure: Construct
    outcome: Construct
    state: str = "live"          # live | pruned | parked (parked: never set, see S3)
    stage: str | None = None     # S2 | S3
    reason: str | None = None
    #: `estimable` | `unknown`. NOT "is this pair worth studying" and NOT "do we
    #: know n" -- it is one question only: COULD a sample size ever be worked
    #: out for this pair, given what the study has exported so far.
    #:   estimable -- both items sit in the same module, so the same people were
    #:               asked both and counting them needs only the lighter export.
    #:               It is a statement about the DATA REQUIREMENT, not a count:
    #:               no participant count of any kind exists in this project
    #:               yet, so even an `estimable` pair still yields
    #:               `analytic_n: null`.
    #:   unknown   -- the items are in different modules, so you would need to
    #:               know how many people completed both, and
    #:               `module_co_completion_counts` does not exist.
    #: `not_estimable` is declared in the type and NEVER assigned: nothing in a
    #: codebook grounds a claim that a pair can never be measured, only that it
    #: cannot be measured today. See `_s3` for why that distinction is kept.
    estimability: str | None = None   # estimable | unknown (not_estimable: never set)
    requires_derivation: bool = False
    tags: dict = field(default_factory=dict)

    @property
    def pair_id(self) -> str:
        return f"{self.exposure.construct_key} -> {self.outcome.construct_key}"


class LoadedConstructs(NamedTuple):
    """Return value of `load_constructs`: constructs plus the dictionary hash.

    `load_constructs` was annotated `-> dict[str, Construct]` while actually
    returning a 2-tuple for as long as the function has existed. Every caller
    unpacks it as `C, version = load_constructs()` (or `C, _ = ...`), so the
    wrong annotation hid the real second element from mypy as `Any` at every
    call site — 4 of the 75 errors on `MYPY_CEILING` before this fix. A named
    tuple is still a tuple, so every existing `a, b = load_constructs()` call
    site keeps working unchanged; it just also gives a new caller `.version`
    instead of a bare position to remember.
    """

    constructs: dict[str, Construct]
    version: str


def load_constructs() -> LoadedConstructs:
    """Load every distinct construct out of the built dictionary.

    Returns:
        The constructs keyed by construct_key, paired with the dictionary
        version_hash they were computed from.
    """
    d = json.loads((BUILD / "dictionary.json").read_text())
    by_ck: dict[str, list[dict]] = {}
    for e in d["entries"]:
        by_ck.setdefault(e["construct_key"], []).append(e)

    out: dict[str, Construct] = {}
    for ck, rows in by_ck.items():
        first = rows[0]
        stem = first["stem_text"] or first["question_text"]
        out[ck] = Construct(
            construct_key=ck,
            module=first["module"],
            base_id=first["base_id"],
            stem_text=stem.replace("\n", " ").strip(),
            member_keys=sorted(r["key"] for r in rows),
            is_group=any(r["is_grid_subitem"] for r in rows),
            is_free_text=any(r["is_free_text"] for r in rows),
            roster_instances=len({r["roster_row"] for r in rows if r["roster_row"]}),
        )
    return LoadedConstructs(out, d["version_hash"])


# --------------------------------------------------------------------------- #
# S1
# --------------------------------------------------------------------------- #

def s1_enumerate(exposures: list[Construct], outcomes: list[Construct]) -> list[Candidate]:
    """Cartesian product. Nothing is selected here and nothing is judged."""
    return [Candidate(exposure=e, outcome=o)
            for e, o in product(exposures, outcomes)
            if e.construct_key != o.construct_key]


# --------------------------------------------------------------------------- #
# S2 — mechanical prunes only. Any criterion whose input does not exist
#      defaults to DO NOT PRUNE, so a missing input can never silently delete
#      a candidate.
# --------------------------------------------------------------------------- #

def s2_prune(cands: list[Candidate]) -> list[Candidate]:
    for c in cands:
        e, o = c.exposure, c.outcome

        if e.is_free_text or o.is_free_text:
            c.state, c.stage = "pruned", "S2"
            c.reason = "free_text_anchor: no response coding exists, so the "\
                       "variable cannot be an exposure or an outcome"
            continue

        # Same question battery on both sides: not a design, a tautology.
        if e.module == o.module and e.base_id.split(".")[0] == o.base_id.split(".")[0]:
            c.state, c.stage = "pruned", "S2"
            c.reason = f"same_battery: both anchors sit in the {e.base_id.split('.')[0]} "\
                       "block of one module"
            continue

        # A grid battery can be an anchor, but only through a signed derivation.
        if e.is_group or o.is_group:
            c.requires_derivation = True

        # branch/skip-logic pruning is INERT: skip logic appears nowhere in a
        # two-column codebook, so the criterion has no input and does not prune.

    return cands


# --------------------------------------------------------------------------- #
# S3 — two-state today (estimable | unknown), non-blocking.
# --------------------------------------------------------------------------- #

def s3_screen(cands: list[Candidate]) -> list[Candidate]:
    """Estimability is the project's fitness function and its headline input —
    module co-completion counts — does not exist. A blocking screen would idle
    the pipeline's central stage indefinitely, so cross-module pairs pass
    through carrying `unknown` and a named blocker.

    Only `estimable` and `unknown` are ever assigned. `not_estimable` (and the
    `parked` state it would produce) is declared on the dataclass but has no
    criterion behind it: a two-column codebook carries no signal — no skip
    logic, no mutual exclusion — that would license concluding a pair can NEVER
    be estimated, as opposed to not-yet. Inventing one just to make an earlier
    draft of this docstring true would be the same failure `estimate_n` refuses
    to commit with n (env/tools.py): a screening verdict with no evidence behind
    it is worse than an admitted gap. So parked_S3 is 0 by construction, not by
    observation, until a real not_estimable criterion is identified.

    Even `estimable` is a lighter promise than a computed n, not one already in
    hand: no participant count of any kind exists in this project yet (see
    HANDOFF_AGENT_PIPELINE.md §6). `estimate_n` (env/tools.py) currently returns
    `unknown` for single-module sets too, blocked on per-item non-missing
    counts — a separate, still-missing input from the module co-completion
    counts this tag is really about. When both arrive, estimate_n switches to
    computed_from_counts, n enters the ordering, and this screen is re-run.
    Nothing else changes, which is the property that makes shipping the
    degraded mode safe.
    """
    for c in cands:
        if c.state != "live":
            continue
        if c.exposure.module == c.outcome.module:
            # No participant count exists anywhere in this project (see
            # docstring above) — this only flags the lighter data requirement.
            c.estimability = "estimable"
        else:
            c.estimability = "unknown"
            c.tags["blocked_on"] = "module_co_completion_counts"
    return cands


# --------------------------------------------------------------------------- #
# S4 — a tag. Never a prune.
# --------------------------------------------------------------------------- #

def s4_tag(cands: list[Candidate]) -> list[Candidate]:
    """A literature-density filter would import two measured failure modes —
    popularity bias and over-reliance on literature — and would delete benchmark
    items before they are ever scored. So it tags, and the tag is discharged
    into selection_rationale.prior_work.
    """
    for c in cands:
        if c.state == "live":
            c.tags["prior_work"] = "unscored: literature tools are absent in "\
                                   "benchmark mode by registry construction"
    return cands


def run(exposures, outcomes) -> tuple[list[Candidate], dict]:
    cands = s4_tag(s3_screen(s2_prune(s1_enumerate(exposures, outcomes))))
    live = [c for c in cands if c.state == "live"]
    counts = {
        "enumerated": len(cands),
        "pruned_S2": sum(1 for c in cands if c.stage == "S2"),
        "parked_S3": sum(1 for c in cands if c.stage == "S3"),
        "live": len(live),
        "estimable": sum(1 for c in live if c.estimability == "estimable"),
        "unknown": sum(1 for c in live if c.estimability == "unknown"),
        "requires_derivation": sum(1 for c in live if c.requires_derivation),
    }
    return cands, counts


# --------------------------------------------------------------------------- #
# T7: the frame is named and hashed, and it is walked in enumeration order
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Frame:
    """A named slice of the instrument that the funnel enumerates.

    The frame decides every reported denominator (`run`'s `enumerated`), and it
    used to be an unnamed list comprehension copied into every driver. Named
    here, and hashed over the exact constructs it enumerates, a denominator can
    say which frame it came from.

    Attributes:
        name: The frame's name, a key of `FRAMES`.
        exposure_module: Module the exposures come from.
        exposure_prefix: Question-id prefix the exposures share.
        outcome_module: Module the outcomes come from.
        outcome_prefix: Question-id prefix the outcomes share.
    """

    name: str
    exposure_module: str
    exposure_prefix: str
    outcome_module: str
    outcome_prefix: str

    def sides(self, constructs: Mapping[str, Construct]
              ) -> tuple[list[Construct], list[Construct]]:
        """The frame's exposures and outcomes, each sorted by question id.

        Args:
            constructs: Construct keys to Construct, from `load_constructs`.

        Returns:
            `(exposures, outcomes)`, in the order `s1_enumerate` crosses them.
        """
        def pick(module: str, prefix: str) -> list[Construct]:
            return sorted((c for c in constructs.values()
                           if c.module == module and c.base_id.startswith(prefix)),
                          key=lambda c: c.base_id)
        return (pick(self.exposure_module, self.exposure_prefix),
                pick(self.outcome_module, self.outcome_prefix))

    def digest(self, constructs: Mapping[str, Construct], version: str) -> str:
        """A hash of exactly what this frame enumerates, against which build.

        Args:
            constructs: Construct keys to Construct.
            version: The dictionary's `version_hash`.

        Returns:
            Twelve hex characters. Any change to either side, the name or the
            build changes them.
        """
        exposures, outcomes = self.sides(constructs)
        payload = {"name": self.name, "dictionary_version": version,
                   "exposures": [c.construct_key for c in exposures],
                   "outcomes": [c.construct_key for c in outcomes]}
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


#: The frames a driver may walk, by name: the one definition every driver uses.
FRAMES: dict[str, Frame] = {
    "m3q16_x_m2q5": Frame("m3q16_x_m2q5", "3", "Q16.", "2", "Q5."),
}

#: The frame every driver built by hand before T7 named it.
DEFAULT_FRAME = "m3q16_x_m2q5"


def walk(frame: Frame, constructs: Mapping[str, Construct]
         ) -> tuple[list[Candidate], dict]:
    """The frame's candidates in enumeration order, with the funnel's counts.

    Enumeration order is the only order. A driver that jumped to the pair it
    found most promising would add a second, value-based selection on top of
    the funnel's, one that no denominator records.

    Args:
        frame: The frame to walk.
        constructs: Construct keys to Construct.

    Returns:
        `run`'s candidates and counts over the frame.
    """
    return run(*frame.sides(constructs))


def live_at(cands: list[Candidate], index: int) -> Candidate:
    """The `index`-th live candidate, counting in enumeration order.

    Args:
        cands: Candidates from `walk`, in its order.
        index: Zero-based position among the live candidates.

    Returns:
        That candidate.

    Raises:
        IndexError: When the frame has fewer live candidates.
    """
    live = [c for c in cands if c.state == "live"]
    if not 0 <= index < len(live):
        raise IndexError(f"the frame has {len(live)} live candidates; "
                         f"index {index} is outside it")
    return live[index]
