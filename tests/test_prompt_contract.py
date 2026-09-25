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


def test_absent_is_scoped_to_the_items_listed_not_the_codebook() -> None:
    """C29a: the model sees k candidates, so `absent` can only mean the list missed.

    It was defined as "the codebook does not measure this" while the model was
    shown a pool, so a pool miss read as an instrument absence.
    """
    import re

    rendered = PC.retrieval_contract("x", PC.candidates_from_keys(KEYS)).render()
    # The schema is JSON inside the prompt, so a wrapped docstring line arrives
    # as a literal backslash-n plus indentation.
    flat = re.sub(r"(\\n|\s)+", " ", rendered)
    assert "none of the items listed measures this" in flat
    assert "codebook does not measure" not in flat
    assert "items listed below" in PC.RETRIEVAL_GUIDANCE


def test_the_retrieval_task_explains_the_family_fact_it_ships():
    """The prompt names `roster_family_size` because the candidates carry it."""
    c = PC.retrieval_contract("x", PC.candidates_from_keys(
        ["m1:1_Q6.3"], {"m1:1_Q6.3": {"roster_family_size": 15}}))
    rendered = c.render()
    assert "roster_family_size" in c.task
    assert '"roster_family_size": 15' in rendered


# --------------------------------------------------------------------------- #
# a default to start from, asked only after `ambiguous`
# --------------------------------------------------------------------------- #


def test_the_verdict_call_still_forbids_picking_one_to_be_helpful() -> None:
    """The default is a SECOND call, so the first one's text did not move.

    `ROSTER_NOTE` was factored out of `RETRIEVAL_GUIDANCE` to share it with the
    default surface. The verdict is a measurement only while its instruction is
    fixed (`AGENTS.md` §Verification Discipline), so the text is pinned whole.
    """
    assert PC.RETRIEVAL_GUIDANCE == (
        "Decide what kind of answer this request has among the survey codebook "
        "items listed below. You have each item's wording and named facts about "
        "it; you do not have response options, value labels, skip logic or any "
        "data. If separating two candidates would need a fact you were not "
        "given, that is `ambiguous`, not a close call. Do not pick one to be "
        "helpful.\n\n"
        "A candidate whose `roster_family_size` is N is one member of a family of "
        "N: the same question put once per person. Those N are not N different "
        "variables, and a request naming no particular member is not answered by "
        "any one of them.")
    rendered = PC.retrieval_contract("x", PC.candidates_from_keys(KEYS)).render()
    assert PC.DEFAULT_GUIDANCE not in rendered
    assert "DefaultPick" not in rendered


def test_the_default_contract_can_refuse_and_carries_what_it_was_given() -> None:
    """Request, role and the settling fact reach the model; keys never do."""
    c = PC.default_contract("does a raise b", "outcome", "which measure",
                            PC.candidates_from_keys(KEYS))
    assert c.refusal == "none"
    assert c.refusal in PC._literal_values(PC.DefaultPick)
    rendered = c.render()
    assert '"does a raise b"' in rendered
    assert "the OUTCOME here" in rendered
    assert "would settle it: which measure" in rendered
    assert PC.ROSTER_NOTE in rendered
    for key in KEYS:
        assert key not in rendered


def test_a_default_contract_with_no_settling_fact_says_none() -> None:
    """A blank `missing_dimension` prints no empty "would settle it:" line."""
    rendered = PC.default_contract("x", "exposure", "  ",
                                   PC.candidates_from_keys(KEYS)).render()
    assert "the earlier reading said would settle it" not in rendered


# --------------------------------------------------------------------------- #
# C29-C: the splitter may leave words out, never add or change one
# --------------------------------------------------------------------------- #

_REQ = "Does smoking and heavy, regular drinking raise the risk of high blood pressure?"


def _reply(exposures: list[str], outcomes: list[str], unsplittable: bool = False) -> str:
    return json.dumps({"exposures": exposures, "outcomes": outcomes,
                       "unsplittable": unsplittable})


def test_a_split_in_the_questions_own_words_is_accepted() -> None:
    """Case, spacing and punctuation are forgiven, and words may be left out."""
    split = PC.parse_split(_REQ, "```json\n" + _reply(
        ["Smoking", "heavy drinking"], ["high blood   pressure"]) + "\n```")
    assert split.exposures == ("Smoking", "heavy drinking")   # "regular" dropped
    assert split.outcomes == ("high blood   pressure",)


def test_a_split_that_adds_changes_or_reorders_a_word_is_refused() -> None:
    """The splitter cannot paraphrase, reorder, or bring in wording of its own."""
    for bad in (_reply(["tobacco use"], ["high blood pressure"]),    # added
                _reply(["smoking"], ["hypertension"]),               # changed
                _reply(["drinking heavy"], ["high blood pressure"]),  # reordered
                _reply(["smoking"], ["   "])):                        # empty
        with pytest.raises(PC.SplitRejected, match="own words"):
            PC.parse_split(_REQ, bad)


def test_a_split_that_contradicts_itself_is_refused() -> None:
    """One entry in both roles, entries beside `unsplittable`, or half a pair."""
    with pytest.raises(PC.SplitRejected, match="both exposure and outcome"):
        PC.parse_split(_REQ, _reply(["smoking"], ["Smoking"]))
    with pytest.raises(PC.SplitRejected, match="unsplittable"):
        PC.parse_split(_REQ, _reply(["smoking"], [], unsplittable=True))
    with pytest.raises(PC.SplitRejected, match="both needed"):
        PC.parse_split(_REQ, _reply(["smoking"], []))
    with pytest.raises(PC.SplitRejected, match="no JSON object"):
        PC.parse_split(_REQ, "I cannot split this.")
    # Anti-vacuity: a request that names neither kind may say so.
    assert PC.parse_split("tell me about the survey", _reply([], [], True)).unsplittable


def test_the_split_prompt_carries_the_request_and_nothing_else_retrieved() -> None:
    """The splitter reads the sentence alone: no candidates, no instrument text."""
    prompt = PC.split_prompt(_REQ)
    assert _REQ in prompt and PC.SPLIT_GUIDANCE in prompt
    assert "Candidates" not in prompt and '"index"' not in prompt
    assert json.dumps(PC.RequestSplit.model_json_schema()) in prompt
    # The developer note stays out of what the model reads.
    assert "prompt text" not in json.dumps(PC.RequestSplit.model_json_schema())
