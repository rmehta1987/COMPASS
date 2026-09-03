"""Model-visible surfaces as typed structures.

These pin the removal of a failure class, not a mitigation of it. Two models
mis-parsed the resolver's delimited candidate line on the same row on
2026-09-01 — one took the roster tag as part of the key, one took the fact
clause as part of the wording — and both returned correct verdicts with correct
reasoning. Here the model receives an integer and never sees a key, so neither
mistake is expressible. Rationale: docs/adr/003-index-selection.md.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Literal

import pytest
from pydantic import BaseModel

from agent import prompt_contract as PC
from env import labels, tools

ENTRIES = tools._load()["entries"]
KEYS = ["m3:Q2.1", "m2:Q9.1", "m1:1_Q6.3"]


class _Answer(BaseModel):
    verdict: Literal["picked", "none"]
    indices: tuple[int, ...] = ()


class _Optional(BaseModel):
    verdict: Literal["picked", "none"] | None = None


class _NoLiterals(BaseModel):
    text: str = ""


def _contract(keys: Sequence[str] = KEYS, facts: Any = None,
              **kw: Any) -> PC.SelectionContract:
    opts: dict[str, Any] = dict(
        name="probe", task="pick one", output_model=_Answer, refusal="none",
        candidates=PC.candidates_from_keys(keys, facts))
    opts.update(kw)
    return PC.SelectionContract(**opts)


# --------------------------------------------------------------------------- #
# the failure class this replaces
# --------------------------------------------------------------------------- #


def test_the_production_prompt_shows_no_key_at_all():
    """Nothing to copy, so nothing to copy wrongly.

    The strongest form of the guarantee: it is not that the model is told not to
    return a key, it is that it was never given one.
    """
    rendered = _contract().render()
    for key in KEYS:
        assert key not in rendered
    assert "Select by `index`" in rendered
    assert "Return the integer only" in rendered


def test_keys_appear_only_when_a_reader_asks_to_audit_the_prompt():
    audit = _contract().render(debug=True)
    for key in KEYS:
        assert key in audit


def test_a_candidate_carries_wording_as_a_field_with_no_delimiter():
    d = _contract().candidates[0].as_dict()
    assert d == {"index": 1, "wording": tools._BY_KEY["m3:Q2.1"]["question_text"]}
    assert json.loads(json.dumps(d))["wording"] == d["wording"]


def test_a_wording_reaches_the_model_byte_for_byte_including_its_newlines():
    """The lossy step a line-oriented block forces does not exist here.

    `env/labels.py::Cited.render` collapses whitespace because a line block
    cannot carry the hard newlines 323 entries contain. JSON escapes them.
    """
    key = next(str(e["key"]) for e in ENTRIES if "\n" in e["question_text"])
    c = PC.candidates_from_keys([key])[0]
    assert "\n" in c.wording
    assert c.wording == tools._BY_KEY[key]["question_text"]
    assert json.loads(json.dumps(c.as_dict()))["wording"] == c.wording


def test_an_index_resolves_to_a_citation_the_model_did_not_have_to_copy():
    cited = _contract().resolve(2)
    assert isinstance(cited, labels.Cited)
    assert cited.key == "m2:Q9.1"
    assert cited.wording == tools._BY_KEY["m2:Q9.1"]["question_text"]


@pytest.mark.parametrize("bad", [0, -1, 4, 99])
def test_an_index_outside_the_offered_range_raises_rather_than_clamps(bad):
    """Selecting what was not offered is a result to record, not to round."""
    with pytest.raises(IndexError, match="outside"):
        _contract().resolve(bad)
    with pytest.raises(IndexError, match="out of range"):
        _contract().facts_for(bad)


def test_candidate_indices_must_be_one_through_n_in_order():
    with pytest.raises(ValueError, match="indices must be"):
        _contract(candidates=(PC.Candidate(index=7, key="m3:Q2.1", wording="x"),))


# --------------------------------------------------------------------------- #
# facts are read by the harness, never transcribed by the model
# --------------------------------------------------------------------------- #


def test_the_harness_reads_a_fact_it_already_gave_the_model():
    """An earlier draft asked for a `family_size` field in the answer.

    That is the transcription failure this module removes, reintroduced one
    field over: the number is already on the candidate the model selected.
    """
    c = _contract(facts={"m1:1_Q6.3": {"roster_family_size": 15}})
    assert c.facts_for(3) == {"roster_family_size": 15}
    assert c.facts_for(1) == {}
    assert "family_size" not in PC.VariableSelection.model_fields


def test_facts_render_as_named_fields_beside_the_wording():
    c = _contract(facts={"m3:Q2.1": {"module": "3", "roster_family_size": 1}})
    d = c.candidates[0].as_dict()
    assert d["module"] == "3" and d["roster_family_size"] == 1
    # Not appended to the wording, which is what the line format did.
    assert "module" not in d["wording"]


# --------------------------------------------------------------------------- #
# refusal is a declared value, never a downstream text heuristic
# --------------------------------------------------------------------------- #


def test_a_contract_that_cannot_say_no_answer_is_refused():
    with pytest.raises(ValueError, match="answers everything"):
        _contract(refusal="  ")


def test_a_refusal_must_name_a_literal_the_output_model_can_hold():
    with pytest.raises(ValueError, match="not expressible"):
        _contract(refusal="abstain")


def test_a_refusal_is_read_from_the_annotations_not_the_rendered_schema():
    """Anti-vacuity: a FIELD NAMED like the refusal must not satisfy it.

    A check that string-searched the rendered JSON would pass on a field name or
    a description, which is how a refusal that names nothing passes a check that
    looks like it means something.
    """
    assert "indices" in json.dumps(_Answer.model_json_schema())
    with pytest.raises(ValueError, match="not expressible"):
        _contract(refusal="indices")
    assert PC._literal_values(_NoLiterals) == frozenset()


def test_a_literal_wrapped_in_optional_is_still_expressible():
    """One-level `get_args` returns empty for `Optional[Literal[...]]`.

    It would reject a refusal the model can express and blame the refusal.
    """
    assert PC._literal_values(_Optional) == frozenset({"picked", "none"})
    assert _contract(output_model=_Optional, refusal="none").refusal == "none"


def test_the_refusal_reaches_the_model_as_an_answer_not_as_a_failure():
    assert "return 'none'. That is an answer" in _contract().render()


# --------------------------------------------------------------------------- #
# the retrieval surface
# --------------------------------------------------------------------------- #


def test_the_retrieval_contract_renders_the_request_and_every_verdict():
    c = PC.retrieval_contract("self-rated overall health",
                              PC.candidates_from_keys(KEYS))
    assert c.refusal == "absent"
    assert c.refusal in PC._literal_values(PC.VariableSelection)
    rendered = c.render()
    assert "self-rated overall health" in rendered
    for v in ("resolved", "family", "derive", "ambiguous", "absent"):
        assert v in rendered
    for key in KEYS:
        assert key not in rendered


def test_the_retrieval_task_explains_the_family_fact_it_ships():
    """The prompt names `roster_family_size` because the candidates carry it."""
    c = PC.retrieval_contract("x", PC.candidates_from_keys(
        ["m1:1_Q6.3"], {"m1:1_Q6.3": {"roster_family_size": 15}}))
    rendered = c.render()
    assert "roster_family_size" in c.task
    assert '"roster_family_size": 15' in rendered
