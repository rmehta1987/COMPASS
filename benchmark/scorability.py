"""benchmark/scorability.py — whether a benchmark paper can be scored at all.

WHAT THIS ANSWERS. The benchmark is rediscovery (`DESIGN.md` §6): hand the
pipeline a published exposure-outcome pair and score how much of that paper's
design it recovers from the instrument. A paper whose exposure or outcome the
questionnaire never asked about cannot test anything, and scoring against it
would move the number for a reason that has nothing to do with the model. So
every answer-key row needs a scorable status, and this file computes one.

IT REPLACES A NUMBER THAT HAD NO DERIVATION. The project's docs asserted that
"about one and a half" of the papers were scorable. Nothing carried a reference
and no code computed it. That figure was the stated reason C12 is the task that
matters, so it needed a derivation or a replacement; this is the replacement, and
`status_counts` is now the only home for the number (`DESIGN.md` §7).

THE ASYMMETRY THAT SHAPES THE WHOLE FILE: REFUTING IS SOUND FROM TEXT,
CONFIRMING IS NOT. `benchmark/tier_gate.py::outcomes_absent_from_instrument`
already says the careful half of this — "a term with a word present is NOT
thereby measurable ... this reports absence and never presence". Measured here
2026-08-28, that limit is not theoretical. Taking word presence as evidence of
scorability admits four papers, and three of them survive on a single common
English word carried by an unrelated question:

    'Chicago Health Atlas neighbourhood + ambient exposures'
        survives on  chicago, health, neighbourhood
    'individual and area characteristics'      survives on  individual
    'household PM2.5'                          survives on  household
    'seven linked community characteristics'   survives on  community

None of those means the instrument measures air pollution or an area-level
index. The fourth is worse in the other direction: 'perceived discrimination in
health care' survives on `health` and `care`, while `discrimination`,
`perceived` and `unfair` each occur ZERO times in `build/dictionary.json` — so
the word test rated that exposure present when the instrument does not carry it
at all. A criterion built on word presence would have declared four papers
scorable and been wrong about every one.

So the two verdicts rest on different evidence and are not each other's
negation:

    REFUTED      no content word of the term occurs anywhere in the built
                 instrument. Conservative and one-directional: a common word
                 makes this refuse LESS often, never more, so a false REFUTED
                 needs the instrument to carry none of the term's words.
    CONFIRMED    an instrument key resolves live through
                 `env.tools.resolve_variable` with `outcome == "unique"`. This
                 is the only positive evidence in the repository, and it is the
                 same discipline `benchmark/calibration_set.py` uses: read the
                 field of the tool's ACTUAL return value that forces the
                 verdict, never a hand-typed status beside a row that looks
                 right.
    UNDETERMINED neither. The honest majority today, and a work list rather
                 than a verdict.

WHY NOTHING IS SCORABLE TODAY, AND WHAT WOULD CHANGE IT. Confirming needs a
resolved key per side. `benchmark/prevalence_key.py` supplies outcome-side keys
— 21 fields, and measured 2026-08-28, six of the sixteen papers have at least
one row carrying a non-null `instrument_key`. Nothing in this repository
supplies an exposure-side key for any paper: `prevalence_key.py` has no exposure
column, and the design detail `cohort_papers.py` points at ("lives in the lane
report") is in neither the tree nor the history. That missing column IS C12, and
it is represented here as `EXPOSURE_KEYS`, an empty mapping this file already
reads. Fill it and papers begin to qualify with no change to this code.

THE GUARANTEE, AND ITS TEST. A paper is `scorable` only when both sides are
CONFIRMED, and CONFIRMED is unreachable without a live-resolved key. So this
module cannot report a paper scorable on word evidence, today or after anyone
edits the term lists. `tests/test_scorability.py::
test_word_presence_alone_can_never_make_a_paper_scorable` pins it, and
`test_a_key_that_names_a_construct_is_not_a_confirmed_variable` pins the case
that a key resolving to a battery is not a variable — `resolve_variable`'s own
log says a protocol may never name a stem.

HELD OUT. This file derives exposure and outcome terms from the bibliography's
design lines, so it is paper content and belongs under `benchmark/` with the
other answer keys. `benchmark/contamination_check.py::check_holdout_not_reachable`
carries it by name, and `tests/test_scorability.py` fails if that name is
dropped.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from benchmark.cohort_papers import COHORT_PAPERS, CohortPaper
from benchmark.instrument_terms import terms_absent_from_instrument
from benchmark.prevalence_key import PREVALENCE_KEY
from benchmark.tier_gate import outcome_terms
from env.tools import resolve_variable

#: The three verdicts a side of a design line can carry. Not a bool: the whole
#: point of the file is that "not refuted" and "confirmed" are different states
#: reached by different evidence.
REFUTED = "refuted"
CONFIRMED = "confirmed"
UNDETERMINED = "undetermined"

#: Named so a caller sees which problem it has, in the style of
#: `benchmark/tier_gate.py`'s blockers — a named refusal instead of a number.
NO_DESIGN_ARROW = "no_design_arrow"
EXPOSURE_ABSENT_FROM_INSTRUMENT = "exposure_absent_from_instrument"
OUTCOME_ABSENT_FROM_INSTRUMENT = "outcome_absent_from_instrument"
EXPOSURE_KEY_COLUMN_MISSING = "exposure_key_column_missing"
#: Renamed from `outcome_key_unresolved` on 2026-08-29. It is raised for either
#: side, and the old name reported an EXPOSURE key that did not resolve as an
#: outcome problem — in a constant whose own comment says it exists "so a caller
#: sees which problem it has".
KEY_DOES_NOT_RESOLVE = "key_does_not_resolve"
KEY_NAMES_A_CONSTRUCT_NOT_A_VARIABLE = "key_names_a_construct_not_a_variable"
#: The honest refutation for an outcome the questionnaire cannot carry. The word
#: test cannot make this call: `serum PSA` shares tokens with a real instrument
#: item (m2:Q6.3 asks whether a PSA TEST was ever had), while the paper's outcome
#: is the assayed value.
#:
#: THE FIELD IS `instrument_region`, NOT `ascertainment`, and the first attempt
#: at this used the wrong one. They answer different questions: `ascertainment`
#: says how the PAPER measured the outcome, `instrument_region` says where the
#: INSTRUMENT holds it. PMID 38961645 is the case that separates them — its
#: outcomes were ascertained administratively, and the instrument carries them
#: anyway at `m2:Q5 diagnosed conditions`. Refuting on ascertainment discarded a
#: paper the questionnaire can score.
OUTCOME_NOT_IN_THE_INSTRUMENT = "outcome_not_in_the_instrument"

#: C12's missing column: PMID -> the instrument keys that carry that paper's
#: EXPOSURE. Empty, and that emptiness is the finding rather than a stub —
#: `prevalence_key.py` resolved the outcome side and left this one unbuilt, so
#: no paper can reach CONFIRMED on both sides today. Populating this mapping is
#: what makes the benchmark scorable; `scorability_for` reads it with no change.
EXPOSURE_KEYS: dict[str, tuple[str, ...]] = {}


class SideVerdict(NamedTuple):
    """One side of a design line — exposure or outcome — and its evidence.

    Attributes:
        side: `"exposure"` or `"outcome"`.
        terms: The phrases the bibliography's design line names on this side.
        status: `REFUTED`, `CONFIRMED` or `UNDETERMINED`.
        keys: Instrument keys that resolved live with `outcome == "unique"`.
        absent_terms: Terms with no content word anywhere in the instrument.
        blockers: Why this side is not CONFIRMED; empty when it is.
    """

    side: str
    terms: tuple[str, ...]
    status: str
    keys: tuple[str, ...]
    absent_terms: tuple[str, ...]
    blockers: tuple[str, ...]


class PaperScorability(NamedTuple):
    """Whether one benchmark paper can be scored against this instrument.

    Attributes:
        pmid: PubMed identifier, as `cohort_papers.py` records it.
        exposure: The exposure side's verdict.
        outcome: The outcome side's verdict.
        status: `REFUTED` when either side is refuted — the instrument cannot
            supply it and no answer key repairs that. `CONFIRMED` only when both
            sides are confirmed. `UNDETERMINED` otherwise.
        blockers: The union of both sides' blockers, in a stable order.
    """

    pmid: str
    exposure: SideVerdict
    outcome: SideVerdict
    status: str
    blockers: tuple[str, ...]


def exposure_terms(paper: CohortPaper) -> tuple[str, ...]:
    """The exposure side of a bibliography design line.

    The mirror of `benchmark/tier_gate.py::outcome_terms`, and derived from the
    same design string rather than from a new field, so this adds no paper
    content to the repository that `cohort_papers.py` did not already hold.

    Args:
        paper: A paper in the bibliography.

    Returns:
        One string per exposure the line names, empty when the line has no
        exposure-to-outcome arrow. The cohort profile is that case: it is a
        descriptive paper, not an analysis, and has no exposure at all.
    """
    if "->" not in paper.design:
        return ()
    left = paper.design.split("->")[0]
    return tuple(t.strip() for t in re.split(r",|/", left) if t.strip())


#: `prevalence_key.py` rows carry a `role`, and only one of the three is this
#: paper's outcome. Measured 2026-08-28: 31 rows are `outcome`, 9 are
#: `covariate` and 1 is `recruitment`. Reading a covariate key as outcome
#: evidence would confirm a paper on a variable it ADJUSTED FOR — found by
#: inspection on PMID 38715087, whose only keyed row is `prevalent hypertension`
#: as a covariate while its outcome is central hemodynamics.
OUTCOME_ROLE = "outcome"


def outcome_keys_on_record(pmid: str) -> tuple[str, ...]:
    """Instrument keys the held-out prevalence key records as a paper's OUTCOME.

    Args:
        pmid: PubMed identifier.

    Returns:
        Sorted distinct `instrument_key` values from `role == OUTCOME_ROLE`
        rows, empty when the key records none. Not yet evidence: `_confirm_keys`
        decides which of these resolve.
    """
    return tuple(sorted({
        row.instrument_key for row in PREVALENCE_KEY
        if row.pmid == pmid and row.instrument_key
        and row.role == OUTCOME_ROLE}))


#: A region the instrument holds names the module it sits in. Measured
#: 2026-08-29 over all 41 rows: the reachable regions are `m2:Q5 diagnosed
#: conditions`, `m2:Q12 cancer history and screening` and `m2 female medical
#: history`; the unreachable ones say so in words — `clinical measurement, not
#: in the instrument`, `lab registry, declared and EMPTY in v1`, `not in the
#: instrument`, `recruitment, not in the instrument`, `anthropometry, not in the
#: instrument`. Prefix-matching the module is structural where matching that
#: prose would not be, and `test_every_instrument_region_parses` fails if a new
#: value fits neither shape rather than letting it default to unreachable.
_MODULE_PREFIXES = ("m1", "m2", "m3")


def region_is_in_the_instrument(region: str) -> bool:
    """Whether a prevalence-key region names a place inside the instrument.

    Args:
        region: A `prevalence_key.py` row's `instrument_region`.

    Returns:
        True when the region names a module of the questionnaire.
    """
    return region.startswith(_MODULE_PREFIXES)


def outcome_reachable_in_instrument(pmid: str) -> bool | None:
    """Whether the held-out key places this paper's outcome inside the instrument.

    Args:
        pmid: PubMed identifier.

    Returns:
        True when any outcome row sits in a module of the questionnaire, False
        when outcome rows exist and none does, and None when the key holds no
        outcome row for this paper — absence of evidence, which may not be read
        as refutation.
    """
    # A null region is dropped rather than counted as unreachable: the field is
    # Optional in the key, and reading "not recorded" as "not in the instrument"
    # would refute a paper on a blank cell. All 41 rows carry one today.
    regions = [r.instrument_region for r in PREVALENCE_KEY
               if r.pmid == pmid and r.role == OUTCOME_ROLE
               and r.instrument_region]
    if not regions:
        return None
    return any(region_is_in_the_instrument(r) for r in regions)


def _confirm_keys(keys: tuple[str, ...]) -> tuple[tuple[str, ...], list[str]]:
    """Split candidate keys into those that resolve to a variable, and why not.

    Calls the real `env.tools.resolve_variable` and reads the `outcome` field of
    its actual return value, rather than trusting the key was correct when it
    was written. `unique` is the only value that names a variable: the tool's own
    log says a group id is a stem "a protocol may never name", and a construct
    key "is the id the enumeration uses, and a protocol may not name it".

    Args:
        keys: Candidate instrument keys.

    Returns:
        The confirmed keys, and one blocker per key that did not confirm.
    """
    confirmed: list[str] = []
    blockers: list[str] = []
    for key in keys:
        outcome = resolve_variable(key)["outcome"]
        if outcome == "unique":
            confirmed.append(key)
        elif outcome in ("group", "construct"):
            blockers.append(KEY_NAMES_A_CONSTRUCT_NOT_A_VARIABLE)
        else:
            blockers.append(KEY_DOES_NOT_RESOLVE)
    return tuple(confirmed), blockers


def _side(side: str, terms: tuple[str, ...], keys: tuple[str, ...],
          missing_column_blocker: str | None,
          self_reported: bool | None = None) -> SideVerdict:
    """Adjudicate one side of a design line from terms and candidate keys.

    Args:
        side: `"exposure"` or `"outcome"`.
        terms: Phrases the design line names on this side.
        keys: Candidate instrument keys from an answer key, possibly empty.
        missing_column_blocker: The blocker naming an absent answer-key column,
            or None when a column exists for this side.
        self_reported: Outcome side only — `outcome_reachable_in_instrument`'s
            verdict. False refutes on evidence the word test cannot reach.

    Returns:
        The side's verdict, with the evidence that produced it.
    """
    absent = terms_absent_from_instrument(terms)
    blockers: list[str] = []

    if not terms:
        return SideVerdict(side, terms, UNDETERMINED, (), absent,
                           (NO_DESIGN_ARROW,))

    confirmed, key_blockers = _confirm_keys(keys)
    blockers.extend(key_blockers)

    # Refutation is checked before confirmation deliberately. A resolved key on
    # a side the instrument cannot supply is a contradiction in the answer key,
    # not a pass — and surfacing it as REFUTED with the term listed is how a
    # reader finds the bad row.
    if self_reported is False:
        # Checked before the word test because it is the better evidence: the
        # key states WHERE the outcome sits, where the word test only observes
        # token overlap with question wording.
        return SideVerdict(side, terms, REFUTED, confirmed, absent,
                           (OUTCOME_NOT_IN_THE_INSTRUMENT, *blockers))

    if absent and len(absent) == len(terms):
        return SideVerdict(side, terms, REFUTED, confirmed, absent,
                           (_absent_blocker(side), *blockers))

    if confirmed:
        return SideVerdict(side, terms, CONFIRMED, confirmed, absent, ())

    if missing_column_blocker is not None and not keys:
        blockers.append(missing_column_blocker)
    elif not keys:
        blockers.append(KEY_DOES_NOT_RESOLVE)
    return SideVerdict(side, terms, UNDETERMINED, confirmed, absent,
                       tuple(blockers))


def _absent_blocker(side: str) -> str:
    """The blocker naming an instrument that cannot supply this side.

    Args:
        side: `"exposure"` or `"outcome"`.

    Returns:
        The matching blocker constant.
    """
    return (EXPOSURE_ABSENT_FROM_INSTRUMENT if side == "exposure"
            else OUTCOME_ABSENT_FROM_INSTRUMENT)


def scorability_for(paper: CohortPaper) -> PaperScorability:
    """Whether one paper can be scored, and the evidence for the verdict.

    Args:
        paper: A paper in the bibliography.

    Returns:
        The paper's status, both sides' verdicts, and every blocker standing.
    """
    exposure = _side("exposure", exposure_terms(paper),
                     EXPOSURE_KEYS.get(paper.pmid, ()),
                     EXPOSURE_KEY_COLUMN_MISSING)
    outcome = _side("outcome", outcome_terms(paper),
                    outcome_keys_on_record(paper.pmid), None,
                    self_reported=outcome_reachable_in_instrument(paper.pmid))

    if REFUTED in (exposure.status, outcome.status):
        status = REFUTED
    elif exposure.status == CONFIRMED and outcome.status == CONFIRMED:
        status = CONFIRMED
    else:
        status = UNDETERMINED

    seen: list[str] = []
    for blocker in (*exposure.blockers, *outcome.blockers):
        if blocker not in seen:
            seen.append(blocker)
    return PaperScorability(paper.pmid, exposure, outcome, status, tuple(seen))


def scorability_report() -> tuple[PaperScorability, ...]:
    """Every paper in the bibliography, in bibliography order.

    Returns:
        One verdict per paper.
    """
    return tuple(scorability_for(p) for p in COHORT_PAPERS)


def status_counts() -> dict[str, int]:
    """How many papers hold each status.

    The replacement for the underived "about one and a half of sixteen". Read it
    with the file's own limit in view: `CONFIRMED` counts papers whose exposure
    AND outcome resolve to a live variable, which is a stricter claim than the
    prose ever made, and `UNDETERMINED` is a work list, not a soft no.

    Returns:
        Counts keyed by `REFUTED`, `CONFIRMED` and `UNDETERMINED`.
    """
    counts = {REFUTED: 0, CONFIRMED: 0, UNDETERMINED: 0}
    for row in scorability_report():
        counts[row.status] += 1
    return counts
