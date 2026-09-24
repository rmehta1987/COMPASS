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

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from generate.funnel import DEFAULT_FRAME, FRAMES, load_constructs, walk  # noqa: E402
from serve.api import State, _enumerate, _spread_by_exposure  # noqa: E402


def _default_frame_candidates() -> list:
    """Every candidate of the endpoint's default frame, in enumeration order.

    Read from `generate/funnel.py::FRAMES`, not rebuilt here: this file used to
    carry its own copy of the frame's four sides, the per-caller copy T7 named
    the frame to end.

    Returns:
        The funnel's candidate list for `FRAMES[DEFAULT_FRAME]`.
    """
    constructs, _ = load_constructs()
    cands, _counts = walk(FRAMES[DEFAULT_FRAME], constructs)
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


# --------------------------------------------------------------------------- #
# C41(a): the endpoint enumerates a named frame, and says which
# --------------------------------------------------------------------------- #


def _state(tmp_path: Path) -> State:
    """A default-bind state whose directories are all under `tmp_path`.

    Args:
        tmp_path: pytest's per-test directory.

    Returns:
        The state `_enumerate` reads.
    """
    return State(tmp_path / "deploy", tmp_path / "site", tmp_path / "run")


def test_the_default_request_enumerates_the_default_frame_and_names_it(
        tmp_path: Path) -> None:
    """The page posts `{}`; the payload says which frame and which build.

    Before C41(a) the payload carried the four sides and no frame, so a count
    on the Generate tab could not say it was `FRAMES[DEFAULT_FRAME]`'s.
    """
    C, version = load_constructs()
    frame = FRAMES[DEFAULT_FRAME]
    out = _enumerate(_state(tmp_path), {})
    assert out["frame"] == {"name": DEFAULT_FRAME,
                            "digest": frame.digest(C, version)}
    _, counts = walk(frame, C)
    assert out["counts"] == counts, "the endpoint's counts are not the frame's walk"


def test_sides_that_match_no_named_frame_are_refused_not_named(
        tmp_path: Path) -> None:
    """A custom frame is refused; the endpoint never names one itself.

    Anti-vacuity first: the default frame's own sides, stated explicitly,
    resolve to it, so the refusal below is about the sides and not about a
    request that states any side at all.
    """
    frame = FRAMES[DEFAULT_FRAME]
    stated = {"exposure_module": frame.exposure_module,
              "exposure_prefix": frame.exposure_prefix,
              "outcome_module": frame.outcome_module,
              "outcome_prefix": frame.outcome_prefix}
    assert _enumerate(_state(tmp_path), stated)["frame"]["name"] == DEFAULT_FRAME

    named = {(f.exposure_module, f.exposure_prefix, f.outcome_module,
              f.outcome_prefix) for f in FRAMES.values()}
    custom = {**stated, "outcome_module": frame.exposure_module,
              "outcome_prefix": frame.exposure_prefix + "999."}
    assert tuple(custom[k] for k in stated) not in named, "pick another custom side"
    with pytest.raises(ValueError, match="no named frame"):
        _enumerate(_state(tmp_path), custom)


def test_enumerate_resolves_its_sides_through_the_frame() -> None:
    """Pinned as `Call` nodes, so a hand-built comprehension reddens this.

    `_enumerate` built both sides with its own `startswith` comprehension and
    called `funnel.run` on them, touching neither `FRAMES`, `Frame` nor `walk`
    (TASKS.md C41). The route and the helper that picks its frame are read
    together, because the frame is chosen in one and walked in the other.
    """
    tree = ast.parse(Path(ROOT / "serve" / "api.py").read_text(encoding="utf-8"))
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name in {"_enumerate", "_named_frame"}}
    assert set(fns) == {"_enumerate", "_named_frame"}, sorted(fns)
    calls = [n for fn in fns.values() for n in ast.walk(fn) if isinstance(n, ast.Call)]
    names = {n.func.id for n in calls if isinstance(n.func, ast.Name)}
    attrs = {n.func.attr for n in calls if isinstance(n.func, ast.Attribute)}
    assert {"walk", "_named_frame"} <= names, (
        f"_enumerate calls {sorted(names)}; its candidates must come from "
        f"`walk` over the frame `_named_frame` picked")
    assert {"sides", "digest"} <= attrs, (
        f"_enumerate calls {sorted(attrs)}; the sides and the digest must be the "
        f"frame's own")
    assert "startswith" not in attrs, "a side is being built by hand again"
    assert not {"run", "funnel_run"} & names, (
        "`funnel.run` on hand-picked sides is the unnamed frame C41 closed")
