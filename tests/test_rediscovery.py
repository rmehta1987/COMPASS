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

from benchmark import rediscovery as RD
from benchmark import scorability as SC
from benchmark.cohort_papers import COHORT_PAPERS
from tests.test_schema import p014

PMID = COHORT_PAPERS[0].pmid


# --- the validator ----------------------------------------------------------- #

def test_the_live_exposure_key_column_is_clean():
    """Whatever is pasted in must pass before anything else here means much."""
    assert RD.validate_exposure_keys() == []


def test_an_empty_column_is_not_a_complaint_and_is_not_progress():
    assert RD.validate_exposure_keys({}) == []
    assert RD.scaffold_status()["exposure_key_rows"] == len(SC.EXPOSURE_KEYS)


def test_a_key_that_names_a_battery_is_rejected_with_the_key_named():
    """The failure an operator will actually make: the construct, not a member.

    `m3:Q16.1` is the construct key the enumeration uses;
    `env/tools.py::resolve_variable`'s own log says a protocol may not name it.
    A complaint that said only "a key did not resolve" would leave the operator
    to work out which of a row's keys was wrong.
    """
    out = RD.validate_exposure_keys({PMID: ("m3:Q16.1",)})
    assert len(out) == 1
    assert "m3:Q16.1" in out[0] and "unique" in out[0]


def test_a_key_that_resolves_to_one_variable_passes():
    assert RD.validate_exposure_keys({PMID: ("m3:Q16.1_1",)}) == []


def test_an_invented_key_is_rejected():
    """`linked:household_poverty` matches KEY_PATTERN and is in no registry."""
    out = RD.validate_exposure_keys({PMID: ("linked:household_poverty",)})
    assert len(out) == 1 and "linked:household_poverty" in out[0]


def test_a_malformed_key_is_rejected_before_it_is_resolved():
    out = RD.validate_exposure_keys({PMID: ("Q16.1_1",)})
    assert len(out) == 1 and "KEY_PATTERN" in out[0]


def test_an_empty_row_is_rejected_because_it_reads_as_a_filled_one():
    out = RD.validate_exposure_keys({PMID: ()})
    assert len(out) == 1 and "asserts nothing" in out[0]


def test_a_pmid_the_bibliography_does_not_carry_is_rejected():
    out = RD.validate_exposure_keys({"99999999": ("m3:Q16.1_1",)})
    assert any("not a pmid" in c for c in out)


def test_a_repeated_key_in_one_row_is_rejected():
    out = RD.validate_exposure_keys({PMID: ("m3:Q16.1_1", "m3:Q16.1_1")})
    assert any("repeats a key" in c for c in out)


# --- the withheld outcome side ------------------------------------------------ #

def test_the_prevalence_key_guard_is_named_not_broad(monkeypatch):
    """An ordinary broken import may never be laundered into a holdout."""
    monkeypatch.setattr(RD, "WITHHELD_MODULES", frozenset())
    with pytest.raises(RuntimeError, match="no longer in WITHHELD_MODULES"):
        RD.prevalence_key_present()


def test_an_unreadable_outcome_column_is_flagged_separately_from_an_empty_one():
    rec = RD.recorded_design(PMID)
    assert rec.outcome_key_readable is RD.prevalence_key_present()
    if not rec.outcome_key_readable:
        assert rec.outcome_keys == (), (
            "an unreadable column must be empty AND flagged; the flag is what "
            "stops the emptiness being read as 'the key records none'")


def test_the_report_exits_incomplete_rather_than_clean_without_the_key(capsys):
    rc = RD._main([])
    if RD.prevalence_key_present():
        assert rc == RD.EXIT_OK
    else:
        assert rc == 2, "exit 2 is the literal, not EXIT_INCOMPLETE re-read"
        assert "NOT a pass" in capsys.readouterr().out


def test_a_complaint_outranks_an_incomplete_run(monkeypatch, capsys):
    monkeypatch.setattr(SC, "EXPOSURE_KEYS", {PMID: ("m3:Q16.1",)})
    assert RD._main([]) == 1, "a failure must outrank a skip"
    assert "COMPLAINT" in capsys.readouterr().out


def test_status_counts_is_null_rather_than_zeroes_where_it_cannot_run():
    status = RD.scaffold_status()
    if not status["outcome_key_readable"]:
        assert status["status_counts"] is None


# --- the side-by-side --------------------------------------------------------- #

def test_an_unfilled_column_is_unavailable_and_never_differs():
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


def test_the_withheld_outcome_column_is_unavailable_in_the_side_by_side():
    rec = RD.recorded_design(PMID)
    rows = {r.field: r for r in RD.compare(rec, p014())}
    if rec.outcome_key_readable:
        pytest.skip("the prevalence key is present here, so nothing is "
                    "unreadable -- NOT a pass for the withheld path")
    assert rows["outcome_keys"].state == RD.UNAVAILABLE
    assert RD.PREVALENCE_KEY in rows["outcome_keys"].why


def test_a_filled_column_that_agrees_reads_MATCH(monkeypatch):
    monkeypatch.setattr(SC, "EXPOSURE_KEYS", {PMID: ("m3:Q16.2",)})
    rec = RD.recorded_design(PMID)
    rows = {r.field: r for r in RD.compare(rec, p014())}
    assert rows["exposure_keys"].state == RD.MATCH
    assert rows["exposure_keys"].recorded == "m3:Q16.2"


def test_a_filled_column_that_disagrees_reads_DIFFERS(monkeypatch):
    monkeypatch.setattr(SC, "EXPOSURE_KEYS", {PMID: ("m3:Q16.3",)})
    rec = RD.recorded_design(PMID)
    rows = {r.field: r for r in RD.compare(rec, p014())}
    assert rows["exposure_keys"].state == RD.DIFFERS


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
           test_a_populated_exposure_key_is_what_flips_a_paper`, guarded
      a confirmed paper moves the count  -> here, key-free
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

    Same row, so the two tests are about one thing and a change to either key
    breaks the pair rather than leaving a silent gap between them.
    """
    assert RD.validate_exposure_keys({"36702470": ("m2:Q5.8",)}) == []


def test_the_scaffold_status_is_json_serialisable():
    json.dumps(RD.scaffold_status())
