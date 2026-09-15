"""Pins for benchmark/rediscovery.py — the T2 scaffolding.

Two guarantees. The validator is C12's ACCEPT criterion made runnable, so it
must reject the rows an operator actually mistypes and name the key that failed.
And the side-by-side must never collapse into a score: an unfilled column, an
unreadable one and an unequal one are three states, and folding any of them
together is how "we could not look" comes to read as "it matched".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark import design_anchor as DA
from benchmark import rediscovery as RD
from benchmark import scorability as SC
from benchmark.cohort_papers import COHORT_PAPERS
from tests.test_schema import p014

PMID = COHORT_PAPERS[0].pmid


def _row(exposure: tuple[DA.Anchor, ...],
         outcome: tuple[DA.Anchor, ...] = (),
         pmid: str = PMID) -> DA.DesignKeyRow:
    """One design-key row, well formed apart from what a caller varies.

    The outcome side defaults to a recorded refutation rather than to `()`,
    because an empty side is itself a complaint and would mask the one the
    caller is testing for.

    Args:
        exposure: Exposure-side anchors.
        outcome: Outcome-side anchors, defaulting to one refutation.
        pmid: PubMed identifier.

    Returns:
        The row.
    """
    return DA.DesignKeyRow(
        pmid, exposure,
        outcome or (DA.Anchor("a phrase", DA.NOT_IN_INSTRUMENT),),
        provenance="fixture", filled_by="test")


def _variable(key: str, term: str = "a phrase") -> tuple[DA.Anchor, ...]:
    """One `variable` anchor naming `key`.

    Args:
        key: The instrument key.
        term: The design-line phrase it answers.

    Returns:
        A one-anchor tuple.
    """
    return (DA.Anchor(term, DA.VARIABLE, key=key),)


def _serve(monkeypatch, rows: tuple[DA.DesignKeyRow, ...]) -> None:
    """Substitute the withheld design key, without importing it.

    Args:
        monkeypatch: pytest's patcher.
        rows: The table to serve.
    """
    monkeypatch.setattr(RD, "design_key_present", lambda: True)
    monkeypatch.setattr(RD, "validate", lambda r=None: DA.validate_design_key(
        rows if r is None else r))
    monkeypatch.setattr(RD, "_row_count", lambda: len(rows))
    monkeypatch.setattr(
        SC, "design_key_row",
        lambda pmid: next((x for x in rows if x.pmid == pmid), None))


# --- the validator ----------------------------------------------------------- #

def test_the_live_design_key_is_reported_honestly_in_either_clone():
    """Whichever clone this is, `scaffold_status` must not blur the two cases.

    Before C36 the exposure column lived in the working clone and `validate()`
    ran over it here. It is withheld now, so where the key is ABSENT the honest
    statement is that the criterion did not run: `design_key_readable` False
    and `design_key_rows` None, which is not the same as zero rows.

    BRANCHED, not asserted one way. An earlier draft asserted
    `design_key_present() is False`, which is true here and FALSE in the
    scoring clone -- so the moment the operator creates the key, this test goes
    red in the only clone where it can actually exercise the readable path.
    That is the permanently-red suite `tests/withheld.py` exists to end, and it
    would have been introduced by the commit that closed C36.
    """
    status = RD.scaffold_status()
    assert status["design_key_readable"] is RD.design_key_present()
    if status["design_key_readable"]:
        assert isinstance(status["design_key_rows"], int), (
            "a readable key must report a row count, even if it is 0")
        assert status["status_counts"] is not None
    else:
        assert status["design_key_rows"] is None, (
            "zero rows and an unreadable table are different facts; None says "
            "which this is")
        assert status["status_counts"] is None
        assert status["complaints"] == [], (
            "nothing was checked, so nothing may be complained about")


def test_an_empty_table_is_not_a_complaint_and_is_not_progress(monkeypatch):
    _serve(monkeypatch, ())
    assert RD.validate() == []
    assert RD.scaffold_status()["design_key_rows"] == 0


def test_a_key_that_names_a_battery_is_rejected_with_the_key_named():
    """The failure an operator will actually make: the construct, not a member.

    `m3:Q16.1` is the construct key the enumeration uses;
    `env/tools.py::resolve_variable`'s own log says a protocol may not name it.
    A complaint that said only "a key did not resolve" would leave the operator
    to work out which of a row's keys was wrong.
    """
    out = RD.validate((_row(_variable("m3:Q16.1")),))
    assert len(out) == 1
    assert "m3:Q16.1" in out[0] and "unique" in out[0]


def test_a_key_that_resolves_to_one_variable_passes():
    assert RD.validate((_row(_variable("m3:Q16.1_1")),)) == []


def test_an_invented_key_is_rejected():
    """`linked:household_poverty` matches KEY_PATTERN and is in no registry."""
    out = RD.validate((_row(_variable("linked:household_poverty")),))
    assert len(out) == 1 and "linked:household_poverty" in out[0]


def test_a_malformed_key_is_rejected_before_it_is_resolved():
    out = RD.validate((_row(_variable("Q16.1_1")),))
    assert len(out) == 1 and "KEY_PATTERN" in out[0]


def test_an_empty_side_is_rejected_because_it_reads_as_a_filled_one():
    out = RD.validate((DA.DesignKeyRow(PMID, (), _variable("m3:Q16.1_1"),
                                       "fixture", "test"),))
    assert len(out) == 1 and "asserts nothing" in out[0]


def test_a_pmid_the_bibliography_does_not_carry_is_rejected():
    out = RD.validate((_row(_variable("m3:Q16.1_1"), pmid="99999999"),))
    assert any("not a pmid" in c for c in out)


def test_a_repeated_key_in_one_row_is_rejected():
    out = RD.validate((_row((*_variable("m3:Q16.1_1"),
                             DA.Anchor("another phrase", DA.VARIABLE,
                                       key="m3:Q16.1_1"))),))
    assert any("repeats a key" in c for c in out)


# --- the withheld design key -------------------------------------------------- #

def test_the_design_key_guard_is_named_not_broad(monkeypatch):
    """An ordinary broken import may never be laundered into a holdout."""
    monkeypatch.setattr(RD, "WITHHELD_MODULES", frozenset())
    with pytest.raises(RuntimeError, match="no longer in WITHHELD_MODULES"):
        RD.design_key_present()


def test_an_unreadable_key_is_flagged_separately_from_an_empty_one():
    rec = RD.recorded_design(PMID)
    assert rec.design_key_readable is RD.design_key_present()
    if not rec.design_key_readable:
        assert rec.exposure_keys == () and rec.outcome_keys == (), (
            "an unreadable key must leave both sides empty AND flagged; the "
            "flag is what stops the emptiness being read as 'the key records "
            "none'")


def test_the_report_exits_incomplete_rather_than_clean_without_the_key(capsys):
    rc = RD._main([])
    if RD.design_key_present():
        assert rc == RD.EXIT_OK
    else:
        assert rc == 2, "exit 2 is the literal, not EXIT_INCOMPLETE re-read"
        assert "NOT a pass" in capsys.readouterr().out


def test_a_complaint_outranks_an_incomplete_run(monkeypatch, capsys):
    """A failure must outrank a skip, and a complaint needs a readable key.

    The readable case is what carries the claim: before C36 an unreadable
    outcome side sat beside a readable exposure column, so a complaint could
    be raised in this clone. Both sides are withheld now, so the served table
    is what makes the ranking observable at all.
    """
    _serve(monkeypatch, (_row(_variable("m3:Q16.1")),))
    assert RD._main([]) == 1, "a failure must outrank a skip"
    assert "COMPLAINT" in capsys.readouterr().out


def test_status_counts_is_null_rather_than_zeroes_where_it_cannot_run():
    status = RD.scaffold_status()
    if not status["design_key_readable"]:
        assert status["status_counts"] is None


# --- the side-by-side --------------------------------------------------------- #

def test_an_unfilled_column_is_unavailable_and_never_differs(monkeypatch):
    _serve(monkeypatch, (_row((DA.Anchor("a phrase",
                                         DA.NOT_IN_INSTRUMENT),)),))
    rec = RD.recorded_design(PMID)
    rows = {r.field: r for r in RD.compare(rec, p014())}
    assert rows["exposure_keys"].state == RD.UNAVAILABLE
    assert rows["exposure_keys"].why, "an UNAVAILABLE row must say why"
    assert rows["adjusted_covariate_keys"].state == RD.UNAVAILABLE
    assert rows["expected_direction"].state == RD.UNAVAILABLE


def test_an_unreadable_recorded_side_is_unavailable_and_never_differs():
    """The distinction the whole exit-status convention rests on.

    A column this clone cannot READ is not a column that disagreed. Seeded on
    the helper directly: the unfilled case and the unreadable case take
    different branches, and a test that covers only the first leaves the second
    free to report DIFFERS against an empty recorded side — which is the
    "could not look" reading as "did not match" that `AGENTS.md`
    §Verification Discipline names.
    """
    unreadable = RD._keys("outcome_keys", (), {"m2:Q5.8"}, False,
                          "the key is withheld")
    assert unreadable.state == RD.UNAVAILABLE
    assert unreadable.why == "the key is withheld"
    unfilled = RD._keys("outcome_keys", (), {"m2:Q5.8"}, True, "")
    assert unfilled.state == RD.UNAVAILABLE and "no row" in unfilled.why


def test_the_withheld_key_makes_both_sides_unavailable_in_the_side_by_side():
    """Both sides now, not just the outcome one -- the change C36 makes here."""
    rec = RD.recorded_design(PMID)
    rows = {r.field: r for r in RD.compare(rec, p014())}
    if rec.design_key_readable:
        pytest.skip("the design key is present here, so nothing is "
                    "unreadable -- NOT a pass for the withheld path")
    for field in ("exposure_keys", "outcome_keys"):
        assert rows[field].state == RD.UNAVAILABLE
        assert RD.DESIGN_KEY in rows[field].why


def test_a_filled_column_that_agrees_reads_MATCH(monkeypatch):
    _serve(monkeypatch, (_row(_variable("m3:Q16.2")),))
    rec = RD.recorded_design(PMID)
    rows = {r.field: r for r in RD.compare(rec, p014())}
    assert rows["exposure_keys"].state == RD.MATCH
    assert rows["exposure_keys"].recorded == "m3:Q16.2"


def test_a_filled_column_that_disagrees_reads_DIFFERS(monkeypatch):
    _serve(monkeypatch, (_row(_variable("m3:Q16.3")),))
    rec = RD.recorded_design(PMID)
    rows = {r.field: r for r in RD.compare(rec, p014())}
    assert rows["exposure_keys"].state == RD.DIFFERS


def test_an_anchor_with_no_key_contributes_none_to_the_side_by_side(monkeypatch):
    """An `area_measure` names a delivery and a refutation names nothing.

    Neither carries a key, and rendering one as a blank would put an empty
    string into a comparison of KEY SETS. The verdict that reads those kinds is
    `scorability.py::_side`, not the side-by-side.
    """
    _serve(monkeypatch, (_row(
        (DA.Anchor("a phrase", DA.AREA_MEASURE,
                   blocked_on=DA.AREA_MEASURE_INVENTORY),)),))
    rec = RD.recorded_design(PMID)
    assert rec.exposure_keys == ()
    rows = {r.field: r for r in RD.compare(rec, p014())}
    assert rows["exposure_keys"].state == RD.UNAVAILABLE
    assert "no row for this paper yet" in rows["exposure_keys"].why


def test_prose_fields_are_handed_to_a_reader_not_compared():
    """`model_form` is never MATCH or DIFFERS.

    A match rate over two different vocabularies is a number with no
    defensible denominator.
    """
    rec = RD.recorded_design(PMID)
    rows = {r.field: r for r in RD.compare(rec, p014())}
    assert rows["model_form"].state == RD.REVIEW
    assert rows["model_form"].recorded == rec.design_line


def test_the_side_by_side_emits_no_total():
    """The guarantee that keeps this a report: no score, anywhere in it."""
    rec = RD.recorded_design(PMID)
    rows = RD.compare(rec, p014())
    text = RD.render(rec, rows)
    assert "NOT A SCORE" in text
    for banned in ("score", "%", "total", "matched of"):
        assert banned not in text.lower().replace("not a score", ""), banned


def test_a_null_analytic_n_is_unavailable_not_a_mismatch():
    rec = RD.recorded_design(PMID)
    rows = {r.field: r for r in RD.compare(rec, p014())}
    assert p014().estimability.analytic_n is None
    assert rows["analytic_n"].state == RD.UNAVAILABLE


def test_every_comparison_state_is_one_of_the_four_declared():
    rec = RD.recorded_design(PMID)
    allowed = {RD.MATCH, RD.DIFFERS, RD.REVIEW, RD.UNAVAILABLE}
    assert {r.state for r in RD.compare(rec, p014())} <= allowed


def test_an_unknown_pmid_raises_rather_than_returning_an_empty_design():
    with pytest.raises(KeyError):
        RD.recorded_design("99999999")


def test_the_cli_renders_a_side_by_side_from_a_record_on_disk(tmp_path, capsys):
    f = tmp_path / "p.json"
    f.write_text(p014().model_dump_json())
    RD._main(["--pmid", PMID, "--record", str(f)])
    out = capsys.readouterr().out
    assert "REDISCOVERY SIDE-BY-SIDE" in out and PMID in out


def test_a_pmid_without_a_record_is_refused():
    with pytest.raises(SystemExit):
        RD._main(["--pmid", PMID])


# --- the column is what unblocks the benchmark --------------------------------- #

def test_rediscovery_is_named_in_the_holdout_registry():
    """It assembles a published design, so a copy on a tool path must be caught."""
    src = Path(__file__).resolve().parents[1] / "benchmark" / "contamination_check.py"
    assert '"rediscovery.py"' in src.read_text(), (
        "check_holdout_not_reachable no longer names rediscovery.py; a copy "
        "under curated/, env/ or agent/ would go undetected")


def test_status_counts_moves_when_a_paper_becomes_confirmed(monkeypatch):
    """T2's third deliverable, key-free half: the aggregate follows the verdict.

    `status_counts` cannot run in this clone — it reaches the withheld outcome
    key through `scorability_for`. Guarding the whole test would move another
    two pieces of coverage out of the clone where prompts are edited
    (`tests/test_withheld.py::GUARD_CEILING`), so the claim is split three ways
    and only the middle link is guarded:

      a pasted row is usable      -> the test below, key-free
      a usable row confirms a paper
        -> `tests/test_scorability.py::
           test_a_populated_design_key_is_what_flips_a_paper`, KEY-FREE since
           C36, because both sides now read one substitutable reader
      a confirmed paper moves the count  -> here, key-free

    So none of the three links is guarded any more, and the split is kept
    because the three claims are still different claims.
    """
    def report(status: str) -> tuple:
        side = SC.SideVerdict("exposure", ("t",), status, ("m3:Q16.1_1",), (), ())
        return (SC.PaperScorability(PMID, side, side, status, ()),)

    monkeypatch.setattr(SC, "scorability_report", lambda: report(SC.UNDETERMINED))
    assert SC.status_counts()[SC.CONFIRMED] == 0
    monkeypatch.setattr(SC, "scorability_report", lambda: report(SC.CONFIRMED))
    assert SC.status_counts()[SC.CONFIRMED] == 1, (
        "a confirmed paper must reach status_counts; the scaffold's number is "
        "the only thing that says a pasted row landed")


def test_a_pasted_row_passes_the_accept_criterion_that_confirms_a_paper():
    """The first link, key-free: the row `test_scorability.py` flips on is usable.

    Same key, so the two tests are about one thing and a change to either
    breaks the pair rather than leaving a silent gap between them. The terms
    come from the paper's own design line: an anchor is filed against the
    phrase it answers, and a row whose terms are invented would validate while
    asserting nothing about that paper.
    """
    paper = next(p for p in COHORT_PAPERS if p.pmid == "36702470")
    terms = SC.exposure_terms(paper) + SC.outcome_terms(paper)
    pool = ("m2:Q5.8", "m2:Q5.2", "m3:Q16.1_1", "m3:Q16.2")[:len(terms)]
    assert len(pool) == len(terms), "need one distinct key per term"
    anchors = [DA.Anchor(term, DA.VARIABLE, key=pool[i])
               for i, term in enumerate(terms)]
    exposure = tuple(anchors[:len(SC.exposure_terms(paper))])
    outcome = tuple(anchors[len(SC.exposure_terms(paper)):])
    assert exposure and outcome, "fixture assumed a paper with both sides"
    row = DA.DesignKeyRow("36702470", exposure, outcome, "fixture", "test")
    assert DA.validate_design_key((row,)) == []


def test_the_scaffold_status_is_json_serialisable():
    json.dumps(RD.scaffold_status())
