"""What `env/tools.py::browse_variables` lists, measured rather than described.

The tool exists because of one recorded run: retrieval ERRORED and the model
located the participant-age item by walking the key space with ~94 brute-force
`resolve_variable` calls. That is not a retrieval result and no ranking change
reaches it, so the environment now hands the key space over.

THREE DEFINITIONS OF "SIZE" LIVE IN THIS AREA and a critic has already called one
of them wrong because another was meant. Everything below is stated in one of
them and says which:

  bare      distinct roster-normalised `searchable_text`, summed. Module 2 is
            1,464 wordings / 176,943 characters over build 6fcd02755bf3.
  rendered  the JSON list of rows a caller receives, which is what
            `listing_chars` reports and what `BROWSE_PAGE_BUDGET` bounds. The
            same module 2 listing is 272,986 characters this way.
  dumped    the whole return value serialised the way the contamination scan
            serialises it, envelope and log included.

`bare` bounds nothing the model reads. The page budget is stated in `rendered`
and the surface pins below are stated in both `rendered` and `dumped`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from env import tools as T  # noqa: E402

#: The build these numbers were measured over. Every pin in this file is a
#: function of the dictionary, so a different build means re-measure, not edit
#: the number until it passes.
# Re-derived 2026-09-02 against d7a70c5014c5. That build differs from
# 6fcd02755bf3 only by BUILD_RULES_VERSION and the two identifier columns,
# which touch no text a browse page renders; the pinned wording and
# character counts were re-measured and did not move.
BUILD = "3dc8415eccfe"


def _pages() -> list[tuple[str, str | None, dict]]:
    """Every page `browse_variables` can return, module page first."""
    out: list[tuple[str, str | None, dict]] = []
    for m in T.BROWSE_MODULES:
        out.append((m, None, T.browse_variables(module=m)))
        for s in T.browse_sections(m):
            out.append((m, s, T.browse_variables(module=m, section=s)))
    return out


def _dumped(page: dict) -> int:
    return len(json.dumps(page, ensure_ascii=False, sort_keys=True))


def test_the_build_these_pins_were_measured_over_is_the_build_under_test():
    """Every number in this file is a function of the dictionary."""
    assert T.dictionary_version() == BUILD, (
        "the dictionary changed; re-measure every pin in this file rather than "
        "editing one until it passes")


# --------------------------------------------------------------------------- #
# the assumption the section index is built on
# --------------------------------------------------------------------------- #

def test_every_construct_key_carries_a_section():
    """`_SECTION_RX`'s comment claims this of all 1,080 keys. Checked, not assumed.

    The section is read off the key because the dictionary has no section field.
    If the build ever emits a key shape that does not carry one, the index grows
    a `?` bucket and this fails, which is the point: a `?` section is a listing
    the caller cannot open.
    """
    keys = sorted(T._BY_CONSTRUCT)
    assert len(keys) == 1080, len(keys)
    unparsed = [k for k in keys if T._section_of(k) == "?"]
    assert unparsed == [], unparsed


# --------------------------------------------------------------------------- #
# the failure this tool was built for
# --------------------------------------------------------------------------- #

def test_module_1_is_listed_whole_and_holds_the_item_the_live_run_brute_forced():
    """The one measured failure, turned into a single call.

    `m1:Q2.15_3` is the item that run found only by walking the key space. It is
    on module 1's own page, at item level, with its wording — no section to pick
    first and no phrase to guess.
    """
    page = T.browse_variables(module="1")
    assert page["outcome"] == "ok"
    assert page["level"] == "item", (
        "module 1 must list whole; paging it defeats the purpose of the tool")
    assert page["n_rows"] == 81
    hit = [r for r in page["rows"] if r["key"] == "m1:Q2.15_3"]
    assert hit, "the item the live run brute-forced is not on module 1's page"
    assert hit[0]["text"] == "What is your birthday? - Year"


def test_a_browse_key_is_always_a_key_that_resolves():
    """A listing that hands out unresolvable keys is worse than no listing.

    Item rows carry a variable key, so they resolve `unique`. Construct keys and
    section signposts resolve `construct` when the construct has members, and
    `unique` when the construct IS a single variable — 1,080 constructs over
    2,804 variables, so most of them are. Neither may ever come back
    `not_found` or `ambiguous`, which are the two outcomes that cost the caller
    a turn.
    """
    for module, section, page in _pages():
        if page["level"] == "item":
            for r in page["rows"]:
                assert T.resolve_variable(key=r["key"])["outcome"] == "unique", (
                    module, section, r["key"])
        else:
            field = ("construct_key" if page["level"] == "construct"
                     else "first_construct_key")
            for r in page["rows"]:
                out = T.resolve_variable(key=r[field])["outcome"]
                assert out in ("construct", "unique"), (module, section, r[field])


# --------------------------------------------------------------------------- #
# the guarantee the docstring and the tool description both make
# --------------------------------------------------------------------------- #

def test_every_page_is_exhaustive_at_the_level_it_reports():
    """"COMPLETE at level=X" is stated in the log and in the tool schema.

    That claim is the whole difference between browsing and searching — an
    absence on an item page is a real absence, where a search miss is a result
    about one wording. Stated in two prompt surfaces and enforced only here.
    """
    for module, section, page in _pages():
        entries = (T._BY_MODULE[module] if section is None
                   else T._BY_SECTION[module][section])
        if page["level"] == "item":
            listed = {r["text"] for r in page["rows"]}
            expected = {T._norm_wording(e["searchable_text"]) for e in entries}
        elif page["level"] == "construct":
            listed = {r["construct_key"] for r in page["rows"]}
            expected = {e["construct_key"] for e in entries}
        else:
            listed = {r["section"] for r in page["rows"]}
            expected = set(T.browse_sections(module))
        assert listed == expected, (module, section, page["level"],
                                    sorted(expected - listed)[:5],
                                    sorted(listed - expected)[:5])


def test_roster_repeats_collapse_to_one_row_and_say_how_many():
    """The collapse is why module 1 fits at all; a silent one would mislead."""
    page = T.browse_variables(module="2", section="8")
    shared = [r for r in page["rows"] if r["n_keys_sharing_wording"] > 1]
    assert shared, "no roster repeat on a page built from a roster battery"
    for r in shared:
        same = [e for e in T._BY_SECTION["2"]["8"]
                if T._norm_wording(e["searchable_text"]) == r["text"]]
        assert len(same) == r["n_keys_sharing_wording"]


# --------------------------------------------------------------------------- #
# module 2 does not blow the context
# --------------------------------------------------------------------------- #

def test_module_2_never_returns_its_1464_wordings():
    """C25's acceptance clause, measured in `rendered` characters.

    The listing module 2 declines is an order of magnitude over the page bound.
    The number is asserted, not described, so a future change that quietly makes
    the fallback unnecessary — or unreachable — shows up here.
    """
    declined = T._chars(T._item_rows(T._BY_MODULE["2"]))
    assert declined == 272_986, declined
    assert declined > 12 * T.BROWSE_PAGE_BUDGET

    page = T.browse_variables(module="2")
    assert page["level"] == "section_index"
    assert page["n_rows"] == 80
    assert page["listing_chars"] == 18_790, page["listing_chars"]


def test_no_page_exceeds_the_page_budget():
    """`BROWSE_PAGE_BUDGET` is a bound on every page, not on some of them.

    Construct level is the last rung — there is nothing coarser to fall back to
    — so this is the assertion that keeps the constant honest. A red here means
    a section grew past the point where the fallback still fits, and the fix is
    a coarser rung or a bigger bound, never a truncated listing.
    """
    over = [(m, s, p["level"], p["listing_chars"]) for m, s, p in _pages()
            if p["listing_chars"] > T.BROWSE_PAGE_BUDGET]
    assert over == [], over


def test_the_page_budget_is_derived_from_the_dictionary_not_chosen():
    """Both bounds in `BROWSE_PAGE_BUDGET`'s comment, re-derived here.

    `SEARCH_SCORE_FLOOR` carried a number that contradicted the sentence beside
    it for two months because nothing re-derived the sentence. This is that
    test, for this constant.
    """
    module_1 = T._chars(T._item_rows(T._BY_MODULE["1"]))
    assert module_1 == 10_534, module_1
    assert module_1 <= T.BROWSE_PAGE_BUDGET, (
        "module 1 no longer fits whole, which is the case the tool exists for")

    biggest = max(p["listing_chars"] for _, _, p in _pages())
    assert biggest == 20_065, biggest
    assert T.BROWSE_PAGE_BUDGET == -(-biggest // 1000) * 1000, (
        "the budget is the smallest whole thousand that bounds the largest page; "
        f"largest page is now {biggest}")


# --------------------------------------------------------------------------- #
# the byte-size pin
# --------------------------------------------------------------------------- #

def test_the_browse_surface_is_pinned_in_bytes():
    """C25's third acceptance clause: growth has to be visible, not inferred.

    Every page is sampled by the contamination scan, so this total IS the
    contribution `browse_variables` makes to the model-visible surface. Both
    definitions are pinned: `rendered` is what the page budget governs, `dumped`
    is what the scan concatenates.

    RE-MEASURED 2026-08-31 by C22, over the same build. `listing_chars` did not
    move — the rows are untouched — and only `dumped` fell, because the log lost
    the 375-character constant tail it repeated on all 135 pages. That tail is
    now stated once in `agent/registry.py::_TOOLS["browse_variables"]`, so the
    text still reaches the model; it reaches it once instead of 135 times.
      dumped total   370,974 -> 317,919   (-53,055, -14.3%)
      log total       53,489 chars, mean 396/page, was 106,544 and mean 789
    The equality is kept rather than relaxed to a ceiling: this pin exists so
    growth is visible rather than inferred, and a ceiling would hide a page that
    grew behind a page that shrank.
    """
    pages = _pages()
    assert len(pages) == 135, len(pages)
    assert sum(p["listing_chars"] for _, _, p in pages) == 247_790
    assert sum(_dumped(p) for _, _, p in pages) == 317_919

    by_module = {m: p for m, s, p in pages if s is None}
    assert [(p["level"], p["n_rows"], p["listing_chars"], _dumped(p))
            for p in by_module.values()] == [
        ("item", 81, 10_534, 11_034),
        ("section_index", 80, 18_790, 19_343),
        ("section_index", 37, 8_357, 8_909),
    ]


# --------------------------------------------------------------------------- #
# the refusals, and the argument shapes a caller actually writes
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(("kwargs", "must_name"), [
    ({"module": "4"}, "['1', '2', '3']"),
    ({"module": "m9"}, "['1', '2', '3']"),
    ({"module": "1", "section": "999"}, "browse_variables(module='1')"),
])
def test_a_refusal_names_what_to_call_instead(kwargs, must_name):
    """59 of 419 live calls died on an argument and the error never said what.

    A `not_found` that does not name the legal values spends the caller's next
    turn on a guess.
    """
    out = T.browse_variables(**kwargs)
    assert out["outcome"] == "not_found"
    assert out["rows"] == [] and out["n_rows"] == 0
    assert must_name in out["log"], out["log"]


@pytest.mark.parametrize(("written", "meant"), [
    ({"module": "m1"}, {"module": "1"}),
    ({"module": " 1 "}, {"module": "1"}),
    ({"module": "2", "section": "Q5"}, {"module": "2", "section": "5"}),
    ({"module": "M2", "section": "q5"}, {"module": "2", "section": "5"}),
])
def test_the_prefixes_a_caller_is_likely_to_write_are_accepted(written, meant):
    """`m1` and `Q5` are how these ids are printed everywhere else here."""
    assert T.browse_variables(**written) == T.browse_variables(**meant)


def test_the_level_is_not_a_caller_argument():
    """A caller who could ask for the unpaged listing would eventually get it.

    Checked on the schema the model is shown and on the function itself, because
    `_logged` replaces the signature and `inspect` alone would report `(*a,
    **kw)` and pass whatever was added.
    """
    from agent.registry import SCHEMAS, build_registry
    props = SCHEMAS["browse_variables"]["parameters"]["properties"]
    assert set(props) == {"module", "section"}, sorted(props)
    calls, _ = build_registry("benchmark")
    with pytest.raises(TypeError):
        calls["browse_variables"](module="2", level="item")
