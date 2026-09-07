"""The tiered harness's declared shape.

Every acceptance here is against synthetic fixtures: the real tiers derive
from the inventory and `inventory/case_map.json`, neither of which may be in
this clone, so nothing here may assert against the real `tier_counts`.
"""

from benchmark.tiered_score import MATRIX, SCOREABLE_CELLS, TIERS, Cell, main, self_check


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
