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

So the verdicts rest on different evidence and are not each other's negation.
FOUR of them since the operator decided C35 on 2026-09-14:

    REFUTED      the instrument cannot supply this side, on either of two
                 pieces of evidence. (a) A `not_in_instrument` ANCHOR: a
                 recorded item-level read of the questionnaire, filed against
                 the design-line phrase it refutes. (b) No content word of any
                 term occurs anywhere in the built instrument — conservative
                 and one-directional, since a common word makes this refuse
                 LESS often, never more, so a false REFUTED needs the
                 instrument to carry none of the term's words. (a) outranks (b)
                 because it is the better evidence: the word test is what
                 admitted four papers on `chicago`, `individual`, `household`
                 and `community`.
    CONFIRMED    EVERY term the design line names on this side is answered by
                 an anchor whose authority said yes — `resolve_variable` with
                 `outcome == "unique"` for a `variable`, `get_derivation` for a
                 `derivation`. Positive evidence is still only ever a live
                 lookup, and it is the same discipline
                 `benchmark/calibration_set.py` uses: read the field of the
                 tool's ACTUAL return value that forces the verdict, never a
                 hand-typed status beside a row that looks right. One term may
                 carry several keys and one resolving key answers it.
    BLOCKED_ON   an `area_measure` anchor sits on this side. C35 answer C: no
    _DELIVERY    authority in this repository resolves an area measure, and the
                 `area_measure_inventory` delivery would change that. Not
                 REFUTED, which would claim the inventory can never arrive; not
                 UNDETERMINED, which would imply this repository could settle
                 it. Ranked above CONFIRMED — part of the design being out of
                 scope is not repaired by the rest of it resolving — and above
                 REFUTED-(b), the word test, because an area measure is never
                 in the instrument by construction, so word absence restates
                 the kind rather than adding evidence. It is ranked BELOW
                 REFUTED-(a), a recorded item-level read, which is a fact about
                 the instrument no delivery repairs.
    UNDETERMINED none of the above. The honest majority, and a work list rather
                 than a verdict.

WHY NOTHING IS SCORABLE TODAY, AND WHAT WOULD CHANGE IT. Confirming needs a
resolved anchor per term per side, and `benchmark/design_key.py` holds the
anchors. It is WITHHELD from every clone but the scoring one
(`contamination_check.py::WITHHELD_MODULES`), so `scorability_for` raises here
rather than returning a verdict — which is the point of C36. The column it
replaces, `EXPOSURE_KEYS`, lived in THIS file, in the clone where prompts,
`agent/schema.py` docstrings and `env/tools.py` are edited; that was safe only
while it was empty, and the first row would have made the editing clone the
clone holding the rediscovery answers.

MEASURED 2026-09-14 in the scoring clone, BEFORE C36, and the number that
motivated it: 10 REFUTED, 0 CONFIRMED, 6 UNDETERMINED, every refutation on the
outcome side. Three papers had a CONFIRMED outcome and exactly one blocker,
`exposure_key_column_missing` — which read as "nobody filled this in" for three
exposures that are area-level and that no key column could ever have carried.
Re-run it; do not quote it.

THE GUARANTEE, AND ITS TEST. A paper is `scorable` only when both sides are
CONFIRMED, and CONFIRMED is unreachable without a live-resolved anchor per
term. So this module cannot report a paper scorable on word evidence, today or
after anyone edits the term lists. `tests/test_scorability.py::
test_word_presence_alone_can_never_make_a_paper_scorable` pins it, and
`test_a_key_that_names_a_construct_is_not_a_confirmed_variable` pins the case
that a key resolving to a battery is not a variable — `resolve_variable`'s own
log says a protocol may never name a stem.

ONE READER FOR DESIGN. The strongest objection to C36 is that it creates a
SECOND answer key, and two keys that can disagree about one paper's outcome are
worse than one key with a blank cell. The mitigation is exclusivity, not care:
this module does not import `benchmark.prevalence_key` and does not import
`benchmark.prevalence_rows`, where the prevalence key's design-shaped accessors
now live, and `tests/test_scorability.py` fails if either import appears.

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
from benchmark.design_anchor import (
    AREA_MEASURE,
    AREA_MEASURE_INVENTORY,
    DERIVATION,
    DERIVATION_OK,
    NOT_IN_INSTRUMENT,
    RESOLVED,
    VARIABLE,
    Anchor,
    DesignKeyRow,
)
from benchmark.instrument_terms import terms_absent_from_instrument
from benchmark.tier_gate import outcome_terms
from env.tools import get_derivation, resolve_variable

#: The three verdicts a side of a design line can carry. Not a bool: the whole
#: point of the file is that "not refuted" and "confirmed" are different states
#: reached by different evidence.
REFUTED = "refuted"
CONFIRMED = "confirmed"
UNDETERMINED = "undetermined"
#: The FOURTH verdict, added 2026-09-14 by the operator's C35 decision. An
#: area-measure exposure is out of scope EXPLICITLY, not unfilled: no authority
#: in this repository resolves one, and the `area_measure_inventory` delivery
#: would change that. REFUTED would claim the inventory can never arrive;
#: UNDETERMINED would imply this repository could settle it. Neither is true, so
#: the honest answer is a third state — the same three-way shape
#: `benchmark/contamination_check.py`'s exit status uses, and the same shape
#: `NO_KEY_TO_RESOLVE` vs `KEY_DOES_NOT_RESOLVE` already splits on this side.
BLOCKED_ON_DELIVERY = "blocked_on_delivery"

#: Named so a caller sees which problem it has, in the style of
#: `benchmark/tier_gate.py`'s blockers — a named refusal instead of a number.
NO_DESIGN_ARROW = "no_design_arrow"
EXPOSURE_ABSENT_FROM_INSTRUMENT = "exposure_absent_from_instrument"
OUTCOME_ABSENT_FROM_INSTRUMENT = "outcome_absent_from_instrument"
#: Renamed from `exposure_key_column_missing` on 2026-09-14 (C36), and the old
#: name is the defect this file already carried: with one key column per side,
#: the strongest thing the exposure side could ever say was "nobody filled this
#: in", for an exposure that is not in the instrument at all. MEASURED
#: 2026-09-14, that is exactly why three unreachable papers presented as one
#: paste from CONFIRMED. Both sides now read one table, so the blocker means
#: what it says: the design key holds no row for this paper. An exposure the
#: instrument does not carry gets `EXPOSURE_NOT_IN_THE_INSTRUMENT` instead.
NO_DESIGN_KEY_ROW = "no_design_key_row"
#: Renamed from `outcome_key_unresolved` on 2026-08-29. It is raised for either
#: side, and the old name reported an EXPOSURE key that did not resolve as an
#: outcome problem — in a constant whose own comment says it exists "so a caller
#: sees which problem it has".
KEY_DOES_NOT_RESOLVE = "key_does_not_resolve"
#: Nothing was supplied on this side, so nothing was looked up. Split out of
#: KEY_DOES_NOT_RESOLVE on 2026-09-14 for the same reason that constant was
#: itself renamed from `outcome_key_unresolved`: a blocker exists "so a caller
#: sees which problem it has", and one string was covering two problems.
#: `KEY_DOES_NOT_RESOLVE` means a key WAS supplied and `resolve_variable`
#: rejected it. This means there was no key to reject, and reporting that as a
#: failed lookup asserts a negative result the module never obtained — the one
#: thing `AGENTS.md` §Verification Discipline refuses.
#:
#: NAMED FOR THE KEY, NOT THE ROW, and the first attempt got that wrong. It was
#: `no_key_row_for_this_paper` for half an hour, which is a THIRD false claim of
#: the same kind. MEASURED 2026-09-14 on PMIDs 38397711 and 38961645:
#: `outcome_keys_on_record` returns zero for both, AND
#: `outcome_reachable_in_instrument` returns True for both — so a key ROW does
#: exist for each, carrying an `instrument_region` inside the questionnaire, and
#: it is the `instrument_key` CELL that is empty. Those two outcomes are
#: fillable, not absent, and a blocker saying "no key row" would have hidden a
#: task behind a word.
NO_KEY_TO_RESOLVE = "no_key_to_resolve"
KEY_NAMES_A_CONSTRUCT_NOT_A_VARIABLE = "key_names_a_construct_not_a_variable"
#: A `derivation` anchor naming a file `curated/derivations/` does not hold. The
#: kind exists because there is no single "physical activity" item — there are
#: 30 — and hundreds of defensible ways to combine them, so a derivation is a
#: signed, reviewable object and naming an unsigned one is an inline recipe
#: wearing a reference's clothes (`agent/schema.py::DerivationRef`).
DERIVATION_NOT_SIGNED = "derivation_not_signed"
#: A phrase the design line names that no anchor answers. The side cannot be
#: CONFIRMED on the anchors that ARE there: confirming part of a design and
#: reporting the whole side confirmed is how one resolved key came to stand for
#: an exposure the instrument does not carry.
TERM_HAS_NO_ANCHOR = "term_has_no_anchor"
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
#: SINCE C36 THE EVIDENCE IS AN ANCHOR, NOT A REGION. The paragraph above
#: describes where this verdict used to come from: the prevalence key's
#: `instrument_region`, prefix-matched against the questionnaire's module names.
#: It now comes from a `not_in_instrument` anchor — a recorded item-level read
#: of the instrument, filed against the design-line phrase it refutes. The
#: reason is the one the paragraph above already gives: the region field answers
#: a question about the PREVALENCE key's layout, and reading it for design made
#: that key a second design authority.
OUTCOME_NOT_IN_THE_INSTRUMENT = "outcome_not_in_the_instrument"
#: The counterpart the exposure side never had, and its absence was a filed
#: defect: `OUTCOME_NOT_IN_THE_INSTRUMENT` came from a column that existed only
#: on the outcome side, so the strongest statement available about an exposure
#: the instrument does not carry was "nobody filled this in". One table with
#: typed anchors gives both sides the same vocabulary.
EXPOSURE_NOT_IN_THE_INSTRUMENT = "exposure_not_in_the_instrument"


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



def design_key_row(pmid: str) -> DesignKeyRow | None:
    """The design-arrow key's row for one paper, or None when it holds none.

    Args:
        pmid: PubMed identifier.

    Returns:
        The row, or None when the key carries no row for this paper. None is
        "no row", not "no key": in a clone without the key this raises instead,
        because reporting a missing table as a missing row would assert a
        negative result the module never obtained.

    Raises:
        ModuleNotFoundError: In every clone but the scoring one.
    """
    # Deferred, not module-level: `benchmark/design_key.py` is withheld
    # (`contamination_check.py::WITHHELD_MODULES`). At module scope this import
    # took `benchmark.contamination_check` -- the MANDATORY gate after any
    # prompt or convention edit -- down with ModuleNotFoundError on every other
    # clone, so the check could not run where the code it checks is written.
    # That is why the prevalence-key import was deferred too; the reason did
    # not change when the table did.
    from benchmark.design_key import DESIGN_KEY

    # Annotated rather than iterated directly: the withheld module is
    # `follow_imports = "skip"` in `pyproject.toml`, so `DESIGN_KEY` is `Any`
    # here and returning an element of it would be an untyped return.
    rows: tuple[DesignKeyRow, ...] = DESIGN_KEY
    for row in rows:
        if row.pmid == pmid:
            return row
    return None


def _resolve_anchor(anchor: Anchor) -> tuple[str | None, str | None]:
    """Ask the authority `anchor.kind` names, and report what it said.

    THIS IS WHAT `kind` BUYS. A bare key string has one implied authority,
    `resolve_variable`, so a derivation id sent through it fails as a malformed
    key and an area measure is unrepresentable. The kind selects, and nothing
    is inferred from the string's shape.

    Each branch reads the `outcome` field of the tool's ACTUAL return value
    rather than trusting the key was right when it was written -- the same
    discipline `benchmark/calibration_set.py` uses.

    Args:
        anchor: The anchor to resolve.

    Returns:
        The confirmed key and None, or None and one blocker. Both are None for
        `not_in_instrument`, which the caller handles: it is a refutation, and
        there is no lookup to make.
    """
    if anchor.kind == VARIABLE:
        outcome = resolve_variable(anchor.key or "")["outcome"]
        if outcome == RESOLVED:
            return anchor.key, None
        if outcome in ("group", "construct"):
            return None, KEY_NAMES_A_CONSTRUCT_NOT_A_VARIABLE
        return None, KEY_DOES_NOT_RESOLVE

    if anchor.kind == DERIVATION:
        if get_derivation(anchor.key or "")["outcome"] == DERIVATION_OK:
            return anchor.key, None
        return None, DERIVATION_NOT_SIGNED

    if anchor.kind == AREA_MEASURE:
        # No resolver exists, by construction and by decision. C35 answer C:
        # the blocker is the DELIVERY the anchor names, in the shape
        # `env/tools.py::estimate_n` already uses -- null, plus a named
        # blocker. Answer D, confirming on the descriptor alone, is refused in
        # `design_anchor.py::validate_design_key`, and this branch is why: a
        # key here would reach no authority at all.
        return None, anchor.blocked_on or AREA_MEASURE_INVENTORY

    return None, None


def _confirm_anchors(
        anchors: tuple[Anchor, ...]) -> tuple[tuple[str, ...], list[str]]:
    """Resolve every anchor on one side.

    Args:
        anchors: That side's anchors.

    Returns:
        The confirmed keys, and one blocker per anchor that did not confirm.
    """
    confirmed: list[str] = []
    blockers: list[str] = []
    for anchor in anchors:
        key, blocker = _resolve_anchor(anchor)
        if key is not None:
            confirmed.append(key)
        elif blocker is not None:
            blockers.append(blocker)
    return tuple(confirmed), blockers


def _unanswered_terms(terms: tuple[str, ...],
                      anchors: tuple[Anchor, ...]) -> tuple[str, ...]:
    """Design-line phrases no CONFIRMING anchor answers.

    THE REASON THE RULE IS "EVERY TERM", NOT "ANY KEY". Before C36 a side
    confirmed on any one resolving key, because a bare key tuple could not say
    which phrase a key answered. It can now, so the weaker rule is no longer
    the best available: a side naming two exposures, one of them absent from the
    instrument, would confirm on the other. A term may carry SEVERAL keys and
    one is enough for that term -- the operator's decided row for 38961645
    splits one phrase across two instrument labels.

    Args:
        terms: Phrases the design line names on this side.
        anchors: That side's anchors.

    Returns:
        The terms with no confirming anchor, in the design line's order.
    """
    answered = {a.term for a in anchors if _resolve_anchor(a)[0] is not None}
    return tuple(t for t in terms if t not in answered)


def _side(side: str, terms: tuple[str, ...],
          anchors: tuple[Anchor, ...] | None) -> SideVerdict:
    """Adjudicate one side of a design line from its terms and its anchors.

    `self_reported=` GONE, and with it the last read of the prevalence key on
    this path. An anchor's `kind` states directly what
    `prevalence_rows.outcome_reachable_in_instrument` inferred from a region
    string's module prefix, so the two keys can no longer disagree about one
    paper's outcome.

    Args:
        side: `"exposure"` or `"outcome"`.
        terms: Phrases the design line names on this side.
        anchors: That side's anchors, or None when the design key holds no row
            for this paper at all. None and `()` are different facts: the
            second is a row with an empty side, which
            `design_anchor.validate_design_key` complains about.

    Returns:
        The side's verdict, with the evidence that produced it.
    """
    absent = terms_absent_from_instrument(terms)

    if not terms:
        return SideVerdict(side, terms, UNDETERMINED, (), absent,
                           (NO_DESIGN_ARROW,))

    if anchors is None:
        # No row. The word test is one-directional and can still refute, which
        # is the one thing it is sound for.
        if absent and len(absent) == len(terms):
            return SideVerdict(side, terms, REFUTED, (), absent,
                               (_absent_blocker(side),))
        return SideVerdict(side, terms, UNDETERMINED, (), absent,
                           (NO_DESIGN_KEY_ROW,))

    confirmed, blockers = _confirm_anchors(anchors)

    # Refutation is checked before confirmation deliberately. A resolved key on
    # a side the instrument cannot supply is a contradiction in the answer key,
    # not a pass — and surfacing it as REFUTED with the term listed is how a
    # reader finds the bad row.
    if any(a.kind == NOT_IN_INSTRUMENT for a in anchors):
        # A RECORDED ITEM-LEVEL READ, which is the upgrade over the word test
        # that admitted four papers on `chicago`, `individual`, `household` and
        # `community`. Checked before the word test because it is the better
        # evidence, exactly as the region field was before it.
        return SideVerdict(side, terms, REFUTED, confirmed, absent,
                           (_not_in_instrument_blocker(side), *blockers))

    if any(a.kind == AREA_MEASURE for a in anchors):
        # C35 answer C. Ranked above CONFIRMED (part of the design being out of
        # scope is not repaired by the rest of it resolving), below REFUTED-on-
        # an-item-level-read, and — the ordering that was wrong until
        # 2026-09-14 — ABOVE THE WORD TEST.
        #
        # An area measure is a linked place-based measure and is therefore
        # never in the instrument BY CONSTRUCTION. So "no content word of this
        # phrase occurs anywhere in the built instrument" restates what `kind`
        # already said; it is not additional evidence. Refuting on it claims
        # the `area_measure_inventory` can never arrive, which is the exact
        # overstatement C35 answer C exists to remove.
        #
        # MEASURED on the case that found this: filed as an `area_measure`,
        # 42034153's exposure `residential greenspace` is word-absent, so the
        # word test fired first and the side read REFUTED — the old
        # `exposure_key_column_missing` failure wearing the other costume. The
        # word-test blocker is still reported when it applies, because the
        # observation is true; it just does not decide the status.
        if absent and len(absent) == len(terms):
            blockers.append(_absent_blocker(side))
        return SideVerdict(side, terms, BLOCKED_ON_DELIVERY, confirmed, absent,
                           tuple(blockers))

    if absent and len(absent) == len(terms):
        return SideVerdict(side, terms, REFUTED, confirmed, absent,
                           (_absent_blocker(side), *blockers))

    if not anchors:
        # A row exists with nothing on this side. Not KEY_DOES_NOT_RESOLVE:
        # there is no key here to have resolved.
        return SideVerdict(side, terms, UNDETERMINED, confirmed, absent,
                           (NO_KEY_TO_RESOLVE,))

    if not _unanswered_terms(terms, anchors):
        return SideVerdict(side, terms, CONFIRMED, confirmed, absent,
                           tuple(blockers))

    if not blockers:
        blockers.append(TERM_HAS_NO_ANCHOR)
    return SideVerdict(side, terms, UNDETERMINED, confirmed, absent,
                       tuple(blockers))


def _absent_blocker(side: str) -> str:
    """The blocker naming an instrument whose WORDS cannot supply this side.

    Args:
        side: `"exposure"` or `"outcome"`.

    Returns:
        The matching blocker constant.
    """
    return (EXPOSURE_ABSENT_FROM_INSTRUMENT if side == "exposure"
            else OUTCOME_ABSENT_FROM_INSTRUMENT)


def _not_in_instrument_blocker(side: str) -> str:
    """The blocker naming a recorded item-level read that refutes this side.

    Args:
        side: `"exposure"` or `"outcome"`.

    Returns:
        The matching blocker constant.
    """
    return (EXPOSURE_NOT_IN_THE_INSTRUMENT if side == "exposure"
            else OUTCOME_NOT_IN_THE_INSTRUMENT)


def scorability_for(paper: CohortPaper) -> PaperScorability:
    """Whether one paper can be scored, and the evidence for the verdict.

    Both sides read ONE table. Before C36 the exposure side read a key column
    in this file and the outcome side read the prevalence key, so the two could
    disagree about one paper and nothing picked between them.

    Args:
        paper: A paper in the bibliography.

    Returns:
        The paper's status, both sides' verdicts, and every blocker standing.

    Raises:
        ModuleNotFoundError: In every clone but the scoring one.
    """
    row = design_key_row(paper.pmid)
    exposure = _side("exposure", exposure_terms(paper),
                     row.exposure if row else None)
    outcome = _side("outcome", outcome_terms(paper),
                    row.outcome if row else None)

    statuses = (exposure.status, outcome.status)
    if REFUTED in statuses:
        status = REFUTED
    elif BLOCKED_ON_DELIVERY in statuses:
        # Ranked below REFUTED and above everything else. An instrument that
        # cannot supply a side is a fact about the instrument; a missing
        # delivery is a fact about this repository, and the first outranks the
        # second because no delivery repairs it.
        status = BLOCKED_ON_DELIVERY
    elif statuses == (CONFIRMED, CONFIRMED):
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
        Counts keyed by `REFUTED`, `CONFIRMED`, `UNDETERMINED` and
        `BLOCKED_ON_DELIVERY`. Four keys since C35 was decided; a caller
        summing three of them is dropping papers.

    Raises:
        ModuleNotFoundError: In every clone but the scoring one.
    """
    counts = {REFUTED: 0, CONFIRMED: 0, UNDETERMINED: 0,
              BLOCKED_ON_DELIVERY: 0}
    for row in scorability_report():
        counts[row.status] += 1
    return counts
