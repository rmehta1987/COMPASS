"""Tests for `serve/api.py::_enumerate`'s shown slice.

Pins the property that made the Generate tab misleading rather than any count:
the funnel's enumeration order is exposure-major, so a head slice shorter than
the outcome count can only ever show one exposure. The page asked for 25 of a
384-pair frame and every pair it could render was `m3:Q16.1 -> ...`.

Counts here are derived from the frame under test, never pinned, so a changed
dictionary moves them without reddening anything. What is pinned is one-sided:
the spread must not collapse to a single exposure, and a pruned pair must carry
the state the page needs to refuse it a launch button.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from generate.funnel import load_constructs, run  # noqa: E402
from serve.api import _enumerate, _spread_by_exposure  # noqa: E402

#: The frame `_enumerate` defaults to, and the one the page always asks for.
FRAME = ("3", "Q16.", "2", "Q5.")


def _default_frame_candidates() -> list:
    """Every candidate of the endpoint's default frame, in enumeration order.

    Returns:
        The funnel's candidate list for module 3 `Q16.` against module 2 `Q5.`.
    """
    constructs, _ = load_constructs()
    ex_mod, ex_pre, out_mod, out_pre = FRAME
    exposures = sorted(
        (c for c in constructs.values()
         if c.module == ex_mod and c.base_id.startswith(ex_pre)),
        key=lambda c: c.base_id)
    outcomes = sorted(
        (c for c in constructs.values()
         if c.module == out_mod and c.base_id.startswith(out_pre)),
        key=lambda c: c.base_id)
    cands, _counts = run(exposures, outcomes)
    return cands


def _distinct_exposures(cands: list) -> set[str]:
    """The construct keys of the exposures present in a candidate list.

    Args:
        cands: Candidates to read.

    Returns:
        One key per distinct exposure.
    """
    return {c.exposure.construct_key for c in cands}


def test_the_head_slice_shows_one_exposure_and_the_spread_shows_them_all() -> None:
    """The defect and its fix, side by side, on whatever the frame holds today."""
    cands = _default_frame_candidates()
    every = _distinct_exposures(cands)
    assert len(every) > 1, "frame has one exposure; this test cannot say anything"
    limit = len(every) * 2

    head = _distinct_exposures(cands[:limit])
    spread = _distinct_exposures(_spread_by_exposure(cands, limit))

    assert len(head) == 1, (
        "enumeration order is no longer exposure-major, so the head slice is no "
        "longer the defect this function exists to work around — re-derive it "
        "rather than adjusting this assertion")
    assert spread == every, (
        f"a slice of {limit} spanned {len(spread)} of {len(every)} exposures; at "
        f"twice the exposure count every exposure must appear")


def test_the_spread_invents_nothing_and_drops_no_duplicate_guard() -> None:
    """The slice is a subset of the funnel's own candidates, each appearing once."""
    cands = _default_frame_candidates()
    out = _spread_by_exposure(cands, 25)
    ids = [c.pair_id for c in out]
    assert len(out) == min(25, len(cands))
    assert len(set(ids)) == len(ids), "the spread repeated a pair"
    assert set(ids) <= {c.pair_id for c in cands}, "the spread invented a pair"


def test_a_limit_over_the_frame_returns_the_whole_frame() -> None:
    """Asking for more than exists returns everything, not a truncated pass."""
    cands = _default_frame_candidates()
    out = _spread_by_exposure(cands, len(cands) + 10)
    assert {c.pair_id for c in out} == {c.pair_id for c in cands}


def test_a_pruned_pair_reaches_the_page_carrying_its_state() -> None:
    """The page cannot refuse a launch button to a state the payload omits.

    Asserted on the dict the endpoint builds, via AST rather than a source
    substring: a comment naming `state` would satisfy a substring check.
    """
    tree = ast.parse(Path(ROOT / "serve" / "api.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_enumerate")
    keys: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            keys |= {k.value for k in node.keys
                     if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    assert {"state", "stage", "reason"} <= keys, (
        f"the pairs payload names {sorted(keys)}; without `state` the page "
        f"cannot tell a pruned pair from a live one")


def test_enumerate_takes_its_slice_through_the_spread() -> None:
    """Pinned as a `Call` node, so restoring `cands[:limit]` reddens this."""
    tree = ast.parse(Path(ROOT / "serve" / "api.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_enumerate")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_spread_by_exposure" in called, (
        f"_enumerate calls {sorted(called)}; it must take its shown slice "
        f"through the spread, not off the head of the list")
    assert callable(_enumerate)
