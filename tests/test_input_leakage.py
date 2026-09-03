"""The input-side check: does a prompt already contain the answer it scores?

Every other contamination test in this repo scans what the environment SAYS to
the model. These scan what the model is ASKED, against the key the answer will
be scored on. `references/PRIOR_ART_CONTAMINATION.md` records two papers that do
this and notes that COMPASS did not; C2 is that gap.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import benchmark.input_leakage as IL  # noqa: E402
from agent.specifier import user_prompt  # noqa: E402
from benchmark.cohort_papers import COHORT_PAPERS  # noqa: E402


@pytest.fixture(scope="module")
def pairs() -> list:
    """Every live pair the current frame enumerates."""
    return IL.enumerated_pairs()


def test_no_enumerated_prompt_contains_a_papers_answer(pairs):
    """The acceptance: 384 pairs against sixteen papers, statically.

    Not one sampled pair. `model_visible_surface` renders `cands[0]` for the
    hash, and a leak reaching only the prompts of pairs 2 through 384 is exactly
    the hole that leaves.
    """
    assert len(pairs) > 1, "a one-pair frame makes this test vacuous"
    assert not IL.check_input_does_not_contain_the_answer()


@pytest.mark.parametrize(
    ("planted", "field"),
    [("see PMID 38715087 for the comparable design", "pubmed_id"),
     ("the analysis used weighted quantile sum regression, WQS", "design_phrase"),
     ("the realised analytic sample was 5,096 participants", "analytic_n"),
     ("published in Circ Cardiovasc Qual Outcomes", "venue")])
def test_the_input_scan_catches_a_planted_answer(planted, field):
    """A scan that has never failed is not known to work — once per field.

    Four fields, four separate mechanisms: an id match, a phrase match against
    the derived answer-only set, a numeral match in both written forms, and a
    venue string. A single control would have left three of them untested.
    """
    hits = IL.scan_prompt("PAIR-control", f"PAIR x\n  {planted}")
    assert any(h.field == field for h in hits), (field, hits)


def test_instrument_vocabulary_is_not_an_answer():
    """The filter that makes this check worth running rather than noise.

    The papers drew on this instrument, so a paper's outcome name being in a
    prompt is the benchmark working. MEASURED 2026-08-28 in
    build/dictionary.json: `uterine fibroid` 2 occurrences, `fibroid` 4,
    `hypertension` 22, `asthma` 4, `breast cancer` 144 — every one of them the
    published outcome of one of the sixteen AND every one of them a question the
    study asked. A scan calling those leaks would be deleted within a week.
    """
    instrument = IL.instrument_text()
    for word in ("uterine fibroid", "fibroid", "hypertension", "asthma",
                 "breast cancer"):
        assert word in instrument, f"{word} is no longer instrument content"
        assert not any(word in IL.answer_only_phrases(p.pmid)
                       for p in COHORT_PAPERS), f"{word} scored as an answer"
    # The DESIGN built out of those words is still answer-only, which is the
    # whole distinction: the instrument supplies `breast cancer`, it does not
    # supply `breast cancer case control`.
    assert "breast cancer case control" in IL.answer_only_phrases("36823587")


def test_the_template_supplies_its_own_vocabulary_and_is_not_an_answer():
    """Boilerplate design words are derived from the prompt, never listed.

    `user_prompt` says `exposure`, `outcome`, `covariate` and `unit of analysis`
    in every prompt it renders. Listing those by hand would need editing every
    time Lane A touches the template — the staleness this project keeps paying
    for — so they come from rendering the template against a blanked pair.
    """
    template = IL.template_text()
    for word in ("exposure", "outcome", "covariate", "falsifier"):
        assert word in template
        assert not any(word == ph
                       for p in COHORT_PAPERS
                       for ph in IL.answer_only_phrases(p.pmid)), word


def test_a_template_edit_cannot_turn_boilerplate_into_a_leak(monkeypatch):
    """The derived filter has to actually follow the template.

    Seeded: add a paper's design word to the template and the check must stay
    clean, because the word is now boilerplate every prompt carries rather than
    something one pair's answer key holds.
    """
    word = "cardiometabolic"
    assert any(word in IL.answer_only_phrases(p.pmid) for p in COHORT_PAPERS)
    monkeypatch.setattr(IL, "user_prompt",
                        lambda pair: f"{user_prompt(pair)}\n{word} note")
    IL.template_text.cache_clear()
    IL.answer_only_phrases.cache_clear()
    try:
        assert word in IL.template_text()
        assert not any(word in IL.answer_only_phrases(p.pmid)
                       for p in COHORT_PAPERS)
    finally:
        IL.template_text.cache_clear()
        IL.answer_only_phrases.cache_clear()


def test_a_missing_dictionary_raises_rather_than_reading_as_empty(monkeypatch):
    """An empty instrument would make every paper phrase look answer-only.

    That is the failure mode where a check reports hundreds of leaks, gets read
    as broken, and is switched off — worse than not having it.
    """
    monkeypatch.setattr(IL, "ROOT", ROOT / "no_such_root")
    IL.instrument_text.cache_clear()
    try:
        with pytest.raises(FileNotFoundError, match=r"run \`python build\.py\`"):
            IL.instrument_text()
    finally:
        IL.instrument_text.cache_clear()


def test_the_environment_forced_fields_are_named_and_not_scored(pairs):
    """The partition C12 needs, computed rather than asserted.

    The enumeration chose the pair, so both anchors, their wording and their
    member keys are in every prompt by construction. They are NOT leaks — but a
    "percent of design recovered" score that counts exposure and outcome
    identification is scoring the funnel, not the model, and this is where that
    is written down.
    """
    supplied = IL.environment_supplied(pairs[0])
    assert set(supplied) == {
        "exposure_key", "exposure_wording", "exposure_member_keys",
        "outcome_key", "outcome_wording", "outcome_member_keys",
        "estimability", "requires_derivation"}
    prompt = user_prompt(pairs[0])
    for field, values in supplied.items():
        for v in values:
            if v:
                assert v in prompt, f"{field} claims {v!r} is in the prompt"
    # And none of them is reported as a leak, in either direction.
    assert not IL.scan_prompt(pairs[0].pair_id, prompt)


def test_the_holdout_placement_holds_for_this_key_too():
    """It reads two answer keys, so it lives where answer keys live."""
    from benchmark.contamination_check import check_holdout_not_reachable

    assert (ROOT / "benchmark" / "input_leakage.py").exists()
    for d in ("curated", "env", "agent"):
        assert not (ROOT / d / "input_leakage.py").exists()
    assert "input_leakage" not in (ROOT / "env" / "tools.py").read_text()
    assert not check_holdout_not_reachable()


def test_a_paper_token_in_the_pair_half_is_found_on_every_pair(monkeypatch):
    """The end-to-end seed, over the frame rather than one hand-built string.

    Rendered before patching so the template is the real one: this seeds the
    PAIR-injected half, which is the half this check owns.
    """
    IL.template_text()          # cache the real template first
    real = IL.user_prompt
    monkeypatch.setattr(IL, "user_prompt",
                        lambda pair: f"{real(pair)}\n  (cf. the E2SFCA analysis)")
    hits = IL.scan_frame()
    assert len(hits) == len(IL.enumerated_pairs())
    assert {h.field for h in hits} == {"design_phrase"}


def test_a_paper_token_in_the_template_is_the_marker_scans_job(monkeypatch):
    """Filter 2 hands off; it does not silently swallow.

    A method token written into the template appears in EVERY prompt, so filter
    2 reads it as boilerplate and this check goes quiet — measured, not assumed.
    The case is not unowned: `check_markers` reads `user_prompt` as one of its
    surfaces and holds E2SFCA as a marker, so the same edit fails there. The two
    checks partition the prompt between them and this test pins the seam.
    """
    from benchmark.contamination_check import MARKERS

    real = IL.user_prompt
    monkeypatch.setattr(IL, "user_prompt",
                        lambda pair: f"{real(pair)}\n  (cf. the E2SFCA analysis)")
    IL.template_text.cache_clear()
    IL.answer_only_phrases.cache_clear()
    try:
        assert not [h for h in IL.scan_frame() if h.field == "design_phrase"]
        assert "E2SFCA" in MARKERS, "the other half of the seam is gone"
    finally:
        IL.template_text.cache_clear()
        IL.answer_only_phrases.cache_clear()
