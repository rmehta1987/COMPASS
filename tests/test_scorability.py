"""Pins for benchmark/scorability.py.

The guarantee under test is the one the module's docstring states: a paper may
reach `scorable` only on a live-resolved instrument key, never on the presence
of a word. That distinction is not academic — the module docstring records four
papers the word test admits, three of them on a single common English word.

MOST OF THIS FILE IS KEY-FREE SINCE C36, and that is the change worth noting.
Before it, the outcome side came from the withheld prevalence key, so twelve
tests here carried a guard and did not run in the clone where prompts,
conventions and `env/tools.py` are edited. Both sides now read one table
through `scorability.design_key_row`, which a test can substitute — so the
verdicts are checkable HERE, against anchors built in the test. Only
`test_word_presence_alone_can_never_make_a_paper_scorable` still needs the real
key, because its subject is the real bibliography's real rows.

The prevalence key's own accessors moved to `benchmark/prevalence_rows.py` and
their tests to `tests/test_prevalence_rows.py`, unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmark import design_anchor as da  # noqa: E402
from benchmark import scorability as sc  # noqa: E402
from benchmark.cohort_papers import COHORT_PAPERS, CohortPaper  # noqa: E402
from benchmark.tier_gate import outcomes_absent_from_instrument  # noqa: E402
from tests.withheld import needs_design_key  # noqa: E402


def _paper(pmid: str) -> CohortPaper:
    return next(p for p in COHORT_PAPERS if p.pmid == pmid)


def _anchors(terms: tuple[str, ...], kind: str,
             keys: tuple[str, ...] = ()) -> tuple[da.Anchor, ...]:
    """One anchor per design-line term, all of one kind.

    The terms come from the paper's own design line rather than being typed, so
    a fixture cannot drift from the phrases `_side` is adjudicating — and no
    published phrase is written into this file.

    Args:
        terms: The side's design-line phrases.
        kind: The kind to give every anchor.
        keys: Keys, positionally matched to `terms`. Required for the kinds
            that carry one.

    Returns:
        The anchors.
    """
    blocked = (da.AREA_MEASURE_INVENTORY if kind == da.AREA_MEASURE else None)
    return tuple(
        da.Anchor(term, kind,  # type: ignore[arg-type]
                  key=keys[i] if i < len(keys) else None,
                  blocked_on=blocked)
        for i, term in enumerate(terms))


def _row(paper: CohortPaper, exposure: tuple[da.Anchor, ...],
         outcome: tuple[da.Anchor, ...]) -> da.DesignKeyRow:
    """A design-key row for one paper.

    Args:
        paper: The paper.
        exposure: Exposure-side anchors.
        outcome: Outcome-side anchors.

    Returns:
        The row.
    """
    return da.DesignKeyRow(paper.pmid, exposure, outcome,
                           provenance="fixture", filled_by="test")


def _serve(monkeypatch: pytest.MonkeyPatch,
           row: da.DesignKeyRow | None) -> None:
    """Substitute the withheld design key with one row, or with no row at all.

    Patching the reader rather than a table means the withheld module is never
    imported, which is what keeps these tests key-free.

    Args:
        monkeypatch: pytest's patcher.
        row: The row to serve for every pmid, or None for "the key holds no row
            for this paper".
    """
    monkeypatch.setattr(sc, "design_key_row",
                        lambda pmid: row if row and row.pmid == pmid else None)


#: Candidate keys for the fixtures below. Not a paper's: every one is checked
#: live, so a build that stops resolving one skips rather than passing.
_CANDIDATES = ("m2:Q5.8", "m2:Q5.2", "m3:Q16.1_1", "m3:Q16.2", "m3:Q16.3",
               "m3:Q16.1_2")


def _resolving_keys(n: int = 1) -> tuple[str, ...]:
    """`n` DISTINCT keys `resolve_variable` calls `unique`, found live.

    Distinct, because a row repeating a key is one the table's own validator
    rejects (`design_anchor.validate_design_key`) -- a fixture that would not
    survive validation is testing a shape the operator cannot paste.

    Args:
        n: How many keys are needed.

    Returns:
        `n` resolving keys.
    """
    from env.tools import resolve_variable
    found = tuple(k for k in _CANDIDATES
                  if resolve_variable(k)["outcome"] == da.RESOLVED)
    if len(found) < n:
        pytest.skip(f"need {n} resolving keys, found {len(found)}")
    return found[:n]


def _resolving_key() -> str:
    """One key `resolve_variable` calls `unique`.

    Returns:
        One resolving instrument key.
    """
    return _resolving_keys(1)[0]


def _construct_key() -> str:
    """A key `resolve_variable` classifies as a construct or group, found live.

    Returns:
        One construct or group key.
    """
    from env.tools import resolve_variable
    for key in ("m1:Q2.2", "m2:Q5.15", "m1:Q6.2"):
        if resolve_variable(key)["outcome"] in ("group", "construct"):
            return key
    pytest.skip("no construct/group key found to test with")


# --- the central guarantee --------------------------------------------------- #


@needs_design_key
def test_word_presence_alone_can_never_make_a_paper_scorable() -> None:
    """The central guarantee: no confirmed key, no scorable paper.

    A future edit that promotes word presence to evidence — the exact mistake
    this file exists to prevent — turns this red. Stated so it survives the
    design key being populated, which is the project's next act: a guard that
    fires on normal operation gets disabled by whoever it annoys (`AGENTS.md`
    §Testing Patterns). The guarantee is not "nothing is scorable" but "nothing
    is scorable without a resolved key on both sides".

    The one test here that still needs the real key: its subject is the real
    bibliography's real rows, so there is no key-free half.
    """
    for row in sc.scorability_report():
        if row.status == sc.CONFIRMED:
            assert row.exposure.keys and row.outcome.keys, (
                f"{row.pmid} is CONFIRMED with exposure keys "
                f"{row.exposure.keys} and outcome keys {row.outcome.keys}. Word "
                f"presence is not evidence: 'household PM2.5' survives the word "
                f"test on 'household' alone.")


def test_a_populated_design_key_is_what_flips_a_paper(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Seeded failure, the positive half: fill the key and it works.

    A checker that can never pass is not a checker. Both sides are given
    resolving `variable` anchors against the paper's own design-line terms, and
    the paper must reach CONFIRMED with no blocker standing.
    """
    paper = _paper("36702470")
    exposure = sc.exposure_terms(paper)
    outcome = sc.outcome_terms(paper)
    assert exposure and outcome, "fixture assumed a paper with both sides"
    keys = _resolving_keys(len(exposure) + len(outcome))
    _serve(monkeypatch, _row(
        paper,
        _anchors(exposure, da.VARIABLE, keys[:len(exposure)]),
        _anchors(outcome, da.VARIABLE, keys[len(exposure):])))
    row = sc.scorability_for(paper)
    assert row.status == sc.CONFIRMED, row
    assert row.exposure.keys == keys[:len(exposure)]
    assert row.blockers == ()


def test_a_key_that_does_not_resolve_confirms_nothing(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The negative half. A key is evidence only once the tool accepts it."""
    paper = _paper("36702470")
    terms = sc.exposure_terms(paper)
    _serve(monkeypatch, _row(
        paper,
        _anchors(terms, da.VARIABLE,
                 tuple(f"m2:Q999.{i}" for i in range(len(terms)))), ()))
    row = sc.scorability_for(paper)
    assert row.status != sc.CONFIRMED
    assert sc.KEY_DOES_NOT_RESOLVE in row.exposure.blockers
    assert row.exposure.keys == ()


def test_a_key_that_names_a_construct_is_not_a_confirmed_variable(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A battery id is a stem, and a protocol may never name a stem.

    `resolve_variable` returns `group` or `construct` for those, and treating
    either as confirmation would let the answer key point at a question nobody
    can answer.
    """
    paper = _paper("36702470")
    terms = sc.exposure_terms(paper)
    construct = _construct_key()
    _serve(monkeypatch, _row(
        paper, (da.Anchor(terms[0], da.VARIABLE, key=construct),), ()))
    row = sc.scorability_for(paper)
    assert row.status != sc.CONFIRMED
    assert sc.KEY_NAMES_A_CONSTRUCT_NOT_A_VARIABLE in row.exposure.blockers


def test_a_derivation_anchor_is_confirmed_by_its_signed_file(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """`kind` selects the resolver, which is the whole point of typing it.

    A derivation id is not a KEY_PATTERN key, so before C36 the only column
    available would have sent it to `resolve_variable` and reported a malformed
    key. Its authority is `get_derivation`, and an unsigned one is an inline
    recipe wearing a reference's clothes.
    """
    from env.tools import get_derivation

    signed = next((d for d in ("met_hours_week", "social_cohesion_scale")
                   if get_derivation(d)["outcome"] == da.DERIVATION_OK), None)
    if signed is None:
        pytest.skip("no signed derivation in this tree")
    paper = _paper("36702470")
    terms = sc.exposure_terms(paper)
    _serve(monkeypatch, _row(
        paper, (da.Anchor(terms[0], da.DERIVATION, key=signed),), ()))
    assert sc.scorability_for(paper).exposure.status != sc.REFUTED
    assert signed in sc.scorability_for(paper).exposure.keys

    _serve(monkeypatch, _row(
        paper, (da.Anchor(terms[0], da.DERIVATION, key="no_such_file"),), ()))
    side = sc.scorability_for(paper).exposure
    assert side.status != sc.CONFIRMED
    assert sc.DERIVATION_NOT_SIGNED in side.blockers


# --- C35's third status ------------------------------------------------------ #


def test_an_area_measure_exposure_is_blocked_on_delivery_not_undetermined(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator's C35 decision, as behaviour.

    REFUTED would claim the `area_measure_inventory` can never arrive;
    UNDETERMINED would imply this repository could settle it. Neither is true,
    so the side takes a third status and the blocker names the delivery.
    """
    paper = _paper("36702470")
    terms = sc.exposure_terms(paper)
    outcome = sc.outcome_terms(paper)
    _serve(monkeypatch, _row(
        paper, _anchors(terms, da.AREA_MEASURE),
        _anchors(outcome, da.VARIABLE, _resolving_keys(len(outcome)))))
    row = sc.scorability_for(paper)
    assert row.exposure.status == sc.BLOCKED_ON_DELIVERY, row.exposure
    assert da.AREA_MEASURE_INVENTORY in row.exposure.blockers, (
        "the blocker must name the delivery, in the shape estimate_n uses")
    assert row.status == sc.BLOCKED_ON_DELIVERY, (
        "a confirmed outcome does not repair an out-of-scope exposure")
    assert row.status not in (sc.UNDETERMINED, sc.REFUTED)


def test_an_area_measure_never_reaches_confirmed_however_much_else_resolves(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """C35 answer D, refused at the verdict as well as at the validator.

    A side carrying one resolving variable and one area measure is not
    confirmed. Confirming it would be the word-presence failure in a new
    costume: the area half would be asserted by nothing.
    """
    paper = _paper("36702470")
    terms = sc.exposure_terms(paper)
    if len(terms) < 2:
        pytest.skip("need a two-term exposure side")
    mixed = (da.Anchor(terms[0], da.VARIABLE, key=_resolving_key()),
             da.Anchor(terms[1], da.AREA_MEASURE,
                       blocked_on=da.AREA_MEASURE_INVENTORY))
    _serve(monkeypatch, _row(paper, mixed, ()))
    side = sc.scorability_for(paper).exposure
    assert side.status == sc.BLOCKED_ON_DELIVERY, side
    assert side.status != sc.CONFIRMED


def test_a_word_absent_area_measure_is_blocked_on_delivery_not_refuted(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The ordering defect a dry run of the first real rows found.

    An area measure is a linked place-based measure and is therefore never in
    the instrument BY CONSTRUCTION, so the word test observing that no content
    word of the phrase occurs anywhere restates what `kind` already says. While
    the word test outranked the anchor, filing 42034153's `residential
    greenspace` as an `area_measure` produced REFUTED -- "never scorable here",
    the exact overstatement C35 answer C exists to remove, and the old
    `exposure_key_column_missing` failure in the other costume.

    The paper is chosen because its exposure is word-absent: this case is
    unreachable on a term the instrument shares a token with, which is why the
    three papers that motivated C35 did not expose it.
    """
    paper = _paper("42034153")
    terms = sc.exposure_terms(paper)
    absent = sc.terms_absent_from_instrument(terms)
    assert absent and len(absent) == len(terms), (
        "fixture assumed an exposure the word test refutes; without that this "
        "test cannot distinguish the two orderings")
    _serve(monkeypatch, _row(paper, _anchors(terms, da.AREA_MEASURE), ()))
    side = sc.scorability_for(paper).exposure
    assert side.status == sc.BLOCKED_ON_DELIVERY, side
    assert side.status != sc.REFUTED, (
        "word absence may not refute a side the answer key has recorded as an "
        "area measure; a delivery could still supply it")
    assert da.AREA_MEASURE_INVENTORY in side.blockers
    assert sc.EXPOSURE_ABSENT_FROM_INSTRUMENT in side.blockers, (
        "the word-test observation is true and must still be reported; it "
        "just does not decide the status")


def test_a_recorded_read_outranks_an_area_measure_on_the_same_side(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """REFUTED-(a) stays above BLOCKED_ON_DELIVERY, and only that one does.

    A recorded item-level read is a fact about the instrument that no delivery
    repairs, so a side carrying both must refute. Without this, raising the
    area-measure branch above the word test could have carried it above the
    recorded read too.
    """
    paper = _paper("42034153")
    terms = sc.exposure_terms(paper)
    mixed = (da.Anchor(terms[0], da.NOT_IN_INSTRUMENT),
             da.Anchor("a second phrase", da.AREA_MEASURE,
                       blocked_on=da.AREA_MEASURE_INVENTORY))
    _serve(monkeypatch, _row(paper, mixed, ()))
    side = sc.scorability_for(paper).exposure
    assert side.status == sc.REFUTED, side


def test_status_counts_carries_the_fourth_status(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller summing three keys would drop papers.

    The stop condition `AGENTS.md` §Verify current state names is a FALLING
    test count; a status quietly missing from this dict is the same class of
    silent loss, and the sum is what `test_every_paper_gets_a_verdict_and_a_
    reason` checks against the bibliography.
    """
    keys = {sc.REFUTED, sc.CONFIRMED, sc.UNDETERMINED, sc.BLOCKED_ON_DELIVERY}
    assert len(keys) == 4, "the four verdicts must be four distinct strings"
    _serve(monkeypatch, None)
    assert set(sc.status_counts()) == keys, (
        "status_counts must key every verdict scorability_for can return, or "
        "it raises KeyError on the first paper that reaches the missing one")


# --- every term, not any key ------------------------------------------------- #


def test_one_resolving_key_does_not_confirm_a_two_term_side(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The rule C36 tightened, and the reason `term` is load-bearing.

    Before C36 a side confirmed on ANY resolving key, because a bare key tuple
    could not say which phrase a key answered. A side naming two exposures
    would then confirm on one of them — reporting the whole design recovered on
    half the evidence. A term may still carry several keys; what may not happen
    is a term carrying none.
    """
    paper = _paper("36702470")
    terms = sc.exposure_terms(paper)
    if len(terms) < 2:
        pytest.skip("need a two-term exposure side")
    _serve(monkeypatch, _row(
        paper, (da.Anchor(terms[0], da.VARIABLE, key=_resolving_key()),), ()))
    side = sc.scorability_for(paper).exposure
    assert side.status != sc.CONFIRMED, side
    assert sc.TERM_HAS_NO_ANCHOR in side.blockers, (
        f"{terms[1]!r} is unanswered and the blocker must say so")


def test_one_term_confirmed_by_either_of_two_keys(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator's decided depression row, as a verdict.

    One phrase, two instrument labels, and the side confirms. A rule requiring
    one key per term would have made the decided row unscorable.
    """
    paper = _paper("36702470")
    terms = sc.exposure_terms(paper)
    keys = _resolving_keys(len(terms))
    doubled = tuple(a for i, t in enumerate(terms) for a in
                    (da.Anchor(t, da.VARIABLE, key=keys[i]),
                     da.Anchor(t, da.VARIABLE, key=f"m2:Q999.{i}")))
    _serve(monkeypatch, _row(paper, doubled, ()))
    side = sc.scorability_for(paper).exposure
    assert side.status == sc.CONFIRMED, side
    assert sc.KEY_DOES_NOT_RESOLVE in side.blockers, (
        "the failed lookup is still reported; it just does not unconfirm a "
        "term another anchor answers")


# --- the word test, and the one thing it is sound for ------------------------ #


def test_there_is_only_one_word_test_in_the_repository() -> None:
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


def test_the_one_word_test_behaves_the_same_on_every_paper(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The behaviour the two copies must share, on the case that exposed the bug."""
    from benchmark import instrument_terms

    _serve(monkeypatch, None)
    for paper in COHORT_PAPERS:
        assert (outcomes_absent_from_instrument(paper)
                == instrument_terms.terms_absent_from_instrument(
                    sc.scorability_for(paper).outcome.terms)), paper.pmid


def test_the_cohort_profile_has_no_exposure_and_says_so(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A descriptive paper is not an analysis, and must not read as refuted."""
    _serve(monkeypatch, None)
    row = sc.scorability_for(_paper("32938600"))
    assert row.exposure.terms == ()
    assert sc.NO_DESIGN_ARROW in row.blockers
    assert row.status == sc.UNDETERMINED


def test_every_paper_gets_a_verdict_and_a_reason(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """No silent pass: a paper that is not confirmed must name a blocker."""
    _serve(monkeypatch, None)
    report = sc.scorability_report()
    assert len(report) == len(COHORT_PAPERS)
    for row in report:
        if row.status != sc.CONFIRMED:
            assert row.blockers, f"{row.pmid} is unscorable for no stated reason"
    assert sum(sc.status_counts().values()) == len(COHORT_PAPERS)


def test_scorability_is_named_in_the_holdout_registry() -> None:
    """It carries published pairings, so a copy on a tool path must be caught."""
    src = ROOT / "benchmark" / "contamination_check.py"
    assert '"scorability.py"' in src.read_text(), (
        "check_holdout_not_reachable no longer names scorability.py; a copy "
        "under curated/ or agent/ would go undetected")


# --- the aggregation rule ---------------------------------------------------- #


def test_either_side_refuted_makes_the_whole_paper_refuted(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The aggregation rule, which no test constrained.

    Weakening `REFUTED in (exposure, outcome)` to `and` left all 348 tests green
    and moved the published headline from 8 refuted to 3 — the same way "about
    one and a half" went stale, in the commit that replaced it. A paper whose
    exposure the instrument cannot supply is not half-scorable.
    """
    paper = _paper("36702470")
    exposure = sc.exposure_terms(paper)
    outcome = sc.outcome_terms(paper)
    _serve(monkeypatch, _row(
        paper,
        _anchors(exposure, da.VARIABLE, _resolving_keys(len(exposure))),
        _anchors(outcome, da.NOT_IN_INSTRUMENT)))
    row = sc.scorability_for(paper)
    assert row.exposure.status == sc.CONFIRMED
    assert row.outcome.status == sc.REFUTED
    assert row.status == sc.REFUTED, (
        "one refuted side is enough; an outcome the instrument cannot carry is "
        "not repaired by a resolved exposure")


def test_refuted_outranks_blocked_on_delivery(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """An instrument that cannot supply a side outranks a missing delivery.

    The first is a fact about the instrument and no delivery repairs it; the
    second is a fact about this repository. Ranking them the other way would
    report a paper as waiting on the study team when the questionnaire settles
    it.
    """
    paper = _paper("36702470")
    _serve(monkeypatch, _row(
        paper, _anchors(sc.exposure_terms(paper), da.AREA_MEASURE),
        _anchors(sc.outcome_terms(paper), da.NOT_IN_INSTRUMENT)))
    assert sc.scorability_for(paper).status == sc.REFUTED


def test_a_recorded_item_level_read_refutes_on_either_side(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The filed defect C36 closes: the exposure side had no such blocker.

    `OUTCOME_NOT_IN_THE_INSTRUMENT` came from a column that existed only on the
    outcome side, so the strongest thing the exposure side could ever say was
    "nobody filled this in" — for an exposure that is not in the instrument at
    all. MEASURED 2026-09-14: that is exactly why three unreachable papers
    presented as one paste from CONFIRMED.
    """
    paper = _paper("36702470")
    for side, blocker in (("exposure", sc.EXPOSURE_NOT_IN_THE_INSTRUMENT),
                          ("outcome", sc.OUTCOME_NOT_IN_THE_INSTRUMENT)):
        terms = (sc.exposure_terms(paper) if side == "exposure"
                 else sc.outcome_terms(paper))
        other = (sc.outcome_terms(paper) if side == "exposure"
                 else sc.exposure_terms(paper))
        absent = _anchors(terms, da.NOT_IN_INSTRUMENT)
        resolved = _anchors(other, da.VARIABLE, _resolving_keys(len(other)))
        _serve(monkeypatch, _row(
            paper, absent if side == "exposure" else resolved,
            resolved if side == "exposure" else absent))
        row = sc.scorability_for(paper)
        assert getattr(row, side).status == sc.REFUTED
        assert blocker in row.blockers, (
            f"the {side} side must be able to say the instrument does not "
            f"carry it, not merely that nobody filled the row in")


def test_a_resolved_key_on_a_word_absent_side_still_refutes(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Refutation is checked before confirmation, and that was a comment only.

    Moving the confirmation branch above the absence check left all 348 tests
    green. A key that resolves on a side the instrument cannot supply is a
    contradiction in the answer key, and it must surface as REFUTED with the
    term named rather than being waved through as confirmed.
    """
    paper = _paper("42034153")           # exposure 'residential greenspace'
    terms = sc.exposure_terms(paper)
    _serve(monkeypatch, _row(
        paper, _anchors(terms, da.VARIABLE, _resolving_keys(len(terms))), ()))
    row = sc.scorability_for(paper)
    assert row.exposure.status == sc.REFUTED, row.exposure
    assert "residential greenspace" in row.exposure.absent_terms


# --- absence is not a failed lookup ------------------------------------------ #
#
# Key-free, as they were before C36: `_side` is pure.

#: A term the instrument plainly carries, so `_side` reaches the blocker branch
#: instead of short-circuiting to REFUTED on the word test. Not a paper's term.
LIVE_TERM = ("cigarettes",)


def test_a_side_with_no_key_does_not_claim_a_lookup_failed() -> None:
    """No key supplied means no lookup happened, and the blocker must say so.

    MEASURED 2026-09-14: both papers reporting `key_does_not_resolve` on the
    outcome side had ZERO keys, so nothing had been looked up. One string was
    covering "a key was rejected" and "there was no key", and only the first
    is a result. The blocker is named for the missing KEY and not a missing
    ROW, because the same measurement showed the rows DO exist with an
    in-instrument region and an empty key cell.
    """
    v = sc._side("outcome", LIVE_TERM, ())
    assert v.status == sc.UNDETERMINED
    assert sc.NO_KEY_TO_RESOLVE in v.blockers
    assert sc.KEY_DOES_NOT_RESOLVE not in v.blockers, (
        "no key was supplied, so no key failed to resolve; saying otherwise "
        "asserts a negative result the module never obtained")


def test_a_supplied_key_that_is_rejected_still_says_so() -> None:
    """The other half of the split, or the rename loses a real failure."""
    v = sc._side("outcome", LIVE_TERM,
                 (da.Anchor(LIVE_TERM[0], da.VARIABLE, key="m2:Q999.9"),))
    assert sc.KEY_DOES_NOT_RESOLVE in v.blockers
    assert sc.NO_KEY_TO_RESOLVE not in v.blockers


def test_the_two_blockers_are_mutually_exclusive() -> None:
    """They describe opposite situations; a side carrying both is incoherent."""
    for keys in ((), ("m2:Q999.9",), ("m3:Q5.5",)):
        anchors = tuple(da.Anchor(LIVE_TERM[0], da.VARIABLE, key=k)
                        for k in keys)
        got = set(sc._side("outcome", LIVE_TERM, anchors).blockers)
        assert not {sc.KEY_DOES_NOT_RESOLVE,
                    sc.NO_KEY_TO_RESOLVE} <= got, keys


def test_a_missing_row_and_an_empty_side_are_different_facts() -> None:
    """`None` is "the key holds no row"; `()` is "a row with nothing here".

    Collapsing them would report a table nobody has filled and a row filled
    wrong as the same problem, which is the distinction `NO_KEY_TO_RESOLVE` was
    split out to preserve one level down.
    """
    missing = sc._side("outcome", LIVE_TERM, None)
    empty = sc._side("outcome", LIVE_TERM, ())
    assert sc.NO_DESIGN_KEY_ROW in missing.blockers
    assert sc.NO_KEY_TO_RESOLVE not in missing.blockers
    assert sc.NO_KEY_TO_RESOLVE in empty.blockers
    assert sc.NO_DESIGN_KEY_ROW not in empty.blockers


# --- one reader for design --------------------------------------------------- #


def test_nothing_on_the_scoring_path_reads_the_prevalence_key() -> None:
    """C36's strongest objection, mitigated by enforcement rather than care.

    C36 creates a SECOND answer key, and two keys that can disagree about one
    paper's outcome are worse than one key with a blank cell. The mitigation is
    exclusivity: `design_key.py` is the only reader for design. Nothing enforces
    that unless a test does, so this reads the source of both modules on the
    scoring path and fails if either reaches the prevalence key — directly, or
    through `benchmark/prevalence_rows.py` where its design-shaped accessors
    now live.
    """
    for module in ("scorability.py", "rediscovery.py"):
        src = (ROOT / "benchmark" / module).read_text()
        for line in src.splitlines():
            stripped = line.strip()
            if not (stripped.startswith("import ")
                    or stripped.startswith("from ")):
                continue
            for banned in ("benchmark.prevalence_key",
                           "benchmark.prevalence_rows"):
                assert banned not in stripped, (
                    f"benchmark/{module} imports {banned} at {stripped!r}. "
                    f"Since C36 the design key is the only reader for design; "
                    f"a second reader can disagree with it about one paper and "
                    f"nothing picks between them.")


# --- the key-free ceiling ----------------------------------------------------- #
#
# Key-free by construction: `_side` is pure, and `key_free_ceiling` reads the
# bibliography's design lines and the built instrument, never a key.

#: A term no content word of which the instrument carries, so the word test
#: refutes on it. Synthetic: no published phrase belongs in this file, and the
#: property under test is about the ORDER of `_side`'s branches, not about any
#: paper. Asserted absent below rather than assumed.
_WORD_ABSENT = ("synthetic unobtainium exposure",)


@pytest.mark.parametrize("kind", da.ANCHOR_KINDS)
def test_a_word_refuted_side_never_reaches_confirmed_whatever_the_key_says(
        kind: str) -> None:
    """No answer-key row can lift a word-refuted side to CONFIRMED.

    This is what makes `key_free_ceiling` a ceiling rather than a guess, and it
    has to hold for EVERY anchor kind: `not_in_instrument` refutes, an
    `area_measure` takes `BLOCKED_ON_DELIVERY`, and the word test refutes the
    rest -- three different branches, all of them above the CONFIRMED branch.
    Parametrised over `ANCHOR_KINDS` rather than over the three names, so a
    fifth kind is tested the day it is added instead of being quietly exempt.
    """
    from benchmark.instrument_terms import terms_absent_from_instrument

    assert terms_absent_from_instrument(_WORD_ABSENT) == _WORD_ABSENT, (
        "the instrument now carries a word of this synthetic term; pick another")

    keys = _resolving_keys(1) if kind == da.VARIABLE else ()
    if kind == da.DERIVATION:
        from env.tools import get_derivation

        signed = next((d for d in ("met_hours_week", "social_cohesion_scale")
                       if get_derivation(d)["outcome"] == da.DERIVATION_OK), None)
        if signed is None:
            pytest.skip("no signed derivation in this tree")
        keys = (signed,)

    for side in ("exposure", "outcome"):
        # Every anchor shape a row can take on this side, plus the two shapes
        # that are not a row at all.
        for anchors in (None, (), _anchors(_WORD_ABSENT, kind, keys)):
            verdict = sc._side(side, _WORD_ABSENT, anchors)
            assert verdict.status != sc.CONFIRMED, (
                f"{side} with {kind!r} anchors={anchors!r} reached CONFIRMED on "
                f"a term the instrument carries no word of")

    # Anti-vacuity: the same anchors on a term the instrument DOES carry must
    # still be able to confirm, or the loop above proves only that `_side`
    # never confirms.
    if kind == da.VARIABLE:
        live = sc._side("exposure", LIVE_TERM, _anchors(LIVE_TERM, kind, keys))
        assert live.status == sc.CONFIRMED, live


def test_the_ceiling_excludes_exactly_the_papers_side_cannot_confirm() -> None:
    """`key_free_ceiling` must agree with the adjudicator, not restate it.

    The count is read off `_side` itself -- the function `scorability_for`
    calls -- driven with NO ROW, which is the state every clone without
    `benchmark/design_key.py` is in. A ceiling derived from a second copy of
    the rule would go green while the rule moved underneath it.

    No oracle: the input is the paper's design line and the built instrument,
    which is what a clone without the key has.
    """
    c = sc.key_free_ceiling()
    assert c.papers == len(COHORT_PAPERS)
    # Anti-vacuity, both ends: a ceiling of 0 or of everything would satisfy
    # the agreement check below without saying anything.
    assert 0 < c.ceiling < c.papers, c

    # THE BEST ROW ANYONE COULD FILL: one live-resolving variable anchor per
    # term. If `_side` will not confirm on that, no key row confirms it, and
    # that is the whole content of the word "ceiling". Asking instead whether
    # `_side` REFUTES with no row is an ORACLE -- it reads `NO_DESIGN_ARROW`
    # back off the thing under test, and it went green when the no-arrow
    # exclusion was deleted from `key_free_ceiling`.
    keys = _resolving_keys(3)
    for row in c.rows:
        paper = _paper(row.pmid)
        statuses = {}
        for side, terms in (("exposure", sc.exposure_terms(paper)),
                            ("outcome", sc.outcome_terms(paper))):
            assert len(terms) <= len(keys), (
                f"{row.pmid} names {len(terms)} terms on {side} and only "
                f"{len(keys)} resolving keys are available")
            best = _anchors(terms, da.VARIABLE, keys[:len(terms)])
            statuses[side] = sc._side(side, terms, best).status
        assert row.confirmable == all(v == sc.CONFIRMED
                                      for v in statuses.values()), (
            f"{row.pmid}: ceiling says confirmable={row.confirmable} while "
            f"_side on the best possible row says {statuses} "
            f"(blockers={row.blockers})")

    assert c.ceiling == sum(1 for r in c.rows if r.confirmable)
    assert c.no_design_arrow + c.word_refuted + c.ceiling == c.papers


def test_the_ceiling_prints_no_paper_content() -> None:
    """A module prints the figure, and it must not print a design line.

    `_main` exists so the number lives in code rather than in `TASKS.md`. The
    design lines it reads are paper content (`AGENTS.md` §Contamination
    Practice), and an operator's terminal, scrollback and shell log are all
    places a term must not land for the sake of a summary line.
    """
    import contextlib
    import io

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert sc._main() == 0
    printed = out.getvalue()

    assert "key-free ceiling" in printed
    # Anti-vacuity: every paper is named, so "no term was printed" is a
    # statement about a report that actually reported.
    for paper in COHORT_PAPERS:
        assert paper.pmid in printed

    for paper in COHORT_PAPERS:
        for terms in (sc.exposure_terms(paper), sc.outcome_terms(paper)):
            for term in terms:
                assert term.lower() not in printed.lower(), (
                    f"_main printed a design-line phrase for {paper.pmid}")
