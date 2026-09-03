"""The gate on a date-based tier comparison. C7's metric is deferred; this is not.

`DESIGN.md` §6 says to run Duan et al.'s vocabulary-overlap diagnostic before
reading any tier gap. That is a guarantee stated in a document and enforced
nowhere, which `AGENTS.md` §Testing Patterns names as this codebase's signature
failure. These tests are the enforcement, and they also re-derive the
measurement the deferral rests on rather than repeating it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import benchmark.tier_gate as TG  # noqa: E402
from benchmark.cohort_papers import COHORT_PAPERS  # noqa: E402

#: Any year between the newest pre-2026 paper and the two 2026 ones. The split
#: is the same for 2024 and 2025, which is itself the point: no choice of cutoff
#: in that range produces a readable comparison.
CUTOFF = 2025


def test_the_post_cutoff_arm_is_empty_of_anything_scorable():
    """The measurement the deferral rests on, re-derived and not repeated.

    Both 2026 papers have outcomes with NO content word anywhere in
    build/dictionary.json — `memory performance` and `cardiovascular
    biomarkers`. Neither is scorable against this instrument, so there is no
    second arm and no gap to read, whatever the diagnostic would have said.
    """
    split = TG.tier_split(CUTOFF)
    assert len(split.members) + len(split.non_members) == len(COHORT_PAPERS)
    assert split.non_members, "no post-cutoff paper at all makes this vacuous"
    assert split.scorable_non_members == (), split.scorable_non_members
    for paper in split.non_members:
        assert TG.outcomes_absent_from_instrument(paper) == TG.outcome_terms(paper)


def test_the_gate_refuses_and_names_what_would_lift_it():
    """A red state that names a defect, not a changed number."""
    with pytest.raises(ValueError) as exc:
        TG.assert_gate_clear(TG.tier_split(CUTOFF))
    message = str(exc.value)
    assert TG.NON_MEMBER_ARM_EMPTY in message
    assert TG.VOCABULARY_OVERLAP_UNDIAGNOSED in message
    assert "2402.07841" in message, "the reader must be able to find the paper"


def test_the_overlap_blocker_stands_even_with_a_scorable_arm(monkeypatch):
    """Filling the corpus does not by itself make a tier gap readable.

    The two blockers are independent: Duan's objection is about how the two sets
    were constructed, and it survives a bigger corpus. A gate that went green
    the moment a post-cutoff paper appeared would be the wrong gate.
    """
    scorable = next(p for p in COHORT_PAPERS
                    if TG.outcome_terms(p)
                    and not TG.outcomes_absent_from_instrument(p))
    monkeypatch.setattr(TG, "COHORT_PAPERS", (scorable._replace(year=2027),))
    split = TG.tier_split(CUTOFF)
    assert split.scorable_non_members, "the fixture did not produce an arm"
    assert split.blockers == (TG.VOCABULARY_OVERLAP_UNDIAGNOSED,)
    with pytest.raises(ValueError, match=r"2402\.07841"):
        TG.assert_gate_clear(split)


def test_the_cutoff_has_no_default():
    """`build_registry(mode)`'s rule, for the same reason.

    A default would let a caller take a tier gap without stating which model's
    cutoff it is a gap against — and agent/RUNNING.md records a target model
    that publishes none at all.
    """
    import inspect

    sig = inspect.signature(TG.tier_split)
    assert sig.parameters["cutoff_year"].default is inspect.Parameter.empty


def test_absence_is_reported_and_presence_never_is():
    """The conservative direction, pinned.

    `screening` occurs in the instrument and says nothing about whether the CRC
    item exists, so a term with a word present is NOT thereby measurable. This
    function reports absence only, and a reader who inverts it is wrong.
    """
    crc = next(p for p in COHORT_PAPERS if p.pmid == "37252073")
    assert "CRC screening" in TG.outcome_terms(crc)
    assert "CRC screening" not in TG.outcomes_absent_from_instrument(crc)
    from benchmark.input_leakage import instrument_text
    assert "screening" in instrument_text()
    # The cohort profile has no arrow, so it names no outcome and is not
    # silently treated as one with an absent outcome.
    profile = next(p for p in COHORT_PAPERS if p.pmid == "32938600")
    assert TG.outcome_terms(profile) == ()
    assert TG.outcomes_absent_from_instrument(profile) == ()


def test_the_phrase_search_that_the_old_measurement_used_is_an_or(monkeypatch):
    """Why the gate reads the dictionary instead of calling search_variables.

    The previous statement of "the tier set is empty" rested on five phrase
    searches. `search_variables` rewrites a phrase to an FTS `OR` of its words,
    so a two-word query never tests for the phrase: `green space` returns one
    hit and that hit is m1:Q2.5, "What is your phone number?", matched on
    `spaces`. Absence of evidence from that tool needs the decomposition read
    first.
    """
    from env.tools import search_variables

    assert search_variables(phrase="greenspace")["n"] == 0
    hits = search_variables(phrase="green space")["hits"]
    assert [h["key"] for h in hits] == ["m1:Q2.5"]
    assert "phone number" in hits[0]["excerpt"].lower()
