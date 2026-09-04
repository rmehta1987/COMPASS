"""The ledger: the row count is the denominator, and a summary cannot lie."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import ledger as L


def _fill(run_dir: Path) -> L.Ledger:
    led = L.Ledger(run_dir, run_id="baseline-test")
    led.append(pair_id="a -> b", exposure_key="a", outcome_key="b",
               exposure_stratum="chronic_condition", outcome_stratum="medication",
               estimability="blocked_no_metadata", outcome="emitted",
               protocol_id="P-1", record_hash="h1", artefact="P-1.h1.json")
    led.append(pair_id="a -> c", exposure_key="a", outcome_key="c",
               exposure_stratum="chronic_condition", outcome_stratum="medication",
               estimability="blocked_no_metadata", outcome="refused",
               note="exposure_unresolvable")
    led.append(pair_id="d -> b", exposure_key="d", outcome_key="b",
               exposure_stratum="reproductive_hormonal", outcome_stratum="medication",
               estimability="blocked_no_metadata", outcome="no_valid_record")
    led.append(pair_id="e -> b", exposure_key="e", outcome_key="b",
               exposure_stratum="ses_employment", outcome_stratum="medication",
               estimability="blocked_no_metadata", outcome="discarded",
               protocol_id="P-2", record_hash="h2", note="validator:temporality")
    return led


def test_total_generated_this_run_is_the_row_count(tmp_path):
    led = _fill(tmp_path / "run")
    s = led.summary()
    assert s.total_generated_this_run == len(led.rows()) == 4
    assert s.by_outcome == {"emitted": 1, "refused": 1, "no_valid_record": 1,
                            "discarded": 1}
    assert s.strata == ("chronic_condition", "medication", "reproductive_hormonal",
                        "ses_employment")


def test_rows_are_contiguous_durable_and_reloadable(tmp_path):
    led = _fill(tmp_path / "run")
    again = L.Ledger(tmp_path / "run")                  # id comes from the rows
    assert again.run_id == "baseline-test"
    assert [r.seq for r in again.rows()] == [0, 1, 2, 3]
    assert again.rows() == led.rows()
    assert (tmp_path / "run" / L.LEDGER_NAME).read_text().count("\n") == 4


def test_a_different_run_id_cannot_be_mixed_into_an_existing_ledger(tmp_path):
    _fill(tmp_path / "run")
    with pytest.raises(ValueError, match="belongs to run 'baseline-test'"):
        L.Ledger(tmp_path / "run", run_id="other")


def test_verify_passes_on_a_written_summary_and_fails_on_a_stale_one(tmp_path):
    led = _fill(tmp_path / "run")
    led.write_summary()
    assert L.verify(tmp_path / "run").total_generated_this_run == 4
    assert L.main([str(tmp_path / "run")]) == 0
    # one more row after the summary: the stored denominator is now a lie
    led.append(pair_id="f -> b", exposure_key="f", outcome_key="b",
               exposure_stratum="tobacco", outcome_stratum="medication",
               estimability="blocked_no_metadata", outcome="emitted")
    with pytest.raises(ValueError, match="stored total 4, rows 5"):
        L.verify(tmp_path / "run")
    assert L.main([str(tmp_path / "run")]) == 1


def test_verify_catches_an_edited_ledger(tmp_path):
    led = _fill(tmp_path / "run")
    led.write_summary()
    lines = led.path.read_text().splitlines()
    del lines[1]                                        # a row removed by hand
    led.path.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="seq"):
        L.verify(tmp_path / "run")


def test_verify_needs_the_summary_file(tmp_path):
    _fill(tmp_path / "run")
    with pytest.raises(ValueError, match="missing"):
        L.verify(tmp_path / "run")


def test_an_unknown_outcome_is_refused(tmp_path):
    led = L.Ledger(tmp_path / "run")
    with pytest.raises(ValueError):
        led.append(pair_id="a -> b", exposure_key="a", outcome_key="b",
                   exposure_stratum="x", outcome_stratum="y",
                   estimability="blocked_no_metadata", outcome="kept")


def test_the_summary_never_stores_a_count_the_rows_do_not_have(tmp_path):
    led = _fill(tmp_path / "run")
    stored = json.loads(led.write_summary().read_text())
    assert stored["total_generated_this_run"] == sum(stored["by_outcome"].values())
    assert stored["total_generated_this_run"] == len(led.rows())
