"""Pins for benchmark/scorability.py.

The guarantee under test is the one the module's docstring states: a paper may
reach `scorable` only on a live-resolved instrument key, never on the presence
of a word. That distinction is not academic — the module docstring records four
papers the word test admits, three of them on a single common English word.
"""
from __future__ import annotations

import pytest

from benchmark import scorability as sc
from benchmark.cohort_papers import COHORT_PAPERS, CohortPaper
from benchmark.tier_gate import outcomes_absent_from_instrument


def _paper(pmid: str) -> CohortPaper:
    return next(p for p in COHORT_PAPERS if p.pmid == pmid)


def test_word_presence_alone_can_never_make_a_paper_scorable():
    """The central guarantee: no confirmed key, no scorable paper.

    `EXPOSURE_KEYS` is empty today, so every paper must fall to REFUTED or
    UNDETERMINED. A future edit that promotes word presence to evidence — the
    exact mistake this file exists to prevent — turns this red.
    """
    for row in sc.scorability_report():
        if row.status == sc.CONFIRMED:
            # Stated so it survives C12 populating EXPOSURE_KEYS, which is the
            # project's next act: a guard that fires on normal operation gets
            # disabled by whoever it annoys (AGENTS.md §Testing Patterns). The
            # guarantee is not "nothing is scorable" but "nothing is scorable
            # without a resolved key on both sides".
            assert row.exposure.keys and row.outcome.keys, (
                f"{row.pmid} is CONFIRMED with exposure keys "
                f"{row.exposure.keys} and outcome keys {row.outcome.keys}. Word "
                f"presence is not evidence: 'household PM2.5' survives the word "
                f"test on 'household' alone.")


def test_a_populated_exposure_key_is_what_flips_a_paper(monkeypatch):
    """Seeded failure, the positive half: fill C12's column and it works.

    PMID 36702470's outcome side is already CONFIRMED by a live-resolved key.
    Giving it a real exposure key must flip the paper to CONFIRMED, or the
    module is a check that cannot pass.
    """
    assert sc.outcome_keys_on_record("36702470") == ("m2:Q5.2",), (
        "fixture assumed 36702470's outcome resolves to m2:Q5.2")

    monkeypatch.setattr(sc, "EXPOSURE_KEYS", {"36702470": ("m2:Q5.8",)})
    row = sc.scorability_for(_paper("36702470"))
    assert row.status == sc.CONFIRMED, row
    assert row.exposure.keys == ("m2:Q5.8",)
    assert row.blockers == ()


def test_a_key_that_does_not_resolve_confirms_nothing(monkeypatch):
    """Seeded failure, the negative half: a plausible key is not a resolved key.

    The failure `resolve_variable`'s own log names — "a key that resolves while
    naming the wrong construct is the failure mode with no automated detector" —
    starts with keys nobody checked. This checks them.
    """
    monkeypatch.setattr(sc, "EXPOSURE_KEYS", {"36702470": ("m2:Q999.9",)})
    row = sc.scorability_for(_paper("36702470"))
    assert row.status != sc.CONFIRMED
    assert sc.KEY_DOES_NOT_RESOLVE in row.exposure.blockers, row.exposure


def test_a_key_that_names_a_construct_is_not_a_confirmed_variable(monkeypatch):
    """A battery id is a stem, and a protocol may never name a stem.

    `resolve_variable` returns `group` or `construct` for those, and treating
    either as confirmation would let the answer key point at a question nobody
    can answer.
    """
    construct = _a_construct_key()
    monkeypatch.setattr(sc, "EXPOSURE_KEYS", {"36702470": (construct,)})
    row = sc.scorability_for(_paper("36702470"))
    assert row.status != sc.CONFIRMED
    assert sc.KEY_NAMES_A_CONSTRUCT_NOT_A_VARIABLE in row.exposure.blockers


def _a_construct_key() -> str:
    """A key `resolve_variable` classifies as a construct or group, found live."""
    from env.tools import resolve_variable
    for paper_key in ("m1:Q2.2", "m2:Q5.15", "m1:Q6.2"):
        if resolve_variable(paper_key)["outcome"] in ("group", "construct"):
            return paper_key
    pytest.skip("no construct/group key found to test with")


def test_there_is_only_one_word_test_in_the_repository():
    """The drift this replaces was invisible to the test written to catch it.

    Two copies existed and an agreement test compared them to each other, so
    raising MIN_CONTENT_WORD from 4 to 5 in one copy left all 348 tests green —
    it pinned the shared bug. Extraction is the fix; this asserts the extraction
    holds rather than comparing two implementations again.
    """
    import benchmark.tier_gate as tg
    from benchmark import instrument_terms

    assert tg.terms_absent_from_instrument is (
        instrument_terms.terms_absent_from_instrument)
    assert not hasattr(tg, "_MIN_WORD"), (
        "tier_gate grew a local word-length constant again")
    assert not hasattr(sc, "MIN_CONTENT_WORD"), (
        "scorability grew a local word-length constant again")
    # And the behaviour they must share, on the case that exposed the bug.
    for paper in COHORT_PAPERS:
        assert (outcomes_absent_from_instrument(paper)
                == instrument_terms.terms_absent_from_instrument(
                    sc.scorability_for(paper).outcome.terms)), paper.pmid


def test_the_cohort_profile_has_no_exposure_and_says_so():
    """A descriptive paper is not an analysis, and must not read as refuted."""
    row = sc.scorability_for(_paper("32938600"))
    assert row.exposure.terms == ()
    assert sc.NO_DESIGN_ARROW in row.blockers
    assert row.status == sc.UNDETERMINED


def test_every_paper_gets_a_verdict_and_a_reason():
    """No silent pass: a paper that is not confirmed must name a blocker."""
    report = sc.scorability_report()
    assert len(report) == len(COHORT_PAPERS)
    for row in report:
        if row.status != sc.CONFIRMED:
            assert row.blockers, f"{row.pmid} is unscorable for no stated reason"
    assert sum(sc.status_counts().values()) == len(COHORT_PAPERS)


def test_scorability_is_named_in_the_holdout_registry():
    """It carries published pairings, so a copy on a tool path must be caught."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "benchmark" / "contamination_check.py"
    assert '"scorability.py"' in src.read_text(), (
        "check_holdout_not_reachable no longer names scorability.py; a copy "
        "under curated/ or agent/ would go undetected")


def test_a_covariate_key_is_not_outcome_evidence():
    """A paper is not confirmed on a variable it adjusted for.

    `prevalence_key.py` rows carry `role`, and 9 of them are covariates. PMID
    38715087's only keyed row is `prevalent hypertension` as a COVARIATE, while
    its outcome is central hemodynamics — so reading roles indiscriminately
    would take an adjustment variable as proof the instrument carries the
    outcome. Found by inspection, not by a failing test, which is why it has one
    now.
    """
    from benchmark.prevalence_key import PREVALENCE_KEY

    covariate_only = {
        r.pmid for r in PREVALENCE_KEY
        if r.instrument_key and r.role != sc.OUTCOME_ROLE}
    assert covariate_only, "fixture assumed the key holds non-outcome rows"
    for pmid in covariate_only:
        keys = sc.outcome_keys_on_record(pmid)
        roles = {r.role for r in PREVALENCE_KEY
                 if r.pmid == pmid and r.instrument_key in keys}
        assert roles <= {sc.OUTCOME_ROLE}, (
            f"{pmid} contributed a {roles - {sc.OUTCOME_ROLE}} key as outcome "
            f"evidence")


def test_either_side_refuted_makes_the_whole_paper_refuted():
    """The aggregation rule, which no test constrained.

    Weakening `REFUTED in (exposure, outcome)` to `and` left all 348 tests green
    and moved the published headline from 8 refuted to 3 — the same way "about
    one and a half" went stale, in the commit that replaced it. A paper whose
    exposure the instrument cannot supply is not half-scorable.
    """
    row = sc.scorability_for(_paper("32542493"))
    assert row.outcome.status == sc.REFUTED
    assert row.exposure.status != sc.REFUTED
    assert row.status == sc.REFUTED, (
        "one refuted side is enough; this paper's outcome is absent from the "
        "instrument and no answer key repairs that")


def test_a_resolved_key_on_an_absent_side_still_refutes(monkeypatch):
    """Refutation is checked before confirmation, and that was a comment only.

    Moving the confirmation branch above the absence check left all 348 tests
    green. The case is unreachable on today's data, which is exactly why it
    needs a constructed one: a key that resolves on a side the instrument cannot
    supply is a contradiction in the answer key, and it must surface as REFUTED
    with the term named rather than being waved through as confirmed.
    """
    absent_side = _paper("42034153")           # exposure 'residential greenspace'
    monkeypatch.setattr(sc, "EXPOSURE_KEYS", {"42034153": ("m2:Q5.8",)})
    row = sc.scorability_for(absent_side)
    assert row.exposure.status == sc.REFUTED, row.exposure
    assert "residential greenspace" in row.exposure.absent_terms


def test_a_paper_the_instrument_carries_is_not_refuted_by_how_it_was_measured():
    """`ascertainment` is not `instrument_region`, and confusing them refutes wrongly.

    PMID 38961645 ascertained anxiety, depression and bipolar disorder
    administratively, and the instrument carries all three at `m2:Q5 diagnosed
    conditions`. A first version of this module refuted it on `ascertainment !=
    self_report`, discarding a paper the questionnaire can score.
    """
    from benchmark.prevalence_key import PREVALENCE_KEY

    rows = [r for r in PREVALENCE_KEY
            if r.pmid == "38961645" and r.role == sc.OUTCOME_ROLE]
    assert rows and all(r.ascertainment != "self_report" for r in rows), (
        "fixture assumed a non-self-reported outcome")
    assert sc.outcome_reachable_in_instrument("38961645") is True
    assert sc.scorability_for(_paper("38961645")).status != sc.REFUTED


def test_every_instrument_region_parses():
    """A new region value must not default silently to unreachable.

    `region_is_in_the_instrument` prefix-matches a module id. A region naming
    neither a module nor its own absence would read as unreachable and refute a
    paper on a typo.
    """
    from benchmark.prevalence_key import PREVALENCE_KEY

    unparsed = sorted({
        r.instrument_region for r in PREVALENCE_KEY
        if not sc.region_is_in_the_instrument(r.instrument_region)
        and "not in the instrument" not in r.instrument_region
        and "EMPTY" not in r.instrument_region})
    assert not unparsed, (
        f"instrument_region values that name neither a module nor their own "
        f"absence: {unparsed}. Decide which they are before they refute a paper.")
