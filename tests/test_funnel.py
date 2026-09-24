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

import ast
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


# --------------------------------------------------------------------------- #
# T7: one named, hashed frame, walked in enumeration order
# --------------------------------------------------------------------------- #


def _builds_a_frame_by_hand(node: ast.AST, prefixes: set[str]) -> bool:
    """Whether a node is a `startswith` call that picks a frame side.

    Two shapes. A frame's own prefix as a constant, on any receiver; or a
    construct's `base_id` as the receiver, with any argument.
    `serve/api.py::_enumerate` escaped the first shape alone for as long as it
    passed its prefixes as variables (TASKS.md C41). The second does not flag
    every variable argument, because two live calls take one for another
    purpose: `benchmark/prevalence_rows.py` and
    `benchmark/unearned_assertions.py`. An alias (`bid = c.base_id`) escapes it
    still.

    Args:
        node: Any AST node.
        prefixes: Every prefix a named frame uses.

    Returns:
        True for either shape.
    """
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "startswith" and node.args):
        return False
    arg, receiver = node.args[0], node.func.value
    return ((isinstance(arg, ast.Constant) and arg.value in prefixes)
            or (isinstance(receiver, ast.Attribute) and receiver.attr == "base_id"))


def test_no_driver_builds_the_frame_by_hand() -> None:
    """The frame was a list comprehension copied into every driver; now one."""
    from generate.funnel import FRAMES

    prefixes = {p for f in FRAMES.values()
                for p in (f.exposure_prefix, f.outcome_prefix)}
    # Every module, not a list of the copies someone remembered: a fifth copy
    # in benchmark/unaided_specifiability.py outlived the first version of
    # this test, which named four.
    drivers = [p for d in ("generate", "benchmark", "serve")
               for p in sorted((ROOT / d).glob("*.py")) if p.name != "funnel.py"]
    for path in drivers:
        tree = ast.parse(path.read_text())
        by_hand = [n.lineno for n in ast.walk(tree)
                   if isinstance(n, ast.Call) and _builds_a_frame_by_hand(n, prefixes)]
        assert not by_hand, f"{path.name} builds a frame by hand at lines {by_hand}"


def test_the_frame_scan_sees_a_variable_prefix_and_passes_other_prefixes() -> None:
    """Both shapes the scan must tell apart, on source it did and did not flag.

    The variable-prefix copy is `serve/api.py::_enumerate` as it stood before
    C41(a); the other two are the live variable-argument calls the scan must
    leave alone.
    """
    from generate.funnel import FRAMES

    prefixes = {p for f in FRAMES.values()
                for p in (f.exposure_prefix, f.outcome_prefix)}

    def flagged(src: str) -> bool:
        return any(_builds_a_frame_by_hand(n, prefixes) for n in ast.walk(ast.parse(src)))

    assert flagged("[c for c in C if c.module == m and c.base_id.startswith(pre)]")
    assert flagged("[c for c in C if c.base_id.startswith('Q16.')]")
    assert flagged("x.startswith('Q5.')")
    assert not flagged("region.startswith(_MODULE_PREFIXES)")
    assert not flagged("path.startswith(SCAN_EXEMPT_PREFIXES)")


def test_the_frame_digest_names_exactly_what_it_enumerates() -> None:
    """Change a side, the build or the name, and the hash changes."""
    import dataclasses

    from generate.funnel import DEFAULT_FRAME, FRAMES

    C, version = load_constructs()
    frame = FRAMES[DEFAULT_FRAME]
    d = frame.digest(C, version)
    assert d == frame.digest(C, version) and len(d) == 12
    exposures, _ = frame.sides(C)
    fewer = {k: v for k, v in C.items() if k != exposures[0].construct_key}
    assert frame.digest(fewer, version) != d
    assert frame.digest(C, "another-build") != d
    assert dataclasses.replace(frame, name="another").digest(C, version) != d


def test_the_frame_is_walked_in_enumeration_order() -> None:
    """The walk is the cartesian product in sorted order; nothing jumps ahead."""
    import pytest

    from generate.funnel import DEFAULT_FRAME, FRAMES, live_at, walk

    C, _ = load_constructs()
    frame = FRAMES[DEFAULT_FRAME]
    cands, counts = walk(frame, C)
    exposures, outcomes = frame.sides(C)
    # Enumeration order is fixed by question id, not by whatever order the
    # dictionary happens to load in.
    for side in (exposures, outcomes):
        assert [c.base_id for c in side] == sorted(c.base_id for c in side)
    assert [c.pair_id for c in cands] == [
        f"{e.construct_key} -> {o.construct_key}"
        for e in exposures for o in outcomes if e.construct_key != o.construct_key]
    assert counts["enumerated"] == len(cands)
    live = [c for c in cands if c.state == "live"]
    assert live_at(cands, 0) is live[0] and live_at(cands, len(live) - 1) is live[-1]
    with pytest.raises(IndexError, match="live candidates"):
        live_at(cands, len(live))


def test_the_live_driver_walks_the_frame_rather_than_naming_a_pair() -> None:
    """Its pair is a position in the walk, defaulting to the first."""
    import ast
    import inspect

    from generate import live_specifier
    from generate.funnel import DEFAULT_FRAME

    args = live_specifier.parse_args([])
    assert args.frame == DEFAULT_FRAME and args.index == 0
    tree = ast.parse(inspect.getsource(live_specifier.main))
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "live_at" in called
