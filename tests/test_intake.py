"""Intake: typed text to RetrievalRequest, deterministic.

The bundle-backed acceptance is check.sh step 7: the canaries now build their
requests through intake, so a parse regression shows there. These pin the
grammar, the shipped contract and the specificity note without the bundle.
"""

from __future__ import annotations

import pytest

from pipeline import canary as C
from pipeline import intake as I
from pipeline.retrieve import load_template


def test_construct_instances_and_timeframe_parse_and_round_trip():
    it = I.parse_request("use of anti-inflammatory medication: ibuprofen, naproxen "
                         "[past 12 months]", role="outcome")
    r = it.request
    assert r.construct == "use of anti-inflammatory medication"
    assert r.instances == ("ibuprofen", "naproxen")
    assert r.timeframe == "past 12 months" and r.role.value == "outcome"
    assert r.population is None
    assert it.query == r.to_query()
    # what the encoder sees is the template's rendering, not the typed line
    assert it.query == ("use of anti-inflammatory medication past 12 months: "
                        "ibuprofen, naproxen")


def test_instances_are_trimmed_deduplicated_and_order_preserving():
    it = I.parse_request("x:  b , a,b,, a ")
    assert it.request.instances == ("b", "a")


def test_population_is_never_set_shipped_contract():
    it = I.parse_request("adults with asthma: inhaler use")
    assert it.request.population is None
    assert "population" not in I.parse_request.__code__.co_varnames[:3]


def test_explicit_timeframe_overrides_the_bracketed_one():
    it = I.parse_request("x [lifetime]", timeframe="current")
    assert it.request.timeframe == "current"


@pytest.mark.parametrize("bad", ["", "   ", ": a, b", "[past year]"])
def test_an_empty_construct_is_refused(bad):
    with pytest.raises(ValueError):
        I.parse_request(bad)


def test_an_unknown_role_is_refused():
    with pytest.raises(ValueError):
        I.parse_request("x", role="mediator")


def test_short_requests_get_the_specificity_note_and_are_never_rewritten():
    it = I.parse_request("smoking")
    assert not it.specific and it.content_words == 1
    assert any("0.493" in n and "0.676" in n for n in it.notes)
    assert any("no instances" in n for n in it.notes)
    assert it.query == "smoking"                         # untouched


def test_instance_naming_requests_are_specific_and_unnoted():
    it = I.parse_request("current cigarette smoking status: daily, some days")
    assert it.specific and it.content_words >= I.SPECIFIC_MIN_CONTENT_WORDS
    assert it.notes == ()


def test_content_words_use_the_templates_own_rule():
    tpl = load_template()
    it = I.parse_request("age when first told they had diabetes")
    assert it.content_words == len(tpl.content_words(it.query, True))


def test_every_canary_request_reproduces_through_intake():
    # item 7's acceptance without the bundle: the request intake builds from
    # the canary's typed form equals the one the canary would build directly
    tpl = load_template()
    for c in C.CANARIES:
        direct = tpl.RetrievalRequest(construct=c.construct,
                                      role=tpl.VariableRole.EXPOSURE,
                                      instances=c.instances)
        assert I.parse_request(c.text()).request == direct, c.name


def test_c3_is_specific_only_because_of_its_instance():
    c3 = next(c for c in C.CANARIES if c.name == "C3")
    with_instance = I.parse_request(c3.text())
    without = I.parse_request(c3.construct)
    assert with_instance.content_words > without.content_words
    assert without.notes and "no instances" in without.notes[-1]
