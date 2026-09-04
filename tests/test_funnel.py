"""Tests for generate/funnel.py — the deterministic S1-S4 screen.

Pins three things that are easy to break silently: the VERIFIED baseline counts
for the 6x64 anchor frame every driver script uses, the current, honest shape
of S3's estimability tag (two states reachable today, `not_estimable` declared
but never assigned — see funnel.py's `s3_screen` docstring for why that is a
deliberate absence, not a bug), and generate/worked_example.py's detectability
numbers, which a cold critic found hand-invented once already (see the test
below).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from env.tools import DETECTABILITY_N_GRID, estimate_detectability  # noqa: E402
from generate.funnel import Construct, load_constructs, run  # noqa: E402
from generate.worked_example import main as worked_example_main  # noqa: E402


def _frame(module_a: str, prefix_a: str, module_b: str, prefix_b: str) -> tuple[
    list[Construct], list[Construct]
]:
    constructs, _ = load_constructs()
    a = sorted(
        (c for c in constructs.values()
         if c.module == module_a and c.base_id.startswith(prefix_a)),
        key=lambda c: c.base_id,
    )
    b = sorted(
        (c for c in constructs.values()
         if c.module == module_b and c.base_id.startswith(prefix_b)),
        key=lambda c: c.base_id,
    )
    return a, b


def test_anchor_frame_counts_match_verified_baseline() -> None:
    """Pin the VERIFIED baseline tuple for the 6x64 anchor frame.

    HANDOFF_AGENT_PIPELINE.md §2 records this exact tuple. An unexplained
    change here means the funnel's selection logic moved silently.
    """
    exposures, outcomes = _frame("3", "Q16.", "2", "Q5.")
    assert len(exposures) == 6
    assert len(outcomes) == 64

    _, counts = run(exposures, outcomes)

    assert counts == {
        "enumerated": 384,
        "pruned_S2": 128,
        "parked_S3": 0,
        "live": 256,
        "estimable": 0,
        "unknown": 256,
        "requires_derivation": 70,
    }


def test_parked_s3_is_structurally_zero_not_just_empirically_zero() -> None:
    """S3 never assigns `stage="S3"` or `state="parked"` — only S2 sets `stage`.

    A frame that is entirely cross-module (the anchor frame above) would
    report parked_S3=0 even if S3 COULD park something; this checks a
    same-module frame too, where estimability *is* reachable, and confirms
    parking still never fires. That is the difference between "0 because
    nothing was tested" and "0 because nothing sets it" — see s3_screen.
    """
    same_module_exposures, same_module_outcomes = _frame("2", "Q5.", "2", "Q12.")
    cross_module_exposures, cross_module_outcomes = _frame("3", "Q16.", "2", "Q5.")

    for exposures, outcomes in (
        (same_module_exposures, same_module_outcomes),
        (cross_module_exposures, cross_module_outcomes),
    ):
        cands, counts = run(exposures, outcomes)
        assert counts["parked_S3"] == 0
        assert all(c.stage != "S3" for c in cands)
        assert all(c.state != "parked" for c in cands)
        assert all(c.estimability != "not_estimable" for c in cands)


def test_estimable_is_reachable_for_a_same_module_frame() -> None:
    """The `estimable` branch of s3_screen is reachable, not dead code.

    The anchor frame (module 3 x module 2) is cross-module by construction,
    so it always reports estimable=0 — that is a property of the frame, not
    proof the `estimable` branch is dead code. A same-module frame (two
    different Q-blocks inside module 2) must produce some.
    """
    exposures, outcomes = _frame("2", "Q5.", "2", "Q12.")
    _, counts = run(exposures, outcomes)
    assert counts["estimable"] > 0
    assert counts["unknown"] == 0


def test_worked_examples_detectability_numbers_are_on_the_environments_curve() -> None:
    """worked_example.py's SDE and falsifier must be real curve points.

    A cold critic found `value=2.1, unit="percentage points", at_n=1800`
    hand-written in generate/worked_example.py — 1800 is on no
    DETECTABILITY_N_GRID this project has used, old or new, so it was a
    number no tool would ever return for any input, the exact shape of
    fabrication agent/tool_authority.py's GateMismatch exists to reject
    (worked_example.py never passes through that gate, so nothing there
    caught it). worked_example.py now derives both numbers at runtime from
    `env.tools.estimate_detectability` instead of a literal; this pins that
    behaviour so a future edit cannot quietly go back to a hand-typed
    constant that goes stale the moment DETECTABILITY_N_GRID moves — the
    same drift `test_the_fixtures_detectability_numbers_are_on_the_environments_curve`
    in tests/test_specifier.py guards for run_specifier.py's fixture.

    Raises:
        AssertionError: If worked_example.py's at_n is off the grid, its value
            is not the curve's value there, or its falsifier no longer clears
            the floor.
    """
    p = worked_example_main()
    sde = p.estimability.smallest_detectable_effect
    assert sde.value is not None  # narrows float | None for mypy and the check below
    assert p.falsifier_threshold is not None

    assert sde.at_n in DETECTABILITY_N_GRID, (
        f"worked_example.py's at_n={sde.at_n} is not on DETECTABILITY_N_GRID "
        f"{DETECTABILITY_N_GRID} — it is fabricating a point off the curve again.")
    curve = {pt["n"]: pt["sde_percentage_points"]
             for pt in estimate_detectability(baseline_prevalence=0.32)["sde_by_n"]}
    assert sde.value == curve[sde.at_n]
    assert p.falsifier_threshold.value > sde.value
