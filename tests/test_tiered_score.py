"""The tiered harness's declared shape.

Every acceptance here is against synthetic fixtures: the real tiers derive
from the inventory and `inventory/case_map.json`, neither of which may be in
this clone, so nothing here may assert against the real `tier_counts`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from benchmark.tiered_score import (
    MATRIX,
    SCOREABLE_CELLS,
    TIERS,
    Cell,
    main,
    self_check,
)
from env.tools import resolve_variable


def test_the_declared_matrix_is_consistent():
    assert self_check() == []


def test_every_component_has_one_cell_per_tier():
    for row in MATRIX:
        assert len(row.cells) == len(TIERS), row.name


def test_the_half_available_row_names_what_blocks_it_and_keeps_its_row():
    # A missing row reads as "not applicable" when it means "not yet built",
    # so the blocked component stays in the matrix with its blocker named.
    half = [row for row in MATRIX if Cell.HALF in row.cells]
    assert [row.name for row in half] == ["modality analogue resolution"]
    assert "16-19" in half[0].blocked


def test_a_dropped_row_is_caught_rather_than_shortening_the_report():
    # Seeded failure for the pin: the scoreable-cell count is what notices a
    # component that quietly leaves the report.
    dropped = MATRIX[:-1]
    scoreable = sum(1 for row in dropped for c in row.cells if c is not Cell.NA)
    assert scoreable != SCOREABLE_CELLS


def test_the_self_check_cli_exits_zero(capsys):
    assert main(["--self-check"]) == 0
    assert "0 problems" in capsys.readouterr().out


# --- item 2: the synthetic tiered inventory -------------------------------
# The real inventory and inventory/case_map.json may never be in this clone,
# so every tier assertion in this file is against these five invented papers.

FAKE = json.loads(Path("tests/fake_tiered_inventory.json").read_text())
HANDOFF = json.loads(Path("handoff/for_harness.json").read_text())
PAPERS = FAKE["papers"]


def _rows(paper: dict) -> list[dict]:
    return [*paper["exposures"], *paper["outcomes"], *paper["covariates"]]


def test_the_fixture_says_it_is_synthetic():
    # A number scored against a synthetic inventory is a rehearsal, not a
    # measurement, and the fixture has to say so where a reader will see it.
    assert FAKE["synthetic"] is True
    assert "SYNTHETIC" in FAKE["notes"]


def test_one_paper_per_tier_plus_the_predicate_exerciser():
    assert [p["paper"] for p in PAPERS] == ["fA", "fB", "fC", "fD", "fE"]
    assert {p["intended_tier"] for p in PAPERS} == {"A", "B", "C", "D"}
    assert len(PAPERS) == 5


def test_the_exerciser_is_the_only_paper_the_two_readings_disagree_on():
    # 2a: without this shape the tier_rule assertion is never tested, because
    # confident_anchor and the bare-status reading agree on every other paper
    # and a mismatch would be silent.
    disagree = [p["paper"] for p in PAPERS
                if p["intended_tier"] != p["intended_tier_bare_status"]]
    assert disagree == ["fE"]
    fe = next(p for p in PAPERS if p["paper"] == "fE")
    (outcome,) = fe["outcomes"]
    assert outcome["status"] == "modality"
    assert outcome["analogue_key"] is not None
    assert outcome["confident"] is False
    assert (fe["intended_tier"], fe["intended_tier_bare_status"]) == ("D", "C")


def test_the_fixture_speaks_the_handoffs_vocabulary():
    # Taken from handoff/for_harness.json at run time, never restated here:
    # a vocabulary this file spelled out again would not notice the real one moving.
    statuses = set(HANDOFF["status_values"])
    modalities = set(HANDOFF["modality_values"])
    for paper in PAPERS:
        for row in _rows(paper):
            assert row["status"] in statuses, (paper["paper"], row)
            if row["status"] == "modality":
                assert row["modality"] in modalities, (paper["paper"], row)
                assert row["analogue_key"] is not None
            if row["status"] == "absent":
                assert row["key"] is None and row["analogue_key"] is None


def test_every_fixture_key_names_a_real_variable():
    # The labels are invented; the keys are real, so resolution, recall and the
    # modal set run against the built dictionary rather than against nothing.
    for paper in PAPERS:
        for row in _rows(paper):
            for key in (row["key"], row["analogue_key"]):
                if key is not None:
                    assert resolve_variable(key)["outcome"] == "unique", key


def test_the_fixture_carries_no_pmid_shaped_id():
    # fA..fE, never a pmid: the paper identity is what the opaque case ids exist
    # to withhold, and a fixture is an easy place to smuggle one back in.
    assert not re.search(r"\b\d{8}\b", json.dumps(FAKE))


def test_pair_counts_are_unbalanced_so_weighting_has_something_to_bite_on():
    # 11a: one real paper holds 23 of 95 triples, so an unweighted rate measures
    # that paper. The fixture reproduces the shape at small scale.
    counts = {p["paper"]: len(p["pairs"]) for p in PAPERS}
    assert counts == {"fA": 1, "fB": 2, "fC": 6, "fD": 1, "fE": 2}
    assert max(counts.values()) * 2 == sum(counts.values())
    ids = [pair["case_id"] for p in PAPERS for pair in p["pairs"]]
    assert len(set(ids)) == len(ids)
