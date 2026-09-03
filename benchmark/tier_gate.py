"""benchmark/tier_gate.py — the gate on a date-based tier comparison, not the metric.

C7 ASKED FOR DUAN ET AL.'S VOCABULARY-OVERLAP DIAGNOSTIC. THIS IS NOT IT, AND
THE ARGUMENT FOR THAT IS THE POINT OF THE FILE.

What C7 wanted. Duan et al. (arXiv 2402.07841 §4, body read) find that
*"decision thresholds derived using temporally-shifted non-members end up
testing for temporal shift rather than membership"*, the mechanism being
vocabulary drift measured as seven-gram overlap falling 39.3% -> 13.9%. Their
recommendation is to compare the vocabulary-overlap distributions of the two
paper sets before reading any gap, and `DESIGN.md` §6 already tells a reader to
do exactly that.

WHY THE METRIC IS PREMATURE AND THE GATE IS NOT. Three measurements, all
2026-08-28:

  1. THE COMPARISON HAS NO SECOND ARM. Splitting `COHORT_PAPERS` at any cutoff
     in 2025 puts fourteen papers before and two after. Both of the two —
     PMID 42034153 (`residential greenspace -> memory performance`) and
     PMID 41883377 (`PM2.5 components -> cardiovascular biomarkers`) — have
     outcomes with NO content word anywhere in `build/dictionary.json`, so
     neither is scorable against this instrument and the post-cutoff arm is
     empty of anything a gap could be read from. `outcomes_absent_from_instrument`
     below re-derives that from the bibliography rather than from a hand-picked
     search list; the previous statement of it rested on searching five terms,
     and one of those searches was misleading (see the note on `green space`).

  2. THERE IS NO TEXT TO COMPUTE SEVEN-GRAMS OVER. `cohort_papers.py` carries a
     one-line design per paper and says in its own docstring that expanding it
     is C12's job. A seven-gram set over a ten-word line has at most four
     members, and the overlap between two such sets is zero for reasons that
     have nothing to do with vocabulary drift. A diagnostic built on that
     returns 0.0 against 0.0 and cannot fail — and `AGENTS.md` §Testing
     Patterns: a check that cannot fail is not evidence. Making it real means
     importing paper full text into the repository, which is a decision about
     the contamination boundary and not a lane's to take.

  3. THE TARGET MODEL MAY PUBLISH NO CUTOFF AT ALL. `agent/RUNNING.md` records,
     INHERITED, that Qwen3 publishes none and that every benchmark paper
     therefore collapses to one tier. That is a property of a model card, not a
     thing this file can fix, and it means `cutoff_year` can never have a
     default here.

So: the metric is deferred and the PRECONDITION is enforced. `DESIGN.md` §6's
"run their vocabulary-overlap diagnostic before reading any gap" is a guarantee
stated in a document and enforced nowhere, which is this codebase's signature
failure. `tier_split` names the blockers; `assert_gate_clear` raises on them. The
next person to compute a tier gap gets a named refusal telling them which of
three things to build first, instead of a number.

WHAT WOULD LIFT EACH BLOCKER, so this is a to-do and not a wall:

    non_member_arm_empty            C12, plus papers whose outcomes the
                                    instrument actually carries
    vocabulary_overlap_undiagnosed  the Duan diagnostic, over real paper text
    cutoff_not_stated_by_model_card the target model's published cutoff

A NOTE ON THE MEASUREMENT THIS REPLACES. The claim "searching `greenspace`
returns 0 hits" is right; `search_variables('green space')` returns 1, and that
hit is `m1:Q2.5`, "What is your phone number?". `env/tools.py::search_variables`
rewrites a phrase to an FTS `OR` of its words, so `space` matched `spaces` in
that item and a two-word query never tests for the phrase. Absence of evidence
from that tool needs the decomposition read first, which is why the check here
reads the built dictionary directly.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from benchmark.cohort_papers import COHORT_PAPERS, CohortPaper
from benchmark.instrument_terms import terms_absent_from_instrument

#: Named so a caller sees which of three different problems it has.
NON_MEMBER_ARM_EMPTY = "non_member_arm_empty"
VOCABULARY_OVERLAP_UNDIAGNOSED = "vocabulary_overlap_undiagnosed"

class TierSplit(NamedTuple):
    """A date-based member/non-member split, with what is wrong with it.

    Attributes:
        cutoff_year: The year the split was taken at. Supplied, never defaulted.
        members: Papers first public at or before the cutoff.
        non_members: Papers first public after it.
        scorable_non_members: The subset of `non_members` whose outcome the
            instrument could plausibly carry. The arm a gap would be read from.
        blockers: Reasons this split may not be read as a membership signal.
            Empty means the gate is clear, which it is not today.
    """

    cutoff_year: int
    members: tuple[CohortPaper, ...]
    non_members: tuple[CohortPaper, ...]
    scorable_non_members: tuple[CohortPaper, ...]
    blockers: tuple[str, ...]


def outcome_terms(paper: CohortPaper) -> tuple[str, ...]:
    """The outcome side of a bibliography design line.

    Derived from the design string rather than from a new field, so this adds no
    paper content to the repository — `cohort_papers.py` already carries the
    line and its docstring defers any expansion to C12.

    Args:
        paper: A paper in the bibliography.

    Returns:
        One string per outcome the line names, empty when the line has no
        exposure-to-outcome arrow (the cohort profile is the case).
    """
    if "->" not in paper.design:
        return ()
    right = paper.design.split("->")[-1].split(";")[0]
    return tuple(t.strip() for t in re.split(r",|/", right) if t.strip())


def outcomes_absent_from_instrument(paper: CohortPaper) -> tuple[str, ...]:
    """Outcome terms with no content word anywhere in the built instrument.

    CONSERVATIVE, and its limit is the reason it is phrased this way: a term with
    a word present is NOT thereby measurable — `screening` occurs in the
    instrument and says nothing about whether the CRC item exists — so this
    reports absence and never presence. That is enough for the only question it
    is asked, which is whether the post-cutoff arm has anything in it.

    Args:
        paper: A paper in the bibliography.

    Returns:
        The terms for which the instrument carries no word at all.
    """
    # The word test moved to benchmark/instrument_terms.py on 2026-08-29, and
    # the move IS the fix: the copy here dropped tokens under four characters,
    # so `serum PSA` refuted while the instrument carried a PSA item. A second
    # copy in scorability.py drifted from this one undetected because the test
    # written to catch drift compared the two copies rather than either against
    # the instrument.
    return terms_absent_from_instrument(outcome_terms(paper))


def tier_split(cutoff_year: int) -> TierSplit:
    """Split the bibliography at a cutoff, and say why the split cannot be read.

    `cutoff_year` has NO DEFAULT, for the same reason `build_registry(mode)` has
    none: a default would let a caller take a tier gap without ever stating which
    model's cutoff it is a gap against, and `agent/RUNNING.md` records a target
    model that publishes none at all.

    Args:
        cutoff_year: Last year counted as inside the model's training data.

    Returns:
        The split, its scorable non-member arm, and its blockers.
    """
    members = tuple(p for p in COHORT_PAPERS if p.year <= cutoff_year)
    non_members = tuple(p for p in COHORT_PAPERS if p.year > cutoff_year)
    scorable = tuple(p for p in non_members
                     if outcome_terms(p) and not outcomes_absent_from_instrument(p))

    blockers = [VOCABULARY_OVERLAP_UNDIAGNOSED]
    if not scorable:
        blockers.insert(0, NON_MEMBER_ARM_EMPTY)
    return TierSplit(cutoff_year, members, non_members, scorable, tuple(blockers))


def assert_gate_clear(split: TierSplit) -> None:
    """Refuse to let a tier gap be read while any blocker stands.

    Args:
        split: A split from `tier_split`.

    Raises:
        ValueError: Whenever `split.blockers` is non-empty, naming each blocker
            and what would lift it. Always today.
    """
    if not split.blockers:
        return
    lifts = {
        NON_MEMBER_ARM_EMPTY:
            f"{len(split.non_members)} paper(s) fall after {split.cutoff_year} "
            f"and none has an outcome this instrument carries, so there is "
            f"nothing to read a gap from. Lifted by C12 plus a post-cutoff "
            f"paper the questionnaire can score.",
        VOCABULARY_OVERLAP_UNDIAGNOSED:
            "Duan et al. arXiv 2402.07841 §4: a temporally shifted comparison "
            "can test temporal shift rather than membership. Their diagnostic "
            "is a seven-gram overlap over paper TEXT, which this repository "
            "does not hold — cohort_papers.py carries one design line per "
            "paper. Lifted by building the diagnostic over real text.",
    }
    raise ValueError(
        "a date-based tier gap may not be read yet:\n"
        + "\n".join(f"  {b}: {lifts[b]}" for b in split.blockers))
