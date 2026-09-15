"""Pins for `benchmark/prevalence_rows.py` — the prevalence key's own accessors.

These tests MOVED here from `tests/test_scorability.py` when C36 made
`benchmark/design_key.py` the single reader for design (2026-09-14). They did
not change: each asserts something about the prevalence key's own data that is
worth keeping under test, and none of them is a design verdict any more.

They stay guarded because they read the withheld key itself. That is the
irreducible half: `AGENTS.md` §Testing Patterns says split a claim so its
key-free half runs in the clone where prompts are edited, and for these three
there is no key-free half — the subject IS the key's rows.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmark import prevalence_rows as pr  # noqa: E402
from tests.withheld import needs_prevalence_key  # noqa: E402


@needs_prevalence_key
def test_a_covariate_key_is_not_returned_as_outcome_evidence() -> None:
    """A paper is not described by a variable it adjusted for.

    `prevalence_key.py` rows carry `role`, and 9 of them are covariates. PMID
    38715087's only keyed row is `prevalent hypertension` as a COVARIATE, while
    its outcome is central hemodynamics — so reading roles indiscriminately
    would take an adjustment variable as proof the instrument carries the
    outcome. Found by inspection, not by a failing test, which is why it has one
    now.

    Since C36 this accessor no longer feeds a verdict, and the risk it guards
    is smaller for it. It is kept because the filter is still what makes the
    accessor mean what its name says.
    """
    from benchmark.prevalence_key import PREVALENCE_KEY

    covariate_only = {
        r.pmid for r in PREVALENCE_KEY
        if r.instrument_key and r.role != pr.OUTCOME_ROLE}
    assert covariate_only, "fixture assumed the key holds non-outcome rows"
    for pmid in covariate_only:
        keys = pr.outcome_keys_on_record(pmid)
        roles = {r.role for r in PREVALENCE_KEY
                 if r.pmid == pmid and r.instrument_key in keys}
        assert roles <= {pr.OUTCOME_ROLE}, (
            f"{pmid} contributed a {roles - {pr.OUTCOME_ROLE}} key as outcome "
            f"evidence")


@needs_prevalence_key
def test_every_instrument_region_parses() -> None:
    """A new region value must not default silently to unreachable.

    `region_is_in_the_instrument` prefix-matches a module id. A region naming
    neither a module nor its own absence would read as unreachable — which
    refuted a paper on a typo while this fed scoring, and would still make the
    accessor answer a question it had not been asked.
    """
    from benchmark.prevalence_key import PREVALENCE_KEY

    unparsed = sorted({
        r.instrument_region for r in PREVALENCE_KEY
        if not pr.region_is_in_the_instrument(r.instrument_region)
        and "not in the instrument" not in r.instrument_region
        and "EMPTY" not in r.instrument_region})
    assert not unparsed, (
        f"instrument_region values that name neither a module nor their own "
        f"absence: {unparsed}. Decide which they are before anything reads "
        f"them.")


@needs_prevalence_key
def test_where_the_instrument_holds_it_is_not_how_the_paper_measured_it() -> None:
    """`ascertainment` and `instrument_region` answer different questions.

    PMID 38961645 ascertained anxiety, depression and bipolar disorder
    administratively, and the instrument carries all three at `m2:Q5 diagnosed
    conditions`. A first version of the scorer refuted it on `ascertainment !=
    self_report`, discarding a paper the questionnaire can score.

    Since C36 no verdict reads either field, so this is the pin on the
    DISTINCTION rather than on the verdict: the two fields still disagree for
    this paper, and anything that starts reading `ascertainment` as a proxy for
    the other will find that out here.
    """
    from benchmark.prevalence_key import PREVALENCE_KEY

    rows = [r for r in PREVALENCE_KEY
            if r.pmid == "38961645" and r.role == pr.OUTCOME_ROLE]
    assert rows and all(r.ascertainment != "self_report" for r in rows), (
        "fixture assumed a non-self-reported outcome")
    assert pr.outcome_reachable_in_instrument("38961645") is True, (
        "the instrument holds this outcome however the paper ascertained it")
