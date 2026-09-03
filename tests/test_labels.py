"""Tests for env/labels.py — the type that forbids a bare variable key.

Every guarantee env/labels.py states in prose is pinned here, in the same commit,
because a guarantee described in a docstring and enforced nowhere is this
codebase's signature failure. The four the module would be worthless without:

  * `Cited.wording` is `question_text` byte for byte, for all 2,804 entries --
    not reconstructed from stem plus sub-item, which is wrong for 2 of them, and
    not stripped of a roster index, which would fail `_wording_is_verbatim`.
  * A rendered `CitedSet` round-trips: every key visible, every wording
    recoverable by the rule the render itself prints.
  * Shared-prefix factoring is byte-exact over all 70 funnel anchor constructs,
    not a sample.
  * The budget reports what it drops, by name. Silent truncation would recreate
    the failure the module exists to remove, one level down.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.schema import _norm  # noqa: E402
from env import labels  # noqa: E402
from env.labels import (  # noqa: E402
    CITATION_BUDGET,
    CitationUnavailable,
    Cited,
    CitedSet,
    cite,
    cite_all,
)
from generate.funnel import Construct, load_constructs  # noqa: E402

MARK = " | "


def _entries() -> list[dict]:
    return json.loads((ROOT / "build" / "dictionary.json").read_text())["entries"]


def _anchor_constructs() -> list[Construct]:
    """The 6x64 funnel anchor frame, as one flat list of 70 constructs.

    The same frame `tests/test_funnel.py::test_anchor_frame_counts_match_verified
    _baseline` pins and `benchmark/contamination_check.py::model_visible_surface`
    scans, so a factoring bug here is a bug on the surface the model actually
    reads.
    """
    constructs, _ = load_constructs()
    exposures = sorted(
        (c for c in constructs.values()
         if c.module == "3" and c.base_id.startswith("Q16.")),
        key=lambda c: c.base_id)
    outcomes = sorted(
        (c for c in constructs.values()
         if c.module == "2" and c.base_id.startswith("Q5.")),
        key=lambda c: c.base_id)
    assert (len(exposures), len(outcomes)) == (6, 64)
    return exposures + outcomes


def _recover(block: str) -> dict[str, str]:
    """Reverse a rendered block using only the rule the render prints.

    This is the round-trip's teeth. Reading the wording straight off the `Cited`
    objects would test nothing -- the question is whether a reader given only the
    rendered string can put the stem back onto each sub-item and get the
    instrument's text.

    Args:
        block: The output of `CitedSet.render`.

    Returns:
        Recovered key-to-wording, whitespace-collapsed as the render shows it.
    """
    out: dict[str, str] = {}
    stem = ""
    for line in block.split("\n"):
        if line.startswith("    (") or line.startswith("    ["):
            continue                                  # the note and the notice
        if line.startswith("    "):
            head, _, rest = line[4:].partition(MARK.rstrip())
            out[head.split(" [roster row")[0]] = stem + rest
        elif MARK in line:
            head, _, rest = line.partition(MARK)
            out[head.split(" [roster row")[0]] = rest
        else:
            stem = line
    return out


# --------------------------------------------------------------------------- #
# (a) the binding itself
# --------------------------------------------------------------------------- #

def test_wording_is_question_text_byte_for_byte_on_every_entry():
    """All 2,804 keys, not a sample. Two of them are why.

    `m3:Q12.12_3_TEXT` and `m3:Q12.13_3_TEXT` do not reconcile as
    `stem_text + " - " + subitem_text`, so any implementation that rebuilds the
    wording instead of copying `question_text` is wrong on exactly those two and
    right on the 874 a sample would have drawn from.
    """
    entries = _entries()
    assert len(entries) == 2804
    for e in entries:
        assert cite(e["key"]).wording == e["question_text"], e["key"]


def test_the_two_unreconcilable_entries_are_still_present_and_still_unreconcilable():
    """A positive control for the test above.

    If the build ever repaired these two, the byte-for-byte test would keep
    passing against a rebuilt wording and stop discriminating. This fails loudly
    instead of letting that go unnoticed.
    """
    by_key = {e["key"]: e for e in _entries()}
    for k in ("m3:Q12.12_3_TEXT", "m3:Q12.13_3_TEXT"):
        e = by_key[k]
        assert e["stem_text"] and e["subitem_text"]
        assert e["stem_text"] + " - " + e["subitem_text"] != e["question_text"]
        assert cite(k).wording == e["question_text"]


def test_roster_prefix_is_never_stripped_from_wording():
    """970 roster entries carry a leading "N - " and it stays.

    `agent/schema.py::_norm` collapses whitespace and nothing else, so a stripped
    wording fails `_wording_is_verbatim` outright. Asserted through `_norm`
    itself rather than a local copy of the rule.
    """
    truth = {e["key"]: e["question_text"] for e in _entries()}
    prefixed = [e for e in _entries()
                if e["roster_row"] is not None
                and e["question_text"].lstrip()[:1].isdigit()
                and " - " in e["question_text"][:6]]
    assert len(prefixed) == 970
    for e in prefixed:
        c = cite(e["key"])
        assert _norm(c.wording) == _norm(truth[c.key])
        assert c.wording.lstrip()[0].isdigit()


def test_roster_row_is_carried_from_the_field_not_inferred_from_the_text():
    """550 roster entries carry no in-text index, so a prefix regex is not a test.

    Their `roster_row` must still be populated -- that is the difference between
    reading a field and guessing at a string.
    """
    entries = _entries()
    roster = [e for e in entries if e["roster_row"] is not None]
    assert len(roster) == 1520
    assert {e["key"] for e in roster} == {
        e["key"] for e in entries if e["is_roster_repeat"]}

    no_prefix = [e for e in roster
                 if not (e["question_text"].lstrip()[:1].isdigit()
                         and " - " in e["question_text"][:6])]
    assert len(no_prefix) == 550
    for e in no_prefix:
        assert cite(e["key"]).roster_row == e["roster_row"]

    for e in entries:
        assert cite(e["key"]).roster_row == e["roster_row"], e["key"]


def test_a_non_roster_key_has_no_roster_row_and_no_roster_tag():
    c = cite("m1:Q2.2_1")
    assert c.roster_row is None
    assert "[roster row" not in c.render()


def test_the_household_member_key_renders_its_roster_row_outside_the_wording():
    """`m1:1_Q6.3` is the key a live run adjusted for as the respondent's own age.

    The roster row must be visible, and it must sit outside the quoted text so
    the wording after the mark stays diffable against the dictionary.
    """
    line = cite("m1:1_Q6.3").render()
    assert "[roster row 1]" in line
    assert line.index("[roster row 1]") < line.index(MARK)
    assert line.split(MARK, 1)[1] == _norm(cite("m1:1_Q6.3").wording)


# --------------------------------------------------------------------------- #
# the type is the guarantee
# --------------------------------------------------------------------------- #

def test_a_cited_cannot_be_built_without_wording():
    with pytest.raises(CitationUnavailable):
        Cited(key="m1:Q2.2_1", wording="")
    with pytest.raises(CitationUnavailable):
        Cited(key="m1:Q2.2_1", wording="   ")
    with pytest.raises(CitationUnavailable):
        Cited(key="", wording="text")


def test_a_cited_is_frozen_and_slotted_so_the_binding_cannot_be_broken():
    """Rebinding `wording` and smuggling on a new attribute must both fail.

    Frozen alone would leave `c.wording_override = ...` available to any caller
    that wanted a bare key back.

    The refusal of an unknown attribute arrives as `TypeError`, not
    `AttributeError`: `@dataclass(slots=True)` rebuilds the class, and the
    `super()` closure inside the frozen `__setattr__` then no longer matches it.
    What matters is that the write is refused and nothing is stored, so this
    asserts both rather than the exception's name.
    """
    c = cite("m1:Q2.2_1")
    with pytest.raises((AttributeError, TypeError)):
        c.wording = "Name"          # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        c.anything = "x"            # type: ignore[attr-defined]
    assert c.wording == "What is your first name and last name? - First Name"
    assert not hasattr(c, "anything")
    assert not hasattr(c, "__dict__")
    assert Cited.__slots__ == ("key", "wording", "roster_row")


def test_citedset_items_are_a_tuple_not_a_list():
    """`frozen=True` stops rebinding the attribute, not mutating a list behind it."""
    s = cite_all(["m1:Q2.2_1", "m1:Q2.2_2"])
    assert isinstance(s.items, tuple)


def test_an_unknown_key_raises_rather_than_returning_an_empty_citation():
    with pytest.raises(CitationUnavailable) as ei:
        cite("linked:household_poverty")
    assert "linked:household_poverty" in str(ei.value)


def test_cite_all_fails_whole_rather_than_returning_the_bindable_subset():
    with pytest.raises(CitationUnavailable):
        cite_all(["m1:Q2.2_1", "m1:NOPE"])


def test_cite_all_dedupes_but_keeps_order():
    s = cite_all(["m1:Q2.2_2", "m1:Q2.2_1", "m1:Q2.2_2"])
    assert s.keys() == ("m1:Q2.2_2", "m1:Q2.2_1")


def test_a_missing_build_gives_an_empty_index_and_a_raise_naming_the_fix():
    """No `build/` must not read as an instrument with no variables in it.

    `_load` in env/tools.py raises for the same reason: a missing generated input
    that reads as empty once made every variable resolve as unknown-provenance,
    which looked like correct behaviour for the wrong reason.
    """
    saved_index, saved_build = labels._INDEX, labels.BUILD
    try:
        labels._INDEX = None
        labels.BUILD = ROOT / "build-does-not-exist"
        assert labels._index() == {}
        with pytest.raises(CitationUnavailable) as ei:
            cite("m1:Q2.2_1")
        assert "build.py" in str(ei.value)
    finally:
        labels._INDEX, labels.BUILD = saved_index, saved_build


# --------------------------------------------------------------------------- #
# (b) and (c) round-trip and factoring
# --------------------------------------------------------------------------- #

def test_flat_matches_schema_norm_on_every_entry():
    """The render's whitespace collapse must be the one `_wording_is_verbatim` uses.

    A second, subtly different implementation of a normalisation rule is how a
    model ends up quoting exactly what it was shown and failing the validator.
    """
    for e in _entries():
        assert labels._flat(e["question_text"]) == _norm(e["question_text"])


def test_render_mark_occurs_in_no_wording():
    """The key/wording separator must never appear inside an instrument string."""
    assert all(MARK.strip() not in e["question_text"] for e in _entries())


def test_factoring_is_byte_exact_on_every_funnel_anchor_construct():
    """Stem + remainder == wording, for all 70 anchor constructs, no sampling.

    This is the raw identity, before any rendering: `_factor` returns a literal
    character prefix and each item's own tail, so the join is exact by
    construction. Asserting it over the whole frame is what makes "0 violations"
    a measurement rather than a hope.
    """
    anchors = _anchor_constructs()
    assert len(anchors) == 70
    factored = 0
    for c in anchors:
        wordings = [cite(k).wording for k in c.member_keys]
        flat = [labels._flat(w) for w in wordings]
        stem, remainders = labels._factor(flat)
        if stem:
            factored += 1
            assert all(r.startswith(" - ") for r in remainders)
        for w, r in zip(flat, remainders, strict=True):
            assert stem + r == w
    assert factored > 0, "no anchor construct factored: the test proved nothing"


def test_a_rendered_set_round_trips_every_key_and_every_wording():
    """Every key in is visible out, and every wording is recoverable.

    Recovery uses only the rule the render prints, so this fails if the printed
    instruction stops describing the printed block.
    """
    for c in _anchor_constructs():
        s = cite_all(c.member_keys, budget=10 ** 6)
        block = s.render()
        for k in c.member_keys:
            assert k in block, (c.construct_key, k)
        recovered = _recover(block)
        assert set(recovered) == set(c.member_keys), c.construct_key
        for k in c.member_keys:
            assert recovered[k] == _norm(cite(k).wording), k


def test_the_recovered_wording_would_pass_the_verbatim_validator():
    """Round-tripping is only worth something if the result validates.

    `_wording_is_verbatim` diffs under `_norm`, so a recovered string that equals
    the dictionary's text under `_norm` is one the model could quote and pass.
    """
    truth = {e["key"]: e["question_text"] for e in _entries()}
    for c in _anchor_constructs():
        for k, w in _recover(cite_all(c.member_keys, budget=10 ** 6).render()).items():
            assert _norm(w) == _norm(truth[k]), k


def test_a_grid_battery_prints_its_stem_once():
    s = cite_all(["m1:Q2.2_1", "m1:Q2.2_2"])
    block = s.render()
    stem = "What is your first name and last name?"
    assert block.count(stem) == 1
    assert block.splitlines()[0] == stem
    assert _recover(block) == {
        "m1:Q2.2_1": "What is your first name and last name? - First Name",
        "m1:Q2.2_2": "What is your first name and last name? - Last Name",
    }


def test_roster_repeats_do_not_factor_and_stay_distinguishable():
    """Their texts differ at character 0, so there is no shared prefix to factor.

    Each line must still carry its own roster row -- that is what separates
    "household member 1" from "household member 2" for the reader.
    """
    block = cite_all(["m1:1_Q6.3", "m1:2_Q6.3", "m1:3_Q6.3"]).render()
    lines = block.splitlines()
    assert len(lines) == 3
    for n, line in enumerate(lines, start=1):
        assert f"[roster row {n}]" in line
        assert line.startswith(f"m1:{n}_Q6.3 ")
    assert _recover(block)["m1:1_Q6.3"].startswith("1 - How old is this household")


def test_factoring_snaps_back_to_a_separator_and_never_cuts_mid_word():
    """A raw character prefix would split inside the longer sub-item's word."""
    stem, rem = labels._factor(["Q - Item A", "Q - Item Absolutely"])
    assert stem == "Q"
    assert rem == [" - Item A", " - Item Absolutely"]


def test_unrelated_wordings_do_not_factor():
    stem, rem = labels._factor(["Alpha thing", "Beta thing"])
    assert stem == ""
    assert rem == ["Alpha thing", "Beta thing"]


def test_a_single_item_never_factors():
    assert labels._factor(["A - B"]) == ("", ["A - B"])


def test_an_empty_set_renders_empty():
    assert CitedSet().render() == ""


# --------------------------------------------------------------------------- #
# (d) the budget reports, it does not truncate
# --------------------------------------------------------------------------- #

def test_the_budget_names_every_key_it_drops():
    """Reporting means naming them. A count alone leaves the reader guessing."""
    keys = [e["key"] for e in _entries()[:40]]
    s = cite_all(keys, budget=120)
    _kept, dropped = s.plan()
    assert dropped, "budget 120 dropped nothing: the test proved nothing"
    block = s.render()
    for c in dropped:
        assert c.key in block, c.key
    assert f"{len(dropped)} withheld" in block
    assert "Nothing was shortened" in block


def test_nothing_the_budget_keeps_is_shortened():
    """Kept wordings are whole. Truncation is the failure, not the fallback."""
    keys = [e["key"] for e in _entries()[:40]]
    s = cite_all(keys, budget=200)
    kept, dropped = s.plan()
    assert kept and dropped
    recovered = _recover(s.render())
    for c in kept:
        assert recovered[c.key] == _norm(c.wording), c.key


def test_plan_and_render_agree_on_what_was_kept():
    """The budget must count exactly the strings the render prints."""
    keys = [e["key"] for e in _entries()[:60]]
    for budget in (0, 50, 120, 300, 600, 5000):
        s = cite_all(keys, budget=budget)
        kept, dropped = s.plan()
        assert len(kept) + len(dropped) == len(keys)
        recovered = _recover(s.render())
        assert set(recovered) == {c.key for c in kept}


def test_a_zero_budget_shows_nothing_and_still_reports_everything():
    keys = [e["key"] for e in _entries()[:5]]
    s = cite_all(keys, budget=0)
    kept, dropped = s.plan()
    assert kept == ()
    assert len(dropped) == 5
    block = s.render()
    for k in keys:
        assert k in block


def test_the_default_budget_is_the_module_constant():
    assert CITATION_BUDGET == 600
    assert cite_all(["m1:Q2.2_1"]).budget == 600


# --------------------------------------------------------------------------- #
# (e) measured render cost
# --------------------------------------------------------------------------- #

def test_render_cost_for_a_funnel_anchor_construct_is_pinned():
    """VERIFIED 2026-09-01 on build 6fcd02755bf3, over all 70 anchor constructs.

        median 116 chars, p90 149 chars, max 1395 chars,
        1 of 70 constructs exceeds CITATION_BUDGET=600.

    Pinned as a range, not an equality: the point is to catch a rendering change
    that quietly multiplies what the model reads, not to name a number that has
    to be edited whenever the instrument is rebuilt. A guard that fires on normal
    operation gets disabled by whoever it annoys.
    """
    costs = sorted(len(cite_all(c.member_keys, budget=10 ** 6).render())
                   for c in _anchor_constructs())
    median = statistics.median(costs)
    p90 = costs[int(0.9 * (len(costs) - 1))]
    assert 80 <= median <= 200, f"median render cost moved to {median}"
    assert 100 <= p90 <= 300, f"p90 render cost moved to {p90}"

    over = [c for c in _anchor_constructs()
            if cite_all(c.member_keys).plan()[1]]
    assert len(over) == 1, (
        f"{len(over)} anchor constructs now exceed CITATION_BUDGET; "
        "one battery did on the pinned build")
